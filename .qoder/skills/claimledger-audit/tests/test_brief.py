from __future__ import annotations

from claimledger.brief import build_brief
from claimledger.cli import build_parser
from claimledger.models import (
    AuditJob,
    Claim,
    Decision,
    Finding,
    FindingStatus,
    JobRequest,
    Locator,
)


def _job() -> AuditJob:
    claims = [
        Claim(
            id="claim-supported",
            text="本月服务请求共 120 单。",
            claim_type="numeric",
            locator=Locator(kind="paragraph", paragraph=1),
        ),
        Claim(
            id="claim-conflict",
            text="本月履约率达到 98.6%。",
            claim_type="numeric",
            locator=Locator(kind="paragraph", paragraph=2),
        ),
        Claim(
            id="claim-unsupported",
            text="客户满意度达到行业领先水平。",
            claim_type="conclusion",
            locator=Locator(kind="paragraph", paragraph=3),
        ),
    ]
    findings = [
        Finding(
            id="finding-supported",
            claim_id="claim-supported",
            status=FindingStatus.SUPPORTED,
            severity="low",
            confidence=0.98,
            explanation="A directly traceable passage supports the material facts and qualifiers in the claim.",
        ),
        Finding(
            id="finding-conflict",
            claim_id="claim-conflict",
            status=FindingStatus.CONFLICT,
            severity="high",
            confidence=0.96,
            explanation="The closest evidence discusses the same subject but a material value or unit differs.",
            suggested_replacement="本月履约率为 96.8%。",
        ),
        Finding(
            id="finding-unsupported",
            claim_id="claim-unsupported",
            status=FindingStatus.UNSUPPORTED,
            severity="high",
            confidence=0.91,
            explanation="No sufficiently relevant passage was found in the supplied evidence set.",
        ),
    ]
    return AuditJob(
        id="job-brief-1",
        request=JobRequest(
            report_path="/private/customer/monthly-report.docx",
            sources_path="/private/customer/evidence",
            case_name="运营月报交付审计",
            rule_pack="operations-zh",
        ),
        status="completed",
        coverage_status="complete",
        claims=claims,
        findings=findings,
        warnings=["failed to read /private/customer/scan.pdf page 2"],
    )


def test_brief_is_chinese_ranked_and_path_safe():
    payload = build_brief(_job(), top=2)
    assert payload["schema_version"] == "claimledger-brief-v1"
    assert payload["phase_label"] == "人工复核待处理"
    assert payload["summary"]["candidate_findings"] == 3
    assert payload["top_findings"][0]["finding_id"] == "finding-conflict"
    assert payload["top_findings"][0]["status_label"] == "证据冲突"
    assert payload["top_findings"][0]["suggested_replacement"] == "本月履约率为 96.8%。"
    assert "/private/customer" not in str(payload)
    assert "[本地路径]" in payload["warnings"][0]


def test_brief_marks_resolved_items_without_reordering_history():
    job = _job()
    job.decisions.append(
        Decision(
            finding_id="finding-conflict",
            action="reject",
            reason="复核原始表后确认是系统误报",
        )
    )
    payload = build_brief(job, top=10)
    conflict = next(
        item for item in payload["top_findings"]
        if item["finding_id"] == "finding-conflict"
    )
    assert conflict["resolved"] is True
    assert payload["summary"]["unresolved_high"] == 1


def test_brief_clamps_top_and_does_not_expose_artifact_paths():
    job = _job()
    job.artifacts["audit"] = "/private/customer/output/audit.json"
    payload = build_brief(job, top=99)
    assert payload["top_limit"] == 10
    assert all("path" not in item for item in payload["artifacts"])


def test_brief_cli_contract():
    args = build_parser().parse_args(["brief", "job-123", "--top", "3", "--json"])
    assert args.command == "brief"
    assert args.job_id == "job-123"
    assert args.top == 3
    assert args.json is True
