"""Scheduler-safe entry point; caller injects an already configured workflow."""
from review_expiry import process_due_reviews


def tick(workflow, now: str) -> list[dict]:
    return process_due_reviews(workflow, now)
