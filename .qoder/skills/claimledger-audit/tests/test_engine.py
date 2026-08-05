from __future__ import annotations

from claimledger.engine import extract_claims, extract_facts, retrieve, verify
from claimledger.models import Locator, ParsedChunk


def chunk(text: str, name: str = "source.docx") -> ParsedChunk:
    return ParsedChunk(
        id="chunk-1",
        file_path=f"/tmp/{name}",
        file_name=name,
        file_hash="a" * 64,
        source_type="docx",
        text=text,
        locator=Locator(kind="paragraph", paragraph=0),
    )


def test_extracts_numbers_dates_and_claims():
    facts = extract_facts("2026年7月价格达到 120,000 元/吨，同比上涨 5%")
    assert {fact.value for fact in facts if fact.kind == "number"} >= {"120000", "5"}
    claims = extract_claims([chunk("市场价格达到 120000 元，较上月增长 5%。普通介绍。")])
    assert len(claims) == 2
    assert all(item.claim_type == "numeric" for item in claims)
    assert claims[0].locator.char_start == 0
    assert claims[0].locator.char_end is not None


def test_long_unformatted_numbers_are_not_truncated_and_dates_are_not_numbers():
    facts = extract_facts("截至2026年7月，销售额达到120000元。")
    assert [item.value for item in facts if item.kind == "number"] == ["120000"]
    assert [item.value for item in facts if item.kind == "date"] == ["2026-07"]


def test_currency_scale_equivalence_and_unit_mismatch():
    claim = extract_claims([chunk("项目金额达到1亿元。")])[0]
    equivalent = chunk("项目金额达到10000万元。")
    assert verify(claim, retrieve(claim, [equivalent]), {"freshness_terms": []}).status.value == "supported"

    mismatched = extract_claims([chunk("项目金额达到100万元。")])[0]
    tiny = chunk("项目金额达到100元。")
    finding = verify(mismatched, retrieve(mismatched, [tiny]), {"freshness_terms": []})
    assert finding.status.value == "conflict"
    assert any(item.value in {"numeric_mismatch", "unit_mismatch"} for item in finding.issue_codes)


def test_long_number_conflict_is_not_hidden_by_prefix():
    claim = extract_claims([chunk("销售额达到120000元。")])[0]
    evidence = chunk("销售额达到120999元。")
    assert verify(claim, retrieve(claim, [evidence]), {"freshness_terms": []}).status.value == "conflict"


def test_supported_when_traceable_number_matches():
    claim = extract_claims([chunk("电池级碳酸锂价格达到 120000 元。")])[0]
    evidence = chunk("2026年7月，电池级碳酸锂价格达到 120000 元。")
    finding = verify(claim, retrieve(claim, [evidence]), {"freshness_terms": []})
    assert finding.status.value == "supported"
    assert finding.evidence[0].quote in evidence.text


def test_numeric_conflict_is_high_severity():
    claim = extract_claims([chunk("电池级碳酸锂价格达到 150000 元。")])[0]
    evidence = chunk("电池级碳酸锂价格达到 120000 元。")
    finding = verify(claim, retrieve(claim, [evidence]), {"freshness_terms": []})
    assert finding.status.value == "conflict"
    assert finding.severity == "high"


def test_lithium_categories_cannot_be_silently_mixed():
    rules = {
        "freshness_terms": [],
        "exclusive_categories": [
            {"id": "product", "values": {"carbonate": ["碳酸锂"], "hydroxide": ["氢氧化锂"]}}
        ],
    }
    claim = extract_claims([chunk("碳酸锂价格达到 100000 元。")])[0]
    evidence = chunk("氢氧化锂价格达到 100000 元。")
    finding = verify(claim, [(evidence, 0.5)], rules)
    assert finding.status.value == "conflict"
