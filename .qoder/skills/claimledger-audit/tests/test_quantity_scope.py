"""Measurement ownership and signed cost changes, independent of demo values."""
from __future__ import annotations

import pytest

from claimledger.engine import _quantity_comparison_candidates, extract_claims, verify
from claimledger.models import IssueCode, Locator, ParsedChunk


def cell(value, *, name="result", header="结果", row="年度成本增加额", sheet="计算", address="C3"):
    return ParsedChunk(
        id=name, file_path="/tmp/arbitrary.xlsx", file_name="arbitrary.xlsx",
        file_hash="a" * 64, source_type="xlsx", text=str(value),
        raw_text=f"{header}: {value}", context_text=f"{row} | {header}: {value}",
        metadata={"header": header, "row_key": row},
        locator=Locator(kind="sheet_cell", sheet=sheet, cell=address),
    )


def claim(text):
    report = ParsedChunk(id="report", file_path="/tmp/input.docx", file_name="input.docx",
                         file_hash="b" * 64, source_type="docx", text=text,
                         locator=Locator(kind="paragraph", paragraph=1))
    return extract_claims([report])[0]


@pytest.mark.parametrize("amount", [321700, 859123])
def test_savings_vs_positive_cost_increase_uses_result_not_tooling_fee(amount):
    target = cell(amount)
    fee = cell("23000 元", name="fee", header="制版费(元)", row="供应商Q", sheet="报价")
    finding = verify(claim("切换供应商Q每年可节省95万元。"), [(target, .85), (fee, .65)], {})
    assert finding.status.value == "conflict"
    check = next(c for c in finding.checks if c.outcome == "fail")
    assert str(amount) in check.evidence_value
    assert "23000" not in check.evidence_value
    assert "元" not in check.evidence_value  # Never invent the source's unit.
    assert {e.chunk_id for e in finding.evidence if e.id in check.evidence_ids} == {"result"}


@pytest.mark.parametrize("value,label,text", [
    (-3200, "年度成本增加额", "每年可节省32万元。"),
    (3200, "年度成本节省额", "每年可节省32万元。"),
    (0, "年度成本增加额", "每年可节省32万元。"),
    (3200, "年度成本差额", "每年可节省32万元。"),
    (3200, "年度收入增加额", "每年可节省32万元。"),
    (3200, "年度成本增加额", "每年无法节省32万元。"),
])
def test_ambiguous_or_nonopposing_direction_does_not_invent_currency(value, label, text):
    target = cell(value, row=label)
    fee = cell("500 元", name="fee", header="费用(元)", row=label, address="D3")
    checks, issues, used = _quantity_comparison_candidates(claim(text), [(target, .9), (fee, .7)], {})
    assert IssueCode.NUMERIC_MISMATCH not in issues
    assert all(c.outcome != "pass" for c in checks)  # Unknown unit is not support.
    assert all(c.id == target.id for c in used)


def test_negative_cost_increase_contradicts_additional_spending():
    target = cell(-9700)
    checks, issues, used = _quantity_comparison_candidates(claim("每年多支出97万元。"), [(target, .9)], {})
    assert IssueCode.NUMERIC_MISMATCH in issues
    assert "-9700" in checks[0].evidence_value
    assert used == [target]


def test_explicit_unit_and_scale_are_still_compared():
    target = cell("321700 元")
    checks, issues, _ = _quantity_comparison_candidates(claim("每年多支出32.17万元。"), [(target, .9)], {})
    assert not issues
    assert checks[0].outcome == "pass"


@pytest.mark.parametrize("sheet,row", [("另一个工作表", "7月"), ("运营", "6月")])
def test_operations_cannot_borrow_a_ratio_from_another_sheet_or_month(sheet, row):
    top = cell("180 万元", header="运费支出(万元)", row="7月", sheet="运营")
    other = cell("-8%", name="other", header="环比变化率", row=row, sheet=sheet, address="D2")
    checks, issues, used = _quantity_comparison_candidates(claim("7月运费环比下降8%。"), [(top, .9), (other, .8)], {})
    assert not issues
    assert all(c.outcome != "pass" for c in checks)
    assert all(c.id == top.id for c in used)


def test_operations_same_row_ratio_keeps_exact_evidence_cell():
    top = cell("180 万元", header="运费支出(万元)", row="7月", sheet="运营")
    change = cell("5.7%", name="change", header="环比变化率", row="7月", sheet="运营", address="D3")
    checks, issues, used = _quantity_comparison_candidates(claim("7月运费环比下降8%。"), [(top, .9), (change, .8)], {})
    assert IssueCode.NUMERIC_MISMATCH in issues
    assert checks[0].evidence_value == "5.7%"
    assert used == [change]


def test_explicit_scope_can_select_the_right_measure_across_sheets():
    rules = {"exclusive_categories": [{"id": "boundary", "values": {
        "hardware": ["硬件市场"], "full": ["全栈市场"],
    }}]}
    top = cell("80 亿元", header="2025市场规模(亿元)", row="基准情景", sheet="预测")
    actual = cell("27 亿元", name="actual", header="市场规模(亿元)", row="2025", sheet="统计")
    actual.context_text = "2025年 | 硬件市场 | 市场规模: 27亿元"
    wrong_year = cell("80 亿元", name="old", header="市场规模(亿元)", row="2024", sheet="统计")
    wrong_year.context_text = "2024年 | 硬件市场 | 市场规模: 80亿元"
    checks, issues, used = _quantity_comparison_candidates(
        claim("2025年硬件市场规模达到80亿元。"), [(top, .9), (wrong_year, .85), (actual, .8)], rules,
    )
    assert IssueCode.NUMERIC_MISMATCH in issues
    assert used == [actual]
    assert checks[0].evidence_value == "27 亿元"


def test_neutral_delta_label_does_not_imply_increase_or_currency():
    target = cell(321700, row="Q相对R年度差额")
    fee = cell("23000 元", name="fee", header="制版费(元)", row="供应商Q", sheet="报价")
    checks, issues, used = _quantity_comparison_candidates(claim("每年可节省95万元。"), [(target, .9), (fee, .7)], {})
    assert not issues
    assert checks[0].outcome == "warn"
    assert used == [target]
