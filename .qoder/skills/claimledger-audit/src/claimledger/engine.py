from __future__ import annotations

import hashlib
import math
import re
import resource
import sys
import time
import uuid
from copy import deepcopy
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable

import yaml

from .config import jobs_dir, skill_root
from .ingestion import snapshot_inputs
from .models import (
    AuditJob,
    CheckDetail,
    Claim,
    Evidence,
    EvidenceRelation,
    Finding,
    FindingStatus,
    IssueCode,
    JobRequest,
    Locator,
    NormalizedFact,
    ParsedChunk,
)
from .parsers import parse_docx, parse_evidence_directory, sha256_file, sha256_text
from .semantic import LocalSemanticClient, augment_claims


NUMBER_RE = re.compile(
    r"(?<![A-Za-z0-9])"
    r"(-?(?:\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?))\s*"
    r"(个百分点|个工作日|个自然日|工作日|自然日|元/个|元/件|元/吨|万元/年|亿元|万元|美元|人民币|"
    r"万吨|千克|公斤|吨|个月|小时|分钟|天|年|万个|万件|万台|个|件|台|套|家|单|次|人|mL|ml|GB|%|倍|元)?"
    r"(?![A-Za-z])"
)
DATE_RE = re.compile(
    r"(?<!\d)20\d{2}(?:[年./-](?:0?[1-9]|1[0-2])(?:[月./-](?:0?[1-9]|[12]\d|3[01])日?)?)?(?!\d)"
)
SENTENCE_RE = re.compile(r"[^。！？!?；;\n]+[。！？!?；;]?|[^\n]+$")
CLAUSE_RE = re.compile(r"[^，,]+[，,]?")
CONCLUSION_TERMS = {
    "增长", "下降", "上升", "减少", "达到", "预计", "显示", "表明", "导致", "高于", "低于",
    "同比", "环比", "占比", "市场", "成本", "价格", "需求", "供应", "最新", "当前", "目前",
    "具备", "通过", "覆盖", "支持", "承诺", "获得", "有效", "一致", "推荐", "优于", "最低", "最高",
    "唯一", "全部", "所有", "均", "满足", "可以", "建议", "节省", "增加", "完成", "没有", "无条件",
}
HIGH_RISK_QUALIFIERS = {
    "全部", "所有", "均", "唯一", "完全", "无条件", "最新", "当前", "截至目前", "第一", "最佳", "最低", "最高",
    "就是", "足以",
}
NEGATIVE_TERMS = (
    "不能", "不可", "不得", "不代表", "不支持", "并非", "没有", "不包含", "另计",
    "未计入", "未包含", "未完成", "未提交", "未通过", "未获得", "未要求", "未设置",
    "尚未", "未经", "仍缺", "无需", "不足以",
)
FILE_TOPIC_TERMS = (
    "检测报告", "CMA", "FSC", "ISO", "银行电子回单", "回单", "报价", "框架合同",
    "合同", "试单验收", "验收", "履约KPI", "履约", "评审会议", "利益冲突", "现场验厂",
)
FILE_TOPIC_GROUPS = (
    (("付款", "款项", "支付", "收款"), ("回单", "合同")),
    (("准时", "交付周期", "质量", "缺陷率", "投诉"), ("履约KPI", "履约", "投诉")),
    (("产能", "产线", "复审"), ("现场验厂",)),
    (("份额", "利益冲突", "委员会", "断供"), ("评审会议", "利益冲突")),
)
LOCAL_TOPIC_TERMS = (
    "检测报告", "样品", "范围", "方法", "证书", "有效期", "持有人", "收款人", "付款",
    "运费", "报价", "复审", "准时交付率", "质量缺陷率", "份额", "产能", "利用率",
    "质量", "利益冲突", "起订量", "制版费", "交付周期", "投诉", "续签",
)


UNIT_MAP: dict[str, tuple[str, str, Decimal]] = {
    "元": ("currency_cny", "CNY", Decimal("1")),
    "人民币": ("currency_cny", "CNY", Decimal("1")),
    "元/个": ("price_per_piece_cny", "CNY/PIECE", Decimal("1")),
    "元/件": ("price_per_piece_cny", "CNY/PIECE", Decimal("1")),
    "元/吨": ("price_per_ton_cny", "CNY/TON", Decimal("1")),
    "万元": ("currency_cny", "CNY", Decimal("10000")),
    "万元/年": ("currency_cny_per_year", "CNY/YEAR", Decimal("10000")),
    "亿元": ("currency_cny", "CNY", Decimal("100000000")),
    "美元": ("currency_usd", "USD", Decimal("1")),
    "%": ("percentage", "PERCENT", Decimal("1")),
    "个百分点": ("percentage_point", "PERCENTAGE_POINT", Decimal("1")),
    "吨": ("mass", "TON", Decimal("1")),
    "万吨": ("mass", "TON", Decimal("10000")),
    "千克": ("mass", "TON", Decimal("0.001")),
    "公斤": ("mass", "TON", Decimal("0.001")),
    "工作日": ("workday", "WORKDAY", Decimal("1")),
    "个工作日": ("workday", "WORKDAY", Decimal("1")),
    "自然日": ("calendar_day", "CALENDAR_DAY", Decimal("1")),
    "个自然日": ("calendar_day", "CALENDAR_DAY", Decimal("1")),
    "天": ("day_unspecified", "DAY", Decimal("1")),
    "小时": ("hour", "HOUR", Decimal("1")),
    "分钟": ("minute", "MINUTE", Decimal("1")),
    "个月": ("month", "MONTH", Decimal("1")),
    "年": ("year", "YEAR", Decimal("1")),
    "个": ("count", "COUNT", Decimal("1")),
    "件": ("count", "COUNT", Decimal("1")),
    "台": ("count", "COUNT", Decimal("1")),
    "套": ("count", "COUNT", Decimal("1")),
    "家": ("count", "COUNT", Decimal("1")),
    "单": ("count", "COUNT", Decimal("1")),
    "次": ("count", "COUNT", Decimal("1")),
    "人": ("count", "COUNT", Decimal("1")),
    "万个": ("count", "COUNT", Decimal("10000")),
    "万件": ("count", "COUNT", Decimal("10000")),
    "万台": ("count", "COUNT", Decimal("10000")),
    "mL": ("volume_ml", "ML", Decimal("1")),
    "ml": ("volume_ml", "ML", Decimal("1")),
    "GB": ("storage_gb", "GB", Decimal("1")),
    "倍": ("multiple", "MULTIPLE", Decimal("1")),
}


def _normalize_number(raw: str) -> Decimal | None:
    try:
        return Decimal(raw.replace(",", ""))
    except InvalidOperation:
        return None


def _decimal_text(value: Decimal) -> str:
    normalized = value.normalize()
    return format(normalized, "f")


def _normalize_date(raw: str) -> str:
    value = raw.replace("年", "-").replace("月", "-").replace("日", "").replace("/", "-").replace(".", "-")
    parts = value.rstrip("-").split("-")
    if len(parts) >= 2:
        parts[1] = parts[1].zfill(2)
    if len(parts) >= 3:
        parts[2] = parts[2].zfill(2)
    return "-".join(parts)


def extract_facts(text: str) -> list[NormalizedFact]:
    facts: list[NormalizedFact] = []
    date_spans: list[tuple[int, int]] = []
    for match in DATE_RE.finditer(text):
        date_spans.append(match.span())
        facts.append(
            NormalizedFact(
                kind="date",
                raw=match.group(0),
                value=_normalize_date(match.group(0)),
                span_start=match.start(),
                span_end=match.end(),
            )
        )
    for match in NUMBER_RE.finditer(text):
        if any(match.start() < end and match.end() > start for start, end in date_spans):
            continue
        raw, unit = match.groups()
        # Calendar shorthands such as “7月” and “15日” are temporal anchors,
        # not scalar business quantities. Treating the bare number as a fact
        # made otherwise exact spreadsheet evidence fail because a row also
        # contained unrelated numeric cells. Real durations such as “7个月”
        # and “15天” already carry an explicit supported unit and are retained.
        following = text[match.end():match.end() + 1]
        if unit is None and following in {"月", "日", "季", "周"}:
            continue
        numeric = _normalize_number(raw)
        if numeric is None:
            continue
        dimension = "scalar"
        base_unit = None
        base_value = numeric
        if unit in UNIT_MAP:
            dimension, base_unit, factor = UNIT_MAP[unit]
            base_value = numeric * factor
        facts.append(
            NormalizedFact(
                kind="number",
                raw=match.group(0).strip(),
                value=_decimal_text(numeric),
                unit=unit,
                dimension=dimension,
                base_value=_decimal_text(base_value),
                base_unit=base_unit,
                span_start=match.start(),
                span_end=match.end(),
            )
        )
    return sorted(facts, key=lambda item: item.span_start or 0)


