from __future__ import annotations

import json
import math
import os
from pathlib import Path
from urllib.parse import urlparse

import httpx
import yaml

from .config import skill_root
from .config import model_api_token
from .models import Claim, Locator, NormalizedFact, ParsedChunk


class LocalSemanticClient:
    """Chat and rerank protocol client restricted to ClaimLedger's loopback gateway."""

    def __init__(self, profile: str, base_url: str | None = None, timeout: float = 1800.0):
        if profile != "balanced":
            raise ValueError(f"semantic profile is not model-assisted: {profile}")
        configured = (
            base_url
            or os.environ.get("CLAIMLEDGER_MODEL_GATEWAY_URL")
            or os.environ.get("CLAIMLEDGER_OVMS_URL")  # v0.3 compatibility
            or "http://127.0.0.1:8877/v3"
        )
        parsed = urlparse(configured)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("model endpoint must be an HTTP loopback URL; cloud endpoints are forbidden")
        manifest = yaml.safe_load((skill_root() / "assets" / "models.yaml").read_text(encoding="utf-8"))
        self.models = manifest["profiles"][profile]
        self.base_url = configured.rstrip("/")
        # Loopback inference must not be redirected through environment proxies.
        configured_timeout = float(os.environ.get("CLAIMLEDGER_MODEL_TIMEOUT_SECONDS", timeout))
        self.client = httpx.Client(timeout=configured_timeout, trust_env=False)
        self.client.headers["Authorization"] = f"Bearer {model_api_token()}"
        self._evidence_ids: list[str] = []
        self._evidence_vectors: list[list[float]] = []
        self._query_vectors: dict[str, list[float]] = {}

    def healthcheck(self) -> None:
        response = self.client.get(f"{self.base_url}/models")
        response.raise_for_status()

    def status(self) -> dict:
        response = self.client.get(f"{self.base_url}/models")
        response.raise_for_status()
        return response.json()

    def extract_conclusions(self, chunks: list[ParsedChunk]) -> list[dict]:
        numbered = "\n".join(f"[{index}] {chunk.text}" for index, chunk in enumerate(chunks))
        prompt = (
            "/no_think\n"
            "Extract only externally verifiable conclusions from the numbered Chinese report paragraphs. "
            "Return a JSON array with objects containing paragraph_index and exact_text. "
            "Do not rewrite text and do not include headings.\n" + numbered[:24000]
        )
        token_budget = min(1400, max(192, len(chunks) * 45))
        response = self.client.post(
            f"{self.base_url}/chat/completions",
            json={
                "model": self.models["generation"],
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
                "max_tokens": token_budget,
            },
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        start, end = content.find("["), content.rfind("]")
        if start < 0 or end < start:
            raise ValueError("local model did not return a JSON array")
        payload = json.loads(content[start:end + 1])
        return [item for item in payload if isinstance(item, dict)]

    def embed(self, texts: list[str]) -> list[list[float]]:
        response = self.client.post(
            f"{self.base_url}/embeddings",
            json={"model": self.models["embeddings"], "input": texts},
        )
        response.raise_for_status()
        ordered = sorted(response.json()["data"], key=lambda item: item.get("index", 0))
        return [item["embedding"] for item in ordered]

    def prepare_evidence(
        self,
        chunks: list[ParsedChunk],
        queries: list[str] | None = None,
        batch_size: int = 64,
    ) -> None:
        """Build one reusable embedding index per audit instead of re-embedding per claim."""
        self._evidence_ids = [chunk.id for chunk in chunks]
        self._evidence_vectors = []
        self._query_vectors = {}
        for start in range(0, len(chunks), batch_size):
            batch = chunks[start:start + batch_size]
            self._evidence_vectors.extend(self.embed([chunk.search_text[:4000] for chunk in batch]))
        unique_queries = list(dict.fromkeys(queries or []))
        for start in range(0, len(unique_queries), batch_size):
            batch = unique_queries[start:start + batch_size]
            vectors = self.embed(batch)
            self._query_vectors.update(zip(batch, vectors))

    def release(self, role: str) -> None:
        response = self.client.post(f"{self.base_url}/admin/release/{role}")
        response.raise_for_status()

    def rerank(self, query: str, chunks: list[ParsedChunk]) -> list[tuple[ParsedChunk, float]]:
        if not chunks:
            return []
        response = self.client.post(
            f"{self.base_url}/rerank",
            json={
                "model": self.models["reranker"],
                "query": query,
                "documents": [chunk.text for chunk in chunks],
                "top_n": min(10, len(chunks)),
            },
        )
        response.raise_for_status()
        results = response.json().get("results", [])
        return [(chunks[item["index"]], float(item["relevance_score"])) for item in results]

    def semantic_candidates(self, query: str, chunks: list[ParsedChunk], limit: int = 20) -> list[ParsedChunk]:
        query_vector = self._query_vectors.get(query)
        if query_vector is None:
            query_vector = self.embed([query])[0]
        if self._evidence_ids == [chunk.id for chunk in chunks] and len(self._evidence_vectors) == len(chunks):
            vectors = self._evidence_vectors
        else:
            vectors = self.embed([chunk.search_text[:4000] for chunk in chunks])

        def cosine(vector: list[float]) -> float:
            numerator = sum(left * right for left, right in zip(query_vector, vector))
            denominator = math.sqrt(sum(value * value for value in query_vector)) * math.sqrt(
                sum(value * value for value in vector)
            )
            return numerator / denominator if denominator else 0.0

        ranked = sorted(zip(chunks, vectors), key=lambda item: cosine(item[1]), reverse=True)
        return [chunk for chunk, _vector in ranked[:limit]]


def augment_claims(existing: list[Claim], report_chunks: list[ParsedChunk], client: LocalSemanticClient) -> list[Claim]:
    known = {claim.text for claim in existing}
    claims = list(existing)
    for item in client.extract_conclusions(report_chunks):
        try:
            index = int(item["paragraph_index"])
            text = str(item["exact_text"])
            source = report_chunks[index]
        except (KeyError, TypeError, ValueError, IndexError):
            continue
        char_start = source.text.find(text)
        if not text.strip() or text in known or char_start < 0:
            continue
        char_end = char_start + len(text)
        claims.append(
            Claim(
                id=f"claim-{len(claims) + 1:04d}",
                text=text,
                claim_type="conclusion",
                locator=source.locator.model_copy(
                    update={
                        "char_start": char_start,
                        "char_end": char_end,
                        "anchor_precision": "span",
                    }
                ),
                facts=[],
                source_chunk_id=source.id,
            )
        )
        known.add(text)
    return claims
