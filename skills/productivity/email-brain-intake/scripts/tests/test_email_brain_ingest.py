import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from email_brain_ingest import apply_update, plan_update
from email_brain_store import EmailBrainStore
from fixtures import canonical_invocation
from email_brain_contract import parse_invocation


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

    def test_existing_matching_artifact_is_reconciled_after_crash(self):
        plan = plan_update(project_payload(), brain_root=self.brain)
        plan.capture_path.parent.mkdir(parents=True, exist_ok=True)
        plan.capture_path.write_text(plan.content)
        result = apply_update(plan, self.store)
        self.assertEqual(result.operation, "reconciled")


if __name__ == "__main__":
    unittest.main()