def _auditable(text: str) -> bool:
    facts = extract_facts(text)
    if facts:
        return True
    return len(text.strip("，,。；; ")) >= 8 and any(term in text for term in CONCLUSION_TERMS)


def _qualifiers(text: str) -> list[str]:
    found = []
    for term in HIGH_RISK_QUALIFIERS:
        if term == "均":
            if re.search(r"(?<!平)均", text):
                found.append(term)
        elif term in text:
            found.append(term)
    return sorted(found)


def _sentence_parts(text: str) -> list[tuple[str, int, int]]:
    parts: list[tuple[str, int, int]] = []
    for match in SENTENCE_RE.finditer(text):
        value = match.group(0).strip()
        if value:
            leading = len(match.group(0)) - len(match.group(0).lstrip())
            parts.append((value, match.start() + leading, match.start() + leading + len(value)))
    return parts


def _atomic_parts(sentence: str, sentence_start: int) -> list[tuple[str, int, int]]:
    clauses = []
    prefix = ""
    prefix_start = sentence_start
    for match in CLAUSE_RE.finditer(sentence):
        raw = match.group(0)
        value = raw.strip(" ，,")
        if not value:
            continue
        absolute_start = sentence_start + match.start() + (len(raw) - len(raw.lstrip()))
        absolute_end = absolute_start + len(value)
        if _auditable(value):
            if prefix:
                value = f"{prefix}，{value}"
                absolute_start = prefix_start
                prefix = ""
            clauses.append((value, absolute_start, absolute_end))
        elif not clauses:
            prefix = f"{prefix}，{value}".strip("，")
            prefix_start = min(prefix_start, absolute_start)
    if len(clauses) >= 2:
        return clauses
    return [(sentence, sentence_start, sentence_start + len(sentence))]


def extract_claims(report_chunks: list[ParsedChunk]) -> list[Claim]:
    claims: list[Claim] = []
    for chunk in report_chunks:
        style_name = str(chunk.metadata.get("style") or "").lower()
        if (
            style_name in {"title", "subtitle", "caption"}
            or style_name.startswith("heading")
            or style_name.startswith("toc")
        ):
            continue
        for sentence_index, (sentence, start, _end) in enumerate(_sentence_parts(chunk.text)):
            parent_id = f"parent-{len(claims) + 1:04d}-{sentence_index + 1}"
            for atomic_index, (atomic, atomic_start, atomic_end) in enumerate(_atomic_parts(sentence, start)):
                if not _auditable(atomic):
                    continue
                facts = extract_facts(atomic)
                numeric = any(fact.kind == "number" for fact in facts)
                dates = any(fact.kind == "date" for fact in facts)
                claim_type = "numeric" if numeric else "date" if dates else "conclusion"
                qualifiers = _qualifiers(atomic)
                materiality = "high" if numeric or qualifiers else "medium"
                locator = chunk.locator.model_copy(
                    update={
                        "char_start": atomic_start,
                        "char_end": atomic_end,
                        "anchor_precision": "span" if chunk.locator.kind in {"paragraph", "table_cell"} else chunk.locator.anchor_precision,
                    }
                )
                claims.append(
                    Claim(
                        id=f"claim-{len(claims) + 1:04d}",
                        text=atomic,
                        claim_type=claim_type,
                        locator=locator,
                        facts=facts,
                        parent_claim_id=parent_id,
                        source_chunk_id=chunk.id,
                        atomic_index=atomic_index,
                        qualifiers=qualifiers,
                        materiality=materiality,
                    )
                )
    return claims


def tokenize(text: str) -> set[str]:
    lowered = text.lower()
    latin = set(re.findall(r"[a-z0-9]+", lowered))
    chinese_runs = re.findall(r"[\u4e00-\u9fff]+", lowered)
    grams: set[str] = set()
    for run in chinese_runs:
        grams.update(run[index:index + 2] for index in range(max(0, len(run) - 1)))
        if len(run) == 1:
            grams.add(run)
    return {token for token in latin | grams if token}


def _fact_keys(text: str) -> set[tuple[str | None, str | None]]:
    return {
        (fact.base_unit or fact.unit, fact.base_value or fact.value)
        for fact in extract_facts(text)
        if fact.kind == "number"
    }


def lexical_score(claim: Claim, chunk: ParsedChunk, rules: dict | None = None) -> float:
    left = tokenize(claim.text)
    context_tokens = tokenize(chunk.search_text)
    local_tokens = tokenize(chunk.text)
    if not left or not context_tokens:
        return 0.0
    context_overlap = len(left & context_tokens) / math.sqrt(len(left) * len(context_tokens))
    local_overlap = (
        len(left & local_tokens) / math.sqrt(len(left) * len(local_tokens))
        if local_tokens
        else 0.0
    )
    # Page and row context improves recall; the exact OCR line/cell still needs
    # to win so unrelated material on the same page does not become evidence.
    overlap = max(local_overlap, context_overlap * 0.72)
    claim_facts = _fact_keys(claim.text)
    local_facts = _fact_keys(chunk.text)
    context_facts = _fact_keys(chunk.search_text)
    number_bonus = (
        0.24
        if claim_facts and claim_facts & local_facts
        else 0.10
        if claim_facts and claim_facts & context_facts
        else 0.0
    )
    exact_bonus = 0.45 if claim.text in chunk.search_text else 0.0
    section_bonus = 0.06 if claim.locator.section and claim.locator.section in chunk.search_text else 0.0
    filename_tokens = tokenize(Path(chunk.file_name).stem)
    filename_overlap = (
        len(left & filename_tokens) / math.sqrt(len(left) * len(filename_tokens))
        if filename_tokens
        else 0.0
    )
    direct_file_topic = any(
        term.lower() in claim.text.lower() and term.lower() in chunk.file_name.lower()
        for term in FILE_TOPIC_TERMS
    )
    grouped_file_topic = any(
        any(term in claim.text for term in claim_terms)
        and any(term in chunk.file_name for term in file_terms)
        for claim_terms, file_terms in FILE_TOPIC_GROUPS
    )
    topic_bonus = 0.34 if direct_file_topic or grouped_file_topic else 0.0
    local_topic_bonus = min(
        0.30,
        0.14 * sum(1 for term in LOCAL_TOPIC_TERMS if term in claim.text and term in _verification_text(chunk)),
    )
    header = str(chunk.metadata.get("header") or "").strip()
    header_tokens = tokenize(header)
    header_overlap = (
        len(left & header_tokens) / math.sqrt(len(left) * len(header_tokens))
        if header_tokens
        else 0.0
    )
    header_bonus = min(0.38, header_overlap * 0.55)
    if header and header.lower() in claim.text.lower():
        header_bonus = max(header_bonus, 0.34)
    row_key = str(chunk.metadata.get("row_key") or "").strip()
    row_bonus = 0.0
    if row_key:
        if row_key.lower() in claim.text.lower():
            row_has_quantity = bool(extract_facts(row_key))
            claim_has_quantity = any(fact.kind == "number" for fact in claim.facts)
            if not row_has_quantity and claim_has_quantity:
                row_bonus = 0.30
            elif not row_has_quantity:
                row_bonus = 0.08
        else:
            month_match = re.search(r"(?<!\d)(1[0-2]|0?[1-9])月", claim.text)
            iso_match = re.fullmatch(r"20\d{2}-(0[1-9]|1[0-2])", row_key)
            if month_match and iso_match and int(month_match.group(1)) == int(iso_match.group(1)):
                row_bonus = 0.16
    claim_negative = any(term in claim.text for term in NEGATIVE_TERMS)
    evidence_negative = any(term in chunk.text for term in NEGATIVE_TERMS)
    local_overlap_count = len(left & local_tokens)
    polarity_bonus = 0.34 if claim_negative != evidence_negative and local_overlap_count >= 6 else 0.0
    category_bonus = 0.0
    category_penalty = 0.0
    if rules:
        claim_categories = _categories(claim.text, rules)
        evidence_categories = _categories(chunk.search_text, rules)
        for group_id, claim_values in claim_categories.items():
            evidence_values = evidence_categories.get(group_id)
            if not evidence_values:
                continue
            if claim_values & evidence_values:
                category_bonus += 0.24
            elif claim_values.isdisjoint(evidence_values):
                # Contradicting scope is still valuable audit evidence. Do not
                # rank it out; only avoid giving it the agreement bonus.
                category_penalty += 0.0
        category_bonus = min(category_bonus, 0.48)
        category_penalty = min(category_penalty, 0.0)
    structured_scope = " ".join(
        item
        for item in [header, row_key]
        if item
    )
    claim_years = set(re.findall(r"20\d{2}", claim.text))
    evidence_years = set(re.findall(r"20\d{2}", structured_scope))
    temporal_penalty = 0.30 if claim_years and evidence_years and claim_years.isdisjoint(evidence_years) else 0.0
    fragment_penalty = 0.0
    if (
        chunk.locator.kind in {"sheet_cell", "table_cell"}
        and not claim.facts
        and not extract_facts(chunk.text)
        and len(local_tokens) < max(3, math.ceil(len(left) * 0.45))
    ):
        fragment_penalty = 0.28
    raw_score = (
        overlap
        + number_bonus
        + exact_bonus
        + section_bonus
        + min(0.24, filename_overlap * 0.34)
        + topic_bonus
        + local_topic_bonus
        + header_bonus
        + row_bonus
        + polarity_bonus
        + category_bonus
        - category_penalty
        - temporal_penalty
        - fragment_penalty
    )
    raw_score = max(0.0, raw_score)
    # Keep scores in [0, 1) without collapsing strong candidates into ties.
    return raw_score / (1.0 + raw_score)


