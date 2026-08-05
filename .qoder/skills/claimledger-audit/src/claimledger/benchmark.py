from __future__ import annotations

import json
from pathlib import Path
from typing import Any
import unicodedata

from .engine import new_job, run_audit
from .exporters import export_standard_artifacts
from .models import JobRequest


RISK_STATUSES = {"partial", "unsupported", "conflict", "stale", "needs_review"}


def _claim_key(text: str) -> str:
    return "".join(
        char
        for char in unicodedata.normalize("NFKC", text)
        if not char.isspace() and not unicodedata.category(char).startswith("P")
    )


def _matched_findings(job, label_text: str):
    """Match a gold sentence to one or more atomic findings.

    The runtime intentionally splits compound sentences into auditable atomic
    claims. A benchmark label may retain the original sentence, so exact string
    matching alone would incorrectly count a successful atomic extraction as a
    miss. Only atomic claims from the same source chunk may be reassembled.
    """

    label_key = _claim_key(label_text)
    findings = {item.claim_id: item for item in job.findings}
    exact = [
        findings[claim.id]
        for claim in job.claims
        if claim.id in findings and _claim_key(claim.text) == label_key
    ]
    if exact:
        return exact

    groups: dict[str, list] = {}
    for claim in job.claims:
        if claim.id not in findings:
            continue
        group_key = claim.source_chunk_id or claim.locator.label()
        groups.setdefault(group_key, []).append(claim)
    for claims in groups.values():
        claims.sort(key=lambda item: item.atomic_index)
        combined = "".join(_claim_key(item.text) for item in claims)
        if combined == label_key or label_key in combined:
            return [findings[item.id] for item in claims]
    return []


def _aggregate_status(findings) -> str:
    priority = {
        "conflict": 6,
        "unsupported": 5,
        "stale": 4,
        "partial": 3,
        "needs_review": 2,
        "supported": 1,
    }
    if not findings:
        return "missing"
    return max((item.status.value for item in findings), key=lambda value: priority[value])


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def _f1(precision: float, recall: float) -> float:
    return round(2 * precision * recall / (precision + recall), 4) if precision + recall else 0.0


