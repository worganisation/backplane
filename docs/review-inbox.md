# Review reply inbox

Phone replies to diary and idea notifications are stored in PostgreSQL before the general assistant processes them. Each receipt keeps the original wording, exact prompt ID and kind. The Home Assistant event context ID is the idempotency key: retransmitting the same request returns its receipt, while changing its contents under that key is rejected.

## Delivery and recovery

The authenticated `POST /api/review-submissions` endpoint acknowledges durable receipt. Receipt does not mean the reply has been interpreted or exported to Obsidian. A failure before this acknowledgement is not guaranteed to be recoverable; Home Assistant reports that boundary explicitly. The inbox does not capture native Assist conversations or replace the three-tool Capture pipeline.

`POST /api/review-submissions/{id}/begin` claims a ten-minute processing attempt. The claim provides exact submission and attempt IDs to the assistant. `get_review_submission` retrieves the stored wording; `get_diary_review` or `get_idea_followup` retrieves its original context. The assistant saves through `save_review_submission`, which uses the stored destination and wording. Only diary decisions are interpreted by the assistant. Vague replies must not be treated as confirmation of attendance or a dog walk.

The first validated interpretation is persisted before domain storage and export. Retries with a pinned interpretation repair that export directly, without another model call. Attempt IDs fence stale model saves and completion callbacks. A successful receipt is terminal: neither a timeout nor later assistant speech can change it back to pending. Existing domain response identities prevent duplicate diary responses and idea development notes.

`POST /api/review-submissions/{id}/finish` stores assistant speech separately. Speech such as “saved” is not evidence of a save: only the server's `saved` status confirms export completion. An attempt that finishes without a save becomes `needs_attention`. A model crash leaves a visible processing receipt that can be retried after ten minutes. There is no automatic retry worker. Diary decisions are ordered by their original receipt time, so retrying an older answer does not override a later correction.

Use `list_review_submissions` to inspect unresolved replies and `get_review_submission` to inspect one receipt. `retry_review_submission` explicitly retries the same item. Home Assistant also offers a Retry notification action. Inactive or expired prompts retain their replies for inspection without silently choosing a new prompt. A clarification reply is a new receipt against the same original prompt, retaining its conversation ID where available. Open Assist starts a separate conversation; ask it to inspect the review inbox for recovery.

Use `archive_review_submission` only on explicit request to hide a handled or unwanted item. Archiving preserves its wording and save status and does not undo exports. Active attempts must finish or expire before archiving. Archiving does not cancel an export already in flight. Archived receipts remain readable by ID but cannot start another attempt.

## Setup and verification

The context database must be at the application's Alembic head. Backplane owns the schema and the owner-authorized `context-migrate` procedure; ordinary deployment does not apply migrations. Home Assistant uses its existing context API bearer secret for receipt, claim, status and completion requests.

Verify a phone reply reaches the inbox before model processing, then inspect both its final receipt and exported note. Exercise a model failure, an export failure and a repeated retry against the same receipt. The raw wording and original prompt must remain unchanged, with one domain response and export. Check that a clarification or failed model call is reported as needing attention rather than saved. Actual phone delivery and dictation require a phone-side check.
