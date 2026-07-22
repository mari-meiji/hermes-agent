"""Strict, dependency-free contracts for email-to-Brain intake."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import re
from typing import Any
from urllib.parse import urlparse


REQUEST = (
    "Capture durable context in Obsidian Brain. Do not send, reply, archive, "
    "delete, schedule, disclose, or take any unrelated external action."
)
SUPPORTED_OPERATIONS = {"email_brain_intake", "email_brain_resolve_review"}
SENSITIVITIES = {"normal", "confidential", "legal", "finance", "security"}
SECRET_PATTERN = re.compile(r"(?:api[_-]?key|access[_-]?token|private[_-]?key|password)\s*[:=]|\bsk-[A-Za-z0-9_-]{6,}", re.I)
INSTRUCTION_PATTERN = re.compile(r"\b(?:ignore|disregard|override)\b.{0,80}\b(?:policy|instruction|rules?)\b|\b(?:send|reply|archive|delete|schedule|disclose)\b", re.I | re.S)
EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_SAFE_BRAIN_PATH_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]*$")
_BRAIN_CAPTURE_ROOT = ("00 Inbox", "Email Captures")


class ContractError(ValueError):
    pass


@dataclass(frozen=True)
class IntakeInvocation:
    operation: str
    schema_version: str
    payload: dict[str, Any]


def _require_string(payload: dict[str, Any], name: str, *, maximum: int | None = None) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{name} must be a nonempty string")
    if maximum is not None and len(value) > maximum:
        raise ContractError(f"{name} exceeds maximum length")
    return value


def _validate_rfc3339(value: str) -> None:
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractError("received_at must be RFC3339") from exc


def _reject_unsafe_text(value: str) -> None:
    if SECRET_PATTERN.search(value):
        raise ContractError("secret material is prohibited")
    if INSTRUCTION_PATTERN.search(value):
        raise ContractError("embedded instruction is prohibited")


def canonical_brain_capture_path(value: object) -> str:
    """Return the sole canonical persisted Brain capture path or reject it."""
    if not isinstance(value, str) or not value or "\\" in value or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ContractError("receipt path must be a nonempty POSIX path without control characters")
    parts = value.split("/")
    if any(not part or part in {".", ".."} or part.endswith((".", " ")) or not _SAFE_BRAIN_PATH_SEGMENT.fullmatch(part) for part in parts):
        raise ContractError("receipt path contains ambiguous or unsafe segments")
    if tuple(parts[:2]) != _BRAIN_CAPTURE_ROOT or len(parts) < 3:
        raise ContractError("receipt path is outside the approved Brain capture root")
    return "/".join(parts)


def validate_payload(payload: dict[str, Any]) -> None:
    if payload.get("type") != "email_brain_intake":
        raise ContractError("unsupported payload type")
    if payload.get("schema_version") != "1.0":
        raise ContractError("unsupported payload schema_version")
    if payload.get("source") != "gmail":
        raise ContractError("unsupported source")
    for name in ("account", "gmail_thread_id", "subject"):
        _require_string(payload, name, maximum=2000)
    gmail_url = _require_string(payload, "gmail_url", maximum=4000)
    parsed_url = urlparse(gmail_url)
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
        raise ContractError("gmail_url must be an absolute URL")
    received_at = _require_string(payload, "received_at", maximum=64)
    _validate_rfc3339(received_at)
    message_ids = payload.get("gmail_message_ids")
    if not isinstance(message_ids, list) or not message_ids or any(not isinstance(i, str) or not i.strip() for i in message_ids):
        raise ContractError("gmail_message_ids must be nonempty strings")
    senders = payload.get("from")
    if not isinstance(senders, list) or not senders:
        raise ContractError("from must be a nonempty sender list")
    for sender in senders:
        if not isinstance(sender, dict) or not isinstance(sender.get("name"), str) or not EMAIL_PATTERN.fullmatch(str(sender.get("email", ""))):
            raise ContractError("invalid sender address")
    summary = _require_string(payload, "triage_summary", maximum=2000)
    excerpt = payload.get("body_excerpt", "")
    if not isinstance(excerpt, str) or len(excerpt) > 4000:
        raise ContractError("body_excerpt exceeds maximum length")
    signals = payload.get("durable_signals")
    if not isinstance(signals, list) or any(not isinstance(item, str) or not item.strip() for item in signals):
        raise ContractError("durable_signals must be strings")
    entities = payload.get("entities")
    if not isinstance(entities, dict) or set(entities) != {"people", "projects", "areas"} or any(not isinstance(entities[k], list) or any(not isinstance(v, str) for v in entities[k]) for k in entities):
        raise ContractError("entities are invalid")
    context = payload.get("action_context")
    if not isinstance(context, dict) or set(context) != {"recommended_next_action", "owner", "deadline"} or any(not isinstance(v, str) for v in context.values()):
        raise ContractError("action_context is invalid")
    if payload.get("sensitivity") not in SENSITIVITIES:
        raise ContractError("unsupported sensitivity")
    if payload.get("request") != REQUEST:
        raise ContractError("request must match the fixed safety boundary")
    for text in (summary, excerpt, payload["subject"], *signals, *context.values()):
        _reject_unsafe_text(text)


def parse_invocation(text: str) -> IntakeInvocation:
    try:
        value = json.loads(text)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ContractError("invocation must be JSON") from exc
    if not isinstance(value, dict):
        raise ContractError("invocation must be an object")
    operation = value.get("operation")
    if operation not in SUPPORTED_OPERATIONS:
        raise ContractError("unsupported operation")
    if value.get("schema_version") != "1.0":
        raise ContractError("unsupported schema_version")
    payload = value.get("payload")
    if not isinstance(payload, dict):
        raise ContractError("payload must be an object")
    if operation != "email_brain_intake":
        raise ContractError("email_brain_resolve_review is not accepted by intake payload parser")
    validate_payload(payload)
    return IntakeInvocation(operation, "1.0", payload)


def canonical_source_identity(payload: dict[str, Any]) -> bytes:
    identity = {
        "schema_version": payload["schema_version"],
        "source": payload["source"],
        "account": payload["account"],
        "gmail_thread_id": payload["gmail_thread_id"],
        "gmail_message_ids": sorted(set(payload["gmail_message_ids"])),
    }
    return json.dumps(identity, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def idempotency_key(payload: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(canonical_source_identity(payload)).hexdigest()


def validate_receipt(receipt: dict[str, Any]) -> None:
    if not isinstance(receipt, dict) or receipt.get("type") != "email_brain_receipt" or receipt.get("schema_version") != "1.0":
        raise ContractError("invalid receipt type or schema_version")
    required = {"type", "schema_version", "status", "idempotency_key", "idempotent_replay", "source", "result", "verification", "review", "error", "processed_at"}
    if set(receipt) != required:
        raise ContractError("receipt fields do not match contract")
    if receipt["status"] not in {"completed", "duplicate", "review_required", "rejected", "expired", "failed_retryable", "failed_terminal"}:
        raise ContractError("invalid receipt status")
    if not isinstance(receipt["idempotency_key"], str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", receipt["idempotency_key"]):
        raise ContractError("invalid receipt idempotency_key")
    if not isinstance(receipt["idempotent_replay"], bool):
        raise ContractError("invalid receipt idempotent_replay")
    source = receipt["source"]
    result = receipt["result"]
    verification = receipt["verification"]
    review = receipt["review"]
    error = receipt["error"]
    if not isinstance(source, dict) or set(source) != {"gmail_thread_id", "gmail_message_ids"} or not isinstance(source["gmail_thread_id"], str) or not isinstance(source["gmail_message_ids"], list) or any(not isinstance(message_id, str) for message_id in source["gmail_message_ids"]):
        raise ContractError("invalid receipt source")
    if not isinstance(result, dict) or set(result) != {"durability", "capture_note", "updated_notes", "created_notes", "unchanged_notes"} or not isinstance(result["durability"], str) or (result["capture_note"] is not None and not isinstance(result["capture_note"], str)) or any(not isinstance(result[name], list) or any(not isinstance(path, str) for path in result[name]) for name in ("updated_notes", "created_notes", "unchanged_notes")):
        raise ContractError("invalid receipt result")
    if not isinstance(verification, dict) or set(verification) != {"brain_sync", "qmd_index", "retrieval_query", "retrieved_paths", "content_hashes"} or verification["brain_sync"] not in {"passed", "failed", "not_run"} or verification["qmd_index"] not in {"passed", "failed", "not_run"} or verification["retrieval_query"] is not None or not isinstance(verification["retrieved_paths"], list) or any(not isinstance(path, str) for path in verification["retrieved_paths"]) or not isinstance(verification["content_hashes"], dict) or set(verification["content_hashes"]) - {"capture"} or any(not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value) for value in verification["content_hashes"].values()):
        raise ContractError("invalid receipt verification")
    for path in (
        *(item for item in [result["capture_note"]] if item is not None),
        *result["updated_notes"],
        *result["created_notes"],
        *result["unchanged_notes"],
        *verification["retrieved_paths"],
    ):
        canonical_brain_capture_path(path)
    if not isinstance(review, dict) or set(review) != {"required", "pending_capture_id", "discord_thread_id", "reason_codes"} or not isinstance(review["required"], bool) or (review["pending_capture_id"] is not None and (not isinstance(review["pending_capture_id"], str) or not review["pending_capture_id"])) or (review["discord_thread_id"] is not None and (not isinstance(review["discord_thread_id"], str) or not review["discord_thread_id"])) or not isinstance(review["reason_codes"], list) or any(not isinstance(code, str) for code in review["reason_codes"]):
        raise ContractError("invalid receipt review")
    if receipt["status"] in {"review_required", "rejected", "expired"} and (not review["required"] or review["pending_capture_id"] is None):
        raise ContractError("review lifecycle receipt requires a pending capture")
    if not isinstance(error, dict) or set(error) != {"code", "message", "retry_after_seconds"} or not isinstance(error["retry_after_seconds"], int) or error["retry_after_seconds"] < 0:
        raise ContractError("invalid receipt error")
    if receipt["status"] in {"completed", "duplicate", "review_required", "rejected", "expired"}:
        if error["code"] is not None or error["message"] is not None or error["retry_after_seconds"] != 0:
            raise ContractError("terminal receipt must not contain an error")
    elif error["code"] is not None and (not isinstance(error["code"], str) or not error["code"] or error["message"] is not None):
        raise ContractError("failed receipt error must be a safe code only")
    processed_at = _require_string(receipt, "processed_at", maximum=64)
    _validate_rfc3339(processed_at)
    safe_text = [
        receipt["source"]["gmail_thread_id"],
        *receipt["source"]["gmail_message_ids"],
        receipt["result"]["durability"],
        *(item for item in [receipt["result"]["capture_note"]] if item is not None),
        *receipt["result"]["updated_notes"],
        *receipt["result"]["created_notes"],
        *receipt["result"]["unchanged_notes"],
        *receipt["verification"]["retrieved_paths"],
        *receipt["review"]["reason_codes"],
    ]
    for value in safe_text:
        _reject_unsafe_text(value)
