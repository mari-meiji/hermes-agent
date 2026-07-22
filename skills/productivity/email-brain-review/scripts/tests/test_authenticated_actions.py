import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from authenticated_actions import AuthorizationError, authorize_action, sign_review_token

ADAM_ID = "552613509909971005"
TOKEN = sign_review_token(
    pending_capture_id="pending-123",
    version=1,
    action="approve",
    expires_at="2026-07-29T12:00:00Z",
    actor_id=ADAM_ID,
    signing_key=b"test-review-signing-key",
)


class AuthenticatedActionTests(unittest.TestCase):
    def test_only_adam_can_approve(self):
        with self.assertRaisesRegex(AuthorizationError, "actor"):
            authorize_action(
                actor_id="other",
                token=TOKEN,
                action="approve",
                pending_capture_id="pending-123",
                version=1,
                now="2026-07-22T12:00:00Z",
                adam_id=ADAM_ID,
                signing_key=b"test-review-signing-key",
            )

    def test_token_is_single_action_and_rejects_tampering(self):
        with self.assertRaisesRegex(AuthorizationError, "action"):
            authorize_action(
                actor_id=ADAM_ID,
                token=TOKEN,
                action="reject",
                pending_capture_id="pending-123",
                version=1,
                now="2026-07-22T12:00:00Z",
                adam_id=ADAM_ID,
                signing_key=b"test-review-signing-key",
            )


if __name__ == "__main__":
    unittest.main()
