from __future__ import annotations

import json
from datetime import date, datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _strict_iso_date(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    if len(value) != 10 or value[4] != "-" or value[7] != "-":
        raise ValueError(f"{field_name} must use YYYY-MM-DD")
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value:
        raise ValueError(f"{field_name} must use YYYY-MM-DD")
    return value


class FindingStatus(StrEnum):
    SUPPORTED = "supported"
    PARTIAL = "partial"
    UNSUPPORTED = "unsupported"
    CONFLICT = "conflict"
    STALE = "stale"
    NEEDS_REVIEW = "needs_review"


class IssueCode(StrEnum):
    DIRECT_SUPPORT = "direct_support"
    MISSING_EVIDENCE = "missing_evidence"
    WEAK_SUPPORT = "weak_support"
    NUMERIC_MISMATCH = "numeric_mismatch"
    UNIT_MISMATCH = "unit_mismatch"
    DATE_MISMATCH = "date_mismatch"
    ENTITY_MISMATCH = "entity_mismatch"
    SCOPE_MISMATCH = "scope_mismatch"
    QUALIFIER_OVERREACH = "qualifier_overreach"
    SOURCE_CONFLICT = "source_conflict"
    STALE_EVIDENCE = "stale_evidence"
    OCR_UNCERTAINTY = "ocr_uncertainty"
    DERIVED_CALCULATION = "derived_calculation"
    LOCATOR_UNCERTAINTY = "locator_uncertainty"


class EvidenceRelation(StrEnum):
    CANDIDATE = "candidate"
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    QUALIFIES = "qualifies"
    BACKGROUND = "background"


class Locator(BaseModel):
    kind: Literal["paragraph", "table_cell", "pdf_page", "sheet_cell", "image"]
    page: int | None = None
    paragraph: int | None = None
    table: int | None = None
    row: int | None = None
    column: int | None = None
    sheet: str | None = None
    cell: str | None = None
    end_cell: str | None = None
    bbox: list[float] | None = None
    canvas_width: float | None = None
    canvas_height: float | None = None
    char_start: int | None = None
    char_end: int | None = None
    section: str | None = None
    anchor_precision: Literal["span", "run", "paragraph", "cell", "range", "page", "bbox"] = "paragraph"

    def label(self) -> str:
        suffix = ""
        if self.char_start is not None and self.char_end is not None:
            suffix = f", chars {self.char_start}:{self.char_end}"
        if self.kind == "pdf_page":
            return f"page {self.page}" + (" · bbox" if self.bbox else "")
        if self.kind == "sheet_cell":
            cell = self.cell or "A1"
            if self.end_cell and self.end_cell != cell:
                cell = f"{cell}:{self.end_cell}"
            return f"{self.sheet}!{cell}"
        if self.kind == "table_cell":
            return f"table {self.table}, row {self.row}, column {self.column}{suffix}"
        if self.kind == "paragraph":
            return f"paragraph {self.paragraph}{suffix}"
        return "image" if not self.page else f"image page {self.page}"


class ParsedChunk(BaseModel):
    id: str
    file_path: str
    file_name: str
    file_hash: str
    source_type: str
    text: str
    raw_text: str | None = None
    context_text: str | None = None
    locator: Locator
    confidence: float = 1.0
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def quote(self) -> str:
        return self.raw_text if self.raw_text is not None else self.text

    @property
    def search_text(self) -> str:
        return self.context_text or self.text


class NormalizedFact(BaseModel):
    kind: Literal["number", "date", "entity", "term"]
    raw: str
    value: str
    unit: str | None = None
    dimension: str | None = None
    base_value: str | None = None
    base_unit: str | None = None
    span_start: int | None = None
    span_end: int | None = None


class Claim(BaseModel):
    id: str
    text: str
    claim_type: Literal["numeric", "date", "entity", "conclusion", "calculation"]
    locator: Locator
    facts: list[NormalizedFact] = Field(default_factory=list)
    parent_claim_id: str | None = None
    source_chunk_id: str | None = None
    atomic_index: int = 0
    qualifiers: list[str] = Field(default_factory=list)
    materiality: Literal["high", "medium", "low"] = "medium"


class Evidence(BaseModel):
    id: str
    chunk_id: str
    file_path: str | None = None
    file_name: str
    file_hash: str
    quote: str
    context_text: str | None = None
    quote_hash: str | None = None
    locator: Locator
    score: float
    rank: int = 1
    confidence: float = 1.0
    relation: EvidenceRelation = EvidenceRelation.CANDIDATE
    authority: Literal["primary", "derived", "self_reported", "unknown"] = "unknown"
    source_date: str | None = None


class CheckDetail(BaseModel):
    code: IssueCode
    outcome: Literal["pass", "fail", "warn", "not_applicable"]
    message: str
    claim_value: str | None = None
    evidence_value: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)


