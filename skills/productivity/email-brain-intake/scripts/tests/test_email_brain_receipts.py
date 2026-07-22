import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from email_brain_receipts import render_receipt
from email_brain_contract import validate_receipt


class ReceiptTests(unittest.TestCase):
    def test_rendered_receipt_validates_and_redacts_source_content(self):
        receipt = render_receipt(
            idempotency_key="sha256:" + "a" * 64,
            payload={"gmail_thread_id": "thread-1", "gmail_message_ids": ["m1"]},
            capture_note="00 Inbox/Capture.md",
            verification={"brain_sync": "passed", "qmd_index": "passed", "retrieval_query": "Acme", "retrieved_paths": ["00 Inbox/Capture.md"], "content_hashes": {}},
        )
        validate_receipt(receipt)
        self.assertNotIn("body_excerpt", str(receipt))


if __name__ == "__main__":
    unittest.main()