def retrieve(
    claim: Claim,
    chunks: list[ParsedChunk],
    limit: int = 60,
    rules: dict | None = None,
) -> list[tuple[ParsedChunk, float]]:
    ranked = sorted(
        ((chunk, lexical_score(claim, chunk, rules)) for chunk in chunks),
        key=lambda item: item[1],
        reverse=True,
    )
    return [(chunk, score) for chunk, score in ranked[:limit] if score > 0]


def _categories(text: str, rules: dict) -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    lowered = text.lower()
    for group in rules.get("exclusive_categories", []):
        matches: list[tuple[int, int, str]] = []
        for category, terms in group.get("values", {}).items():
            for term in terms:
                normalized = str(term).lower()
                start = lowered.find(normalized)
                while start >= 0:
                    matches.append((start, start + len(normalized), category))
                    start = lowered.find(normalized, start + 1)
        # Prefer the longest phrase at overlapping positions. This prevents
        # “无需补充” from simultaneously matching both “无需” and “需补充”
        # while still allowing genuinely different clauses to carry opposing
        # categories.
        accepted: list[tuple[int, int, str]] = []
        for start, end, category in sorted(matches, key=lambda item: (-(item[1] - item[0]), item[0])):
            if any(start < current_end and end > current_start for current_start, current_end, _ in accepted):
                continue
            accepted.append((start, end, category))
        for _start, _end, category in accepted:
            found.setdefault(group["id"], set()).add(category)
    return found


def _category_conflicts(claim_text: str, evidence_text: str, rules: dict) -> list[tuple[str, set[str], set[str], IssueCode]]:
    left = _categories(claim_text, rules)
    groups = {group["id"]: group for group in rules.get("exclusive_categories", [])}

    def compare(right: dict[str, set[str]]) -> list[tuple[str, set[str], set[str], IssueCode]]:
        conflicts = []
        for group_id, claim_values in left.items():
            evidence_values = right.get(group_id)
            if evidence_values and claim_values.isdisjoint(evidence_values):
                code_value = groups.get(group_id, {}).get("issue_code", "scope_mismatch")
                try:
                    code = IssueCode(code_value)
                except ValueError:
                    code = IssueCode.SCOPE_MISMATCH
                conflicts.append((group_id, claim_values, evidence_values, code))
        return conflicts

    whole_conflicts = compare(_categories(evidence_text, rules))
    if whole_conflicts:
        return whole_conflicts
    # A sentence may mention two scenarios for different purposes, e.g.
    # “收入采用基准情景，乐观情景仅用于压力测试”. Bagging the whole
    # sentence hides the relationship. Compare claim-relevant clauses so the
    # category attached to the same subject/predicate remains auditable.
    claim_tokens = tokenize(claim_text)
    scoped: list[tuple[str, set[str], set[str], IssueCode]] = []
    seen: set[tuple[str, tuple[str, ...], tuple[str, ...]]] = set()
    for clause in re.split(r"[，,；;。！？!?]", evidence_text):
        if len(claim_tokens & tokenize(clause)) < 2:
            continue
        for conflict in compare(_categories(clause, rules)):
            key = (conflict[0], tuple(sorted(conflict[1])), tuple(sorted(conflict[2])))
            if key not in seen:
                scoped.append(conflict)
                seen.add(key)
    return scoped


def _cross_candidate_category_conflict(
    claim: Claim,
    candidates: list[tuple[ParsedChunk, float]],
    rules: dict,
) -> tuple[ParsedChunk, list[tuple[str, set[str], set[str], IssueCode]]] | None:
    if not candidates or not claim.qualifiers:
        return None
    top_score = candidates[0][1]
    for chunk, score in candidates[:6]:
        if score < max(0.24, top_score * 0.72):
            continue
        conflicts = _category_conflicts(claim.text, chunk.search_text, rules)
        if conflicts and len(tokenize(claim.text) & tokenize(chunk.search_text)) >= 3:
            return chunk, conflicts
    return None


def _entity_value_pairs(text: str, rules: dict) -> dict[tuple[str, str], set[tuple[str, str]]]:
    """Associate nearby quantities with configured entities.

    This catches relationship reversals such as “B 70%, A 30%” versus
    “B 30%, A 70%”, which an unordered bag-of-numbers comparison cannot.
    """

    facts = [fact for fact in extract_facts(text) if fact.kind == "number"]
    pairs: dict[tuple[str, str], set[tuple[str, str]]] = {}
    lowered = text.lower()
    for group in rules.get("exclusive_categories", []):
        if group.get("issue_code") != IssueCode.ENTITY_MISMATCH.value and "entity" not in str(group.get("id", "")):
            continue
        for category, terms in group.get("values", {}).items():
            for term in sorted((str(item) for item in terms), key=len, reverse=True):
                start = lowered.find(term.lower())
                while start >= 0:
                    end = start + len(term)
                    nearby = [
                        fact
                        for fact in facts
                        if fact.span_start is not None
                        and -4 <= fact.span_start - end <= 24
                    ]
                    if nearby:
                        nearest = min(nearby, key=lambda fact: abs((fact.span_start or 0) - end))
                        key = nearest.base_unit or nearest.unit or nearest.dimension or "scalar"
                        value = nearest.base_value or nearest.value
                        pairs.setdefault((str(group["id"]), str(category)), set()).add((str(key), value))
                    start = lowered.find(term.lower(), start + len(term))
    return pairs


def _entity_value_mismatch(claim: Claim, evidence_text: str, rules: dict) -> CheckDetail | None:
    left = _entity_value_pairs(claim.text, rules)
    right = _entity_value_pairs(evidence_text, rules)
    for entity in set(left) & set(right):
        left_values = left[entity]
        right_values = right[entity]
        common_units = {unit for unit, _value in left_values} & {unit for unit, _value in right_values}
        for unit in common_units:
            expected = {value for current_unit, value in left_values if current_unit == unit}
            actual = {value for current_unit, value in right_values if current_unit == unit}
            if expected.isdisjoint(actual):
                return CheckDetail(
                    code=IssueCode.NUMERIC_MISMATCH,
                    outcome="fail",
                    message=f"Quantity associated with entity '{entity[1]}' differs in the evidence.",
                    claim_value=", ".join(sorted(expected)),
                    evidence_value=", ".join(sorted(actual)),
                )
    return None


def _quantity_comparison(claim: Claim, evidence_text: str) -> tuple[list[CheckDetail], list[IssueCode]]:
    claim_numbers = [fact for fact in claim.facts if fact.kind == "number"]
    evidence_numbers = [fact for fact in extract_facts(evidence_text) if fact.kind == "number"]
    checks: list[CheckDetail] = []
    issues: list[IssueCode] = []
    for expected in claim_numbers:
        exact = [
            actual
            for actual in evidence_numbers
            if (actual.base_unit or actual.unit) == (expected.base_unit or expected.unit)
            and (actual.base_value or actual.value) == (expected.base_value or expected.value)
        ]
        if exact:
            checks.append(
                CheckDetail(
                    code=IssueCode.DIRECT_SUPPORT,
                    outcome="pass",
                    message="The normalized quantity is present in the evidence.",
                    claim_value=expected.raw,
                    evidence_value=exact[0].raw,
                )
            )
            continue
        same_dimension = [actual for actual in evidence_numbers if actual.dimension == expected.dimension]
        if same_dimension:
            issues.append(IssueCode.NUMERIC_MISMATCH)
            checks.append(
                CheckDetail(
                    code=IssueCode.NUMERIC_MISMATCH,
                    outcome="fail",
                    message="The evidence contains a different value for a comparable quantity.",
                    claim_value=expected.raw,
                    evidence_value=", ".join(item.raw for item in same_dimension[:4]),
                )
            )
            continue
        same_raw = [actual for actual in evidence_numbers if actual.value == expected.value and actual.unit != expected.unit]
        if same_raw:
            issues.append(IssueCode.UNIT_MISMATCH)
            checks.append(
                CheckDetail(
                    code=IssueCode.UNIT_MISMATCH,
                    outcome="fail",
                    message="The same figure appears under a different or incompatible unit.",
                    claim_value=expected.raw,
                    evidence_value=", ".join(item.raw for item in same_raw[:4]),
                )
            )
            continue
        checks.append(
            CheckDetail(
                code=IssueCode.WEAK_SUPPORT,
                outcome="warn",
                message="A material quantity in the claim is not stated in the candidate evidence.",
                claim_value=expected.raw,
            )
        )
    return checks, list(dict.fromkeys(issues))


