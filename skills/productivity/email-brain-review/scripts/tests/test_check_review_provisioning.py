import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
from check_review_provisioning import (
    ADAM_ID,
    CREATE_PRIVATE_THREADS,
    MANAGE_THREADS,
    ProvisioningError,
    READ_MESSAGE_HISTORY,
    REQUIRED_BOT_PERMISSIONS,
    SEND_MESSAGES,
    SEND_MESSAGES_IN_THREADS,
    VIEW_CHANNEL,
    check_provisioning,
)

GUILD_ID = "1494167632335868076"
CHANNEL_ID = "1529492744773566578"
BOT_ID = "1494171782708723804"
ALL_REQUIRED = sum(REQUIRED_BOT_PERMISSIONS.values())


def configured_env(**extra):
    values = {
        "DISCORD_ALLOW_ALL_USERS": "false",
        "DISCORD_BOT_TOKEN": "test-token",
        "EMAIL_BRAIN_REVIEW_GUILD_ID": GUILD_ID,
        "EMAIL_BRAIN_REVIEW_CHANNEL_ID": CHANNEL_ID,
        "EMAIL_BRAIN_ADAM_DISCORD_USER_ID": ADAM_ID,
        "EMAIL_BRAIN_REVIEW_SIGNING_KEY": "a" * 43,
    }
    values.update(extra)
    return values


def api_fixture(*, owner_id=ADAM_ID):
    return {
        f"/guilds/{GUILD_ID}": {"id": GUILD_ID, "owner_id": owner_id},
        f"/channels/{CHANNEL_ID}": {
            "id": CHANNEL_ID,
            "guild_id": GUILD_ID,
            "permission_overwrites": [
                {"id": GUILD_ID, "type": 0, "allow": "0", "deny": str(VIEW_CHANNEL)},
                {"id": BOT_ID, "type": 1, "allow": str(ALL_REQUIRED), "deny": "0"},
            ],
        },
        "/users/@me": {"id": BOT_ID},
        f"/guilds/{GUILD_ID}/roles": [
            {"id": GUILD_ID, "permissions": "0"},
        ],
        f"/guilds/{GUILD_ID}/members/{BOT_ID}": {"user": {"id": BOT_ID}, "roles": []},
    }


def api_get(data):
    def get(_token, path):
        return data[path]
    return get


class ProvisioningTests(unittest.TestCase):
    def test_missing_restricted_configuration_fails_closed(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ProvisioningError, "restricted review guild"):
                check_provisioning()

    def test_allow_all_never_enables_sensitive_review(self):
        env = configured_env(DISCORD_ALLOW_ALL_USERS="true")
        with self.assertRaisesRegex(ProvisioningError, "allow-all"):
            check_provisioning(env, api_get=api_get(api_fixture()))

    def test_owner_has_effective_view_without_redundant_member_overwrite(self):
        result = check_provisioning(configured_env(), api_get=api_get(api_fixture()))
        self.assertEqual(result["status"], "ENABLED")
        self.assertEqual(result["owner_effective_view_channel"], "true")

    def test_non_owner_is_denied_even_with_same_acl_shape(self):
        with self.assertRaisesRegex(ProvisioningError, "not the configured guild owner"):
            check_provisioning(configured_env(), api_get=api_get(api_fixture(owner_id="999999999999999999")))

    def test_missing_bot_manage_threads_is_denied(self):
        data = api_fixture()
        data[f"/channels/{CHANNEL_ID}"]["permission_overwrites"][1]["allow"] = str(
            ALL_REQUIRED - MANAGE_THREADS
        )
        with self.assertRaisesRegex(ProvisioningError, "MANAGE_THREADS"):
            check_provisioning(configured_env(), api_get=api_get(data))

    def test_unexpected_member_overwrite_is_denied(self):
        data = api_fixture()
        data[f"/channels/{CHANNEL_ID}"]["permission_overwrites"].append(
            {"id": "999999999999999999", "type": 1, "allow": str(VIEW_CHANNEL), "deny": "0"}
        )
        with self.assertRaisesRegex(ProvisioningError, "unexpected member overwrite"):
            check_provisioning(configured_env(), api_get=api_get(data))


if __name__ == "__main__":
    unittest.main()
