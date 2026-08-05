from __future__ import annotations

import os
import shutil
from pathlib import Path

from .config import ensure_private_dir, ensure_private_file, jobs_dir
from .models import AuditJob, SourceRecord
from .parsers import SUPPORTED_EVIDENCE, sha256_file, sha256_text


DEFAULT_MAX_FILES = 500
DEFAULT_MAX_FILE_BYTES = 200 * 1024 * 1024
DEFAULT_MAX_TOTAL_BYTES = 2 * 1024 * 1024 * 1024
MIN_FREE_BUFFER_BYTES = 256 * 1024 * 1024


def _limit(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _safe_files(root: Path) -> list[Path]:
    resolved_root = root.resolve()
    files: list[Path] = []
    for item in sorted(root.rglob("*")):
        if not item.is_file():
            continue
        if item.is_symlink():
            raise ValueError(f"symbolic links are not allowed in evidence packs: {item.name}")
        resolved = item.resolve()
        try:
            resolved.relative_to(resolved_root)
        except ValueError as exc:
            raise ValueError(f"evidence path escapes its root: {item}") from exc
        if item.suffix.lower() in SUPPORTED_EVIDENCE:
            files.append(item)
    return files


def snapshot_inputs(job: AuditJob) -> AuditJob:
    report = Path(job.request.report_path).expanduser().resolve()
    sources = Path(job.request.sources_path).expanduser().resolve()
    if not report.is_file():
        raise ValueError(f"report does not exist: {report}")
    if report.suffix.lower() != ".docx":
        raise ValueError("report must be DOCX")
    if not sources.is_dir():
        raise ValueError(f"evidence path is not a directory: {sources}")
    if report.is_symlink():
        raise ValueError("the report cannot be a symbolic link")

    evidence_files = _safe_files(sources)
    if not evidence_files:
        raise ValueError("the evidence directory contains no supported files")
    max_files = _limit("CLAIMLEDGER_MAX_FILES", DEFAULT_MAX_FILES)
    max_file_bytes = _limit("CLAIMLEDGER_MAX_FILE_BYTES", DEFAULT_MAX_FILE_BYTES)
    max_total_bytes = _limit("CLAIMLEDGER_MAX_TOTAL_BYTES", DEFAULT_MAX_TOTAL_BYTES)
    if len(evidence_files) > max_files:
        raise ValueError(f"evidence pack contains {len(evidence_files)} files; limit is {max_files}")

    all_files = [report, *evidence_files]
    oversized = [item for item in all_files if item.stat().st_size > max_file_bytes]
    if oversized:
        raise ValueError(f"input exceeds per-file limit: {oversized[0].name}")
    total_bytes = sum(item.stat().st_size for item in all_files)
    if total_bytes > max_total_bytes:
        raise ValueError(f"input size {total_bytes} bytes exceeds limit {max_total_bytes}")

    work_dir = ensure_private_dir(jobs_dir() / job.id)
    snapshot_root = work_dir / "inputs"
    free_bytes = shutil.disk_usage(work_dir.parent).free
    required = total_bytes * 2 + MIN_FREE_BUFFER_BYTES
    if free_bytes < required:
        raise ValueError(f"insufficient disk space: need at least {required} bytes free")
    ensure_private_dir(snapshot_root)
    report_dir = ensure_private_dir(snapshot_root / "report")
    evidence_dir = ensure_private_dir(snapshot_root / "evidence")

    report_hash = sha256_file(report)
    report_snapshot = report_dir / report.name
    shutil.copy2(report, report_snapshot)
    ensure_private_file(report_snapshot)
    if sha256_file(report_snapshot) != report_hash:
        report_snapshot.unlink(missing_ok=True)
        raise ValueError("report changed while its audit snapshot was being created")
    inventory = [
        SourceRecord(
            id=f"source-{report_hash[:12]}",
            role="report",
            original_path=str(report),
            snapshot_path=str(report_snapshot),
            file_name=report.name,
            file_hash=report_hash,
            size_bytes=report.stat().st_size,
        )
    ]
    seen_hashes = {report_hash}
    for source in evidence_files:
        digest = sha256_file(source)
        if digest in seen_hashes:
            if digest == report_hash:
                raise ValueError(f"evidence pack contains the report itself or an identical copy: {source.name}")
        seen_hashes.add(digest)
        relative = source.relative_to(sources)
        destination = evidence_dir / relative
        current_dir = evidence_dir
        for part in relative.parent.parts:
            current_dir = ensure_private_dir(current_dir / part)
        shutil.copy2(source, destination)
        ensure_private_file(destination)
        if sha256_file(destination) != digest:
            destination.unlink(missing_ok=True)
            raise ValueError(f"evidence changed while its audit snapshot was being created: {source.name}")
        inventory.append(
            SourceRecord(
                id=f"source-{digest[:12]}",
                role="evidence",
                original_path=str(source),
                snapshot_path=str(destination),
                file_name=source.name,
                file_hash=digest,
                size_bytes=source.stat().st_size,
            )
        )
    job.report_snapshot = str(report_snapshot)
    job.sources_snapshot = str(evidence_dir)
    job.source_inventory = inventory
    return job


def verify_snapshot_integrity(job: AuditJob) -> list[str]:
    issues: list[str] = []
    report_records = [record for record in job.source_inventory if record.role == "report"]
    evidence_records = [record for record in job.source_inventory if record.role == "evidence"]
    if len(report_records) != 1:
        issues.append("source inventory must contain exactly one audited report")
    if not evidence_records:
        issues.append("source inventory contains no evidence files")
    for record in job.source_inventory:
        snapshot = Path(record.snapshot_path)
        if not snapshot.is_file():
            issues.append(f"snapshot missing: {record.file_name}")
            continue
        if sha256_file(snapshot) != record.file_hash:
            issues.append(f"snapshot hash changed: {record.file_name}")
    return issues


def verify_input_integrity(job: AuditJob) -> list[str]:
    issues = verify_snapshot_integrity(job)
    for record in job.source_inventory:
        original = Path(record.original_path)
        if not original.is_file():
            issues.append(f"original input missing after audit: {record.file_name}")
        elif sha256_file(original) != record.file_hash:
            issues.append(f"original input changed after audit: {record.file_name}")
    return issues


def verify_citation_integrity(job: AuditJob) -> list[str]:
    """Verify that delivered citations still match their audited quote records."""

    issues: list[str] = []
    inventory_hashes = {
        record.file_hash
        for record in job.source_inventory
        if record.role == "evidence"
    }
    for finding in job.findings:
        for evidence in finding.evidence:
            if evidence.file_hash not in inventory_hashes:
                issues.append(
                    f"evidence source hash is not in inventory: {evidence.id}"
                )
            if not evidence.quote_hash:
                issues.append(f"evidence quote hash is missing: {evidence.id}")
            elif sha256_text(evidence.quote) != evidence.quote_hash:
                issues.append(f"evidence quote hash changed: {evidence.id}")
    return issues