class Finding(BaseModel):
    id: str
    claim_id: str
    status: FindingStatus
    severity: Literal["high", "medium", "low"]
    confidence: float
    explanation: str
    evidence: list[Evidence] = Field(default_factory=list)
    issue_codes: list[IssueCode] = Field(default_factory=list)
    checks: list[CheckDetail] = Field(default_factory=list)
    suggested_replacement: str | None = None
    memory_matches: list["MemoryMatch"] = Field(default_factory=list)

    @field_validator("checks", mode="before")
    @classmethod
    def migrate_legacy_checks(cls, value):
        """Migrate free-form check dicts saved by v0.1.x jobs.

        Early jobs persisted debugging context as a plain dict, which predates
        the structured ``CheckDetail`` rows. Keep that context readable for
        auditability without letting it crash briefs, exports, or the review
        page; ``not_applicable`` keeps it out of the fail/warn brief channel.
        """

        if not isinstance(value, dict):
            return value
        migrated: list[CheckDetail] = []
        claim_numbers = value.get("claim_numbers")
        evidence_numbers = value.get("evidence_numbers")
        if claim_numbers is not None or evidence_numbers is not None:
            migrated.append(
                CheckDetail(
                    code=IssueCode.NUMERIC_MISMATCH,
                    outcome="not_applicable",
                    message="旧版本数值核对上下文(仅保留备查,未参与判定)",
                    claim_value=", ".join(str(item) for item in claim_numbers or []),
                    evidence_value=", ".join(str(item) for item in evidence_numbers or []),
                )
            )
        if "top_score" in value or "number_match" in value:
            migrated.append(
                CheckDetail(
                    code=IssueCode.WEAK_SUPPORT,
                    outcome="not_applicable",
                    message=(
                        "旧版本检索核对上下文(仅保留备查,未参与判定):"
                        f"top_score={value.get('top_score')}, "
                        f"number_match={value.get('number_match')}"
                    ),
                )
            )
        known = {"claim_numbers", "evidence_numbers", "top_score", "number_match"}
        unknown = {key: item for key, item in value.items() if key not in known}
        if unknown:
            migrated.append(
                CheckDetail(
                    code=IssueCode.DERIVED_CALCULATION,
                    outcome="not_applicable",
                    message="旧版本检查上下文(仅保留备查,未参与判定):"
                    + json.dumps(unknown, ensure_ascii=False, sort_keys=True),
                )
            )
        return migrated


class ReviewerProfile(BaseModel):
    id: str = Field(default_factory=lambda: f"profile-{uuid4().hex[:12]}")
    name: str
    role_template: Literal["generic", "audit", "operations", "consulting"] = "generic"
    preferences: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)

    @field_validator("name")
    @classmethod
    def valid_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or len(normalized) > 64:
            raise ValueError("profile name must contain 1-64 characters")
        return normalized


class ReviewerProfileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    role_template: Literal["generic", "audit", "operations", "consulting"] = "generic"
    preferences: dict[str, Any] = Field(default_factory=dict)


