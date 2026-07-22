"""Read-only fail-closed gate for sensitive Email-Brain Discord review.

This intentionally does not create a channel, edit Hermes config, or call Discord.
A live adapter must separately provide cryptographic/ACL evidence of membership before
it is permitted to post a redacted review card.
"""
from __future__ import annotations

import os

ADAM_ID = "552613509909971005"


class ProvisioningError(RuntimeError):
    pass


def check_provisioning(environ: dict[str, str] | None = None) -> dict[str, str]:
    env = os.environ if environ is None else environ
    if env.get("DISCORD_ALLOW_ALL_USERS", "").strip().lower() in {"1", "true", "yes", "on"}:
        raise ProvisioningError("gateway allow-all cannot authorize restricted review actions")
    channel = env.get("EMAIL_BRAIN_REVIEW_CHANNEL_ID", "").strip()
    adam = env.get("EMAIL_BRAIN_ADAM_DISCORD_USER_ID", "").strip()
    key = env.get("EMAIL_BRAIN_REVIEW_SIGNING_KEY", "").strip()
    if not channel or not adam or not key:
        raise ProvisioningError("restricted review configuration is incomplete")
    if adam != ADAM_ID:
        raise ProvisioningError("Adam immutable Discord identity is required")
    # Environment/configuration can never prove Discord ACLs. This standalone,
    # read-only command therefore remains disabled until a live transport calls
    # its own authenticated membership check immediately before every effect.
    raise ProvisioningError("restricted membership requires live adapter verification")


if __name__ == "__main__":
    try:
        check_provisioning()
    except ProvisioningError as exc:
        print(f"DISABLED: {exc}")
        raise SystemExit(1)
    print("ENABLED: restricted review provisioning is verified")
