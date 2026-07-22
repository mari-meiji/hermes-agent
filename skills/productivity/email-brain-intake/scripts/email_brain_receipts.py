"""Construct machine-readable receipts from explicit safe-field projections."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import PurePosixPath
import re
from typing import Any

_HASH = re.compile(r"^[0-9a-f]{64}$")
_SAFE_PATH = re.compile(r"^[A-Za-z0-9._ /-]+$")


def _safe_relative_path(value: object) -> str | None:
    if not isinstance(value, str) or not _SAFE_PATH.fullmatch(value):
        return None
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        return None
    return path.as_posix()


def _safe_verification(value: object) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    paths = []
    for path in source.get("retrieved_paths", []):
        safe_path = _safe_relative_path(path)
        if safe_path:
            paths.append(safe_path)
    hashes = source.get("content_hashes", {})
    capture_hash = hashes.get("capture") if isinstance(hashes, dict) else None
    return {
        "brain_sync": source.get("brain_sync") if source.get("brain_sync") in {"passed", "failed", "not_run"} else "not_run",
        "qmd_index": source.get("qmd_index") if source.get("qmd_index") in {"passed", "failed", "not_run"} else "not_run",
        "retrieval_query": None,
        "retrieved_paths": paths,
        "content_hashes": {"capture": capture_hash} if isinstance(capture_hash, str) and _HASH.fullmatch(capture_hash) else {},
    }


def render_receipt(*, idempotency_key: str, payload: dict[str, Any], capture_note: str | None, verification: dict[str, Any], status: str = "completed", durability: str = "captured") -> dict[str, Any]:
    safe_capture_note = _safe_relative_path(capture_note)
    return {
        "type": "email_brain_receipt",
        "schema_version": "1.0",
        "status": status,
        "idempotency_key": idempotency_key,
        "idempotent_replay": False,
        "source": {
            "gmail_thread_id": payload["gmail_thread_id"],
            "gmail_message_ids": sorted(set(payload["gmail_message_ids"])),
        },
        "result": {
            "durability": durability,
            "capture_note": safe_capture_note,
            "updated_notes": [],
            "created_notes": [safe_capture_note] if safe_capture_note else [],
            "unchanged_notes": [],
        },
        "verification": _safe_verification(verification),
        "review": {"required": False, "pending_capture_id": None, "discord_thread_id": None, "reason_codes": []},
        "error": {"code": None, "message": None, "retry_after_seconds": 0},
        "processed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
