import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from email_brain_review import FakeDiscord, ReviewLedger, ReviewWorkflow

ADAM_ID = "552613509909971005"
PENDING_ID = "pending-123"


class ReviewExpiryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger = ReviewLedger(Path(self.tmp.name) / "state.sqlite3")
        self.ledger.seed_pending(PENDING_ID, version=1, sensitivity="legal", summary="Redacted", subject="Legal", gmail_thread_id="thread-1", expires_at="2026-07-29T12:00:00Z")
        self.transport = FakeDiscord(parent_members={ADAM_ID, "mari-bot"})
        self.workflow = ReviewWorkflow(self.ledger, self.transport, parent_channel_id="restricted-parent", adam_id=ADAM_ID, signing_key=b"key", now=lambda: "2026-07-22T12:00:00Z")
        self.workflow.open_review(PENDING_ID)

    def tearDown(self):
        self.ledger.close()
        self.tmp.cleanup()

    def test_reminders_are_each_posted_once(self):
        first = self.workflow.process_due_reviews("2026-07-23T12:00:00Z")
        second = self.workflow.process_due_reviews("2026-07-23T12:00:00Z")
        self.assertEqual([item["status"] for item in first], ["reminded_24h"])
        self.assertEqual(second, [])
        self.assertEqual(len(self.transport.posts), 2)
        self.assertEqual(self.transport.posts[-1]["mentions"], [])

    def test_seven_day_expiry_never_captures(self):
        results = self.workflow.process_due_reviews("2026-07-29T12:00:00Z")
        self.assertEqual(results[0]["status"], "expired")
        self.assertEqual(self.ledger.capture_count(PENDING_ID), 0)
        self.assertTrue(self.transport.archived_threads)


if __name__ == "__main__":
    unittest.main()
