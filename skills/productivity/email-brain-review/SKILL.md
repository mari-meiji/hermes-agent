---
name: email-brain-review
description: Fail-closed restricted Discord review for explicitly selected email Brain review operations.
---

Trigger only for canonical JSON operations email_brain_open_review, email_brain_record_review_action, or email_brain_expire_review with schema version 1.0. Do not infer review activity from ordinary Discord or email text.

Before any Discord operation, run scripts/check_review_provisioning.py. If it fails, post nothing, create nothing, schedule nothing, and return the safe retryable status to the calling intake workflow. The gateway-wide allow-all setting is never authorization.

A live adapter must independently verify the restricted parent membership and authenticated immutable actor ID before it creates a thread, posts a redacted card, or resolves an action. Only Adam ID 552613509909971005 may approve, reject, or request safer context. Do not use natural-language approval.

Never write raw email, attachments, credentials, account figures, or legal advice to Discord. Use only the deterministic scripts and return a single JSON receipt/status with no prose.