class MemoryEvent(BaseModel):
    id: str = Field(default_factory=lambda: f"memory-{uuid4().hex[:12]}")
    profile_id: str
    source_job_id: str
    finding_id: str
    decision_event_id: str
    action: Literal["accept", "reject", "replace", "waive"]
    claim_excerpt: str
    claim_type: str
    severity: Literal["high", "medium", "low"]
    rule_pack: str
    issue_codes: list[str] = Field(default_factory=list)
    normalized_facts: list[dict[str, Any]] = Field(default_factory=list)
    signature: str
    reason: str | None = None
    replacement_text: str | None = None
    created_at: str = Field(default_factory=utc_now)
    expires_at: str | None = None


class MemoryMatch(BaseModel):
    memory_id: str
    action: Literal["accept", "reject", "replace", "waive"]
    score: float
    match_factors: list[str] = Field(default_factory=list)
    source_job_id: str
    finding_id: str
    claim_excerpt: str
    reason: str | None = None
    replacement_text: str | None = None
    created_at: str
    advisory_only: bool = True


class PolicyRule(BaseModel):
    id: str = Field(default_factory=lambda: f"policy-{uuid4().hex[:12]}")
    profile_id: str
    version: int = 1
    state: Literal["draft", "active", "retired"] = "draft"
    source_memory_id: str
    rule: dict[str, Any] = Field(default_factory=dict)
    reason: str
    created_by: str = "local-user"
    created_at: str = Field(default_factory=utc_now)
    activated_at: str | None = None
    retired_at: str | None = None
    hash: str


class PolicyDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_memory_id: str
    kind: Literal["attention", "severity_floor", "terminology", "replacement_style"] = "attention"
    actor: str = "local-user"
    reason: str


class PolicyTransitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actor: str = "local-user"
    reason: str


class PolicySnapshot(BaseModel):
    profile_id: str | None = None
    profile_name: str | None = None
    role_template: Literal["generic", "audit", "operations", "consulting"] = "generic"
    role_version: str = "1"
    active_policy_ids: list[str] = Field(default_factory=list)
    memory_event_ids: list[str] = Field(default_factory=list)
    policy_hash: str | None = None
    memory_snapshot_hash: str | None = None
    captured_at: str = Field(default_factory=utc_now)


class Decision(BaseModel):
    event_id: str = Field(default_factory=lambda: f"decision-{uuid4().hex[:12]}")
    finding_id: str
    action: Literal["accept", "reject", "replace", "waive"]
    replacement_text: str | None = None
    reason: str | None = None
    selected_evidence_ids: list[str] = Field(default_factory=list)
    actor: str = "local-user"
    risk_owner: str | None = None
    waiver_expires_at: str | None = None
    waiver_scope: Literal["not_applicable", "permanent", "temporary"] = "not_applicable"
    recheck_status: Literal["not_required", "not_run", "passed", "failed"] = "not_required"
    recheck_message: str | None = None
    decided_at: str = Field(default_factory=utc_now)

    @field_validator("waiver_expires_at")
    @classmethod
    def valid_waiver_expiry(cls, value: str | None) -> str | None:
        return _strict_iso_date(value, "waiver_expires_at")

    @model_validator(mode="after")
    def validate_action_payload(self):
        if self.action in {"reject", "waive"} and not (self.reason or "").strip():
            raise ValueError(f"{self.action} decisions require a reason")
        if self.action == "replace" and not (self.replacement_text or "").strip():
            raise ValueError("replace decisions require replacement text")
        if self.action == "replace" and self.recheck_status == "not_required":
            self.recheck_status = "not_run"
        if self.action == "waive" and not self.risk_owner:
            self.risk_owner = self.actor
        if self.action == "waive":
            self.waiver_scope = "temporary" if self.waiver_expires_at else "permanent"
        else:
            if self.waiver_expires_at:
                raise ValueError("waiver_expires_at is only valid for waive decisions")
            self.waiver_scope = "not_applicable"
        return self