def _aggregate_quantity(
    claim: Claim,
    candidates: list[tuple[ParsedChunk, float]],
) -> tuple[NormalizedFact, Decimal, list[ParsedChunk]] | None:
    if not any(term in claim.text for term in ("累计", "合计", "总计", "共计")):
        return None
    expected_facts = [
        fact
        for fact in claim.facts
        if fact.kind == "number" and (fact.base_unit or fact.unit) in {"CNY", "USD", "COUNT"}
    ]
    if len(expected_facts) != 1:
        return None
    expected = expected_facts[0]
    expected_unit = expected.base_unit or expected.unit
    payment_claim = any(term in claim.text for term in ("付款", "款项", "支付", "收款"))
    contributing: list[ParsedChunk] = []
    values: list[Decimal] = []
    seen_files: set[str] = set()
    for chunk, _score in candidates:
        if chunk.file_hash in seen_files:
            continue
        if payment_claim and "回单" not in chunk.file_name:
            continue
        matching = [
            fact
            for fact in extract_facts(chunk.text)
            if fact.kind == "number"
            and (fact.base_unit or fact.unit) == expected_unit
            and fact.base_value is not None
        ]
        if not matching:
            continue
        try:
            value = Decimal(matching[0].base_value)
        except InvalidOperation:
            continue
        seen_files.add(chunk.file_hash)
        contributing.append(chunk)
        values.append(value)
    if len(contributing) < 2:
        return None
    return expected, sum(values, Decimal("0")), contributing


def _date_to_day(value: str, *, end: bool = False) -> date | None:
    parts = value.split("-")
    try:
        if len(parts) == 1:
            return date(int(parts[0]), 12 if end else 1, 31 if end else 1)
        if len(parts) == 2:
            year, month = map(int, parts)
            if end:
                next_month = date(year + (month == 12), 1 if month == 12 else month + 1, 1)
                return next_month - timedelta(days=1)
            return date(year, month, 1)
        return date.fromisoformat("-".join(parts[:3]))
    except (ValueError, TypeError):
        return None


def _freshness_check(claim: Claim, evidence_text: str, rules: dict, as_of_date: str) -> CheckDetail | None:
    freshness_terms = rules.get("freshness_terms", [])
    expiry_terms = rules.get("expiry_terms", ["有效期至", "到期", "失效"])
    freshness_claim = any(term in claim.text for term in freshness_terms)
    expiry_evidence = any(term in evidence_text for term in expiry_terms)
    if not freshness_claim and not expiry_evidence:
        return None
    dates = [fact.value for fact in extract_facts(evidence_text) if fact.kind == "date"]
    resolved = [_date_to_day(value, end=True) for value in dates]
    resolved = [value for value in resolved if value]
    if not resolved:
        return None
    latest = max(resolved)
    anchor = date.fromisoformat(as_of_date)
    window_days = int(rules.get("freshness_window_days", 548))
    stale = latest < anchor if expiry_evidence else latest < anchor - timedelta(days=window_days)
    return CheckDetail(
        code=IssueCode.STALE_EVIDENCE,
        outcome="fail" if stale else "pass",
        message=("The evidence is expired or outside the configured freshness window." if stale else "The evidence date is within the configured window."),
        evidence_value=latest.isoformat(),
    )


def _structured_metric_matches(left: ParsedChunk, right: ParsedChunk, claim: Claim) -> bool:
    """Prevent unrelated cells in the same workbook from becoming conflicts."""

    left_header = str(left.metadata.get("header") or "").strip().lower()
    right_header = str(right.metadata.get("header") or "").strip().lower()
    left_row = str(left.metadata.get("row_key") or "").strip().lower()
    right_row = str(right.metadata.get("row_key") or "").strip().lower()
    if left_header and right_header and left_header != right_header:
        return False
    one_header = left_header or right_header
    if one_header and not (left_header and right_header):
        generic_tokens = {"元", "个", "件", "台", "天", "年", "数", "量", "值"}
        if not ((tokenize(one_header) & tokenize(claim.text)) - generic_tokens):
            return False
    if left_row and right_row and left_row != right_row:
        return False
    return True


def _verification_text(chunk: ParsedChunk) -> str:
    return (
        chunk.search_text
        if chunk.locator.kind in {"sheet_cell", "table_cell"}
        else chunk.text
    )


def _numeric_verification_text(chunk: ParsedChunk) -> str:
    """Return the smallest text span that owns a structured numeric value.

    Spreadsheet and Word-table search context intentionally includes the full
    row for retrieval and scope checks. Numeric comparison must stay at the
    selected cell, otherwise sibling metrics (orders, rates, costs) become
    false contradictions to an exact value in the target cell.
    """

    if chunk.locator.kind in {"sheet_cell", "table_cell"}:
        return chunk.text
    return _verification_text(chunk)


def _best_quantity_chunk(
    claim: Claim,
    candidates: list[tuple[ParsedChunk, float]],
) -> ParsedChunk:
    """Choose the cell that owns the claim's quantity inside a structured row.

    A report may say “运费环比下降 8%” while retrieval correctly lands first
    on the adjacent “运费支出” cell. When the top candidate has no comparable
    quantity, an adjacent same-row cell with the expected dimension is a
    better verification target than treating the whole row as one passage.
    """

    top_chunk, top_score = candidates[0]
    expected = [
        fact
        for fact in claim.facts
        if fact.kind == "number" and (fact.base_unit or fact.unit or fact.dimension) != "scalar"
    ]
    if not expected or top_chunk.locator.kind not in {"sheet_cell", "table_cell"}:
        return top_chunk
    expected_dimensions = {fact.dimension for fact in expected}
    expected_units = {fact.base_unit or fact.unit for fact in expected if fact.base_unit or fact.unit}

    def comparable(chunk: ParsedChunk) -> bool:
        facts = [fact for fact in extract_facts(_numeric_verification_text(chunk)) if fact.kind == "number"]
        return any(
            fact.dimension in expected_dimensions
            or (fact.base_unit or fact.unit) in expected_units
            for fact in facts
        )

    if comparable(top_chunk):
        return top_chunk
    top_sheet = top_chunk.locator.sheet
    top_row = str(top_chunk.metadata.get("row_key") or "")
    for chunk, score in candidates[1:16]:
        if score < max(0.16, top_score * 0.62):
            continue
        if chunk.file_hash != top_chunk.file_hash or chunk.locator.kind != top_chunk.locator.kind:
            continue
        if top_sheet and chunk.locator.sheet != top_sheet:
            continue
        candidate_row = str(chunk.metadata.get("row_key") or "")
        if top_row and candidate_row and top_row != candidate_row:
            continue
        if comparable(chunk):
            return chunk
    return top_chunk


def _material_quantity_facts(claim: Claim) -> list[NormalizedFact]:
    facts = []
    for fact in claim.facts:
        if fact.kind != "number":
            continue
        tail = claim.text[(fact.span_end or 0):(fact.span_end or 0) + 10]
        # “24家样本中有15家……” uses 24 as the population scope; the
        # auditable outcome is 15. Requiring both values in one metric cell
        # creates a false contradiction even when the numerator is exact.
        if re.match(r"\s*(?:个)?样本中(?:有)?", tail):
            continue
        facts.append(fact)
    return facts


