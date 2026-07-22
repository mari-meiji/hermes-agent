"""HMAC-bound, single-purpose authentication for email-Brain review actions."""
from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
import hmac
import json


class AuthorizationError(ValueError):
    pass


def _canonical(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def sign_review_token(*, pending_capture_id: str, version: int, action: str, expires_at: str, actor_id: str, signing_key: bytes) -> str:
    payload = {"action": action, "actor_id": actor_id, "expires_at": expires_at, "pending_capture_id": pending_capture_id, "version": version}
    encoded = base64.urlsafe_b64encode(_canonical(payload)).rstrip(b"=")
    signature = hmac.new(signing_key, encoded, hashlib.sha256).hexdigest().encode("ascii")
    return (encoded + b"." + signature).decode("ascii")


def authorize_action(*, actor_id: str, token: str, action: str, pending_capture_id: str, version: int, now: str, adam_id: str, signing_key: bytes) -> dict:
    if actor_id != adam_id:
        raise AuthorizationError("actor is not authorized")
    try:
        encoded, supplied_signature = token.encode("ascii").split(b".", 1)
        expected_signature = hmac.new(signing_key, encoded, hashlib.sha256).hexdigest().encode("ascii")
        if not hmac.compare_digest(supplied_signature, expected_signature):
            raise ValueError
        payload = json.loads(base64.urlsafe_b64decode(encoded + b"=" * (-len(encoded) % 4)))
    except (ValueError, UnicodeError, json.JSONDecodeError) as exc:
        raise AuthorizationError("invalid review token") from exc
    if payload.get("action") != action:
        raise AuthorizationError("action does not match token")
    if payload.get("actor_id") != actor_id or payload.get("pending_capture_id") != pending_capture_id or payload.get("version") != version:
        raise AuthorizationError("token binding does not match action")
    try:
        expired = datetime.fromisoformat(payload["expires_at"].replace("Z", "+00:00")) <= datetime.fromisoformat(now.replace("Z", "+00:00"))
    except (KeyError, ValueError) as exc:
        raise AuthorizationError("invalid token expiry") from exc
    if expired:
        raise AuthorizationError("review token expired")
    return payload