class DecisionRequest(BaseModel):
    """Client-submitted fields; event metadata is always server-generated."""

    model_config = ConfigDict(extra="forbid")

    finding_id: str
    action: Literal["accept", "reject", "replace", "waive"]
    replacement_text: str | None = None
    reason: str | None = None
    selected_evidence_ids: list[str] = Field(default_factory=list)
    actor: str = "local-user"
    risk_owner: str | None = None
    waiver_expires_at: str | None = None

    @field_validator("waiver_expires_at")
    @classmethod
    def valid_waiver_expiry(cls, value: str | None) -> str | None:
        return _strict_iso_date(value, "waiver_expires_at")

    @model_validator(mode="after")
    def validate_action_payload(self):
        if self.action in {"reject", "waive"} and not (self.reason or "").strip():
            raise ValueError(f"{self.action} decisions require a reason")
        if self.action == "replace" and not (self.replacement_text or "").strip():
            raise ValueError("replace decisions require replacement text")
        if self.action != "waive" and self.waiver_expires_at:
            raise ValueError("waiver_expires_at is only valid for waive decisions")
        return self

    def to_decision(self) -> Decision:
        return Decision(**self.model_dump())


class JobRequest(BaseModel):
    report_path: str
    sources_path: str
    case_name: str = "claimledger-audit"
    profile: Literal["deterministic", "lite", "balanced"] = "lite"
    rule_pack: str = "generic-zh"
    as_of_date: str = Field(default_factory=lambda: date.today().isoformat())
    review_profile: str | None = None

    @field_validator("report_path")
    @classmethod
    def report_must_be_docx(cls, value: str) -> str:
        if Path(value).suffix.lower() != ".docx":
            raise ValueError("the audited report must be a DOCX file")
        return value

    @field_validator("rule_pack")
    @classmethod
    def safe_rule_pack(cls, value: str) -> str:
        allowed = {"generic-zh", "procurement-zh", "operations-zh", "consulting-zh", "lithium-demo"}
        if value not in allowed:
            raise ValueError(f"unknown rule pack: {value}")
        return value

    @field_validator("as_of_date")
    @classmethod
    def valid_as_of_date(cls, value: str) -> str:
        date.fromisoformat(value)
        return value


class SourceRecord(BaseModel):
    id: str
    role: Literal["report", "evidence"]
    original_path: str
    snapshot_path: str
    file_name: str
    file_hash: str
    size_bytes: int
    status: Literal["ready", "parsed", "failed", "skipped"] = "ready"
    error: str | None = None
    page_count: int | None = None
    parsed_chunks: int = 0
    ocr_chunks: int = 0
    low_confidence_chunks: int = 0


class ArtifactManifest(BaseModel):
    job_id: str
    created_at: str = Field(default_factory=utc_now)
    decision_revision: int = 0
    artifact_bundle_id: str | None = None
    artifact_kind: Literal["standard", "final"] | None = None
    inputs: list[SourceRecord] = Field(default_factory=list)
    outputs: dict[str, str] = Field(default_factory=dict)
    profile: str
    rule_pack: str
    rule_hash: str | None = None
    models: dict[str, Any] = Field(default_factory=dict)
    runtime: dict[str, Any] = Field(default_factory=dict)
    run_parameters: dict[str, Any] = Field(default_factory=dict)
    review_profile_id: str | None = None
    role_template_version: str | None = None
    policy_version_hash: str | None = None
    memory_snapshot_hash: str | None = None
    package_version: str = "0.5.1"