def _quantity_comparison_candidates(
    claim: Claim,
    candidates: list[tuple[ParsedChunk, float]],
    rules: dict,
) -> tuple[list[CheckDetail], list[IssueCode], list[ParsedChunk]]:
    """Compare each material quantity with its best structured evidence cell."""

    material_facts = _material_quantity_facts(claim)
    comparison_claim = claim.model_copy(update={"facts": material_facts})
    top_chunk, top_score = candidates[0]
    if not material_facts or top_chunk.locator.kind not in {"sheet_cell", "table_cell"}:
        checks, issues = _quantity_comparison(comparison_claim, _numeric_verification_text(top_chunk))
        return checks, issues, [top_chunk] * len(checks)

    def exact_count(chunk: ParsedChunk) -> int:
        evidence_facts = [fact for fact in extract_facts(_numeric_verification_text(chunk)) if fact.kind == "number"]
        return sum(
            any(
                (actual.base_unit or actual.unit) == (expected.base_unit or expected.unit)
                and (actual.base_value or actual.value) == (expected.base_value or expected.value)
                for actual in evidence_facts
            )
            for expected in material_facts
        )

    # Prefer a coherent passage that states every quantity over combining
    # cells. This is common for methodology notes and interview summaries.
    complete = [
        (chunk, score)
        for chunk, score in candidates[:16]
        if score >= max(0.16, top_score * 0.58)
        and exact_count(chunk) == len(material_facts)
    ]
    top_has_comparable = any(
        fact.kind == "number"
        and any(
            actual.dimension == fact.dimension
            or (
                (fact.base_unit or fact.unit)
                and (actual.base_unit or actual.unit) == (fact.base_unit or fact.unit)
            )
            for actual in extract_facts(_numeric_verification_text(top_chunk))
            if actual.kind == "number"
        )
        for fact in material_facts
    )
    coherent_external = [
        item for item in complete if item[0].locator.kind not in {"sheet_cell", "table_cell"}
    ]
    if len(material_facts) >= 2 and complete:
        chunk, _score = max(complete, key=lambda item: item[1])
        checks, issues = _quantity_comparison(comparison_claim, _numeric_verification_text(chunk))
        return checks, issues, [chunk] * len(checks)
    if not top_has_comparable and coherent_external:
        chunk, _score = max(coherent_external, key=lambda item: item[1])
        checks, issues = _quantity_comparison(comparison_claim, _numeric_verification_text(chunk))
        return checks, issues, [chunk] * len(checks)

    claim_tokens = tokenize(claim.text)
    claim_categories = _categories(claim.text, rules)
    checks: list[CheckDetail] = []
    issues: list[IssueCode] = []
    used_chunks: list[ParsedChunk] = []
    for expected in material_facts:
        eligible: list[tuple[float, ParsedChunk]] = []
        expected_unit = expected.base_unit or expected.unit
        for chunk, score in candidates[:20]:
            if score < max(0.14, top_score * 0.52):
                continue
            if chunk.locator.kind != top_chunk.locator.kind or chunk.file_hash != top_chunk.file_hash:
                continue
            evidence_facts = [
                fact
                for fact in extract_facts(_numeric_verification_text(chunk))
                if fact.kind == "number"
            ]
            comparable = [
                fact
                for fact in evidence_facts
                if fact.dimension == expected.dimension
                or (expected_unit and (fact.base_unit or fact.unit) == expected_unit)
            ]
            if not comparable:
                continue
            header_tokens = tokenize(str(chunk.metadata.get("header") or ""))
            row_tokens = tokenize(str(chunk.metadata.get("row_key") or ""))
            header_match = (
                len(claim_tokens & header_tokens) / math.sqrt(len(claim_tokens) * len(header_tokens))
                if header_tokens
                else 0.0
            )
            row_match = (
                len(claim_tokens & row_tokens) / math.sqrt(len(claim_tokens) * len(row_tokens))
                if row_tokens
                else 0.0
            )
            exact = any(
                (actual.base_unit or actual.unit) == expected_unit
                and (actual.base_value or actual.value) == (expected.base_value or expected.value)
                for actual in comparable
            )
            evidence_categories = _categories(chunk.search_text, rules)
            category_score = 0.0
            for group_id, claim_values in claim_categories.items():
                evidence_values = evidence_categories.get(group_id)
                if not evidence_values:
                    continue
                category_score += 0.20 if claim_values & evidence_values else -0.18
            semantic_score = (
                score
                + header_match * 0.48
                + row_match * 0.18
                + (0.04 if exact else 0.0)
                + max(-0.36, min(0.40, category_score))
            )
            eligible.append((semantic_score, chunk))
        selected = max(eligible, key=lambda item: item[0])[1] if eligible else top_chunk
        single_claim = claim.model_copy(update={"facts": [expected]})
        current_checks, current_issues = _quantity_comparison(
            single_claim,
            _numeric_verification_text(selected),
        )
        checks.extend(current_checks)
        issues.extend(current_issues)
        used_chunks.extend([selected] * len(current_checks))
    return checks, list(dict.fromkeys(issues)), used_chunks


def _relevant_number_values(chunk: ParsedChunk, claim: Claim) -> dict[str, set[str]]:
    expected_keys = {
        (fact.base_unit or fact.unit or fact.dimension)
        for fact in claim.facts
        if fact.kind == "number" and (fact.base_unit or fact.unit or fact.dimension) != "scalar"
    }
    values: dict[str, set[str]] = {}
    for fact in extract_facts(_numeric_verification_text(chunk)):
        if fact.kind != "number":
            continue
        key = fact.base_unit or fact.unit or fact.dimension
        if key in expected_keys:
            values.setdefault(str(key), set()).add(fact.base_value or fact.value)
    return values


def _source_conflict(candidates: list[tuple[ParsedChunk, float]], claim: Claim, rules: dict) -> tuple[ParsedChunk, ParsedChunk] | None:
    if len(candidates) < 2:
        return None
    if any(term in claim.text for term in ("累计", "合计", "总计", "共计")):
        return None
    top_chunk, top_score = candidates[0]
    top_values = _relevant_number_values(top_chunk, claim)
    if not top_values:
        return None
    for other, score in candidates[1:50]:
        if top_chunk.search_text == other.search_text:
            continue
        if _category_conflicts(claim.text, other.search_text, rules):
            continue
        if not _structured_metric_matches(top_chunk, other, claim):
            continue
        structured_pair = bool(top_chunk.metadata.get("header") and other.metadata.get("header"))
        if score < (0.18 if structured_pair else max(0.18, top_score * 0.58)):
            continue
        other_values = _relevant_number_values(other, claim)
        common = set(top_values) & set(other_values)
        if not any(top_values[key].isdisjoint(other_values[key]) for key in common):
            continue
        overlap = tokenize(top_chunk.search_text) & tokenize(other.search_text) & tokenize(claim.text)
        if structured_pair or len(overlap) >= 3:
            return top_chunk, other
    return None


def _authority_for(chunk: ParsedChunk, rules: dict) -> str:
    name = chunk.file_name.lower()
    for item in rules.get("source_authority", []):
        if any(str(pattern).lower() in name for pattern in item.get("patterns", [])):
            return item.get("level", "unknown")
    return "unknown"


def _absolute_numeric_counterexample(
    claim: Claim,
    candidates: list[tuple[ParsedChunk, float]],
) -> ParsedChunk | None:
    """Return a concrete row/cell that disproves an absolute threshold claim.

    For statements such as “all warehouses are above 99%” or “every region is
    below three days”, the most useful evidence is the violating outlier, not
    the first row that happens to satisfy the threshold.
    """

    if not any(term in claim.qualifiers for term in ("全部", "所有", "均")):
        return None
    comparator: tuple[str, bool] | None = None
    for term, direction, inclusive in (
        ("不低于", "minimum", True),
        ("不小于", "minimum", True),
        ("至少", "minimum", True),
        ("高于", "minimum", False),
        ("大于", "minimum", False),
        ("超过", "minimum", False),
        ("不高于", "maximum", True),
        ("不超过", "maximum", True),
        ("至多", "maximum", True),
        ("低于", "maximum", False),
        ("小于", "maximum", False),
    ):
        if term in claim.text:
            comparator = (direction, inclusive)
            break
    if comparator is None or not candidates:
        return None
    thresholds = _material_quantity_facts(claim)
    if not thresholds:
        return None
    threshold = thresholds[-1]
    threshold_unit = threshold.base_unit or threshold.unit
    try:
        threshold_value = Decimal(threshold.base_value or threshold.value)
    except InvalidOperation:
        return None

    top_score = candidates[0][1]
    claim_tokens = tokenize(claim.text)
    violations: list[tuple[Decimal, float, ParsedChunk]] = []
    for chunk, score in candidates[:40]:
        if score < max(0.14, top_score * 0.48):
            continue
        header = str(chunk.metadata.get("header") or "")
        if header and not (claim_tokens & tokenize(header)):
            continue
        for fact in extract_facts(_numeric_verification_text(chunk)):
            if fact.kind != "number":
                continue
            fact_unit = fact.base_unit or fact.unit
            if threshold_unit and fact_unit != threshold_unit:
                continue
            if not threshold_unit and fact.dimension != threshold.dimension:
                continue
            try:
                actual = Decimal(fact.base_value or fact.value)
            except InvalidOperation:
                continue
            direction, inclusive = comparator
            if direction == "minimum":
                violates = actual < threshold_value if inclusive else actual <= threshold_value
                distance = threshold_value - actual
            else:
                violates = actual > threshold_value if inclusive else actual >= threshold_value
                distance = actual - threshold_value
            if violates:
                violations.append((distance, score, chunk))
    if not violations:
        return None
    return max(violations, key=lambda item: (item[0], item[1]))[2]


def _expiry_evidence_candidate(
    claim: Claim,
    candidates: list[tuple[ParsedChunk, float]],
    rules: dict,
) -> ParsedChunk | None:
    if not any(term in claim.text for term in rules.get("freshness_terms", [])):
        return None
    expiry_terms = tuple(rules.get("expiry_terms", ["有效期至", "到期", "失效", "过期"]))
    return next(
        (
            chunk
            for chunk, _score in candidates[:30]
            if any(term in chunk.quote for term in expiry_terms)
            and any(fact.kind == "date" for fact in extract_facts(chunk.quote))
        ),
        None,
    )


