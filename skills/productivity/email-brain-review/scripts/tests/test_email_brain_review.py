import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent
INTAKE_SCRIPTS = SCRIPTS.parent.parent / "email-brain-intake" / "scripts"
sys.path[:0] = [str(SCRIPTS), str(INTAKE_SCRIPTS)]

from email_brain_review import (
    FakeDiscord,
    RestrictedSurfaceError,
    ReviewLedger,
    ReviewWorkflow,
)

ADAM_ID = "552613509909971005"
PENDING_ID = "pending-123"


class EmailBrainReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger = ReviewLedger(Path(self.tmp.name) / "state.sqlite3")
        self.ledger.seed_pending(
            PENDING_ID,
            version=1,
            sensitivity="finance",
            summary="Private figure 123456; raw body must never appear.",
            subject="Bank account reconciliation",
            gmail_thread_id="thread-sensitive-123",
        )
        self.transport = FakeDiscord(parent_members={ADAM_ID, "mari-bot"})
        self.workflow = ReviewWorkflow(
            self.ledger,
            self.transport,
            parent_channel_id="restricted-parent",
            adam_id=ADAM_ID,
            signing_key=b"test-review-signing-key",
            now=lambda: "2026-07-22T12:00:00Z",
        )

    def tearDown(self):
        self.ledger.close()
        self.tmp.cleanup()

    def test_privacy_check_failure_posts_nothing(self):
        blocked = ReviewWorkflow(
            self.ledger,
            FakeDiscord(parent_members={"someone-else"}),
            parent_channel_id="restricted-parent",
            adam_id=ADAM_ID,
            signing_key=b"test-review-signing-key",
            now=lambda: "2026-07-22T12:00:00Z",
        )
        with self.assertRaises(RestrictedSurfaceError):
            blocked.open_review(PENDING_ID)
        self.assertEqual(blocked.transport.posts, [])

    def test_rejects_any_review_identity_other_than_adam_immutable_id(self):
        with self.assertRaisesRegex(RestrictedSurfaceError, "immutable"):
            ReviewWorkflow(self.ledger, self.transport, parent_channel_id="restricted-parent", adam_id="other", signing_key=b"key", now=lambda: "2026-07-22T12:00:00Z")

    def test_open_review_mentions_adam_once_and_redacts_sensitive_values(self):
        receipt = self.workflow.open_review(PENDING_ID)
        self.assertEqual(receipt["status"], "review_required")
        self.assertEqual(len(self.transport.posts), 1)
        card = self.transport.posts[0]["content"]
        self.assertEqual(self.transport.posts[0]["mentions"], [ADAM_ID])
        self.assertIn("Review required", card)
        self.assertNotIn("123456", card)
        self.assertNotIn("raw body", card)
        replay = self.workflow.open_review(PENDING_ID)
        self.assertEqual(replay, receipt)
        self.assertEqual(len(self.transport.posts), 1)


if __name__ == "__main__":
    unittest.main()
