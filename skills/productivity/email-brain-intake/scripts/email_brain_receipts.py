"""Render redacted machine-readable receipts."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def render_receipt(*, idempotency_key: str, payload: dict[str, Any], capture_note: str | None, verification: dict[str, Any], status: str = "completed", durability: str = "captured") -> dict[str, Any]:
    return {
        "type": "email_brain_receipt",
        "schema_version": "1.0",
        "status": status,
        "idempotency_key": idempotency_key,
        "idempotent_replay": False,
        "source": {"gmail_thread_id": payload["gmail_thread_id"], "gmail_message_ids": sorted(set(payload["gmail_message_ids"]))},
        "result": {"durability": durability, "capture_note": capture_note, "updated_notes": [], "created_notes": [capture_note] if capture_note else [], "unchanged_notes": []},
        "verification": verification,
        "review": {"required": False, "pending_capture_id": None, "discord_thread_id": None, "reason_codes": []},
        "error": {"code": None, "message": None, "retry_after_seconds": 0},
        "processed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