def _review_category_counterexample(
    claim: Claim,
    candidates: list[tuple[ParsedChunk, float]],
    rules: dict,
) -> ParsedChunk | None:
    """Find a category counterexample for the reviewer without changing status.

    The decision engine deliberately uses a narrow cross-candidate window to
    avoid treating another supplier, region, or scenario as the claim's source
    of truth. The review panel can safely be broader: surfacing a plausible
    counterexample is useful even when a human must decide whether it applies.
    """

    if not candidates or not _categories(claim.text, rules):
        return None
    top_score = candidates[0][1]
    has_absolute_scope = any(term in claim.qualifiers for term in ("全部", "所有", "均"))
    eligible: list[tuple[bool, float, ParsedChunk]] = []
    authority_weight = {"primary": 0.30, "derived": 0.16, "self_reported": 0.05, "unknown": 0.0}
    for chunk, score in candidates[:30]:
        if score < max(0.24, top_score * (0.58 if has_absolute_scope else 0.70)):
            continue
        local_conflicts = _category_conflicts(claim.text, chunk.quote, rules)
        conflicts = local_conflicts or _category_conflicts(claim.text, chunk.search_text, rules)
        if not conflicts:
            continue
        if not has_absolute_scope and all(code == IssueCode.ENTITY_MISMATCH for _group, _left, _right, code in conflicts):
            continue
        if len(tokenize(claim.text) & tokenize(chunk.search_text)) < 3:
            continue
        if not has_absolute_scope:
            direct_topic = any(
                term.lower() in claim.text.lower() and term.lower() in chunk.file_name.lower()
                for term in FILE_TOPIC_TERMS
            )
            grouped_topic = any(
                any(term in claim.text for term in claim_terms)
                and any(term in chunk.file_name for term in file_terms)
                for claim_terms, file_terms in FILE_TOPIC_GROUPS
            )
            if not direct_topic and not grouped_topic:
                continue
        structured_bonus = 0.30 if chunk.locator.kind in {"sheet_cell", "table_cell"} else 0.0
        authority_bonus = authority_weight.get(_authority_for(chunk, rules), 0.0)
        local_overlap = len(tokenize(claim.text) & tokenize(chunk.quote))
        review_score = score + structured_bonus + authority_bonus + min(0.18, local_overlap * 0.025)
        eligible.append((bool(local_conflicts), review_score, chunk))
    if not eligible:
        return None
    local = [item for item in eligible if item[0]]
    return max(local or eligible, key=lambda item: item[1])[2]


def _review_priority_chunks(
    claim: Claim,
    candidates: list[tuple[ParsedChunk, float]],
    rules: dict,
) -> list[ParsedChunk]:
    """Identify passages that materially drive the audit decision."""

    priority: list[ParsedChunk] = []
    category_counterexample = _review_category_counterexample(claim, candidates, rules)
    if category_counterexample:
        priority.append(category_counterexample)
    absolute_counterexample = _absolute_numeric_counterexample(claim, candidates)
    if absolute_counterexample:
        priority.append(absolute_counterexample)
    if candidates and any(fact.kind == "number" for fact in claim.facts):
        _checks, _issues, quantity_chunks = _quantity_comparison_candidates(claim, candidates, rules)
        priority.extend(quantity_chunks)
    expiry = _expiry_evidence_candidate(claim, candidates, rules)
    if expiry:
        priority.append(expiry)
    unique: list[ParsedChunk] = []
    seen: set[str] = set()
    for chunk in priority:
        if chunk.id in seen:
            continue
        unique.append(chunk)
        seen.add(chunk.id)
    return unique


def _evidence_items(candidates: list[tuple[ParsedChunk, float]], claim: Claim, rules: dict) -> list[Evidence]:
    suffix = claim.id.split("-")[-1]
    # Keep the strongest exact fragments while guaranteeing that the first
    # five expose at least one independent source when one is available.
    # Reviewers otherwise see five sibling cells/blocks from the same file and
    # can miss a corroborating contract, receipt, or source document.
    selected: list[tuple[ParsedChunk, float]] = []
    if candidates:
        selected.append(candidates[0])
        primary_hash = candidates[0][0].file_hash
        diverse = next(
            (candidate for candidate in candidates[1:20] if candidate[0].file_hash != primary_hash),
            None,
        )
        if diverse:
            selected.append(diverse)
        selected_ids = {chunk.id for chunk, _score in selected}
        candidates_by_id = {candidate[0].id: candidate for candidate in candidates}
        for chunk in _review_priority_chunks(claim, candidates, rules):
            if chunk.id in selected_ids:
                continue
            selected.append(candidates_by_id[chunk.id])
            selected_ids.add(chunk.id)
            if len(selected) == 5:
                break
        for candidate in candidates[1:]:
            if len(selected) == 5:
                break
            if candidate[0].id in selected_ids:
                continue
            selected.append(candidate)
            selected_ids.add(candidate[0].id)
    selected_ids = {chunk.id for chunk, _score in selected}
    seen_files = {chunk.file_hash for chunk, _score in selected}
    for candidate in candidates:
        chunk, _score = candidate
        if chunk.id in selected_ids or chunk.file_hash in seen_files:
            continue
        selected.append(candidate)
        selected_ids.add(chunk.id)
        seen_files.add(chunk.file_hash)
        if len(selected) == 8:
            break
    for candidate in candidates:
        if candidate[0].id in selected_ids:
            continue
        selected.append(candidate)
        selected_ids.add(candidate[0].id)
        if len(selected) == 8:
            break
    items = []
    for index, (chunk, score) in enumerate(selected):
        source_dates = [fact.value for fact in extract_facts(chunk.search_text) if fact.kind == "date"]
        stored_quote = chunk.quote[:1600]
        items.append(
            Evidence(
                id=f"evidence-{suffix}-{index + 1}",
                chunk_id=chunk.id,
                file_path=chunk.file_path,
                file_name=chunk.file_name,
                file_hash=chunk.file_hash,
                quote=stored_quote,
                context_text=chunk.search_text[:2400] if chunk.search_text != chunk.quote else None,
                quote_hash=sha256_text(stored_quote),
                locator=chunk.locator,
                score=round(score, 4),
                rank=index + 1,
                confidence=chunk.confidence,
                authority=_authority_for(chunk, rules),
                source_date=max(source_dates) if source_dates else None,
            )
        )
    return items


