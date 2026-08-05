from __future__ import annotations

import pytest

from claimledger.models import Claim, Locator, ParsedChunk
from claimledger.semantic import LocalSemanticClient, augment_claims


def test_semantic_backend_rejects_cloud_endpoint():
    with pytest.raises(ValueError, match="loopback"):
        LocalSemanticClient("balanced", "https://api.example.com/v3")


def test_semantic_backend_accepts_loopback_endpoint():
    client = LocalSemanticClient("balanced", "http://127.0.0.1:8877/v3")
    assert client.base_url == "http://127.0.0.1:8877/v3"


class StubSemanticClient:
    def __init__(self, conclusions: list[dict]):
        self.conclusions = conclusions

    def extract_conclusions(self, _chunks: list[ParsedChunk]) -> list[dict]:
        return self.conclusions


def _report_chunk(text: str) -> ParsedChunk:
    return ParsedChunk(
        id="report-chunk-0001",
        file_path="/tmp/report.docx",
        file_name="report.docx",
        file_hash="a" * 64,
        source_type="docx",
        text=text,
        locator=Locator(
            kind="paragraph",
            paragraph=3,
            section="经营回顾",
            anchor_precision="paragraph",
        ),
    )


def test_augment_claims_anchors_exact_model_text_to_source_span():
    paragraph = "经营回顾：公司2025年营收增长20%，海外业务保持稳定。"
    exact_text = "公司2025年营收增长20%"
    chunk = _report_chunk(paragraph)

    claims = augment_claims(
        [],
        [chunk],
        StubSemanticClient([{"paragraph_index": 0, "exact_text": exact_text}]),
    )

    assert len(claims) == 1
    claim = claims[0]
    expected_start = paragraph.index(exact_text)
    assert claim.text == exact_text
    assert claim.source_chunk_id == chunk.id
    assert claim.locator.paragraph == chunk.locator.paragraph
    assert claim.locator.section == chunk.locator.section
    assert claim.locator.char_start == expected_start
    assert claim.locator.char_end == expected_start + len(exact_text)
    assert claim.locator.anchor_precision == "span"
    assert chunk.locator.char_start is None
    assert chunk.locator.anchor_precision == "paragraph"


def test_augment_claims_skips_ungrounded_model_text_and_preserves_existing_claim():
    chunk = _report_chunk("经营回顾：公司2025年营收增长20%。")
    existing = Claim(
        id="claim-0001",
        text="公司2025年营收增长20%",
        claim_type="numeric",
        locator=Locator(
            kind="paragraph",
            paragraph=3,
            char_start=5,
            char_end=19,
            anchor_precision="span",
        ),
        source_chunk_id=chunk.id,
    )

    claims = augment_claims(
        [existing],
        [chunk],
        StubSemanticClient(
            [
                {"paragraph_index": 0, "exact_text": "公司2025年营收增长30%"},
                {"paragraph_index": 0, "exact_text": " 公司2025年营收增长20% "},
            ]
        ),
    )

    assert claims == [existing]
    assert claims[0] is existing
