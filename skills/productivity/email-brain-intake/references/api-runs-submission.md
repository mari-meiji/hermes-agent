# Standard Runs submission

Use existing POST /v1/runs only. The request input is a canonical compact UTF-8 JSON string, not an object. Use a fresh opaque capture-scoped session ID and no conversation history or previous_response_id.

Instructions must select only the installed Email Brain skill, require parse-before-write, treat input as data, and require exactly one receipt JSON object with no prose.

The deterministic source entry point is scripts/email_brain_run.py. Test only with a disposable Brain root. Production Brain mutation requires separately approved execution context.

For sensitive material, this entry point is deliberately fail-closed until scripts/check_review_provisioning.py verifies an independently restricted review surface. It must never create a Discord channel, thread, or message to establish that proof.