class AuditJob(BaseModel):
    id: str
    state_revision: int = 0
    decision_revision: int = 0
    status: Literal["queued", "running", "completed", "failed"] = "queued"
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)
    request: JobRequest
    report_snapshot: str | None = None
    sources_snapshot: str | None = None
    source_inventory: list[SourceRecord] = Field(default_factory=list)
    coverage_status: Literal["pending", "complete", "incomplete"] = "pending"
    claims: list[Claim] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    decisions: list[Decision] = Field(default_factory=list)
    artifacts: dict[str, str] = Field(default_factory=dict)
    artifact_hashes: dict[str, str] = Field(default_factory=dict)
    artifacts_revision: int | None = None
    artifacts_kind: Literal["standard", "final"] | None = None
    artifact_bundle_id: str | None = None
    artifact_history: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    integrity_issues: list[str] = Field(default_factory=list)
    stage_timings_ms: dict[str, int] = Field(default_factory=dict)
    runtime_metrics: dict[str, Any] = Field(default_factory=dict)
    policy_snapshot: PolicySnapshot = Field(default_factory=PolicySnapshot)
    error: str | None = None

    @model_validator(mode="after")
    def normalize_decision_revision(self):
        # Backward-compatible migration for jobs saved before decision revisions
        # were introduced.
        self.decision_revision = max(self.decision_revision, len(self.decisions))
        return self

    def latest_decisions(self) -> dict[str, Decision]:
        latest: dict[str, Decision] = {}
        for decision in self.decisions:
            latest[decision.finding_id] = decision
        return latest

    def invalidate_artifacts(self, reason: str) -> None:
        """Stop advertising an artifact bundle after the review state changes.

        Historical bundles remain immutable on disk for auditability, but only
        ``artifacts`` is the current deliverable pointer.
        """

        if self.artifacts:
            self.artifact_history.append(
                {
                    "revision": self.artifacts_revision,
                    "kind": self.artifacts_kind,
                    "bundle_id": self.artifact_bundle_id,
                    "artifacts": dict(self.artifacts),
                    "artifact_hashes": dict(self.artifact_hashes),
                    "invalidated_at": utc_now(),
                    "reason": reason,
                }
            )
        self.artifacts = {}
        self.artifact_hashes = {}
        self.artifacts_revision = None
        self.artifacts_kind = None
        self.artifact_bundle_id = None

    def record_decision(self, decision: Decision) -> None:
        self.decision_revision = max(self.decision_revision, len(self.decisions))
        self.invalidate_artifacts(f"superseded by decision event {decision.event_id}")
        self.decisions.append(decision)
        self.decision_revision += 1

    def decision_resolves(self, decision: Decision | None) -> bool:
        if decision is None or decision.action == "accept":
            return False
        if decision.action == "replace":
            return decision.recheck_status == "passed"
        if decision.action == "waive":
            if decision.waiver_expires_at:
                return date.fromisoformat(decision.waiver_expires_at) >= date.today()
            return True
        return decision.action == "reject"

    def summary(self) -> dict[str, int | bool | str]:
        counts: dict[str, int | bool | str] = {status.value: 0 for status in FindingStatus}
        for finding in self.findings:
            counts[finding.status.value] = int(counts[finding.status.value]) + 1
        latest = self.latest_decisions()
        unresolved_high = sum(
            1
            for finding in self.findings
            if finding.severity == "high" and not self.decision_resolves(latest.get(finding.id))
        )
        counts["total"] = len(self.findings)
        counts["decision_events"] = len(self.decisions)
        counts["decision_revision"] = self.decision_revision
        counts["unresolved_high"] = unresolved_high
        counts["expired_waivers"] = sum(
            1
            for decision in latest.values()
            if decision.action == "waive"
            and decision.waiver_expires_at
            and date.fromisoformat(decision.waiver_expires_at) < date.today()
        )
        counts["coverage_status"] = self.coverage_status
        counts["artifacts_current"] = bool(
            self.artifacts and self.artifacts_revision == self.decision_revision
        )
        counts["delivery_ready"] = bool(
            self.status == "completed"
            and self.coverage_status == "complete"
            and unresolved_high == 0
            and not self.integrity_issues
            and bool(self.findings)
        )
        counts["delivery_artifact_current"] = bool(
            counts["delivery_ready"]
            and counts["artifacts_current"]
            and self.artifacts_kind == "final"
            and "delivery_report" in self.artifacts
        )
        return counts
