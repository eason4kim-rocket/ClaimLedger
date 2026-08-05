from __future__ import annotations

import sqlite3
import threading
import os
from datetime import date
from pathlib import Path
from typing import Callable, TypeVar

from .config import (
    PRIVATE_FILE_MODE,
    database_path,
    ensure_private_dir,
    ensure_private_file,
)
from .models import AuditJob, MemoryEvent, PolicyRule, ReviewerProfile, utc_now


T = TypeVar("T")


class ConcurrentUpdateError(RuntimeError):
    """Raised instead of silently overwriting a newer persisted job state."""


class JobStore:
    SCHEMA_VERSION = 2

    def __init__(self, path: Path | None = None):
        self.path = path or database_path()
        ensure_private_dir(self.path.parent)
        self._lock = threading.RLock()
        self._initialize()

    def _secure_database_files(self) -> None:
        for suffix in ("", "-wal", "-shm"):
            ensure_private_file(Path(f"{self.path}{suffix}"))

    def _connect(self) -> sqlite3.Connection:
        # Pre-create the database with a restrictive mode. sqlite3 otherwise
        # creates it according to the caller's process-wide umask.
        descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT, PRIVATE_FILE_MODE)
        os.close(descriptor)
        ensure_private_file(self.path)
        connection = sqlite3.connect(self.path, timeout=30)
        connection.execute("PRAGMA journal_mode=WAL")
        self._secure_database_files()
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS reviewer_profiles (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_events (
                    id TEXT PRIMARY KEY,
                    profile_id TEXT NOT NULL,
                    decision_event_id TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    expires_at TEXT,
                    payload TEXT NOT NULL,
                    FOREIGN KEY(profile_id) REFERENCES reviewer_profiles(id) ON DELETE CASCADE
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS memory_profile_created "
                "ON memory_events(profile_id, created_at DESC)"
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS policy_rules (
                    id TEXT PRIMARY KEY,
                    profile_id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(profile_id) REFERENCES reviewer_profiles(id) ON DELETE CASCADE
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS policy_profile_state "
                "ON policy_rules(profile_id, state, version DESC)"
            )
            connection.execute(
                "INSERT INTO metadata(key, value) VALUES ('schema_version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (str(self.SCHEMA_VERSION),),
            )
            self._secure_database_files()

    def save(self, job: AuditJob) -> AuditJob:
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT payload FROM jobs WHERE id = ?", (job.id,)).fetchone()
            if row:
                persisted = AuditJob.model_validate_json(row[0])
                if persisted.state_revision != job.state_revision:
                    raise ConcurrentUpdateError(
                        f"job {job.id} changed concurrently "
                        f"(expected revision {job.state_revision}, found {persisted.state_revision})"
                    )
                job.state_revision += 1
                job.updated_at = utc_now()
                connection.execute(
                    "UPDATE jobs SET status = ?, payload = ?, updated_at = ? WHERE id = ?",
                    (job.status, job.model_dump_json(), job.updated_at, job.id),
                )
            else:
                job.state_revision = 1
                job.updated_at = utc_now()
                connection.execute(
                    "INSERT INTO jobs(id, status, payload, updated_at) VALUES (?, ?, ?, ?)",
                    (job.id, job.status, job.model_dump_json(), job.updated_at),
                )
            self._secure_database_files()
        return job

    def mutate(
        self,
        job_id: str,
        mutator: Callable[[AuditJob], T],
    ) -> tuple[AuditJob, T] | None:
        """Apply one read-modify-write operation under a SQLite write lock."""

        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT payload FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if not row:
                return None
            job = AuditJob.model_validate_json(row[0])
            job.state_revision += 1
            job.updated_at = utc_now()
            result = mutator(job)
            connection.execute(
                "UPDATE jobs SET status = ?, payload = ?, updated_at = ? WHERE id = ?",
                (job.status, job.model_dump_json(), job.updated_at, job.id),
            )
            self._secure_database_files()
            return job, result

    def get(self, job_id: str) -> AuditJob | None:
        with self._lock, self._connect() as connection:
            row = connection.execute("SELECT payload FROM jobs WHERE id = ?", (job_id,)).fetchone()
            self._secure_database_files()
        return AuditJob.model_validate_json(row[0]) if row else None

    def list(self, limit: int = 50) -> list[AuditJob]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM jobs ORDER BY updated_at DESC LIMIT ?", (limit,)
            ).fetchall()
            self._secure_database_files()
        return [AuditJob.model_validate_json(row[0]) for row in rows]

    def schema_version(self) -> int:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT value FROM metadata WHERE key = 'schema_version'"
            ).fetchone()
        return int(row[0]) if row else 0

    def create_profile(self, profile: ReviewerProfile) -> ReviewerProfile:
        with self._lock, self._connect() as connection:
            existing = connection.execute(
                "SELECT 1 FROM reviewer_profiles WHERE name = ?", (profile.name,)
            ).fetchone()
            if existing:
                raise ValueError(f"reviewer profile already exists: {profile.name}")
            connection.execute(
                "INSERT INTO reviewer_profiles(id, name, payload, updated_at) VALUES (?, ?, ?, ?)",
                (profile.id, profile.name, profile.model_dump_json(), profile.updated_at),
            )
            self._secure_database_files()
        return profile

    def get_profile(self, name_or_id: str) -> ReviewerProfile | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM reviewer_profiles WHERE id = ? OR name = ?",
                (name_or_id, name_or_id),
            ).fetchone()
        return ReviewerProfile.model_validate_json(row[0]) if row else None

    def list_profiles(self) -> list[ReviewerProfile]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM reviewer_profiles ORDER BY name"
            ).fetchall()
        return [ReviewerProfile.model_validate_json(row[0]) for row in rows]

    def delete_profile(self, name_or_id: str) -> bool:
        profile = self.get_profile(name_or_id)
        if not profile:
            return False
        with self._lock, self._connect() as connection:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("DELETE FROM memory_events WHERE profile_id = ?", (profile.id,))
            connection.execute("DELETE FROM policy_rules WHERE profile_id = ?", (profile.id,))
            connection.execute("DELETE FROM reviewer_profiles WHERE id = ?", (profile.id,))
            self._secure_database_files()
        return True

    def add_memory(self, event: MemoryEvent) -> MemoryEvent:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO memory_events(
                    id, profile_id, decision_event_id, created_at, expires_at, payload
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    event.id,
                    event.profile_id,
                    event.decision_event_id,
                    event.created_at,
                    event.expires_at,
                    event.model_dump_json(),
                ),
            )
            self._secure_database_files()
        return event

    def list_memories(
        self,
        profile_id: str,
        *,
        include_expired: bool = False,
        limit: int = 1000,
    ) -> list[MemoryEvent]:
        query = "SELECT payload FROM memory_events WHERE profile_id = ?"
        params: list[object] = [profile_id]
        if not include_expired:
            query += " AND (expires_at IS NULL OR expires_at >= ?)"
            params.append(date.today().isoformat())
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._lock, self._connect() as connection:
            rows = connection.execute(query, tuple(params)).fetchall()
        return [MemoryEvent.model_validate_json(row[0]) for row in rows]

    def get_memory(self, memory_id: str) -> MemoryEvent | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM memory_events WHERE id = ?", (memory_id,)
            ).fetchone()
        return MemoryEvent.model_validate_json(row[0]) if row else None

    def prune_memories(self, profile_id: str, before: str | None = None) -> int:
        with self._lock, self._connect() as connection:
            if before:
                cursor = connection.execute(
                    """
                    DELETE FROM memory_events
                    WHERE profile_id = ?
                    AND (
                        (expires_at IS NOT NULL AND expires_at < ?)
                        OR substr(created_at, 1, 10) < ?
                    )
                    """,
                    (profile_id, before, before),
                )
            else:
                cursor = connection.execute(
                    """
                    DELETE FROM memory_events
                    WHERE profile_id = ?
                    AND expires_at IS NOT NULL
                    AND expires_at < ?
                    """,
                    (profile_id, date.today().isoformat()),
                )
            self._secure_database_files()
            return cursor.rowcount

    def save_policy(self, policy: PolicyRule) -> PolicyRule:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO policy_rules(id, profile_id, state, version, payload, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    state = excluded.state,
                    payload = excluded.payload,
                    updated_at = excluded.updated_at
                """,
                (
                    policy.id,
                    policy.profile_id,
                    policy.state,
                    policy.version,
                    policy.model_dump_json(),
                    utc_now(),
                ),
            )
            self._secure_database_files()
        return policy

    def get_policy(self, policy_id: str) -> PolicyRule | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM policy_rules WHERE id = ?", (policy_id,)
            ).fetchone()
        return PolicyRule.model_validate_json(row[0]) if row else None

    def list_policies(
        self,
        profile_id: str,
        *,
        state: str | None = None,
    ) -> list[PolicyRule]:
        query = "SELECT payload FROM policy_rules WHERE profile_id = ?"
        params: list[object] = [profile_id]
        if state:
            query += " AND state = ?"
            params.append(state)
        query += " ORDER BY version DESC, updated_at DESC"
        with self._lock, self._connect() as connection:
            rows = connection.execute(query, tuple(params)).fetchall()
        return [PolicyRule.model_validate_json(row[0]) for row in rows]
