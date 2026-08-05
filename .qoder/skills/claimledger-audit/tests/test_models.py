from __future__ import annotations

import pytest
from pydantic import ValidationError

from claimledger.models import (
    AuditJob,
    CheckDetail,
    Claim,
    Decision,
    Finding,
    FindingStatus,
    IssueCode,
    JobRequest,
    Locator,
)


def test_report_must_be_docx():
    with pytest.raises(ValidationError):
        JobRequest(report_path="report.pdf", sources_path="evidence")


def test_waiver_requires_reason():
    with pytest.raises(ValidationError):
        Decision(finding_id="finding-1", action="waive")


def high_risk_job() -> AuditJob:
    request = JobRequest(report_path="report.docx", sources_path="evidence")
    claim = Claim(
        id="claim-1",
        text="金额达到100万元。",
        claim_type="numeric",
        locator=Locator(kind="paragraph", paragraph=0),
    )
    finding = Finding(
        id="finding-1",
        claim_id=claim.id,
        status=FindingStatus.CONFLICT,
        severity="high",
        confidence=0.9,
        explanation="conflict",
    )
    return AuditJob(
        id="job-1",
        request=request,
        status="completed",
        coverage_status="complete",
        claims=[claim],
        findings=[finding],
    )


def test_accept_is_append_only_but_does_not_release_high_risk():
    job = high_risk_job()
    job.decisions.append(Decision(finding_id="finding-1", action="accept"))
    assert job.summary()["unresolved_high"] == 1
    assert job.summary()["delivery_ready"] is False

    job.decisions.append(Decision(finding_id="finding-1", action="reject", reason="confirmed false positive"))
    assert len(job.decisions) == 2
    assert job.summary()["unresolved_high"] == 0
    assert job.summary()["delivery_ready"] is True

    job.decisions.append(Decision(finding_id="finding-1", action="accept"))
    assert len(job.decisions) == 3
    assert job.summary()["unresolved_high"] == 1


def test_replacement_only_releases_risk_after_recheck_passes():
    job = high_risk_job()
    job.decisions.append(
        Decision(
            finding_id="finding-1",
            action="replace",
            replacement_text="金额达到90万元。",
            recheck_status="failed",
        )
    )
    assert job.summary()["unresolved_high"] == 1
    job.decisions.append(
        Decision(
            finding_id="finding-1",
            action="replace",
            replacement_text="金额达到100万元。",
            recheck_status="passed",
        )
    )
    assert job.summary()["unresolved_high"] == 0


def _legacy_finding_payload(checks) -> dict:
    return {
        "id": "finding-1",
        "claim_id": "claim-1",
        "status": "conflict",
        "severity": "high",
        "confidence": 0.72,
        "explanation": "legacy finding",
        "evidence": [],
        "checks": checks,
    }


def test_legacy_numeric_check_dict_migrates_to_structured_rows():
    finding = Finding.model_validate(
        _legacy_finding_payload({"claim_numbers": ["25", "85"], "evidence_numbers": ["202", "62"]})
    )
    assert len(finding.checks) == 1
    check = finding.checks[0]
    assert isinstance(check, CheckDetail)
    assert check.code == IssueCode.NUMERIC_MISMATCH
    assert check.outcome == "not_applicable"
    assert check.claim_value == "25, 85"
    assert check.evidence_value == "202, 62"


def test_legacy_retrieval_check_dict_migrates_without_crashing():
    finding = Finding.model_validate(
        _legacy_finding_payload({"top_score": 0.1549, "number_match": True})
    )
    assert len(finding.checks) == 1
    check = finding.checks[0]
    assert check.code == IssueCode.WEAK_SUPPORT
    assert check.outcome == "not_applicable"
    assert "top_score=0.1549" in check.message


def test_legacy_unknown_check_keys_are_preserved_as_context():
    finding = Finding.model_validate(_legacy_finding_payload({"custom_flag": "x"}))
    assert len(finding.checks) == 1
    assert finding.checks[0].outcome == "not_applicable"
    assert "custom_flag" in finding.checks[0].message


def test_legacy_checks_stay_out_of_the_fail_warn_brief_channel():
    finding = Finding.model_validate(
        _legacy_finding_payload({"claim_numbers": ["85"], "evidence_numbers": ["62"]})
    )
    assert all(check.outcome not in {"fail", "warn"} for check in finding.checks)
