"""Live, read-only fail-closed gate for sensitive Email-Brain Discord review.

The check proves the configured guild/channel and Discord permission surface before
any review adapter may create a thread or post a redacted card.  It never creates,
updates, or posts Discord content.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from typing import Any

ADAM_ID = "552613509909971005"
DISCORD_API_BASE = "https://discord.com/api/v10"

VIEW_CHANNEL = 1 << 10
SEND_MESSAGES = 1 << 11
READ_MESSAGE_HISTORY = 1 << 16
MANAGE_THREADS = 1 << 34
CREATE_PRIVATE_THREADS = 1 << 36
SEND_MESSAGES_IN_THREADS = 1 << 38

REQUIRED_BOT_PERMISSIONS = {
    "VIEW_CHANNEL": VIEW_CHANNEL,
    "SEND_MESSAGES": SEND_MESSAGES,
    "READ_MESSAGE_HISTORY": READ_MESSAGE_HISTORY,
    "MANAGE_THREADS": MANAGE_THREADS,
    "CREATE_PRIVATE_THREADS": CREATE_PRIVATE_THREADS,
    "SEND_MESSAGES_IN_THREADS": SEND_MESSAGES_IN_THREADS,
}


class ProvisioningError(RuntimeError):
    pass


def _snowflake(value: str, label: str) -> str:
    if not value.isdecimal() or int(value) <= 0:
        raise ProvisioningError(f"{label} must be a Discord snowflake")
    return value


def _permission_set(value: int, bit: int) -> bool:
    return bool(value & bit)


def _discord_get(token: str, path: str) -> dict[str, Any] | list[dict[str, Any]]:
    request = urllib.request.Request(
        f"{DISCORD_API_BASE}{path}",
        headers={
            "Authorization": f"Bot {token}",
            "Content-Type": "application/json",
            "User-Agent": "Hermes-Agent (https://github.com/NousResearch/hermes-agent)",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        raise ProvisioningError(f"Discord API rejected provisioning check ({exc.code})") from exc
    except (OSError, ValueError) as exc:
        raise ProvisioningError("Discord API provisioning check is unavailable") from exc
    if not isinstance(result, (dict, list)):
        raise ProvisioningError("Discord API returned an invalid provisioning response")
    return result


def _apply_overwrites(permission: int, overwrites: list[dict[str, Any]]) -> int:
    deny = 0
    allow = 0
    for overwrite in overwrites:
        try:
            deny |= int(str(overwrite["deny"]))
            allow |= int(str(overwrite["allow"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise ProvisioningError("Discord channel overwrite is malformed") from exc
    return (permission & ~deny) | allow


def _bot_permissions(
    *, guild_id: str, bot_id: str, bot_member: Mapping[str, Any], roles: list[dict[str, Any]], overwrites: list[dict[str, Any]],
) -> int:
    role_permissions: dict[str, int] = {}
    for role in roles:
        try:
            role_permissions[str(role["id"])] = int(str(role["permissions"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise ProvisioningError("Discord guild role is malformed") from exc
    if guild_id not in role_permissions:
        raise ProvisioningError("Discord @everyone role is unavailable")

    assigned_roles = bot_member.get("roles")
    if not isinstance(assigned_roles, list):
        raise ProvisioningError("Discord bot member roles are malformed")
    permissions = role_permissions[guild_id]
    for role_id in assigned_roles:
        permissions |= role_permissions.get(str(role_id), 0)

    everyone = [item for item in overwrites if item.get("type") == 0 and str(item.get("id")) == guild_id]
    role_overwrites = [
        item for item in overwrites
        if item.get("type") == 0 and str(item.get("id")) in {str(role_id) for role_id in assigned_roles}
    ]
    member = [item for item in overwrites if item.get("type") == 1 and str(item.get("id")) == bot_id]
    return _apply_overwrites(_apply_overwrites(_apply_overwrites(permissions, everyone), role_overwrites), member)


def check_provisioning(
    environ: Mapping[str, str] | None = None,
    *,
    api_get: Callable[[str, str], dict[str, Any] | list[dict[str, Any]]] | None = None,
) -> dict[str, str]:
    env = os.environ if environ is None else environ
    if env.get("DISCORD_ALLOW_ALL_USERS", "").strip().lower() in {"1", "true", "yes", "on"}:
        raise ProvisioningError("gateway allow-all cannot authorize restricted review actions")

    guild_id = _snowflake(env.get("EMAIL_BRAIN_REVIEW_GUILD_ID", "").strip(), "restricted review guild")
    channel_id = _snowflake(env.get("EMAIL_BRAIN_REVIEW_CHANNEL_ID", "").strip(), "restricted review channel")
    adam_id = env.get("EMAIL_BRAIN_ADAM_DISCORD_USER_ID", "").strip()
    signing_key = env.get("EMAIL_BRAIN_REVIEW_SIGNING_KEY", "").strip()
    token = env.get("DISCORD_BOT_TOKEN", "").strip()
    if adam_id != ADAM_ID:
        raise ProvisioningError("Adam immutable Discord identity is required")
    if len(signing_key) < 32:
        raise ProvisioningError("restricted review signing key is missing or too short")
    if not token:
        raise ProvisioningError("Discord bot token is required for live provisioning verification")

    get = api_get or _discord_get
    guild = get(token, f"/guilds/{guild_id}")
    channel = get(token, f"/channels/{channel_id}")
    bot = get(token, "/users/@me")
    roles = get(token, f"/guilds/{guild_id}/roles")
    if not isinstance(guild, dict) or not isinstance(channel, dict) or not isinstance(bot, dict) or not isinstance(roles, list):
        raise ProvisioningError("Discord API returned malformed provisioning data")
    bot_id = str(bot.get("id", ""))
    if not bot_id.isdecimal():
        raise ProvisioningError("Discord bot identity is malformed")
    bot_member = get(token, f"/guilds/{guild_id}/members/{bot_id}")
    if not isinstance(bot_member, dict):
        raise ProvisioningError("Discord bot membership is malformed")

    if str(guild.get("owner_id")) != ADAM_ID:
        raise ProvisioningError("Adam is not the configured guild owner")
    if str(channel.get("guild_id")) != guild_id:
        raise ProvisioningError("restricted review channel is not in the configured guild")
    overwrites = channel.get("permission_overwrites")
    if not isinstance(overwrites, list):
        raise ProvisioningError("restricted review channel overwrites are unavailable")
    if not all(isinstance(item, dict) for item in overwrites):
        raise ProvisioningError("restricted review channel overwrite is malformed")

    everyone_overwrites = [item for item in overwrites if item.get("type") == 0 and str(item.get("id")) == guild_id]
    if not any(_permission_set(int(str(item.get("deny", "0"))), VIEW_CHANNEL) for item in everyone_overwrites):
        raise ProvisioningError("@everyone must be explicitly denied View Channel")

    unexpected_members = {
        str(item.get("id")) for item in overwrites
        if item.get("type") == 1 and str(item.get("id")) not in {ADAM_ID, bot_id}
    }
    if unexpected_members:
        raise ProvisioningError("restricted review channel has an unexpected member overwrite")
    role_view_allows = [
        item for item in overwrites
        if item.get("type") == 0 and str(item.get("id")) != guild_id and _permission_set(int(str(item.get("allow", "0"))), VIEW_CHANNEL)
    ]
    if role_view_allows:
        raise ProvisioningError("restricted review channel grants View Channel through a role overwrite")

    permissions = _bot_permissions(
        guild_id=guild_id, bot_id=bot_id, bot_member=bot_member, roles=roles, overwrites=overwrites
    )
    missing = [name for name, bit in REQUIRED_BOT_PERMISSIONS.items() if not _permission_set(permissions, bit)]
    if missing:
        raise ProvisioningError("bot lacks required restricted-review permission: " + ", ".join(missing))

    # Discord guild owners bypass all channel overwrites.  Do not require an
    # artificial Adam member overwrite: Discord's owner_id is the authority.
    return {
        "status": "ENABLED",
        "guild_id": guild_id,
        "channel_id": channel_id,
        "adam_id": ADAM_ID,
        "bot_id": bot_id,
        "owner_effective_view_channel": "true",
        "required_bot_permissions": ",".join(REQUIRED_BOT_PERMISSIONS),
    }


if __name__ == "__main__":
    try:
        print(json.dumps(check_provisioning(), sort_keys=True))
    except ProvisioningError as exc:
        print(f"DISABLED: {exc}")
        raise SystemExit(1)
