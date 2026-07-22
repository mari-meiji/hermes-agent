import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
from check_review_provisioning import ProvisioningError, check_provisioning


class ProvisioningTests(unittest.TestCase):
    def test_missing_restricted_configuration_fails_closed(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ProvisioningError, "restricted"):
                check_provisioning()

    def test_allow_all_never_enables_sensitive_review(self):
        with patch.dict(os.environ, {
            "DISCORD_ALLOW_ALL_USERS": "true",
            "EMAIL_BRAIN_REVIEW_CHANNEL_ID": "123",
            "EMAIL_BRAIN_ADAM_DISCORD_USER_ID": "552613509909971005",
            "EMAIL_BRAIN_REVIEW_SIGNING_KEY": "test-key",
        }, clear=True):
            with self.assertRaisesRegex(ProvisioningError, "allow-all"):
                check_provisioning()
    def test_environment_self_attestation_never_enables_review(self):
        with patch.dict(os.environ, {
            "DISCORD_ALLOW_ALL_USERS": "false",
            "EMAIL_BRAIN_REVIEW_CHANNEL_ID": "123",
            "EMAIL_BRAIN_ADAM_DISCORD_USER_ID": "552613509909971005",
            "EMAIL_BRAIN_REVIEW_SIGNING_KEY": "test-key",
            "EMAIL_BRAIN_RESTRICTED_MEMBERSHIP_VERIFIED": "true",
        }, clear=True):
            with self.assertRaisesRegex(ProvisioningError, "live adapter"):
                check_provisioning()


if __name__ == "__main__":
    unittest.main()
