from __future__ import annotations

import sqlite3

import pytest

from claimledger.memory import (
    apply_memory_matches,
    capture_policy_snapshot,
    draft_policy,
    memory_from_decision,
    transition_policy,
)
from claimledger.models import (
    AuditJob,
    Claim,
    Decision,
    Finding,
    FindingStatus,
    IssueCode,
    JobRequest,
    Locator,
    NormalizedFact,
    ReviewerProfile,
)
from claimledger.storage import JobStore


def _job(profile_name: str | None = None) -> AuditJob:
    return AuditJob(
        id="job-test-memory",
        request=JobRequest(
            report_path="/tmp/report.docx",
            sources_path="/tmp/sources",
            rule_pack="operations-zh",
            review_profile=profile_name,
        ),
        claims=[
            Claim(
                id="claim-0001",
                text="本月运营成本为120万元。",
                claim_type="numeric",
                locator=Locator(kind="paragraph", paragraph=1),
                facts=[
                    NormalizedFact(
                        kind="number",
                        raw="120万元",
                        value="120",
                        unit="万元",
                        dimension="currency_cny",
                        base_value="1200000",
                        base_unit="CNY",
                    )
                ],
            )
        ],
        findings=[
            Finding(
                id="finding-0001",
                claim_id="claim-0001",
                status=FindingStatus.CONFLICT,
                severity="high",
                confidence=0.9,
                explanation="金额不一致",
                issue_codes=[IssueCode.NUMERIC_MISMATCH],
            )
        ],
    )


def test_schema_migrates_existing_jobs_table(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE jobs (id TEXT PRIMARY KEY, status TEXT NOT NULL, payload TEXT NOT NULL, updated_at TEXT NOT NULL)"
        )
    store = JobStore(path)
    assert store.schema_version() == 2
    assert store.list_profiles() == []


def test_memory_is_profile_isolated_and_advisory(tmp_path):
    store = JobStore(tmp_path / "memory.sqlite3")
    left = store.create_profile(ReviewerProfile(name="left", role_template="operations"))
    right = store.create_profile(ReviewerProfile(name="right", role_template="audit"))
    job = _job("left")
    job.policy_snapshot = capture_policy_snapshot(store, "left")
    decision = Decision(
        finding_id="finding-0001",
        action="accept",
        reason="确认金额冲突",
    )
    event = memory_from_decision(job, job.findings[0], job.claims[0], decision)
    assert event is not None
    store.add_memory(event)

    later = _job("left")
    later.policy_snapshot = capture_policy_snapshot(store, "left")
    apply_memory_matches(store, later)
    assert later.findings[0].memory_matches
    assert later.findings[0].memory_matches[0].advisory_only is True
    assert later.findings[0].status == FindingStatus.CONFLICT

    isolated = _job("right")
    isolated.policy_snapshot = capture_policy_snapshot(store, "right")
    apply_memory_matches(store, isolated)
    assert isolated.findings[0].memory_matches == []
    assert left.id != right.id


def test_waiver_memory_cannot_be_promoted(tmp_path):
    store = JobStore(tmp_path / "memory.sqlite3")
    store.create_profile(ReviewerProfile(name="auditor", role_template="audit"))
    job = _job("auditor")
    job.policy_snapshot = capture_policy_snapshot(store, "auditor")
    decision = Decision(
        finding_id="finding-0001",
        action="waive",
        reason="一次性业务例外",
    )
    event = memory_from_decision(job, job.findings[0], job.claims[0], decision)
    assert event is not None
    store.add_memory(event)
    with pytest.raises(ValueError, match="waiver"):
        draft_policy(
            store,
            event.id,
            actor="auditor",
            reason="不应成功",
        )


def test_policy_activation_only_changes_new_snapshots(tmp_path):
    store = JobStore(tmp_path / "memory.sqlite3")
    store.create_profile(ReviewerProfile(name="operator", role_template="operations"))
    original = capture_policy_snapshot(store, "operator")
    job = _job("operator")
    job.policy_snapshot = original
    event = memory_from_decision(
        job,
        job.findings[0],
        job.claims[0],
        Decision(
            finding_id="finding-0001",
            action="accept",
            reason="确认",
        ),
    )
    assert event is not None
    store.add_memory(event)
    draft = draft_policy(
        store,
        event.id,
        actor="operator",
        reason="以后重点关注",
        kind="severity_floor",
    )
    active = transition_policy(
        store,
        draft.id,
        target="active",
        actor="operator",
        reason="人工批准",
    )
    newer = capture_policy_snapshot(store, "operator")
    assert original.active_policy_ids == []
    assert newer.active_policy_ids == [active.id]
    assert original.policy_hash != newer.policy_hash


def test_reject_requires_high_similarity(tmp_path):
    store = JobStore(tmp_path / "memory.sqlite3")
    store.create_profile(ReviewerProfile(name="audit", role_template="audit"))
    source = _job("audit")
    source.policy_snapshot = capture_policy_snapshot(store, "audit")
    event = memory_from_decision(
        source,
        source.findings[0],
        source.claims[0],
        Decision(
            finding_id="finding-0001",
            action="reject",
            reason="该指标按含税口径填写",
        ),
    )
    assert event is not None
    store.add_memory(event)

    unrelated = _job("audit")
    unrelated.policy_snapshot = source.policy_snapshot
    unrelated.claims[0].text = "客户投诉率同比下降3个百分点。"
    unrelated.claims[0].facts = []
    unrelated.findings[0].issue_codes = [IssueCode.DATE_MISMATCH]
    apply_memory_matches(store, unrelated)
    assert unrelated.findings[0].memory_matches == []


def test_profile_delete_removes_memory_and_policy(tmp_path):
    store = JobStore(tmp_path / "memory.sqlite3")
    profile = store.create_profile(ReviewerProfile(name="delete-me"))
    job = _job("delete-me")
    job.policy_snapshot = capture_policy_snapshot(store, "delete-me")
    event = memory_from_decision(
        job,
        job.findings[0],
        job.claims[0],
        Decision(finding_id="finding-0001", action="accept", reason="确认"),
    )
    assert event is not None
    store.add_memory(event)
    draft = draft_policy(store, event.id, actor="owner", reason="测试")
    assert store.delete_profile(profile.id) is True
    assert store.get_memory(event.id) is None
    assert store.get_policy(draft.id) is None
