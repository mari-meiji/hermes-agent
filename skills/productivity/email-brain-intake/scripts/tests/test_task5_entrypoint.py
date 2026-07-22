import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent
REVIEW_SCRIPTS = SCRIPTS.parent.parent / "email-brain-review" / "scripts"
sys.path[:0] = [str(SCRIPTS), str(REVIEW_SCRIPTS)]

from email_brain_run import execute_invocation
from fixtures import canonical_invocation


class DisposableRunner:
    def __init__(self, brain_root=None):
        self.brain_root = brain_root
        self.synced = False
        self.paths = []

    def sync(self):
        self.synced = True

    def query(self, query):
        return self.paths


class Task5EntrypointTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name) / "state" / "email-brain.sqlite3"
        self.brain = (Path(self.tmp.name) / "email-brain-disposable-test").resolve()
        self.brain.mkdir()
        (self.brain / ".email-brain-disposable").write_text("test-only\n")
        self.runner = DisposableRunner(self.brain)

    def tearDown(self):
        self.tmp.cleanup()

    def _invoke(self, *, sensitivity="normal", signals=None):
        value = json.loads(canonical_invocation())
        value["payload"]["sensitivity"] = sensitivity
        if signals is not None:
            value["payload"]["durable_signals"] = signals
        return json.dumps(value, sort_keys=True, separators=(",", ":"))

    def test_ordinary_text_never_triggers_and_returns_terminal_receipt(self):
        receipt = execute_invocation("please summarize this email", state_path=self.state, brain_root=self.brain, runner=self.runner)
        self.assertEqual(receipt["status"], "failed_terminal")
        self.assertEqual(list(self.brain.rglob("*.md")), [])

    def test_disposable_normal_capture_is_verified_and_replayed_without_second_artifact(self):
        raw = self._invoke()
        expected = "00 Inbox/Email Captures/2026-07-21 - Launch - Launch commitment.md"
        self.runner.paths = [expected]
        first = execute_invocation(raw, state_path=self.state, brain_root=self.brain, runner=self.runner)
        replay = execute_invocation(raw, state_path=self.state, brain_root=self.brain, runner=self.runner)
        self.assertEqual(first["status"], "completed")
        self.assertEqual(first["result"]["capture_note"], expected)
        self.assertTrue(self.runner.synced)
        self.assertEqual(replay["status"], "duplicate")
        self.assertTrue(replay["idempotent_replay"])
        self.assertEqual(list(self.brain.rglob("*.md")).__len__(), 1)

    def test_non_durable_candidate_writes_nothing(self):
        receipt = execute_invocation(self._invoke(signals=[]), state_path=self.state, brain_root=self.brain, runner=self.runner)
        self.assertEqual(receipt["status"], "completed")
        self.assertEqual(receipt["result"]["durability"], "not_durable")
        self.assertEqual(list(self.brain.rglob("*.md")), [])

    def test_unmarked_or_production_root_is_refused_before_mutation(self):
        unsafe = Path(self.tmp.name) / "unsafe-root"
        unsafe.mkdir()
        receipt = execute_invocation(self._invoke(), state_path=self.state, brain_root=unsafe, runner=self.runner)
        self.assertEqual(receipt["status"], "failed_terminal")
        self.assertEqual(receipt["error"]["code"], "unsafe_brain_root")
        self.assertEqual(list(unsafe.rglob("*.md")), [])

    def test_sensitive_capture_is_fail_closed_when_review_surface_is_not_verified(self):
        receipt = execute_invocation(self._invoke(sensitivity="finance"), state_path=self.state, brain_root=self.brain, runner=self.runner)
        self.assertEqual(receipt["status"], "failed_retryable")
        self.assertEqual(receipt["result"]["durability"], "blocked")
        self.assertEqual(list(self.brain.rglob("*.md")), [])


if __name__ == "__main__":
    unittest.main()
