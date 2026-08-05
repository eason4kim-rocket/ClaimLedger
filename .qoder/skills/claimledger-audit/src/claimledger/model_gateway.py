from __future__ import annotations

import gc
import os
import resource
import sys
import threading
import time
from pathlib import Path
from typing import Any

import yaml
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from .config import model_api_token, models_dir, skill_root


class ChatRequest(BaseModel):
    model: str
    messages: list[dict[str, str]]
    temperature: float = 0
    max_tokens: int = 1600


class EmbeddingsRequest(BaseModel):
    model: str
    input: list[str] | str


class RerankRequest(BaseModel):
    model: str
    query: str
    documents: list[str]
    top_n: int = 10


class ModelRuntime:
    def __init__(self) -> None:
        manifest = yaml.safe_load(
            (skill_root() / "assets" / "models.yaml").read_text(encoding="utf-8")
        )
        self.models = manifest["profiles"]["balanced"]
        requested = os.environ.get("CLAIMLEDGER_MODEL_DEVICE", "CPU").upper()
        self.device = self._resolve_device(requested)
        self._lock = threading.RLock()
        self.generation = None
        self.embedding = None
        self.reranker = None
        self.timings_ms: dict[str, int] = {}

    @staticmethod
    def _resolve_device(requested: str) -> str:
        try:
            from openvino import Core

            available = set(Core().available_devices)
        except Exception as exc:
            raise RuntimeError("OpenVINO is not installed") from exc
        if requested == "AUTO":
            return "AUTO:GPU,CPU" if "GPU" in available else "CPU"
        if requested.startswith("AUTO:"):
            return requested if "GPU" in available else "CPU"
        if requested not in available:
            raise RuntimeError(
                f"requested OpenVINO device {requested} is unavailable; "
                f"available devices: {', '.join(sorted(available)) or 'none'}"
            )
        return requested

    def model_path(self, model_id: str) -> Path:
        if model_id not in {
            self.models["generation"],
            self.models["embeddings"],
            self.models["reranker"],
        }:
            raise ValueError(f"model is not allowed by the balanced manifest: {model_id}")
        path = models_dir() / model_id.replace("/", "--")
        if not path.is_dir() or not (path / "openvino_model.xml").is_file():
            raise FileNotFoundError(
                f"model is not installed: {model_id}; "
                "run claimledger models install --profile balanced --execute"
            )
        return path

    def _release(self, role: str) -> None:
        if role in {"generation", "all"}:
            self.generation = None
        if role in {"embedding", "all"}:
            self.embedding = None
        if role in {"reranker", "all"}:
            self.reranker = None
        gc.collect()

    def release(self, role: str) -> None:
        if role not in {"generation", "embedding", "reranker", "all"}:
            raise ValueError("unknown model role")
        with self._lock:
            self._release(role)

    def _load_generation(self):
        with self._lock:
            if self.generation is None:
                self._release("embedding")
                self._release("reranker")
                started = time.perf_counter()
                import openvino_genai as ov_genai

                cache_dir = models_dir() / ".openvino-cache" / "generation"
                cache_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
                self.generation = ov_genai.LLMPipeline(
                    self.model_path(self.models["generation"]),
                    self.device,
                    {"CACHE_DIR": str(cache_dir)},
                )
                self.timings_ms["generation_load"] = round(
                    (time.perf_counter() - started) * 1000
                )
            return self.generation

    def _load_embedding(self):
        with self._lock:
            if self.embedding is None:
                self._release("generation")
                started = time.perf_counter()
                import openvino_genai as ov_genai

                self.embedding = ov_genai.TextEmbeddingPipeline(
                    self.model_path(self.models["embeddings"]),
                    self.device,
                )
                self.timings_ms["embedding_load"] = round(
                    (time.perf_counter() - started) * 1000
                )
            return self.embedding

    def _load_reranker(self):
        with self._lock:
            if self.reranker is None:
                self._release("generation")
                started = time.perf_counter()
                import openvino_genai as ov_genai

                self.reranker = ov_genai.TextRerankPipeline(
                    self.model_path(self.models["reranker"]),
                    self.device,
                )
                self.timings_ms["reranker_load"] = round(
                    (time.perf_counter() - started) * 1000
                )
            return self.reranker

    def generate(self, request: ChatRequest) -> str:
        if request.model != self.models["generation"]:
            raise ValueError("generation model does not match the balanced manifest")
        with self._lock:
            pipeline = self._load_generation()
            try:
                prompt = pipeline.get_tokenizer().apply_chat_template(
                    request.messages,
                    True,
                    extra_context={"enable_thinking": False},
                )
            except Exception:
                prompt = "\n".join(
                    f"{item.get('role', 'user')}: {item.get('content', '')}"
                    for item in request.messages
                )

            state = {"started": False, "depth": 0, "in_string": False, "escape": False}

            def stop_after_json_array(fragment: str) -> bool:
                for character in fragment:
                    if not state["started"]:
                        if character == "[":
                            state["started"] = True
                            state["depth"] = 1
                        continue
                    if state["in_string"]:
                        if state["escape"]:
                            state["escape"] = False
                        elif character == "\\":
                            state["escape"] = True
                        elif character == '"':
                            state["in_string"] = False
                        continue
                    if character == '"':
                        state["in_string"] = True
                    elif character == "[":
                        state["depth"] += 1
                    elif character == "]":
                        state["depth"] -= 1
                        if state["depth"] == 0:
                            return True
                return False

            result = pipeline.generate(
                prompt,
                max_new_tokens=request.max_tokens,
                do_sample=False,
                stop_strings={"<|im_end|>", "<|endoftext|>"},
                streamer=stop_after_json_array,
            )
        if isinstance(result, str):
            return result
        texts = getattr(result, "texts", None)
        return str(texts[0] if texts else result)

    def embed(self, request: EmbeddingsRequest) -> list[list[float]]:
        if request.model != self.models["embeddings"]:
            raise ValueError("embedding model does not match the balanced manifest")
        texts = [request.input] if isinstance(request.input, str) else request.input
        with self._lock:
            vectors = self._load_embedding().embed_documents(texts)
        return [[float(value) for value in vector] for vector in vectors]

    def rerank(self, request: RerankRequest) -> list[tuple[int, float]]:
        if request.model != self.models["reranker"]:
            raise ValueError("reranker model does not match the balanced manifest")
        with self._lock:
            values = self._load_reranker().rerank(request.query, request.documents)
        return [(int(index), float(score)) for index, score in values[: request.top_n]]

    def status(self) -> dict[str, Any]:
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        peak_rss_bytes = int(rss if sys.platform == "darwin" else rss * 1024)
        return {
            "device": self.device,
            "models": self.models,
            "loaded": {
                "generation": self.generation is not None,
                "embedding": self.embedding is not None,
                "reranker": self.reranker is not None,
            },
            "timings_ms": self.timings_ms,
            "peak_rss_bytes": peak_rss_bytes,
        }


