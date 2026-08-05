from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .localization import (
    COVERAGE_ZH,
    ISSUE_ZH,
    SEVERITY_ZH,
    STATUS_ZH,
    locator_zh,
    message_zh,
    zh,
)
from .models import AuditJob, Finding


_STATUS_PRIORITY = {
    "conflict": 0,
    "unsupported": 1,
    "stale": 2,
    "partial": 3,
    "needs_review": 4,
    "supported": 5,
}
_ARTIFACT_LABELS = {
    "annotated_report": "带批注报告",
    "claim_ledger": "证据台账",
    "audit": "审计 JSON",
    "manifest": "产物清单",
    "delivery_report": "最终交付稿",
}
_LOCAL_PATH = re.compile(r"(?:/[^\s:：]+){2,}|[A-Za-z]:\\(?:[^\\\s]+\\)+[^\\\s]*")


def _short(value: str | None, limit: int) -> str:
    text = " ".join((value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 1)].rstrip() + "…"


def _safe_warning(value: str) -> str:
    return _short(_LOCAL_PATH.sub("[本地路径]", value), 180)


def _suggested_action(finding: Finding) -> str:
    return {
        "conflict": "确认权威来源后修正结论，无法消除时由责任人正式豁免。",
        "unsupported": "补充可定位证据，或删除、收窄无依据表述。",
        "stale": "换用有效期内证据，或调整“当前、最新”等时效表述。",
        "partial": "收窄结论范围，或补充能覆盖全部限定条件的材料。",
        "needs_review": "查看原始证据和定位信息后人工确认。",
        "supported": "当前无需处理，交付前仍可抽样复验。",
    }[finding.status.value]


def _difference(finding: Finding) -> str:
    checks = [
        message_zh(item.message)
        for item in finding.checks
        if item.outcome in {"fail", "warn"} and item.message
    ]
    if checks:
        return _short("；".join(dict.fromkeys(checks)), 260)
    return _short(message_zh(finding.explanation), 260)


def _finding_sort_key(
    item: tuple[int, Finding],
    job: AuditJob,
) -> tuple[int, int, int]:
    report_index, finding = item
    resolved = job.decision_resolves(job.latest_decisions().get(finding.id))
    unresolved_high = finding.severity == "high" and not resolved
    return (
        0 if unresolved_high else 1,
        _STATUS_PRIORITY.get(finding.status.value, 99),
        report_index,
    )


def _phase(job: AuditJob, delivery_ready: bool) -> tuple[str, str]:
    if delivery_ready:
        return "trusted_delivery", "可信交付可生成"
    if job.status == "completed":
        return "human_review", "人工复核待处理"
    return "automatic_audit", "自动审计进行中"


def build_brief(job: AuditJob, top: int = 5) -> dict[str, Any]:
    """Return a compact, token-free Chinese brief for agent and widget use."""

    top = max(1, min(int(top), 10))
    summary = job.summary()
    latest = job.latest_decisions()
    phase, phase_label = _phase(job, bool(summary["delivery_ready"]))
    ranked = sorted(enumerate(job.findings), key=lambda item: _finding_sort_key(item, job))
    claims = {claim.id: claim for claim in job.claims}
    findings: list[dict[str, Any]] = []
    for report_index, finding in ranked[:top]:
        claim = claims.get(finding.claim_id)
        evidence = finding.evidence[0] if finding.evidence else None
        resolved = job.decision_resolves(latest.get(finding.id))
        findings.append(
            {
                "report_order": report_index + 1,
                "finding_id": finding.id,
                "review_anchor": finding.id,
                "status": finding.status.value,
                "status_label": zh(STATUS_ZH, finding.status.value),
                "severity": finding.severity,
                "severity_label": zh(SEVERITY_ZH, finding.severity),
                "resolved": resolved,
                "claim": _short(claim.text if claim else "", 320),
                "report_location": locator_zh(claim.locator) if claim else "报告位置未知",
                "evidence_summary": _short(evidence.quote if evidence else "未找到可用证据", 240),
                "evidence_location": (
                    f"{Path(evidence.file_name).name} · {locator_zh(evidence.locator)}"
                    if evidence
                    else "未定位到证据"
                ),
                "difference": _difference(finding),
                "suggested_action": _suggested_action(finding),
                "suggested_replacement": _short(finding.suggested_replacement, 320)
                if finding.suggested_replacement
                else None,
                "issue_labels": [
                    zh(ISSUE_ZH, issue.value) for issue in finding.issue_codes
                ],
            }
        )

    status_counts = {
        status: {
            "label": label,
            "count": int(summary.get(status, 0)),
        }
        for status, label in STATUS_ZH.items()
    }
    available = set(job.artifacts)
    artifacts = [
        {
            "kind": kind,
            "label": label,
            "available": kind in available,
        }
        for kind, label in _ARTIFACT_LABELS.items()
    ]
    risk_total = len(job.findings) - int(summary.get("supported", 0))
    report_name = (
        Path(job.source_inventory[0].file_name).name
        if job.source_inventory
        else Path(job.request.report_path).name
    )
    return {
        "schema_version": "claimledger-brief-v1",
        "job_id": job.id,
        "case_name": _short(job.request.case_name, 120),
        "report_name": report_name,
        "rule_pack": job.request.rule_pack,
        "phase": phase,
        "phase_label": phase_label,
        "coverage_status": job.coverage_status,
        "coverage_label": zh(COVERAGE_ZH, job.coverage_status),
        "summary": {
            "candidate_findings": len(job.findings),
            "risk_findings": risk_total,
            "unresolved_high": int(summary["unresolved_high"]),
            "human_decisions": int(summary["decision_events"]),
            "delivery_ready": bool(summary["delivery_ready"]),
        },
        "status_counts": status_counts,
        "top_findings": findings,
        "top_limit": top,
        "warnings": [_safe_warning(item) for item in job.warnings[:3]],
        "warning_count": len(job.warnings),
        "artifacts": artifacts,
        "final_export_available": bool(summary["delivery_ready"]),
        "next_step": (
            "所有交付阻断项已处理，可以生成最终交付包。"
            if summary["delivery_ready"]
            else "请先逐条处理未解决的高风险候选发现。"
        ),
    }
