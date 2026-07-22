"""Expiry entry point delegated to the deterministic workflow."""


def process_due_reviews(workflow, now: str) -> list[dict]:
    return workflow.process_due_reviews(now)
