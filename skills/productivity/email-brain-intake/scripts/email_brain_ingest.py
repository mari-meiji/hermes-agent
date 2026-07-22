"""Plan and atomically apply normal, redacted email Brain captures."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import os
from pathlib import Path
import re
import tempfile
from typing import Any

from email_brain_contract import idempotency_key


@dataclass(frozen=True)
class UpdatePlan:
    capture_path: Path
    relative_path: str
    content: str
    content_hash: str
    idempotency_key: str
    retrieval_query: str


@dataclass(frozen=True)
class MutationResult:
    capture_note: str
    operation: str
    content_hash: str
    retrieval_query: str


def _safe_part(value: str, fallback: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._ -]+", "", value).strip().replace("/", "-")
    return (cleaned[:80] or fallback).strip(" .")


def plan_update(payload: dict[str, Any], brain_root: str | Path) -> UpdatePlan:
    root = Path(brain_root)
    date = datetime.fromisoformat(payload["received_at"].replace("Z", "+00:00")).date().isoformat()
    entity = _safe_part((payload["entities"]["projects"] or payload["entities"]["people"] or ["Email"])[0], "Email")
    subject = _safe_part(payload["subject"], "Update")
    relative = Path("00 Inbox") / "Email Captures" / f"{date} - {entity} - {subject}.md"
    lines = [
        "---",
        "type: email-capture",
        f"sensitivity: {payload['sensitivity']}",
        "---",
        "",
        f"# {subject}",
        "",
        f"Gmail thread: {payload['gmail_thread_id']}",
        f"Gmail messages: {', '.join(sorted(set(payload['gmail_message_ids'])))}",
        f"Gmail URL: {payload['gmail_url']}",
        f"Received at: {payload['received_at']}",
        "",
        "## Durable context",
        payload["triage_summary"],
        "",
        "## Signals",
        *[f"- {signal}" for signal in payload["durable_signals"]],
        "",
        "## Action context",
        f"Owner: {payload['action_context']['owner'] or 'Unassigned'}",
        f"Recommended next action: {payload['action_context']['recommended_next_action'] or 'None'}",
        f"Deadline: {payload['action_context']['deadline'] or 'None'}",
        "",
        "## Canonical targets",
        *[f"- {name}" for category in ("people", "projects", "areas") for name in payload["entities"][category]],
        "",
        "## Redactions",
        "Raw email bodies, quoted chains, and attachments are intentionally excluded.",
        "",
    ]
    content = "\n".join(lines)
    return UpdatePlan(
        capture_path=root / relative,
        relative_path=relative.as_posix(),
        content=content,
        content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        idempotency_key=idempotency_key(payload),
        retrieval_query=f"{entity} {payload['durable_signals'][0]}",
    )


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def apply_update(plan: UpdatePlan, store: Any) -> MutationResult:
    if plan.capture_path.exists():
        existing = plan.capture_path.read_text(encoding="utf-8")
        if hashlib.sha256(existing.encode("utf-8")).hexdigest() == plan.content_hash:
            store.record_mutation(plan.idempotency_key, plan.relative_path, "capture", plan.content_hash)
            return MutationResult(plan.capture_path.as_posix(), "reconciled", plan.content_hash, plan.retrieval_query)
        raise FileExistsError(f"capture path collision: {plan.capture_path}")
    _atomic_write(plan.capture_path, plan.content)
    store.record_mutation(plan.idempotency_key, plan.relative_path, "capture", plan.content_hash)
    return MutationResult(plan.capture_path.as_posix(), "created", plan.content_hash, plan.retrieval_query)
