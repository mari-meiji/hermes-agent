"""Restricted, redacted Discord review workflow; no live transport is bundled here."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import uuid
from typing import Callable

from authenticated_actions import authorize_action, sign_review_token


ADAM_IMMUTABLE_DISCORD_USER_ID = "552613509909971005"


class RestrictedSurfaceError(RuntimeError):
    pass


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class FakeDiscord:
    """Test-only transport recording posts. Production must supply a verified transport."""
    def __init__(self, *, parent_members: set[str]):
        self.parent_members = parent_members
        self.posts: list[dict] = []
        self.archived_threads: list[str] = []
        self._threads: dict[str, str] = {}

    def verify_restricted_parent(self, parent_channel_id: str, adam_id: str) -> bool:
        return adam_id in self.parent_members and self.parent_members <= {adam_id, "mari-bot"}

    def create_thread(self, parent_channel_id: str, title: str) -> str:
        thread_id = self._threads.setdefault(title, f"thread-{len(self._threads) + 1}")
        return thread_id

    def post(self, thread_id: str, content: str, *, mentions: list[str]) -> None:
        self.posts.append({"thread_id": thread_id, "content": content, "mentions": mentions})

    def archive(self, thread_id: str) -> None:
        self.archived_threads.append(thread_id)


class ReviewLedger:
    def __init__(self, path: str | Path):
        self.connection = sqlite3.connect(str(path), isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA busy_timeout=5000")
        self.connection.executescript("""
        CREATE TABLE IF NOT EXISTS pending_reviews (
          pending_capture_id TEXT PRIMARY KEY, version INTEGER NOT NULL, state TEXT NOT NULL,
          sensitivity TEXT NOT NULL, summary TEXT NOT NULL, subject TEXT NOT NULL,
          gmail_thread_id TEXT NOT NULL, expires_at TEXT NOT NULL, thread_id TEXT
        );
        CREATE TABLE IF NOT EXISTS review_actions (
          event_id TEXT PRIMARY KEY, pending_capture_id TEXT NOT NULL,
          action_fingerprint TEXT NOT NULL UNIQUE, result_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS reminders (
          pending_capture_id TEXT NOT NULL, kind TEXT NOT NULL, sent_at TEXT, PRIMARY KEY(pending_capture_id, kind)
        );
        """)
        columns = {row[1] for row in self.connection.execute("PRAGMA table_info(review_actions)")}
        if "action_fingerprint" not in columns:
            self.connection.execute("ALTER TABLE review_actions ADD COLUMN action_fingerprint TEXT")
            self.connection.execute("UPDATE review_actions SET action_fingerprint=event_id WHERE action_fingerprint IS NULL")
        self.connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS review_actions_fingerprint_unique ON review_actions(action_fingerprint)")

    def close(self) -> None:
        self.connection.close()

    def seed_pending(self, pending_capture_id: str, *, version: int, sensitivity: str, summary: str, subject: str, gmail_thread_id: str, expires_at: str | None = None) -> None:
        expires_at = expires_at or _iso(datetime.now(timezone.utc) + timedelta(days=7))
        self.connection.execute("INSERT INTO pending_reviews VALUES (?, ?, 'pending', ?, ?, ?, ?, ?, NULL)", (pending_capture_id, version, sensitivity, summary, subject, gmail_thread_id, expires_at))

    def pending(self, pending_capture_id: str):
        return self.connection.execute("SELECT * FROM pending_reviews WHERE pending_capture_id=?", (pending_capture_id,)).fetchone()

    def capture_count(self, pending_capture_id: str) -> int:
        return int(self.connection.execute("SELECT COUNT(*) FROM review_actions WHERE pending_capture_id=?", (pending_capture_id,)).fetchone()[0])


class ReviewWorkflow:
    def __init__(self, ledger: ReviewLedger, transport, *, parent_channel_id: str, adam_id: str, signing_key: bytes, now: Callable[[], str], resolution_submitter: Callable[[dict], dict] | None = None):
        if adam_id != ADAM_IMMUTABLE_DISCORD_USER_ID:
            raise RestrictedSurfaceError("Adam immutable Discord identity is required")
        self.ledger, self.transport = ledger, transport
        self.parent_channel_id, self.adam_id, self.signing_key, self.now = parent_channel_id, adam_id, signing_key, now
        self.resolution_submitter = resolution_submitter or (lambda invocation: {"status": "submitted"})

    def _post(self, thread_id: str, content: str, *, mentions: list[str]) -> None:
        if not self.transport.verify_restricted_parent(self.parent_channel_id, self.adam_id):
            raise RestrictedSurfaceError("restricted Discord surface cannot be verified")
        self.transport.post(thread_id, content, mentions=mentions)

    def _redacted_card(self, row) -> str:
        return "\n".join((
            "Review required",
            f"Pending capture: {row['pending_capture_id']}",
            f"Source thread: …{row['gmail_thread_id'][-8:]}",
            f"Sensitivity: {row['sensitivity']}",
            "Summary: Redacted durable-context proposal.",
            "Proposed operation: capture redacted durable context.",
        ))

    def open_review(self, pending_capture_id: str) -> dict:
        row = self.ledger.pending(pending_capture_id)
        if row is None or row["state"] != "pending":
            raise RestrictedSurfaceError("pending review is unavailable")
        if not self.transport.verify_restricted_parent(self.parent_channel_id, self.adam_id):
            raise RestrictedSurfaceError("restricted Discord surface cannot be verified")
        thread_id = row["thread_id"]
        if not thread_id:
            thread_id = self.transport.create_thread(self.parent_channel_id, f"Email Brain review {pending_capture_id[:8]}")
            self.ledger.connection.execute("UPDATE pending_reviews SET thread_id=? WHERE pending_capture_id=? AND state='pending'", (thread_id, pending_capture_id))
            self._post(thread_id, self._redacted_card(row), mentions=[self.adam_id])
        return {"status": "review_required", "pending_capture_id": pending_capture_id, "discord_thread_id": thread_id}

    def resolve_action(self, event: dict) -> dict:
        required = {"event_id", "actor_id", "action", "pending_capture_id", "version", "token"}
        if set(event) != required:
            raise RestrictedSurfaceError("invalid authenticated action event")
        authorize_action(
            actor_id=event["actor_id"], token=event["token"], action=event["action"],
            pending_capture_id=event["pending_capture_id"], version=event["version"],
            now=self.now(), adam_id=self.adam_id, signing_key=self.signing_key,
        )
        if event["action"] not in {"approve", "reject", "request_safer_summary"}:
            raise RestrictedSurfaceError("unsupported review action")

        fingerprint = hashlib.sha256(event["token"].encode("ascii")).hexdigest()
        processing = {"status": "processing", "pending_capture_id": event["pending_capture_id"], "action": event["action"]}
        self.ledger.connection.execute("BEGIN IMMEDIATE")
        try:
            existing = self.ledger.connection.execute("SELECT result_json FROM review_actions WHERE event_id=?", (event["event_id"],)).fetchone()
            if existing:
                self.ledger.connection.commit()
                return json.loads(existing["result_json"])
            claim = self.ledger.connection.execute(
                "UPDATE pending_reviews SET state='resolving' "
                "WHERE pending_capture_id=? AND state='pending' AND version=? AND expires_at > ?",
                (event["pending_capture_id"], event["version"], self.now()),
            )
            if claim.rowcount != 1:
                row = self.ledger.pending(event["pending_capture_id"])
                self.ledger.connection.rollback()
                if row is not None and row["state"] == "pending" and _parse(row["expires_at"]) <= _parse(self.now()):
                    raise RestrictedSurfaceError("review action is expired")
                raise RestrictedSurfaceError("stale or already claimed review action")
            self.ledger.connection.execute(
                "INSERT INTO review_actions (event_id, pending_capture_id, action_fingerprint, result_json) VALUES (?, ?, ?, ?)",
                (event["event_id"], event["pending_capture_id"], fingerprint, json.dumps(processing, sort_keys=True)),
            )
            self.ledger.connection.commit()
        except Exception:
            self.ledger.connection.rollback()
            raise

        invocation = {"operation": "email_brain_resolve_review", "schema_version": "1.0", "payload": {"pending_capture_id": event["pending_capture_id"], "action": event["action"], "approval_event_id": event["event_id"], "expected_pending_capture_version": event["version"]}}
        try:
            terminal = self.resolution_submitter(invocation)
            result = {"status": terminal["status"], "pending_capture_id": event["pending_capture_id"], "action": event["action"]}
        except Exception as exc:
            failed = {"status": "failed_retryable", "pending_capture_id": event["pending_capture_id"], "action": event["action"]}
            self.ledger.connection.execute("BEGIN IMMEDIATE")
            try:
                self.ledger.connection.execute("UPDATE review_actions SET result_json=? WHERE event_id=?", (json.dumps(failed, sort_keys=True), event["event_id"]))
                self.ledger.connection.commit()
            except Exception:
                self.ledger.connection.rollback()
                raise
            raise RestrictedSurfaceError("resolution submission failed after durable claim") from exc

        next_state = "approved" if event["action"] == "approve" else "rejected"
        self.ledger.connection.execute("BEGIN IMMEDIATE")
        try:
            finalized = self.ledger.connection.execute(
                "UPDATE pending_reviews SET state=? WHERE pending_capture_id=? AND state='resolving' AND version=?",
                (next_state, event["pending_capture_id"], event["version"]),
            )
            if finalized.rowcount != 1:
                raise RuntimeError("durable review claim was lost")
            self.ledger.connection.execute("UPDATE review_actions SET result_json=? WHERE event_id=?", (json.dumps(result, sort_keys=True), event["event_id"]))
            self.ledger.connection.commit()
        except Exception:
            self.ledger.connection.rollback()
            raise
        row = self.ledger.pending(event["pending_capture_id"])
        if row and row["thread_id"]:
            self._post(row["thread_id"], f"Review resolved: {next_state}.", mentions=[])
        return result

    def process_due_reviews(self, now: str) -> list[dict]:
        outcomes = []
        for row in self.ledger.connection.execute("SELECT * FROM pending_reviews WHERE state='pending'").fetchall():
            opened = _parse(row["expires_at"]) - timedelta(days=7)
            age = _parse(now) - opened
            if _parse(now) >= _parse(row["expires_at"]):
                self.ledger.connection.execute("BEGIN IMMEDIATE")
                try:
                    expired = self.ledger.connection.execute(
                        "UPDATE pending_reviews SET state='expired' "
                        "WHERE pending_capture_id=? AND state='pending' AND expires_at <= ?",
                        (row["pending_capture_id"], now),
                    )
                    self.ledger.connection.commit()
                except Exception:
                    self.ledger.connection.rollback()
                    raise
                if expired.rowcount != 1:
                    continue
                if row["thread_id"]:
                    self._post(row["thread_id"], "Review expired without capture.", mentions=[])
                    self.transport.archive(row["thread_id"])
                outcomes.append({"status": "expired", "pending_capture_id": row["pending_capture_id"]})
                continue
            for hours, kind in ((72, "reminder_72h"), (24, "reminder_24h")):
                if age >= timedelta(hours=hours):
                    inserted = self.ledger.connection.execute("INSERT OR IGNORE INTO reminders VALUES (?, ?, ?)", (row["pending_capture_id"], kind, now))
                    if inserted.rowcount and row["thread_id"]:
                        self._post(row["thread_id"], "Review reminder: awaiting Adam's decision.", mentions=[])
                        outcomes.append({"status": f"reminded_{hours}h", "pending_capture_id": row["pending_capture_id"]})
                    break
        return outcomes
