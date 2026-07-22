import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from email_brain_store import EmailBrainStore

KEY = "sha256:" + "a" * 64
DISTINCTIVE_EXCERPT = "EXCERPT-DO-NOT-PERSIST-7e56dbec-0a5a-4fe7-a4f4-0c6654214fd3"
PAYLOAD_JSON = json.dumps({
    "subject": "Original",
    "body_excerpt": DISTINCTIVE_EXCERPT,
    "from": [{"email": "sender@example.com"}],
    "account": "adam@meghji.org",
    "gmail_thread_id": "thread-1",
    "gmail_message_ids": ["m1"],
    "triage_summary": "A durable project update.",
    "durable_signals": ["Project status changed."],
}, sort_keys=True)
PAYLOAD_HASH = "a" * 64
CORRECTED_SUMMARY_JSON = json.dumps({"subject": "Corrected"}, sort_keys=True)
CORRECTED_SUMMARY_HASH = "b" * 64
COMPLETED_RECEIPT = {
    "status": "completed",
    "idempotent_replay": False,
    "result": {"durability": "captured", "capture_note": "00 Inbox/example.md"},
}


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tempdir.name) / "email-brain.sqlite3"
        self.store = EmailBrainStore(self.db_path)

    def tearDown(self):
        self.store.close()
        self.tempdir.cleanup()

    def claim(self):
        return self.store.claim_intake(KEY, PAYLOAD_HASH, PAYLOAD_JSON)

    def finish(self, claim, receipt=COMPLETED_RECEIPT):
        return self.store.finish_intake(KEY, claim.claim_token, receipt)

    def test_same_key_replays_stored_receipt(self):
        first = self.claim()
        self.assertEqual(first.kind, "process")
        self.finish(first)
        replay = self.store.claim_intake(KEY, PAYLOAD_HASH, PAYLOAD_JSON)
        self.assertEqual(replay.kind, "replay")
        self.assertEqual(replay.receipt["status"], "duplicate")
        self.assertTrue(replay.receipt["idempotent_replay"])
        self.assertEqual(replay.receipt["result"], COMPLETED_RECEIPT["result"])

    def test_corrected_summary_for_same_source_does_not_duplicate(self):
        claim = self.claim()
        self.finish(claim)
        replay = self.store.claim_intake(KEY, CORRECTED_SUMMARY_HASH, CORRECTED_SUMMARY_JSON)
        self.assertEqual(replay.kind, "replay")
        self.assertEqual(self.store.mutation_count(KEY), 1)

    def test_claim_never_persists_distinctive_excerpt_or_sender_address(self):
        claim = self.claim()
        self.finish(claim)
        database_bytes = self.db_path.read_bytes()
        self.assertNotIn(DISTINCTIVE_EXCERPT.encode(), database_bytes)
        self.assertNotIn(b"sender@example.com", database_bytes)
        row = sqlite3.connect(self.db_path).execute(
            "SELECT payload_json FROM intake_receipts WHERE idempotency_key=?", (KEY,)
        ).fetchone()
        self.assertIsNotNone(row)
        normalized = json.loads(row[0])
        self.assertNotIn("body_excerpt", normalized)
        self.assertNotIn("from", normalized)
        self.assertEqual(normalized["gmail_thread_id"], "thread-1")
        self.assertEqual(normalized["triage_summary"], "A durable project update.")

    def test_stale_worker_cannot_finish_after_foreign_claim(self):
        first = self.claim()
        self.store.release_claim_for_retry(KEY, first.claim_token)
        replacement = self.claim()
        self.assertEqual(replacement.kind, "process")
        with self.assertRaisesRegex(RuntimeError, "claim"):
            self.finish(first)
        self.finish(replacement)

    def test_duplicate_finalization_cannot_overwrite_completed_receipt(self):
        claim = self.claim()
        completed = self.finish(claim)
        with self.assertRaisesRegex(RuntimeError, "claim"):
            self.finish(claim, {"status": "failed_retryable", "result": {"durability": "blocked"}})
        replay = self.store.claim_intake(KEY, PAYLOAD_HASH, PAYLOAD_JSON)
        self.assertEqual(replay.receipt["result"], completed["result"])

    def test_review_compare_and_swap_is_single_use(self):
        pending = self.store.create_pending_review(KEY, payload=PAYLOAD_JSON, version=1)
        result = self.store.resolve_review(pending, expected_version=1, event_id="evt-1", action="approve")
        self.assertEqual(result.kind, "apply")
        replay = self.store.resolve_review(pending, expected_version=1, event_id="evt-1", action="approve")
        self.assertEqual(replay.kind, "replay")


if __name__ == "__main__":
    unittest.main()
