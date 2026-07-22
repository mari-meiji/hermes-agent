"""Deterministic entry point for explicitly selected Email-to-Mari Brain Runs.

This module is deliberately transport-agnostic: Hermes /v1/runs supplies only the
string-valued invocation. No Gmail, calendar, Discord, or general messaging tools
are used here. Sensitive intake is fail-closed until a separately provisioned,
verifiably restricted review surface dispatches a resolution invocation.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

from brain_sync_verify import VerificationPending, sync_and_verify
from email_brain_contract import ContractError, idempotency_key, parse_invocation
from email_brain_ingest import apply_update, plan_update
from email_brain_receipts import render_receipt
from email_brain_store import EmailBrainStore


SENSITIVE = {"confidential", "legal", "finance", "security"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _source(payload: dict[str, Any]) -> dict[str, Any]:
    return {"gmail_thread_id": payload.get("gmail_thread_id", ""), "gmail_message_ids": sorted(set(payload.get("gmail_message_ids", [])))}


def _terminal_error(*, payload: dict[str, Any], key: str, code: str, retryable: bool) -> dict[str, Any]:
    receipt = render_receipt(
        idempotency_key=key,
        payload=payload,
        capture_note=None,
        verification={"brain_sync": "not_run", "qmd_index": "not_run", "retrieved_paths": [], "content_hashes": {}},
        status="failed_retryable" if retryable else "failed_terminal",
        durability="blocked",
    )
    receipt["error"] = {"code": code, "message": None, "retry_after_seconds": 60 if retryable else 0}
    return receipt


def _malformed_receipt(code: str) -> dict[str, Any]:
    return {
        "type": "email_brain_receipt", "schema_version": "1.0", "status": "failed_terminal",
        "idempotency_key": "sha256:" + hashlib.sha256(code.encode("utf-8")).hexdigest(), "idempotent_replay": False,
        "source": {"gmail_thread_id": "", "gmail_message_ids": []},
        "result": {"durability": "blocked", "capture_note": None, "updated_notes": [], "created_notes": [], "unchanged_notes": []},
        "verification": {"brain_sync": "not_run", "qmd_index": "not_run", "retrieval_query": None, "retrieved_paths": [], "content_hashes": {}},
        "review": {"required": False, "pending_capture_id": None, "discord_thread_id": None, "reason_codes": []},
        "error": {"code": code, "message": None, "retry_after_seconds": 0}, "processed_at": _now(),
    }


def _verified_disposable_root(value: str | Path) -> Path | None:
    root = Path(value)
    try:
        resolved = root.resolve(strict=True)
    except OSError:
        return None
    marker = resolved / ".email-brain-disposable"
    if root != resolved or not resolved.name.startswith("email-brain-disposable-") or not marker.is_file() or marker.is_symlink():
        return None
    return resolved


def execute_invocation(text: str, *, state_path: str | Path, brain_root: str | Path, runner: Any | None = None) -> dict[str, Any]:
    """Execute exactly one explicit intake invocation and return exactly one receipt."""
    try:
        invocation = parse_invocation(text)
    except ContractError as exc:
        return _malformed_receipt("invalid_invocation")
    payload = invocation.payload
    key = idempotency_key(payload)
    safe_root = _verified_disposable_root(brain_root)
    if safe_root is None:
        return _terminal_error(payload=payload, key=key, code="unsafe_brain_root", retryable=False)
    if runner is None:
        return _terminal_error(payload=payload, key=key, code="disposable_verifier_required", retryable=True)
    try:
        runner_root = Path(runner.brain_root).resolve(strict=True)
    except (AttributeError, OSError, TypeError):
        return _terminal_error(payload=payload, key=key, code="disposable_verifier_required", retryable=True)
    if runner_root != safe_root:
        return _terminal_error(payload=payload, key=key, code="disposable_verifier_root_mismatch", retryable=True)
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    payload_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    store = EmailBrainStore(state_path)
    try:
        claim = store.claim_intake(key, payload_hash, canonical)
        if claim.kind == "replay":
            return claim.receipt or _terminal_error(payload=payload, key=key, code="missing_replay", retryable=True)
        if claim.kind != "process" or not claim.claim_token:
            return _terminal_error(payload=payload, key=key, code="intake_in_progress", retryable=True)
        if payload["sensitivity"] in SENSITIVE:
            # Review creation is intentionally unavailable until independent ACL and
            # actor authorization provisioning can be proven. Never write or post.
            receipt = _terminal_error(payload=payload, key=key, code="review_surface_not_provisioned", retryable=True)
            return store.finish_intake(key, claim.claim_token, receipt)
        if not payload["durable_signals"]:
            receipt = render_receipt(
                idempotency_key=key, payload=payload, capture_note=None,
                verification={"brain_sync": "not_run", "qmd_index": "not_run", "retrieved_paths": [], "content_hashes": {}},
                durability="not_durable",
            )
            return store.finish_intake(key, claim.claim_token, receipt)
        plan = plan_update(payload, safe_root)
        mutation = apply_update(plan, store)
        try:
            verification = sync_and_verify(mutation, runner)
        except VerificationPending:
            receipt = _terminal_error(payload=payload, key=key, code="verification_pending", retryable=True)
            return store.finish_intake(key, claim.claim_token, receipt)
        receipt = render_receipt(
            idempotency_key=key, payload=payload, capture_note=plan.relative_path,
            verification={
                "brain_sync": verification.brain_sync, "qmd_index": verification.qmd_index,
                "retrieved_paths": [plan.relative_path], "content_hashes": {"capture": mutation.content_hash},
            },
        )
        return store.finish_intake(key, claim.claim_token, receipt)
    finally:
        store.close()
