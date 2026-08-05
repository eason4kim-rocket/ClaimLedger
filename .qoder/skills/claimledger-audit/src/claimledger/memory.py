from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import date, timedelta
from typing import Iterable

from .models import (
    AuditJob,
    Claim,
    Decision,
    Finding,
    MemoryEvent,
    MemoryMatch,
    PolicyRule,
    PolicySnapshot,
    ReviewerProfile,
    utc_now,
)
from .storage import JobStore
from .config import skill_root


ROLE_TEMPLATE_VERSION = "1"
SAFE_POLICY_KINDS = {"attention", "severity_floor", "terminology", "replacement_style"}


def _tokens(text: str) -> set[str]:
    lowered = text.lower()
    latin = set(re.findall(r"[a-z0-9]+", lowered))
    chinese_runs = re.findall(r"[\u4e00-\u9fff]+", lowered)
    grams: set[str] = set()
    for run in chinese_runs:
        grams.update(run[index:index + 2] for index in range(max(0, len(run) - 1)))
        if len(run) == 1:
            grams.add(run)
    return {item for item in latin | grams if item}


def stable_hash(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def claim_signature(claim: Claim, finding: Finding, rule_pack: str) -> str:
    payload = {
        "claim_type": claim.claim_type,
        "rule_pack": rule_pack,
        "issues": sorted(item.value for item in finding.issue_codes),
        "facts": [
            {
                "kind": fact.kind,
                "value": fact.base_value or fact.value,
                "unit": fact.base_unit or fact.unit,
                "dimension": fact.dimension,
            }
            for fact in claim.facts
        ],
        "qualifiers": sorted(claim.qualifiers),
    }
    return stable_hash(payload)


def capture_policy_snapshot(store: JobStore, profile_name: str | None) -> PolicySnapshot:
    if not profile_name:
        return PolicySnapshot(memory_snapshot_hash=stable_hash([]))
    profile = store.get_profile(profile_name)
    if not profile:
        raise ValueError(f"reviewer profile not found: {profile_name}")
    active = store.list_policies(profile.id, state="active")
    memories = store.list_memories(profile.id)
    return PolicySnapshot(
        profile_id=profile.id,
        profile_name=profile.name,
        role_template=profile.role_template,
        role_version=ROLE_TEMPLATE_VERSION,
        active_policy_ids=[item.id for item in active],
        memory_event_ids=[item.id for item in memories],
        policy_hash=stable_hash([item.model_dump(mode="json") for item in active]),
        memory_snapshot_hash=stable_hash(
            [{"id": item.id, "signature": item.signature, "action": item.action} for item in memories]
        ),
    )


def memory_from_decision(
    job: AuditJob,
    finding: Finding,
    claim: Claim,
    decision: Decision,
) -> MemoryEvent | None:
    profile_id = job.policy_snapshot.profile_id
    if not profile_id:
        return None
    expires = (date.today() + timedelta(days=365)).isoformat()
    return MemoryEvent(
        profile_id=profile_id,
        source_job_id=job.id,
        finding_id=finding.id,
        decision_event_id=decision.event_id,
        action=decision.action,
        claim_excerpt=claim.text[:240],
        claim_type=claim.claim_type,
        severity=finding.severity,
        rule_pack=job.request.rule_pack,
        issue_codes=[item.value for item in finding.issue_codes],
        normalized_facts=[
            {
                "kind": fact.kind,
                "value": fact.base_value or fact.value,
                "unit": fact.base_unit or fact.unit,
                "dimension": fact.dimension,
            }
            for fact in claim.facts
        ],
        signature=claim_signature(claim, finding, job.request.rule_pack),
        reason=decision.reason,
        replacement_text=decision.replacement_text[:240] if decision.replacement_text else None,
        expires_at=expires,
    )


def _fact_keys(items: Iterable[dict]) -> set[tuple[str, str, str]]:
    return {
        (
            str(item.get("kind") or ""),
            str(item.get("unit") or item.get("dimension") or ""),
            str(item.get("value") or ""),
        )
        for item in items
    }


def match_memories(
    store: JobStore,
    snapshot: PolicySnapshot,
    claim: Claim,
    finding: Finding,
    rule_pack: str,
    *,
    limit: int = 3,
) -> list[MemoryMatch]:
    if not snapshot.profile_id:
        return []
    target_signature = claim_signature(claim, finding, rule_pack)
    target_issues = {item.value for item in finding.issue_codes}
    target_facts = _fact_keys(
        {
            "kind": fact.kind,
            "value": fact.base_value or fact.value,
            "unit": fact.base_unit or fact.unit,
            "dimension": fact.dimension,
        }
        for fact in claim.facts
    )
    target_tokens = _tokens(claim.text)
    ranked: list[tuple[float, MemoryEvent, list[str]]] = []
    allowed_memory_ids = set(snapshot.memory_event_ids)
    for event in store.list_memories(snapshot.profile_id):
        if event.id not in allowed_memory_ids:
            continue
        factors: list[str] = []
        score = 0.0
        if event.signature == target_signature:
            score += 0.52
            factors.append("规范化事实指纹一致")
        if event.rule_pack == rule_pack:
            score += 0.10
            factors.append("规则包一致")
        if event.claim_type == claim.claim_type:
            score += 0.08
            factors.append("结论类型一致")
        issue_overlap = target_issues & set(event.issue_codes)
        if issue_overlap:
            score += min(0.18, 0.08 * len(issue_overlap))
            factors.append("问题代码：" + "、".join(sorted(issue_overlap)))
        fact_overlap = target_facts & _fact_keys(event.normalized_facts)
        if fact_overlap:
            score += min(0.18, 0.06 * len(fact_overlap))
            factors.append("数字/单位/日期口径相似")
        event_tokens = _tokens(event.claim_excerpt)
        if target_tokens and event_tokens:
            lexical = len(target_tokens & event_tokens) / math.sqrt(len(target_tokens) * len(event_tokens))
            score += min(0.20, lexical * 0.24)
            if lexical >= 0.35:
                factors.append("结论文本相似")
        # A rejected false-positive is intentionally held to a higher bar.
        threshold = 0.74 if event.action == "reject" else 0.45
        if score >= threshold:
            ranked.append((score, event, factors))
    ranked.sort(key=lambda item: (item[0], item[1].created_at), reverse=True)
    return [
        MemoryMatch(
            memory_id=event.id,
            action=event.action,
            score=round(min(1.0, score), 3),
            match_factors=factors,
            source_job_id=event.source_job_id,
            finding_id=event.finding_id,
            claim_excerpt=event.claim_excerpt,
            reason=event.reason,
            replacement_text=event.replacement_text,
            created_at=event.created_at,
        )
        for score, event, factors in ranked[:limit]
    ]


def apply_memory_matches(store: JobStore, job: AuditJob) -> None:
    claims = {item.id: item for item in job.claims}
    for finding in job.findings:
        claim = claims[finding.claim_id]
        finding.memory_matches = match_memories(
            store,
            job.policy_snapshot,
            claim,
            finding,
            job.request.rule_pack,
        )


def draft_policy(
    store: JobStore,
    memory_id: str,
    *,
    actor: str,
    reason: str,
    kind: str = "attention",
) -> PolicyRule:
    if kind not in SAFE_POLICY_KINDS:
        raise ValueError(f"unsupported safe policy kind: {kind}")
    memory = store.get_memory(memory_id)
    if not memory:
        raise ValueError("memory event not found")
    if memory.action == "waive":
        raise ValueError("waiver memories cannot be promoted into policy")
    version = max((item.version for item in store.list_policies(memory.profile_id)), default=0) + 1
    rule = {
        "kind": kind,
        "match": {
            "rule_pack": memory.rule_pack,
            "claim_type": memory.claim_type,
            "issue_codes": memory.issue_codes,
            "signature": memory.signature,
        },
        "effect": {
            "advisory": True,
            "never_auto_resolve": True,
            "source_action": memory.action,
            "severity_floor": memory.severity if kind == "severity_floor" else None,
        },
    }
    digest = stable_hash(
        {
            "profile_id": memory.profile_id,
            "version": version,
            "source_memory_id": memory.id,
            "rule": rule,
            "reason": reason,
        }
    )
    return store.save_policy(
        PolicyRule(
            profile_id=memory.profile_id,
            version=version,
            source_memory_id=memory.id,
            rule=rule,
            reason=reason,
            created_by=actor,
            hash=digest,
        )
    )


def transition_policy(
    store: JobStore,
    policy_id: str,
    *,
    target: str,
    actor: str,
    reason: str,
) -> PolicyRule:
    policy = store.get_policy(policy_id)
    if not policy:
        raise ValueError("policy not found")
    if target not in {"active", "retired"}:
        raise ValueError("policy target must be active or retired")
    if not reason.strip():
        raise ValueError("policy transition requires a reason")
    if target == "active" and policy.state != "draft":
        raise ValueError("only draft policies can be activated")
    if target == "retired" and policy.state != "active":
        raise ValueError("only active policies can be retired")
    updated = policy.model_copy(
        update={
            "state": target,
            "created_by": actor,
            "reason": reason,
            "activated_at": utc_now() if target == "active" else policy.activated_at,
            "retired_at": utc_now() if target == "retired" else None,
        }
    )
    return store.save_policy(updated)


def export_profile(profile: ReviewerProfile, policies: list[PolicyRule]) -> dict:
    """Export preferences and approved policy only; never export raw memory."""

    return {
        "format": "claimledger-review-profile-v1",
        "profile": {
            "name": profile.name,
            "role_template": profile.role_template,
            "preferences": profile.preferences,
        },
        "policies": [
            item.model_dump(mode="json", exclude={"profile_id"})
            for item in policies
            if item.state == "active"
        ],
    }


def _severity_rank(value: str) -> int:
    return {"low": 0, "medium": 1, "high": 2}.get(value, 0)


def _raise_severity(finding: Finding, floor: str | None) -> None:
    if floor and _severity_rank(floor) > _severity_rank(finding.severity):
        finding.severity = floor  # type: ignore[assignment]


def apply_profile_guidance(store: JobStore, job: AuditJob) -> None:
    """Apply only monotonic, review-preserving profile guidance.

    Role templates and approved policies may raise attention/severity. They
    never change finding status and never create a resolving decision.
    """

    if not job.policy_snapshot.profile_id:
        return
    template_path = (
        skill_root()
        / "assets"
        / "profiles"
        / f"{job.policy_snapshot.role_template}.yaml"
    )
    if template_path.is_file():
        import yaml

        template = yaml.safe_load(template_path.read_text(encoding="utf-8")) or {}
        floors = template.get("severity_floor_by_issue", {})
        for finding in job.findings:
            for code in finding.issue_codes:
                _raise_severity(finding, floors.get(code.value))

    claims = {item.id: item for item in job.claims}
    for policy_id in job.policy_snapshot.active_policy_ids:
        policy = store.get_policy(policy_id)
        if not policy:
            continue
        match = policy.rule.get("match", {})
        effect = policy.rule.get("effect", {})
        for finding in job.findings:
            claim = claims[finding.claim_id]
            signature = claim_signature(claim, finding, job.request.rule_pack)
            if match.get("signature") and match["signature"] != signature:
                continue
            required_issues = set(match.get("issue_codes", []))
            actual_issues = {item.value for item in finding.issue_codes}
            if required_issues and not required_issues.issubset(actual_issues):
                continue
            _raise_severity(finding, effect.get("severity_floor"))
