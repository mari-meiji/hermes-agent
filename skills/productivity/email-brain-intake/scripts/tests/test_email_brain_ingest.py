import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from email_brain_ingest import apply_update, plan_update
from email_brain_store import EmailBrainStore
from email_brain_receipts import render_receipt
from fixtures import canonical_invocation
from email_brain_contract import parse_invocation


DISTINCTIVE_EXCERPT = "EXCERPT-DO-NOT-PERSIST-1e6a3199-d420-4471-9396-c909111402b5"


def project_payload():
    payload = parse_invocation(canonical_invocation(summary="Acme committed to launch. Adam owns the next step.", excerpt="FULL RAW BODY must never be retained.")).payload
    payload["action_context"]["owner"] = "Adam"
    return payload


class IngestTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.brain = Path(self.tempdir.name) / "brain"
        self.store = EmailBrainStore(Path(self.tempdir.name) / "state.sqlite3")

    def tearDown(self):
        self.store.close()
        self.tempdir.cleanup()

    def test_project_commitment_writes_capture_without_raw_body(self):
        plan = plan_update(project_payload(), brain_root=self.brain)
        result = apply_update(plan, self.store)
        text = Path(result.capture_note).read_text()
        self.assertIn("Gmail thread:", text)
        self.assertIn("Owner: Adam", text)
        self.assertNotIn("FULL RAW BODY", text)

    def test_distinctive_excerpt_never_reaches_database_artifact_or_receipt(self):
        payload = parse_invocation(canonical_invocation(excerpt=DISTINCTIVE_EXCERPT)).payload
        plan = plan_update(payload, brain_root=self.brain)
        key = plan.idempotency_key
        claim = self.store.claim_intake(key, "d" * 64, json.dumps(payload, sort_keys=True))
        result = apply_update(plan, self.store)
        receipt = render_receipt(
            idempotency_key=key,
            payload=payload,
            capture_note=plan.relative_path,
            verification={"brain_sync": "passed", "qmd_index": "passed", "retrieved_paths": [plan.relative_path], "content_hashes": {"capture": result.content_hash}},
        )
        self.store.finish_intake(key, claim.claim_token, receipt)
        self.assertNotIn(DISTINCTIVE_EXCERPT.encode(), (Path(self.tempdir.name) / "state.sqlite3").read_bytes())
        self.assertNotIn(DISTINCTIVE_EXCERPT, Path(result.capture_note).read_text())
        self.assertNotIn(DISTINCTIVE_EXCERPT, json.dumps(receipt, sort_keys=True))

    def test_existing_matching_artifact_is_reconciled_after_crash(self):
        plan = plan_update(project_payload(), brain_root=self.brain)
        plan.capture_path.parent.mkdir(parents=True, exist_ok=True)
        plan.capture_path.write_text(plan.content)
        result = apply_update(plan, self.store)
        self.assertEqual(result.operation, "reconciled")


if __name__ == "__main__":
    unittest.main()
