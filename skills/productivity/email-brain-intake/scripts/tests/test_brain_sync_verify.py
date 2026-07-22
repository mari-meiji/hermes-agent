import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from brain_sync_verify import VerificationPending, sync_and_verify
from email_brain_ingest import MutationResult


class FakeRunner:
    def __init__(self, qmd_paths):
        self.qmd_paths = qmd_paths

    def sync(self):
        return None

    def query(self, query):
        return self.qmd_paths


MUTATION_RESULT = MutationResult(
    capture_note="00 Inbox/Email Captures/2026-07-21 - Acme - Launch.md",
    operation="created",
    content_hash="a" * 64,
    retrieval_query="Acme launch commitment",
)


class SyncVerifyTests(unittest.TestCase):
    def test_verification_requires_expected_path(self):
        runner = FakeRunner(qmd_paths=["25 People/Other.md"])
        with self.assertRaises(VerificationPending):
            sync_and_verify(MUTATION_RESULT, runner)

    def test_verification_accepts_expected_path(self):
        runner = FakeRunner(qmd_paths=[MUTATION_RESULT.capture_note])
        result = sync_and_verify(MUTATION_RESULT, runner)
        self.assertEqual(result.retrieved_paths, [MUTATION_RESULT.capture_note])


if __name__ == "__main__":
    unittest.main()
