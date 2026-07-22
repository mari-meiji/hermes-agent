import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from email_brain_receipts import render_receipt
from email_brain_contract import validate_receipt

LEAK = "RECEIPT-LEAK-5fcbd0f4-0418-4b69-a1bf-f2a6bc12449b"


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

    def test_receipt_uses_safe_structural_fields_not_untrusted_result_data(self):
        receipt = render_receipt(
            idempotency_key="sha256:" + "a" * 64,
            payload={"gmail_thread_id": "thread-1", "gmail_message_ids": ["m1"]},
            capture_note="00 Inbox/Capture.md",
            verification={
                "brain_sync": "passed",
                "qmd_index": "passed",
                "retrieval_query": LEAK,
                "retrieved_paths": ["00 Inbox/Capture.md", f"/tmp/{LEAK}"],
                "content_hashes": {"capture": "a" * 64, "nested": {"error": LEAK}},
                "result": {"sender": "sender@example.com", "body": LEAK},
                "error": {"message": LEAK},
            },
            status="completed",
            durability="captured",
        )
        serialized = json.dumps(receipt, sort_keys=True)
        self.assertNotIn(LEAK, serialized)
        self.assertNotIn("sender@example.com", serialized)
        self.assertEqual(receipt["verification"]["brain_sync"], "passed")
        self.assertEqual(receipt["verification"]["qmd_index"], "passed")
        self.assertEqual(receipt["verification"]["retrieved_paths"], ["00 Inbox/Capture.md"])
        self.assertEqual(receipt["verification"]["content_hashes"], {"capture": "a" * 64})
        validate_receipt(receipt)


if __name__ == "__main__":
    unittest.main()
