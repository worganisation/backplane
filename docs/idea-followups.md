# Idea follow-ups

Idea follow-ups use the context database for notification claims and immutable responses, and the Obsidian vault for original ideas and development notes. Original capture files are never rewritten. Individual `idea-…` IDs are eligible; legacy minute groups and setup probes are excluded. Ideas already linked from a task's `source_capture` are excluded too.

## Notification lifecycle

Home Assistant checks every 15 minutes while `input_boolean.idea_followups` is enabled. It requires `person.will` to be home for 15 minutes, `binary_sensor.will_mood_prompt_receptive` to be on for 10 minutes, and `binary_sensor.quiet_hours` to be off. Unknown or unavailable required signals suppress selection. The receptive sensor incorporates phone activity, do-not-disturb, call activity, exercise, personal laptop focus and an 08:00–22:00 window; it is a conservative availability proxy, not proof of free time.

`POST /api/idea-followups/reserve` atomically claims the oldest eligible idea under the shared user policy lock. There is at most one idea notification per rolling 24 hours, also subject to the shared context budget and cooldown. A claim is returned only once, including across concurrent requests and process restarts. Losing the response or failing to send the notification does not trigger automatic redelivery. This deliberately favours a missed optional prompt over repeated interruptions.

Notifications use `script.notify_will` and offer Reply / dictate, Tomorrow and Dismiss. Replies carry the exact prompt ID through the general Backplane-enabled agent, and subsequent replies retain its conversation ID. Tapping the notification opens the explicitly selected general Assist pipeline as a separate conversation; it does not carry the notification's prompt context. A 12-hour phone timeout bounds stale notifications. “Tomorrow” records an idempotent snooze and permits one retry at least 24 hours later, when the availability conditions hold again. An ignored, dismissed or expanded idea receives no automatic repeat. There are at most two notifications for any idea.

The `/delivered` callback records notification submission, with `receipt_confirmed: false`; successful HA service execution does not prove that a phone displayed it. Separate event-driven callbacks persist snooze/dismiss across HA restarts and clear the exact notification only after the server confirms the action.

## Assist and saved elaboration

The GPT conversation agent uses `deploy/assist-prompt.jinja` followed by `deploy/idea-followup-prompt.jinja` as its repository-managed instructions. Apply their combined text through the supported HA conversation subentry configuration API; do not edit `.storage`. The follow-up fragment takes precedence for an existing idea discussion.

Use Reply / dictate on the notification for an exact prompt handoff. The agent calls `get_idea_followup` with that prompt ID before discussing it. The response contains the exact prompt ID, stable idea ID, original wording and prior elaborations. Implicit context expires after 12 hours and excludes snoozed or dismissed prompts. Explicit IDs can retrieve older conversations; an absent current context requires clarification rather than selecting a different idea.

`save_idea_elaboration` stores the user's wording as an immutable context response and writes one Markdown note in `Inbox/Idea development/<capture_id>/<response_id>.md`, linked to the original idea. Identical text on the same prompt is idempotent. If the vault write fails after the database save, retrying repairs the export without duplicating the response. The tool confirms success only when the export succeeds.

Developing an idea does not create a commitment. When explicitly requested, use `capture_task` followed by `link_task_to_capture` with the returned task metadata filename without its final `.md` extension and the original capture ID. This saves a task without a second model call; pass `project` when the user explicitly assigns it. Reuse the same task idempotency key on retries; retry the linking step if it fails. Use `create_vault_entity` for an explicitly requested project and place the original idea and development-note links in its Overview. Keep speculation in the development note.

## Configuration and verification

The context schema must be at the application's Alembic head, with `CONTEXT_DATABASE_URL` and `CONTEXT_API_TOKEN` configured. Infrastructure owns database/login provisioning and secret distribution. Ordinary deploys only check schema compatibility; `just context-migrate` is the separate owner-authorized migration procedure.

Home Assistant requires `backplane_context_authorization` in its secret store, containing `Bearer ` followed by the same context API token. Its repository defines the REST command and automations; enable `input_boolean.idea_followups` only with the configured Backplane service available. The helper restores its state and defaults off on first creation.

For a functional check, use a dedicated idea and record its stable ID. Check the automation trace for availability, the returned claim and notification submission; confirm the phone actually displays it. Open Assist with the GPT pipeline, elaborate, then verify both `get_idea_followup` and the exported development note against that same ID. Verify the original note is unchanged. Exercise Tomorrow and Dismiss on dedicated prompts, confirm their persisted results, and check repeated reserve calls return no duplicate. Do not shorten the live cadence for tests.

The focused tests use isolated vaults and PostgreSQL 17 databases in Testcontainers to exercise REST/MCP adapters, concurrency, daily bounds, snooze/dismiss, task exclusion, exact-ID binding, immutable wording and export recovery. Each pytest worker reuses a container, while each test gets a separate database initialized through Alembic. Concurrent operations use independent sessions and connections; a row-lock test verifies blocking through PostgreSQL itself. Docker must be available to run the database tests. Actual phone/voice behaviour requires environment-level verification.

The [Companion actionable-notification reference](https://companion.home-assistant.io/docs/notifications/actionable-notifications/) documents notification actions and Android intent URIs. The [Android manifest](https://github.com/home-assistant/android/blob/main/app/src/main/AndroidManifest.xml) declares the Assist activity's `android.intent.action.ASSIST` entry point.

Phone notification replies use the [durable review inbox](review-inbox.md) before model processing. Its receipt status determines whether export completed; assistant speech alone does not confirm a save.