def verify(
    claim: Claim,
    candidates: list[tuple[ParsedChunk, float]],
    rules: dict,
    *,
    as_of_date: str | None = None,
) -> Finding:
    finding_id = f"finding-{claim.id.split('-')[-1]}"
    evidence = _evidence_items(candidates, claim, rules)
    as_of_date = as_of_date or date.today().isoformat()
    if not candidates or candidates[0][1] < float(rules.get("retrieval", {}).get("minimum_score", 0.08)):
        return Finding(
            id=finding_id,
            claim_id=claim.id,
            status=FindingStatus.UNSUPPORTED,
            severity="high",
            confidence=0.9,
            explanation="No sufficiently relevant passage was found in the supplied evidence set.",
            evidence=evidence,
            issue_codes=[IssueCode.MISSING_EVIDENCE],
            checks=[CheckDetail(code=IssueCode.MISSING_EVIDENCE, outcome="fail", message="No relevant evidence candidate was retrieved.")],
        )

    top_chunk, top_score = candidates[0]
    top_text = _verification_text(top_chunk)
    low_ocr_threshold = float(rules.get("ocr", {}).get("review_below", 0.72))
    aggregate = _aggregate_quantity(claim, candidates)
    if aggregate:
        expected, computed, contributing = aggregate
        contributing_ids = {item.id for item in contributing}
        evidence_ids = []
        for item in evidence:
            if item.chunk_id in contributing_ids:
                item.relation = EvidenceRelation.SUPPORTS
                evidence_ids.append(item.id)
        expected_value = Decimal(expected.base_value or expected.value)
        calculation = CheckDetail(
            code=IssueCode.DERIVED_CALCULATION,
            outcome="pass" if computed == expected_value else "fail",
            message="The reported aggregate was recalculated from distinct source records.",
            claim_value=_decimal_text(expected_value),
            evidence_value=_decimal_text(computed),
            evidence_ids=evidence_ids,
        )
        low_confidence = min(item.confidence for item in contributing) < low_ocr_threshold
        if computed != expected_value:
            return Finding(
                id=finding_id,
                claim_id=claim.id,
                status=FindingStatus.CONFLICT,
                severity="high",
                confidence=0.92,
                explanation="The reported aggregate does not equal the sum of the retrieved source records.",
                evidence=evidence,
                issue_codes=[IssueCode.DERIVED_CALCULATION, IssueCode.NUMERIC_MISMATCH],
                checks=[calculation],
            )
        if low_confidence:
            return Finding(
                id=finding_id,
                claim_id=claim.id,
                status=FindingStatus.NEEDS_REVIEW,
                severity="medium",
                confidence=min(item.confidence for item in contributing),
                explanation="The aggregate reconciles, but one or more contributing OCR records require visual confirmation.",
                evidence=evidence,
                issue_codes=[IssueCode.DERIVED_CALCULATION, IssueCode.OCR_UNCERTAINTY],
                checks=[
                    calculation,
                    CheckDetail(
                        code=IssueCode.OCR_UNCERTAINTY,
                        outcome="warn",
                        message="A contributing OCR record falls below the configured review threshold.",
                        evidence_ids=evidence_ids,
                    ),
                ],
            )
        return Finding(
            id=finding_id,
            claim_id=claim.id,
            status=FindingStatus.SUPPORTED,
            severity="low",
            confidence=0.94,
            explanation="The reported aggregate reconciles to distinct source records under the normalized unit.",
            evidence=evidence,
            issue_codes=[IssueCode.DERIVED_CALCULATION],
            checks=[calculation],
        )
    if top_chunk.confidence < low_ocr_threshold:
        evidence[0].relation = EvidenceRelation.QUALIFIES
        return Finding(
            id=finding_id,
            claim_id=claim.id,
            status=FindingStatus.NEEDS_REVIEW,
            severity="medium",
            confidence=top_chunk.confidence,
            explanation="The closest evidence came from low-confidence OCR and requires visual confirmation.",
            evidence=evidence,
            issue_codes=[IssueCode.OCR_UNCERTAINTY],
            checks=[
                CheckDetail(
                    code=IssueCode.OCR_UNCERTAINTY,
                    outcome="warn",
                    message=f"OCR confidence {top_chunk.confidence:.2f} is below {low_ocr_threshold:.2f}.",
                    evidence_ids=[evidence[0].id],
                )
            ],
        )

    cross_category = _cross_candidate_category_conflict(claim, candidates, rules)
    if cross_category:
        conflict_chunk, conflicts = cross_category
        issue_codes = list(dict.fromkeys(item[3] for item in conflicts))
        for item in evidence:
            if item.chunk_id == conflict_chunk.id:
                item.relation = EvidenceRelation.CONTRADICTS
        checks = [
            CheckDetail(
                code=code,
                outcome="fail",
                message=f"Relevant evidence uses a conflicting value for exclusive scope '{group}'.",
                claim_value=", ".join(sorted(left)),
                evidence_value=", ".join(sorted(right)),
                evidence_ids=[item.id for item in evidence if item.chunk_id == conflict_chunk.id],
            )
            for group, left, right, code in conflicts
        ]
        return Finding(
            id=finding_id,
            claim_id=claim.id,
            status=FindingStatus.CONFLICT,
            severity="high",
            confidence=min(0.97, 0.65 + cross_category[0].confidence / 4),
            explanation="A materially relevant candidate uses a conflicting entity, category, or statistical scope.",
            evidence=evidence,
            issue_codes=issue_codes,
            checks=checks,
        )

    source_conflict = _source_conflict(candidates, claim, rules)
    if source_conflict:
        for item in evidence:
            if item.chunk_id == source_conflict[0].id:
                item.relation = EvidenceRelation.SUPPORTS
            elif item.chunk_id == source_conflict[1].id:
                item.relation = EvidenceRelation.CONTRADICTS
        return Finding(
            id=finding_id,
            claim_id=claim.id,
            status=FindingStatus.CONFLICT,
            severity="high",
            confidence=min(0.96, 0.66 + top_score / 3),
            explanation="Two materially relevant sources state different values under a comparable scope.",
            evidence=evidence,
            issue_codes=[IssueCode.SOURCE_CONFLICT],
            checks=[
                CheckDetail(
                    code=IssueCode.SOURCE_CONFLICT,
                    outcome="fail",
                    message="Relevant evidence sources conflict and require a human source-of-truth decision.",
                    evidence_ids=[item.id for item in evidence if item.chunk_id in {source_conflict[0].id, source_conflict[1].id}],
                )
            ],
        )

    category_conflicts = _category_conflicts(claim.text, top_text, rules)
    if category_conflicts:
        issue_codes = list(dict.fromkeys(item[3] for item in category_conflicts))
        evidence[0].relation = EvidenceRelation.CONTRADICTS
        checks = [
            CheckDetail(
                code=code,
                outcome="fail",
                message=f"Exclusive scope '{group}' differs between claim and evidence.",
                claim_value=", ".join(sorted(left)),
                evidence_value=", ".join(sorted(right)),
                evidence_ids=[evidence[0].id],
            )
            for group, left, right, code in category_conflicts
        ]
        return Finding(
            id=finding_id,
            claim_id=claim.id,
            status=FindingStatus.CONFLICT,
            severity="high",
            confidence=min(0.98, 0.68 + top_score / 3),
            explanation="The claim and evidence use mutually exclusive entities, categories, or statistical scopes.",
            evidence=evidence,
            issue_codes=issue_codes,
            checks=checks,
        )

    paired_mismatch = _entity_value_mismatch(claim, top_text, rules)
    if paired_mismatch:
        evidence[0].relation = EvidenceRelation.CONTRADICTS
        paired_mismatch.evidence_ids = [evidence[0].id]
        return Finding(
            id=finding_id,
            claim_id=claim.id,
            status=FindingStatus.CONFLICT,
            severity="high",
            confidence=min(0.97, 0.67 + top_score / 3),
            explanation="The evidence assigns a material value to a different entity or reverses the claimed allocation.",
            evidence=evidence,
            issue_codes=[IssueCode.NUMERIC_MISMATCH],
            checks=[paired_mismatch],
        )

    quantity_checks, quantity_issues, quantity_chunks = _quantity_comparison_candidates(
        claim,
        candidates,
        rules,
    )
    for check, quantity_chunk in zip(quantity_checks, quantity_chunks):
        if not check.evidence_ids:
            check.evidence_ids = [item.id for item in evidence if item.chunk_id == quantity_chunk.id]
    if quantity_issues:
        quantity_chunk_ids = {chunk.id for chunk in quantity_chunks}
        for item in evidence:
            if item.chunk_id in quantity_chunk_ids:
                item.relation = EvidenceRelation.CONTRADICTS
        return Finding(
            id=finding_id,
            claim_id=claim.id,
            status=FindingStatus.CONFLICT,
            severity="high",
            confidence=min(0.97, 0.64 + top_score / 3),
            explanation="The closest evidence discusses the same subject but a material value or unit differs.",
            evidence=evidence,
            issue_codes=quantity_issues,
            checks=quantity_checks,
        )

    claim_negative = any(term in claim.text for term in NEGATIVE_TERMS)
    # Spreadsheet search context contains sibling cells. Polarity belongs to
    # the selected cell itself; “运费另计” elsewhere in the row must not negate
    # a supplier, capital, date, or quantity claim.
    polarity_text = top_chunk.text if top_chunk.locator.kind in {"sheet_cell", "table_cell"} else top_text
    evidence_negative = any(term in polarity_text for term in NEGATIVE_TERMS)
    if claim_negative != evidence_negative and top_score >= 0.22:
        evidence[0].relation = EvidenceRelation.CONTRADICTS
        return Finding(
            id=finding_id,
            claim_id=claim.id,
            status=FindingStatus.CONFLICT,
            severity="high",
            confidence=min(0.95, 0.62 + top_score / 3),
            explanation="The evidence negates a material assertion in the claim, or vice versa.",
            evidence=evidence,
            issue_codes=[IssueCode.QUALIFIER_OVERREACH],
            checks=[CheckDetail(code=IssueCode.QUALIFIER_OVERREACH, outcome="fail", message="Negation differs between claim and evidence.", evidence_ids=[evidence[0].id])],
        )

    freshness = _freshness_check(claim, top_chunk.search_text, rules, as_of_date)
    if freshness and freshness.outcome == "fail":
        evidence[0].relation = EvidenceRelation.QUALIFIES
        return Finding(
            id=finding_id,
            claim_id=claim.id,
            status=FindingStatus.STALE,
            severity="medium",
            confidence=0.84,
            explanation="The claim uses current-validity language but the candidate evidence is expired or stale.",
            evidence=evidence,
            issue_codes=[IssueCode.STALE_EVIDENCE],
            checks=[freshness],
        )

    unsupported_qualifiers = [term for term in claim.qualifiers if term not in top_text]
    if unsupported_qualifiers:
        evidence[0].relation = EvidenceRelation.QUALIFIES
        return Finding(
            id=finding_id,
            claim_id=claim.id,
            status=FindingStatus.PARTIAL,
            severity="medium",
            confidence=min(0.9, 0.55 + top_score / 3),
            explanation="Evidence supports the topic but not every absolute or freshness qualifier in the claim.",
            evidence=evidence,
            issue_codes=[IssueCode.QUALIFIER_OVERREACH],
            checks=[CheckDetail(code=IssueCode.QUALIFIER_OVERREACH, outcome="warn", message="Unsupported qualifiers: " + ", ".join(unsupported_qualifiers), evidence_ids=[evidence[0].id])],
        )

    number_claim = any(fact.kind == "number" for fact in claim.facts)
    all_numbers_pass = number_claim and quantity_checks and all(item.outcome == "pass" for item in quantity_checks)
    if claim.text in top_text or (top_score >= 0.38 and (all_numbers_pass or not number_claim)):
        status = FindingStatus.SUPPORTED
        severity = "low"
        explanation = "A directly traceable passage supports the material facts and qualifiers in the claim."
        issue_codes = [IssueCode.DIRECT_SUPPORT]
        evidence[0].relation = EvidenceRelation.SUPPORTS
    elif top_score >= 0.16:
        status = FindingStatus.PARTIAL
        severity = "medium"
        explanation = "Related evidence was found, but it does not clearly support every material clause or qualifier."
        issue_codes = [IssueCode.WEAK_SUPPORT]
        evidence[0].relation = EvidenceRelation.QUALIFIES
    else:
        status = FindingStatus.UNSUPPORTED
        severity = "high"
        explanation = "The available passages are too weak to support the claim inside the supplied evidence pack."
        issue_codes = [IssueCode.MISSING_EVIDENCE]
    checks = quantity_checks or [
        CheckDetail(
            code=issue_codes[0],
            outcome="pass" if status == FindingStatus.SUPPORTED else "warn" if status == FindingStatus.PARTIAL else "fail",
            message=explanation,
            evidence_ids=[evidence[0].id] if evidence else [],
        )
    ]
    return Finding(
        id=finding_id,
        claim_id=claim.id,
        status=status,
        severity=severity,
        confidence=round(min(0.98, 0.5 + top_score / 2), 3),
        explanation=explanation,
        evidence=evidence,
        issue_codes=issue_codes,
        checks=checks,
    )