def create_model_app(runtime: ModelRuntime | None = None) -> FastAPI:
    app = FastAPI(
        title="ClaimLedger Local Model Gateway",
        version="0.5.1",
        docs_url=None,
        redoc_url=None,
    )
    app.state.token = model_api_token()
    app.state.runtime = runtime

    def authorize(authorization: str | None = Header(default=None)) -> None:
        supplied = (authorization or "").removeprefix("Bearer ").strip()
        if supplied != app.state.token:
            raise HTTPException(status_code=401, detail="invalid local model token")

    def get_runtime() -> ModelRuntime:
        if app.state.runtime is None:
            try:
                app.state.runtime = ModelRuntime()
            except Exception as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc
        return app.state.runtime

    @app.get("/v3/models", dependencies=[Depends(authorize)])
    def models() -> dict:
        return get_runtime().status()

    @app.post("/v3/chat/completions", dependencies=[Depends(authorize)])
    def chat(request: ChatRequest) -> dict:
        try:
            content = get_runtime().generate(request)
        except Exception as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return {"choices": [{"index": 0, "message": {"role": "assistant", "content": content}}]}

    @app.post("/v3/embeddings", dependencies=[Depends(authorize)])
    def embeddings(request: EmbeddingsRequest) -> dict:
        try:
            vectors = get_runtime().embed(request)
        except Exception as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return {
            "data": [
                {"object": "embedding", "index": index, "embedding": vector}
                for index, vector in enumerate(vectors)
            ]
        }

    @app.post("/v3/rerank", dependencies=[Depends(authorize)])
    def rerank(request: RerankRequest) -> dict:
        try:
            values = get_runtime().rerank(request)
        except Exception as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return {
            "results": [
                {"index": index, "relevance_score": score}
                for index, score in values
            ]
        }

    @app.post("/v3/admin/release/{role}", dependencies=[Depends(authorize)])
    def release(role: str) -> dict:
        try:
            get_runtime().release(role)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return get_runtime().status()

    return app


app = create_model_app()
