import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from authenticated_actions import sign_review_token
from email_brain_review import FakeDiscord, ReviewLedger, ReviewWorkflow

ADAM_ID = "552613509909971005"
PENDING_ID = "pending-123"


class DiscordReviewTransportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger = ReviewLedger(Path(self.tmp.name) / "state.sqlite3")
        self.ledger.seed_pending(PENDING_ID, version=1, sensitivity="security", summary="Redacted summary", subject="Security alert", gmail_thread_id="thread-1")
        self.transport = FakeDiscord(parent_members={ADAM_ID, "mari-bot"})
        self.calls = []
        self.workflow = ReviewWorkflow(
            self.ledger, self.transport, parent_channel_id="restricted-parent", adam_id=ADAM_ID,
            signing_key=b"key", now=lambda: "2026-07-22T12:00:00Z",
            resolution_submitter=lambda invocation: self.calls.append(invocation) or {"status": "completed"},
        )
        self.workflow.open_review(PENDING_ID)

    def tearDown(self):
        self.ledger.close()
        self.tmp.cleanup()

    def test_duplicate_component_delivery_resolves_once(self):
        token = sign_review_token(pending_capture_id=PENDING_ID, version=1, action="approve", expires_at="2026-07-29T12:00:00Z", actor_id=ADAM_ID, signing_key=b"key")
        event = {"event_id": "evt-1", "actor_id": ADAM_ID, "action": "approve", "pending_capture_id": PENDING_ID, "version": 1, "token": token}
        first = self.workflow.resolve_action(event)
        second = self.workflow.resolve_action(event)
        self.assertEqual(first, second)
        self.assertEqual(self.ledger.capture_count(PENDING_ID), 1)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.transport.posts[-1]["content"], "Review resolved: approved.")


if __name__ == "__main__":
    unittest.main()