def _merge_rules(generic: dict, specific: dict) -> dict:
    merged = deepcopy(generic)
    for key, value in specific.items():
        if key == "name":
            merged[key] = value
        elif isinstance(value, list) and isinstance(merged.get(key), list):
            merged[key] = [*merged[key], *value]
        elif isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **value}
        else:
            merged[key] = value
    return merged


def rule_path(rule_pack: str) -> Path:
    if rule_pack not in {"generic-zh", "procurement-zh", "operations-zh", "consulting-zh", "lithium-demo"}:
        raise ValueError(f"unknown rule pack: {rule_pack}")
    root = (skill_root() / "assets" / "rules").resolve()
    selected = (root / f"{rule_pack}.yaml").resolve()
    try:
        selected.relative_to(root)
    except ValueError as exc:
        raise ValueError("rule pack path escapes the rule directory") from exc
    if not selected.is_file():
        raise ValueError(f"rule pack is not installed: {rule_pack}")
    return selected


def load_rules(rule_pack: str) -> dict:
    generic_path = rule_path("generic-zh")
    generic = yaml.safe_load(generic_path.read_text(encoding="utf-8"))
    if rule_pack == "generic-zh":
        return generic
    specific_path = rule_path(rule_pack)
    specific = yaml.safe_load(specific_path.read_text(encoding="utf-8"))
    return _merge_rules(generic, specific)


def _record_timing(job: AuditJob, name: str, started: float) -> None:
    job.stage_timings_ms[name] = round((time.perf_counter() - started) * 1000)


def _update_inventory(job: AuditJob, chunks: list[ParsedChunk], failures: list[str]) -> None:
    by_path: dict[str, list[ParsedChunk]] = {}
    for chunk in chunks:
        by_path.setdefault(str(Path(chunk.file_path).resolve()), []).append(chunk)
    for record in job.source_inventory:
        if record.role == "report":
            continue
        found = by_path.get(str(Path(record.snapshot_path).resolve()), [])
        record.parsed_chunks = len(found)
        record.ocr_chunks = sum(1 for item in found if item.metadata.get("ocr"))
        record.low_confidence_chunks = sum(1 for item in found if item.confidence < 0.72)
        if found:
            record.status = "parsed"
        else:
            record.status = "failed"
            record.error = next((item for item in failures if record.file_name in item), "no readable content")
    job.coverage_status = "complete" if all(item.status in {"ready", "parsed"} for item in job.source_inventory) and not failures else "incomplete"


def run_audit(job: AuditJob, store=None) -> tuple[AuditJob, list[ParsedChunk]]:
    total_started = time.perf_counter()
    job.status = "running"
    if not job.report_snapshot or not job.sources_snapshot:
        started = time.perf_counter()
        snapshot_inputs(job)
        _record_timing(job, "preflight_and_snapshot", started)
    report_path = Path(job.report_snapshot).resolve()
    sources_path = Path(job.sources_snapshot).resolve()
    work_dir = jobs_dir() / job.id

    started = time.perf_counter()
    report_chunks = parse_docx(report_path)
    _record_timing(job, "parse_report", started)
    report_record = next(item for item in job.source_inventory if item.role == "report")
    report_record.status = "parsed"
    report_record.parsed_chunks = len(report_chunks)

    started = time.perf_counter()
    evidence_chunks, warnings, failures = parse_evidence_directory(
        sources_path,
        work_dir / "ocr-cache",
        enable_ocr=job.request.profile in {"lite", "balanced"},
    )
    _record_timing(job, "parse_evidence", started)
    job.warnings.extend(warnings)
    _update_inventory(job, evidence_chunks, failures)

    started = time.perf_counter()
    claims = extract_claims(report_chunks)
    semantic_client = None
    if job.request.profile == "balanced":
        semantic_client = LocalSemanticClient(job.request.profile)
        try:
            semantic_client.healthcheck()
        except Exception as exc:
            raise ValueError(
                "the balanced profile requires a healthy loopback OpenVINO Model Server; "
                "start it on CLAIMLEDGER_MODEL_GATEWAY_URL or use --profile lite"
            ) from exc
        claims = augment_claims(claims, report_chunks, semantic_client)
        semantic_client.release("generation")
        semantic_client.prepare_evidence(evidence_chunks, [item.text for item in claims])
        semantic_client.release("embedding")
    if not claims:
        raise ValueError("no auditable claims were found in the report")
    _record_timing(job, "extract_claims", started)

    rules = load_rules(job.request.rule_pack)
    started = time.perf_counter()
    findings = []
    for claim in claims:
        if semantic_client:
            semantic_pool = semantic_client.semantic_candidates(claim.text, evidence_chunks)
            candidates = semantic_client.rerank(claim.text, semantic_pool)
        else:
            candidates = retrieve(claim, evidence_chunks, rules=rules)
        findings.append(verify(claim, candidates, rules, as_of_date=job.request.as_of_date))
    if semantic_client:
        semantic_client.release("reranker")
        job.runtime_metrics["model_gateway"] = semantic_client.status()
    _record_timing(job, "retrieve_and_verify", started)
    job.claims = claims
    job.findings = findings
    if store is not None and job.policy_snapshot.profile_id:
        from .memory import apply_memory_matches, apply_profile_guidance

        apply_profile_guidance(store, job)
        apply_memory_matches(store, job)
    job.status = "completed"
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    job.runtime_metrics["peak_rss_bytes"] = int(
        rss if sys.platform == "darwin" else rss * 1024
    )
    _record_timing(job, "total", total_started)
    return job, evidence_chunks


def recheck_replacement(job: AuditJob, finding_id: str, replacement_text: str) -> tuple[bool, str]:
    finding = next((item for item in job.findings if item.id == finding_id), None)
    if not finding:
        return False, "finding not found"
    original_claim = next(item for item in job.claims if item.id == finding.claim_id)
    replacement = original_claim.model_copy(
        update={
            "text": replacement_text,
            "facts": extract_facts(replacement_text),
            "qualifiers": _qualifiers(replacement_text),
        }
    )
    chunks = [
        ParsedChunk(
            id=item.chunk_id,
            file_path=item.file_path or item.file_name,
            file_name=item.file_name,
            file_hash=item.file_hash,
            source_type=Path(item.file_name).suffix.lower().lstrip("."),
            text=item.quote,
            raw_text=item.quote,
            context_text=item.context_text or item.quote,
            locator=item.locator,
            confidence=item.confidence,
        )
        for item in finding.evidence
    ]
    rules = load_rules(job.request.rule_pack)
    result = verify(
        replacement,
        retrieve(replacement, chunks, rules=rules),
        rules,
        as_of_date=job.request.as_of_date,
    )
    passed = result.status == FindingStatus.SUPPORTED
    return passed, f"replacement recheck: {result.status.value} — {result.explanation}"


def new_job(request: JobRequest, store=None) -> AuditJob:
    job = AuditJob(id=f"job-{uuid.uuid4().hex[:12]}", request=request)
    if request.review_profile:
        if store is None:
            from .storage import JobStore

            store = JobStore()
        from .memory import capture_policy_snapshot

        job.policy_snapshot = capture_policy_snapshot(store, request.review_profile)
    return job
