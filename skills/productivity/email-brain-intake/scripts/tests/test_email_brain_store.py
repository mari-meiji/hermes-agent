import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from email_brain_store import EmailBrainStore

KEY = "sha256:" + "a" * 64
PAYLOAD_JSON = json.dumps({"subject": "Original"}, sort_keys=True)
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
        self.store = EmailBrainStore(Path(self.tempdir.name) / "email-brain.sqlite3")

    def tearDown(self):
        self.store.close()
        self.tempdir.cleanup()

    def test_same_key_replays_stored_receipt(self):
        first = self.store.claim_intake(KEY, PAYLOAD_HASH, PAYLOAD_JSON)
        self.assertEqual(first.kind, "process")
        self.store.finish_intake(KEY, COMPLETED_RECEIPT)
        replay = self.store.claim_intake(KEY, PAYLOAD_HASH, PAYLOAD_JSON)
        self.assertEqual(replay.kind, "replay")
        self.assertEqual(replay.receipt["status"], "duplicate")
        self.assertTrue(replay.receipt["idempotent_replay"])
        self.assertEqual(replay.receipt["result"], COMPLETED_RECEIPT["result"])

    def test_corrected_summary_for_same_source_does_not_duplicate(self):
        self.store.claim_intake(KEY, PAYLOAD_HASH, PAYLOAD_JSON)
        self.store.finish_intake(KEY, COMPLETED_RECEIPT)
        replay = self.store.claim_intake(KEY, CORRECTED_SUMMARY_HASH, CORRECTED_SUMMARY_JSON)
        self.assertEqual(replay.kind, "replay")
        self.assertEqual(self.store.mutation_count(KEY), 1)

    def test_review_compare_and_swap_is_single_use(self):
        pending = self.store.create_pending_review(KEY, payload=PAYLOAD_JSON, version=1)
        result = self.store.resolve_review(pending, expected_version=1, event_id="evt-1", action="approve")
        self.assertEqual(result.kind, "apply")
        replay = self.store.resolve_review(pending, expected_version=1, event_id="evt-1", action="approve")
        self.assertEqual(replay.kind, "replay")


if __name__ == "__main__":
    unittest.main()