def run_benchmark(dataset_path: Path, *, export_cases: bool = False) -> dict[str, Any]:
    dataset_path = dataset_path.expanduser().resolve()
    payload = json.loads(dataset_path.read_text(encoding="utf-8"))
    base = dataset_path.parent
    totals = {
        "labeled_claims": 0,
        "extracted_claims": 0,
        "matched_predictions": 0,
        "all_predictions": 0,
        "true_positives": 0,
        "false_positives": 0,
        "false_negatives": 0,
        "unlabeled_claims": 0,
        "unlabeled_risk_predictions": 0,
        "status_matches": 0,
        "evidence_expected": 0,
        "evidence_top5_hits": 0,
        "high_risk_expected": 0,
        "high_risk_hits": 0,
        "issue_true_positives": 0,
        "issue_false_positives": 0,
        "issue_false_negatives": 0,
        "issue_macro_f1_sum": 0.0,
        "issue_macro_items": 0,
    }
    cases: list[dict[str, Any]] = []
    for case in payload["cases"]:
        report = (base / case["report"]).resolve()
        sources = (base / case["sources"]).resolve()
        job = new_job(
            JobRequest(
                report_path=str(report),
                sources_path=str(sources),
                case_name=case["name"],
                profile=case.get("profile", "deterministic"),
                rule_pack=case.get("rule_pack", "generic-zh"),
                as_of_date=case.get("as_of_date", "2026-07-18"),
            )
        )
        job, _ = run_audit(job)
        artifacts = export_standard_artifacts(job) if export_cases else {}
        findings_by_claim = {item.claim_id: item for item in job.findings}
        labeled_finding_ids = {
            finding.id
            for label in case["claims"]
            for finding in _matched_findings(job, label["text"])
        }
        unlabeled_claims = [
            {
                "text": _claim_key(claim.text),
                "status": findings_by_claim[claim.id].status.value,
            }
            for claim in job.claims
            if claim.id in findings_by_claim
            and findings_by_claim[claim.id].id not in labeled_finding_ids
        ]
        unlabeled_risks = [item for item in unlabeled_claims if item["status"] in RISK_STATUSES]
        totals["matched_predictions"] += len(labeled_finding_ids)
        totals["all_predictions"] += len(findings_by_claim)
        totals["unlabeled_claims"] += len(unlabeled_claims)
        totals["unlabeled_risk_predictions"] += len(unlabeled_risks)
        totals["false_positives"] += len(unlabeled_risks)
        case_results = []
        case_counts = {
            "labeled_claims": 0,
            "extracted_claims": 0,
            "true_positives": 0,
            "false_positives": len(unlabeled_risks),
            "false_negatives": 0,
            "status_matches": 0,
            "evidence_expected": 0,
            "evidence_top5_hits": 0,
        }
        for label in case["claims"]:
            totals["labeled_claims"] += 1
            case_counts["labeled_claims"] += 1
            matched = _matched_findings(job, label["text"])
            finding = matched[0] if matched else None
            predicted = _aggregate_status(matched)
            should_flag = bool(label["should_flag"])
            extracted = bool(matched)
            flagged = extracted and predicted in RISK_STATUSES
            if extracted:
                totals["extracted_claims"] += 1
                case_counts["extracted_claims"] += 1
            if should_flag and flagged:
                totals["true_positives"] += 1
                case_counts["true_positives"] += 1
            elif not should_flag and flagged:
                totals["false_positives"] += 1
                case_counts["false_positives"] += 1
            elif should_flag and not flagged:
                totals["false_negatives"] += 1
                case_counts["false_negatives"] += 1
            if predicted in label.get("accepted_statuses", []):
                totals["status_matches"] += 1
                case_counts["status_matches"] += 1
            if should_flag and label.get("expected_severity") == "high":
                totals["high_risk_expected"] += 1
                totals["high_risk_hits"] += int(
                    flagged and any(item.severity == "high" for item in matched)
                )
            expected_issues = set(label.get("expected_issue_codes", []))
            if expected_issues:
                predicted_issues = {
                    code
                    for matched_finding in matched
                    for code in matched_finding.issue_codes
                }
                issue_tp = len(expected_issues & predicted_issues)
                issue_fp = len(predicted_issues - expected_issues)
                issue_fn = len(expected_issues - predicted_issues)
                totals["issue_true_positives"] += issue_tp
                totals["issue_false_positives"] += issue_fp
                totals["issue_false_negatives"] += issue_fn
                item_precision = issue_tp / (issue_tp + issue_fp) if issue_tp + issue_fp else 0.0
                item_recall = issue_tp / (issue_tp + issue_fn) if issue_tp + issue_fn else 0.0
                totals["issue_macro_f1_sum"] += _f1(item_precision, item_recall)
                totals["issue_macro_items"] += 1
            evidence_file = label.get("evidence_file")
            evidence_hit = None
            if evidence_file:
                totals["evidence_expected"] += 1
                case_counts["evidence_expected"] += 1
                expected_quote = label.get("evidence_quote")
                expected_locator = label.get("evidence_locator")
                evidence_hit = bool(
                    finding
                    and any(
                        item.file_name == evidence_file
                        and (not expected_quote or expected_quote in item.quote)
                        and (not expected_locator or expected_locator == item.locator.label())
                        for matched_finding in matched
                        for item in matched_finding.evidence[:5]
                    )
                )
                totals["evidence_top5_hits"] += int(evidence_hit)
                case_counts["evidence_top5_hits"] += int(evidence_hit)
            case_results.append(
                {
                    "text": label["text"],
                    "expected_flag": should_flag,
                    "predicted_status": predicted,
                    "evidence_top5_hit": evidence_hit,
                }
            )
        case_predicted_positive = case_counts["true_positives"] + case_counts["false_positives"]
        case_actual_positive = case_counts["true_positives"] + case_counts["false_negatives"]
        case_precision = _ratio(case_counts["true_positives"], case_predicted_positive)
        case_recall = _ratio(case_counts["true_positives"], case_actual_positive)
        cases.append(
            {
                "name": case["name"],
                "coverage_status": job.coverage_status,
                "stage_timings_ms": job.stage_timings_ms,
                "runtime_metrics": job.runtime_metrics,
                "artifacts": artifacts,
                "unlabeled_claims": unlabeled_claims,
                "metrics": {
                    "claim_extraction_recall": _ratio(
                        case_counts["extracted_claims"], case_counts["labeled_claims"]
                    ),
                    "error_precision": case_precision,
                    "error_recall": case_recall,
                    "error_f1": _f1(case_precision, case_recall),
                    "status_accuracy": _ratio(
                        case_counts["status_matches"], case_counts["labeled_claims"]
                    ),
                    "evidence_top5_recall": _ratio(
                        case_counts["evidence_top5_hits"], case_counts["evidence_expected"]
                    ),
                },
                "results": case_results,
            }
        )
    predicted_positive = totals["true_positives"] + totals["false_positives"]
    actual_positive = totals["true_positives"] + totals["false_negatives"]
    extraction_precision = _ratio(totals["matched_predictions"], totals["all_predictions"])
    extraction_recall = _ratio(totals["extracted_claims"], totals["labeled_claims"])
    error_precision = _ratio(totals["true_positives"], predicted_positive)
    error_recall = _ratio(totals["true_positives"], actual_positive)
    issue_precision = _ratio(
        totals["issue_true_positives"],
        totals["issue_true_positives"] + totals["issue_false_positives"],
    )
    issue_recall = _ratio(
        totals["issue_true_positives"],
        totals["issue_true_positives"] + totals["issue_false_negatives"],
    )
    metrics = {
        "claim_extraction_precision": extraction_precision,
        "claim_extraction_recall": extraction_recall,
        "claim_extraction_f1": _f1(extraction_precision, extraction_recall),
        "error_precision": error_precision,
        "error_recall": error_recall,
        "error_f1": _f1(error_precision, error_recall),
        "status_accuracy": _ratio(totals["status_matches"], totals["labeled_claims"]),
        "evidence_top5_recall": _ratio(totals["evidence_top5_hits"], totals["evidence_expected"]),
        "high_risk_recall": _ratio(totals["high_risk_hits"], totals["high_risk_expected"]),
        "issue_code_micro_precision": issue_precision,
        "issue_code_micro_recall": issue_recall,
        "issue_code_micro_f1": _f1(issue_precision, issue_recall),
        "issue_code_macro_f1": round(
            totals["issue_macro_f1_sum"] / totals["issue_macro_items"], 4
        )
        if totals["issue_macro_items"]
        else 0.0,
    }
    return {"dataset": payload.get("name", dataset_path.stem), "metrics": metrics, "counts": totals, "cases": cases}
