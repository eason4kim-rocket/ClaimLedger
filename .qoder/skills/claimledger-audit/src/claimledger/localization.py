from __future__ import annotations

from .models import Locator


STATUS_ZH = {
    "supported": "证据充分",
    "partial": "部分支持",
    "unsupported": "缺少证据",
    "conflict": "证据冲突",
    "stale": "证据过期",
    "needs_review": "需要复核",
}

SEVERITY_ZH = {
    "high": "高风险",
    "medium": "中风险",
    "low": "低风险",
}

ISSUE_ZH = {
    "direct_support": "直接支持",
    "missing_evidence": "缺少证据",
    "weak_support": "支持不足",
    "numeric_mismatch": "数值不一致",
    "unit_mismatch": "单位不一致",
    "date_mismatch": "日期不一致",
    "entity_mismatch": "主体不一致",
    "scope_mismatch": "统计口径不一致",
    "qualifier_overreach": "结论表述过度",
    "source_conflict": "来源相互冲突",
    "stale_evidence": "证据已过期",
    "ocr_uncertainty": "OCR 识别不确定",
    "derived_calculation": "衍生计算核对",
    "locator_uncertainty": "来源定位不确定",
}

RELATION_ZH = {
    "candidate": "候选证据",
    "supports": "支持",
    "contradicts": "反驳",
    "qualifies": "有限支持",
    "background": "背景材料",
}

ACTION_ZH = {
    "accept": "确认发现",
    "reject": "驳回误报",
    "replace": "修正并复验",
    "waive": "正式豁免",
    "unreviewed": "尚未复核",
    "unresolved": "尚未处理",
}

OUTCOME_ZH = {
    "pass": "通过",
    "fail": "不通过",
    "warn": "需关注",
}

ROLE_ZH = {
    "report": "待审报告",
    "evidence": "证据材料",
}

SOURCE_STATUS_ZH = {
    "parsed": "解析成功",
    "failed": "解析失败",
    "skipped": "已跳过",
}

WAIVER_SCOPE_ZH = {
    "not_applicable": "不适用",
    "permanent": "永久豁免",
    "temporary": "临时豁免",
}

RECHECK_ZH = {
    "not_required": "无需复验",
    "not_run": "尚未复验",
    "passed": "复验通过",
    "failed": "复验未通过",
}

COVERAGE_ZH = {
    "pending": "等待解析",
    "complete": "完整",
    "incomplete": "不完整",
}

MESSAGE_ZH = {
    "No sufficiently relevant passage was found in the supplied evidence set.": "在所提供的证据材料中未找到足够相关的支持内容。",
    "No relevant evidence candidate was retrieved.": "未召回相关证据候选。",
    "The normalized quantity is present in the evidence.": "证据中存在规范化后可比对的数值。",
    "The evidence contains a different value for a comparable quantity.": "证据中的同口径数值与报告不一致。",
    "The same figure appears under a different or incompatible unit.": "相同数值使用了不同或不兼容的单位。",
    "A material quantity in the claim is not stated in the candidate evidence.": "候选证据未明确给出结论中的关键数值。",
    "The reported aggregate was recalculated from distinct source records.": "已根据不同来源记录重新计算报告汇总值。",
    "The reported aggregate does not equal the sum of the retrieved source records.": "报告汇总值与召回的来源记录合计不一致。",
    "The aggregate reconciles, but one or more contributing OCR records require visual confirmation.": "汇总计算可以勾稽，但部分 OCR 记录仍需人工查看原图确认。",
    "A contributing OCR record falls below the configured review threshold.": "参与计算的 OCR 记录低于设定的人工复核置信度。",
    "The reported aggregate reconciles to distinct source records under the normalized unit.": "报告汇总值在统一单位后可与各来源记录勾稽一致。",
    "The closest evidence came from low-confidence OCR and requires visual confirmation.": "最相关证据来自低置信度 OCR，需要人工查看原图确认。",
    "A materially relevant candidate uses a conflicting entity, category, or statistical scope.": "关键候选证据使用了不同的主体、品类或统计口径。",
    "Two materially relevant sources state different values under a comparable scope.": "两个关键来源在可比口径下给出了不同数值。",
    "Relevant evidence sources conflict and require a human source-of-truth decision.": "相关证据来源相互冲突，需要人工确定权威来源。",
    "The claim and evidence use mutually exclusive entities, categories, or statistical scopes.": "报告结论与证据使用了互斥的主体、品类或统计口径。",
    "The evidence assigns a material value to a different entity or reverses the claimed allocation.": "证据把关键数值归属于其他主体，或与报告中的归属关系相反。",
    "The closest evidence discusses the same subject but a material value or unit differs.": "最相关证据讨论同一事项，但关键数值或单位不一致。",
    "The evidence negates a material assertion in the claim, or vice versa.": "证据与报告结论在关键肯定或否定表述上相反。",
    "Negation differs between claim and evidence.": "报告结论与证据的肯定/否定表述不一致。",
    "The claim uses current-validity language but the candidate evidence is expired or stale.": "报告使用了当前有效的表述，但候选证据已经过期或超出时效窗口。",
    "Evidence supports the topic but not every absolute or freshness qualifier in the claim.": "证据支持该主题，但不能支持结论中的全部绝对化或时效性表述。",
    "Related evidence was found, but it does not clearly support every material clause or qualifier.": "已找到相关证据，但不能明确支持全部关键事实和限定条件。",
    "A directly traceable passage supports the material facts and qualifiers in the claim.": "可追溯的原始证据直接支持该结论的关键事实和限定条件。",
}


def zh(mapping: dict[str, str], value: str | None) -> str:
    if value is None:
        return ""
    return mapping.get(value, value)


def message_zh(value: str | None) -> str:
    if not value:
        return ""
    if value.startswith("Unsupported qualifiers: "):
        return "证据不支持以下限定词：" + value.removeprefix("Unsupported qualifiers: ")
    if value.startswith("Exclusive scope '") and value.endswith(
        "' differs between claim and evidence."
    ):
        scope = value.removeprefix("Exclusive scope '").removesuffix(
            "' differs between claim and evidence."
        )
        return f"报告结论与证据使用了不同的统计口径（{scope}）。"
    if value.startswith("replacement recheck: "):
        remainder = value.removeprefix("replacement recheck: ")
        state, separator, detail = remainder.partition(" — ")
        return f"修正内容复验：{zh(STATUS_ZH, state)}{('——' + message_zh(detail)) if separator else ''}"
    return MESSAGE_ZH.get(value, value)


def locator_zh(locator: Locator) -> str:
    suffix = ""
    if locator.char_start is not None and locator.char_end is not None:
        suffix = f"，字符 {locator.char_start}:{locator.char_end}"
    if locator.kind == "pdf_page":
        return f"第 {locator.page or 1} 页" + (" · 坐标框" if locator.bbox else "")
    if locator.kind == "sheet_cell":
        cell = locator.cell or "A1"
        if locator.end_cell and locator.end_cell != cell:
            cell = f"{cell}:{locator.end_cell}"
        return f"工作表“{locator.sheet}”单元格 {cell}"
    if locator.kind == "table_cell":
        return f"表格 {locator.table}，第 {locator.row} 行，第 {locator.column} 列{suffix}"
    if locator.kind == "paragraph":
        return f"第 {locator.paragraph} 段{suffix}"
    return "图片" if not locator.page else f"图片第 {locator.page} 页"
