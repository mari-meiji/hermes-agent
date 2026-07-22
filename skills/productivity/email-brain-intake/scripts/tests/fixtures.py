import json

REQUEST = (
    "Capture durable context in Obsidian Brain. Do not send, reply, archive, "
    "delete, schedule, disclose, or take any unrelated external action."
)


def canonical_invocation(*, message_ids=None, summary="Ada confirmed the launch commitment.", excerpt="", version="1.0"):
    payload = {
        "type": "email_brain_intake",
        "schema_version": version,
        "source": "gmail",
        "account": "adam@example.test",
        "gmail_thread_id": "thread-123",
        "gmail_message_ids": message_ids or ["m1"],
        "gmail_url": "https://mail.google.test/mail/u/0/#all/thread-123",
        "received_at": "2026-07-21T12:00:00Z",
        "from": [{"name": "Ada Example", "email": "ada@example.test"}],
        "subject": "Launch commitment",
        "triage_summary": summary,
        "durable_signals": ["project commitment"],
        "entities": {"people": [], "projects": ["Launch"], "areas": []},
        "action_context": {"recommended_next_action": "", "owner": "", "deadline": ""},
        "body_excerpt": excerpt,
        "sensitivity": "normal",
        "request": REQUEST,
    }
    return json.dumps(
        {"operation": "email_brain_intake", "schema_version": version, "payload": payload},
        sort_keys=True,
        separators=(",", ":"),
    )
