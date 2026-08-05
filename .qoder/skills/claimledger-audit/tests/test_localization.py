from __future__ import annotations

from claimledger.localization import (
    ACTION_ZH,
    ISSUE_ZH,
    STATUS_ZH,
    locator_zh,
    message_zh,
    zh,
)
from claimledger.models import Locator


def test_primary_review_labels_are_chinese():
    assert zh(STATUS_ZH, "conflict") == "证据冲突"
    assert zh(ISSUE_ZH, "numeric_mismatch") == "数值不一致"
    assert zh(ACTION_ZH, "replace") == "修正并复验"


def test_known_engine_message_is_localized():
    assert message_zh(
        "The evidence contains a different value for a comparable quantity."
    ) == "证据中的同口径数值与报告不一致。"
    assert message_zh(
        "Exclusive scope 'order-denominator' differs between claim and evidence."
    ) == "报告结论与证据使用了不同的统计口径（order-denominator）。"


def test_locator_is_presented_in_chinese():
    assert locator_zh(
        Locator(kind="sheet_cell", sheet="运营月报", cell="C7", anchor_precision="cell")
    ) == "工作表“运营月报”单元格 C7"
    assert locator_zh(
        Locator(kind="pdf_page", page=3, bbox=[1, 2, 3, 4], anchor_precision="bbox")
    ) == "第 3 页 · 坐标框"
