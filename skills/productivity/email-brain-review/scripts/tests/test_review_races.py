import sys
import tempfile
import threading
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from authenticated_actions import sign_review_token
from email_brain_review import FakeDiscord, RestrictedSurfaceError, ReviewLedger, ReviewWorkflow


ADAM_ID = "552613509909971005"
PENDING_ID = "pending-race"
SIGNING_KEY = b"race-test-key"
TOKEN_EXPIRES = "2026-07-30T12:00:00Z"


def approved_event(event_id: str) -> dict:
    return {
        "event_id": event_id,
        "actor_id": ADAM_ID,
        "action": "approve",
        "pending_capture_id": PENDING_ID,
        "version": 1,
        "token": sign_review_token(
            pending_capture_id=PENDING_ID,
            version=1,
            action="approve",
            expires_at=TOKEN_EXPIRES,
            actor_id=ADAM_ID,
            signing_key=SIGNING_KEY,
        ),
    }


class ReviewRaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "state.sqlite3"
        self.ledger = ReviewLedger(self.db)
        self.ledger.seed_pending(
            PENDING_ID,
            version=1,
            sensitivity="finance",
            summary="Redacted",
            subject="Redacted",
            gmail_thread_id="thread-race",
            expires_at="2026-07-29T12:00:00Z",
        )
        self.transport = FakeDiscord(parent_members={ADAM_ID, "mari-bot"})

    def tearDown(self):
        self.ledger.close()
        self.tmp.cleanup()

    def workflow(self, *, now="2026-07-22T12:00:00Z", submitter=None, ledger=None):
        return ReviewWorkflow(
            ledger or self.ledger,
            self.transport,
            parent_channel_id="restricted-parent",
            adam_id=ADAM_ID,
            signing_key=SIGNING_KEY,
            now=lambda: now,
            resolution_submitter=submitter,
        )

    def test_different_events_with_same_token_claim_one_resolution(self):
        started = threading.Event()
        release = threading.Event()
        calls = []
        results, errors = [], []

        def submitter(invocation):
            calls.append(invocation)
            started.set()
            release.wait(timeout=2)
            return {"status": "completed"}

        def resolve(event_id):
            ledger = ReviewLedger(self.db)
            workflow = self.workflow(submitter=submitter, ledger=ledger)
            try:
                results.append(workflow.resolve_action(approved_event(event_id)))
            except Exception as exc:
                errors.append(exc)
            finally:
                ledger.close()

        first_thread = threading.Thread(target=resolve, args=("evt-one",))
        first_thread.start()
        self.assertTrue(started.wait(timeout=2))
        second_thread = threading.Thread(target=resolve, args=("evt-two",))
        second_thread.start()
        second_thread.join(timeout=2)
        release.set()
        first_thread.join(timeout=2)

        self.assertEqual(len(calls), 1)
        self.assertEqual(len(results), 1)
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], RestrictedSurfaceError)
        self.assertEqual(self.ledger.pending(PENDING_ID)["state"], "approved")

    def test_expired_pending_row_never_calls_resolver(self):
        calls = []
        workflow = self.workflow(now="2026-07-29T12:00:00Z", submitter=lambda invocation: calls.append(invocation))

        with self.assertRaisesRegex(RestrictedSurfaceError, "expired"):
            workflow.resolve_action(approved_event("evt-expired"))

        self.assertEqual(calls, [])
        self.assertEqual(self.ledger.pending(PENDING_ID)["state"], "pending")

    def test_scheduler_cannot_expire_after_approval_claims_resolution(self):
        started = threading.Event()
        release = threading.Event()
        calls = []

        def submitter(invocation):
            calls.append(invocation)
            started.set()
            release.wait(timeout=2)
            return {"status": "completed"}

        result = []

        def resolve():
            ledger = ReviewLedger(self.db)
            workflow = self.workflow(submitter=submitter, ledger=ledger)
            try:
                result.append(workflow.resolve_action(approved_event("evt-race")))
            finally:
                ledger.close()

        thread = threading.Thread(target=resolve)
        thread.start()
        self.assertTrue(started.wait(timeout=2))

        scheduler = self.workflow(now="2026-07-29T12:00:00Z")
        self.assertEqual(scheduler.process_due_reviews("2026-07-29T12:00:00Z"), [])
        self.assertEqual(self.ledger.pending(PENDING_ID)["state"], "resolving")
        release.set()
        thread.join(timeout=2)

        self.assertEqual(len(calls), 1)
        self.assertEqual(result[0]["status"], "completed")
        self.assertEqual(self.ledger.pending(PENDING_ID)["state"], "approved")


if __name__ == "__main__":
    unittest.main()
