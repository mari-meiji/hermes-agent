"""SQLite/WAL state machine for deterministic email-to-Brain intake."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import uuid
from typing import Any


@dataclass(frozen=True)
class ClaimResult:
    kind: str
    claim_token: str | None = None
    receipt: dict[str, Any] | None = None


@dataclass(frozen=True)
class ReviewResolution:
    kind: str
    pending_capture_id: str
    action: str
    result: dict[str, Any] | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _payload_object(payload_json: str) -> dict[str, Any]:
    try:
        payload = json.loads(payload_json)
    except json.JSONDecodeError as exc:
        raise ValueError("payload_json must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("payload_json must be an object")
    return payload


def _minimize_payload(payload_json: str) -> str:
    """Keep only server-authoritative fields needed for recovery/review.

    Source excerpts, sender identity, account, URL, and unknown input keys are
    intentionally excluded from all SQLite payload storage.
    """
    payload = _payload_object(payload_json)
    action = payload.get("action_context") if isinstance(payload.get("action_context"), dict) else {}
    entities = payload.get("entities") if isinstance(payload.get("entities"), dict) else {}
    normalized = {
        "schema_version": payload.get("schema_version"),
        "source": payload.get("source"),
        "gmail_thread_id": payload.get("gmail_thread_id"),
        "gmail_message_ids": sorted(set(payload.get("gmail_message_ids", []))),
        "received_at": payload.get("received_at"),
        "subject": payload.get("subject"),
        "triage_summary": payload.get("triage_summary"),
        "durable_signals": payload.get("durable_signals", []),
        "entities": {name: entities.get(name, []) for name in ("people", "projects", "areas")},
        "action_context": {name: action.get(name, "") for name in ("recommended_next_action", "owner", "deadline")},
        "sensitivity": payload.get("sensitivity"),
    }
    return json.dumps(normalized, sort_keys=True, separators=(",", ":"), allow_nan=False)


class EmailBrainStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(str(self.path), timeout=5, isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.execute("PRAGMA busy_timeout=5000")
        self._initialize()

    def close(self) -> None:
        self.connection.close()

    def _initialize(self) -> None:
        self.connection.executescript("""
        CREATE TABLE IF NOT EXISTS intake_receipts (
          idempotency_key TEXT PRIMARY KEY,
          payload_hash TEXT NOT NULL,
          payload_json TEXT NOT NULL,
          status TEXT NOT NULL,
          claim_token TEXT,
          receipt_json TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS brain_mutations (
          id INTEGER PRIMARY KEY,
          idempotency_key TEXT NOT NULL,
          artifact_path TEXT NOT NULL,
          mutation_type TEXT NOT NULL,
          content_hash TEXT NOT NULL,
          UNIQUE(idempotency_key, artifact_path, content_hash)
        );
        CREATE TABLE IF NOT EXISTS pending_reviews (
          pending_capture_id TEXT PRIMARY KEY,
          idempotency_key TEXT NOT NULL,
          version INTEGER NOT NULL,
          state TEXT NOT NULL,
          payload_json TEXT NOT NULL,
          expires_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS review_actions (
          event_id TEXT PRIMARY KEY,
          pending_capture_id TEXT NOT NULL,
          actor_id TEXT NOT NULL,
          action TEXT NOT NULL,
          result_json TEXT
        );
        CREATE TABLE IF NOT EXISTS review_threads (
          pending_capture_id TEXT PRIMARY KEY,
          parent_channel_id TEXT NOT NULL,
          starter_message_id TEXT NOT NULL,
          thread_id TEXT NOT NULL,
          state TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS reminders (
          pending_capture_id TEXT NOT NULL,
          kind TEXT NOT NULL,
          due_at TEXT NOT NULL,
          sent_at TEXT,
          PRIMARY KEY(pending_capture_id, kind)
        );
        """)
        columns = {row[1] for row in self.connection.execute("PRAGMA table_info(intake_receipts)")}
        if "claim_token" not in columns:
            self.connection.execute("ALTER TABLE intake_receipts ADD COLUMN claim_token TEXT")

    def _begin(self) -> None:
        self.connection.execute("BEGIN IMMEDIATE")

    def claim_intake(self, idempotency_key: str, payload_hash: str, payload_json: str) -> ClaimResult:
        minimized_payload = _minimize_payload(payload_json)
        self._begin()
        try:
            row = self.connection.execute(
                "SELECT status, receipt_json FROM intake_receipts WHERE idempotency_key=?", (idempotency_key,)
            ).fetchone()
            if row is None:
                now = _now()
                token = str(uuid.uuid4())
                self.connection.execute(
                    "INSERT INTO intake_receipts (idempotency_key, payload_hash, payload_json, status, claim_token, receipt_json, created_at, updated_at) VALUES (?, ?, ?, 'processing', ?, NULL, ?, ?)",
                    (idempotency_key, payload_hash, minimized_payload, token, now, now),
                )
                self.connection.commit()
                return ClaimResult("process", token)
            if row["receipt_json"] is not None:
                receipt = json.loads(row["receipt_json"])
                receipt["status"] = "duplicate"
                receipt["idempotent_replay"] = True
                self.connection.commit()
                return ClaimResult("replay", receipt=receipt)
            self.connection.commit()
            return ClaimResult("in_progress")
        except Exception:
            self.connection.rollback()
            raise

    def release_claim_for_retry(self, idempotency_key: str, claim_token: str) -> None:
        self._begin()
        try:
            result = self.connection.execute(
                "DELETE FROM intake_receipts WHERE idempotency_key=? AND status='processing' AND claim_token=?",
                (idempotency_key, claim_token),
            )
            if result.rowcount != 1:
                raise RuntimeError("claim is not active")
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

    def finish_intake(self, idempotency_key: str, claim_token: str | None, receipt: dict[str, Any]) -> dict[str, Any]:
        if not claim_token:
            raise RuntimeError("claim token is required")
        self._begin()
        try:
            stored = dict(receipt)
            stored["idempotent_replay"] = False
            status = stored.get("status", "completed")
            result = self.connection.execute(
                "UPDATE intake_receipts SET status=?, claim_token=NULL, receipt_json=?, updated_at=? WHERE idempotency_key=? AND status='processing' AND claim_token=?",
                (status, json.dumps(stored, sort_keys=True, separators=(",", ":")), _now(), idempotency_key, claim_token),
            )
            if result.rowcount != 1:
                raise RuntimeError("claim is stale, foreign, or already finalized")
            self.connection.execute(
                "INSERT OR IGNORE INTO brain_mutations (idempotency_key, artifact_path, mutation_type, content_hash) VALUES (?, ?, ?, ?)",
                (idempotency_key, "__receipt__", "receipt_finalized", idempotency_key),
            )
            self.connection.commit()
            return stored
        except Exception:
            self.connection.rollback()
            raise

    def record_mutation(self, idempotency_key: str, artifact_path: str, mutation_type: str, content_hash: str) -> None:
        self._begin()
        try:
            self.connection.execute(
                "INSERT OR IGNORE INTO brain_mutations (idempotency_key, artifact_path, mutation_type, content_hash) VALUES (?, ?, ?, ?)",
                (idempotency_key, artifact_path, mutation_type, content_hash),
            )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

    def mutation_count(self, idempotency_key: str) -> int:
        return int(self.connection.execute("SELECT COUNT(*) FROM brain_mutations WHERE idempotency_key=?", (idempotency_key,)).fetchone()[0])

    def create_pending_review(self, idempotency_key: str, *, payload: str, version: int) -> str:
        pending_id = str(uuid.uuid4())
        expires = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat().replace("+00:00", "Z")
        minimized_payload = _minimize_payload(payload)
        self._begin()
        try:
            self.connection.execute(
                "INSERT INTO pending_reviews VALUES (?, ?, ?, 'pending', ?, ?)",
                (pending_id, idempotency_key, version, minimized_payload, expires),
            )
            self.connection.commit()
            return pending_id
        except Exception:
            self.connection.rollback()
            raise

    def resolve_review(self, pending_capture_id: str, *, expected_version: int, event_id: str, action: str, actor_id: str = "") -> ReviewResolution:
        self._begin()
        try:
            prior = self.connection.execute("SELECT result_json, pending_capture_id, action FROM review_actions WHERE event_id=?", (event_id,)).fetchone()
            if prior is not None:
                self.connection.commit()
                return ReviewResolution("replay", prior["pending_capture_id"], prior["action"], json.loads(prior["result_json"] or "{}"))
            row = self.connection.execute("SELECT version, state FROM pending_reviews WHERE pending_capture_id=?", (pending_capture_id,)).fetchone()
            if row is None or row["state"] != "pending" or row["version"] != expected_version:
                self.connection.rollback()
                return ReviewResolution("stale", pending_capture_id, action)
            result = {"pending_capture_id": pending_capture_id, "action": action, "expected_version": expected_version}
            next_state = "approved" if action == "approve" else "rejected"
            self.connection.execute("UPDATE pending_reviews SET state=? WHERE pending_capture_id=? AND version=?", (next_state, pending_capture_id, expected_version))
            self.connection.execute("INSERT INTO review_actions VALUES (?, ?, ?, ?, ?)", (event_id, pending_capture_id, actor_id, action, json.dumps(result, sort_keys=True)))
            self.connection.commit()
            return ReviewResolution("apply", pending_capture_id, action, result)
        except Exception:
            self.connection.rollback()
            raise
