# Automatic diary

Home Assistant schedules authenticated `POST /api/diary/sync` calls. Backplane reads the owner's allowlisted HA entities, stores versioned daily snapshots in the existing PostgreSQL context ledger, and exports the generated `Automatic diary` section to the daily Obsidian note. `Diary`, `Journal`, `Summary` and other manual sections remain separate. No additional database migration is required.

## Sources and dates

The collector uses Pixel daily steps and distance, Spotify listening intervals, `person.will` named-place intervals, tentative home-return outings with walking activity, `calendar.will_personal` and the direct work feed `calendar.will_garside_yantratech_com_2`, Wger dated weight records, and AppDaemon's dated habit/mood attributes. Calendar titles and scheduled times are retained; descriptions, meeting URLs and attendee addresses are excluded. Scheduled events remain scheduled until explicitly confirmed as attended. Outings require explicit confirmation to become dog walks. Visits shorter than three minutes are ignored; unknown location intervals break outing continuity.

Activity days use Europe/London midnight boundaries with UTC duration arithmetic for daylight-saving transitions. Mood entries retain the habit tracker's 04:00 logical-day assignment, original wording and recorded timestamp. Date-only records stay date-only. Habit completions use dated counts rather than the current due/not-due state. Phone daily counters use the latest source-dated reading, including downward corrections. Missing measurements appear as source gaps, never fabricated zeros.

AppDaemon owns `completion_history` on configured habit status sensors and `diary_checkins`, `diary_history_start`, `diary_history_end` on the mood summary sensor. These contain a rolling 28-day view from its durable store. Missing dated exports block reconciliation instead of erasing prior records. Empty covered days represent no recorded checkins/completions. Habit labels reflect the configured slot name.

## Rendering and review

Facts include a timeline, daily totals, unresolved confirmations, explicit review notes and source gaps. Numeric properties `diary_steps`, `diary_distance_km`, `diary_music_minutes` and `diary_weight_kg` support Obsidian queries. A separately labelled Qwen narrative uses local `qwen3:4b-instruct` through `OLLAMA_BASE_URL`; `DIARY_NARRATIVE_MODEL` selects the model. The model receives factual text without tools. Its prose is generated interpretation, while the factual record remains authoritative. A failed generation leaves facts saved and narrative pending. Cached prose is reused only for identical facts and confirmations.

HA refreshes today every 30 minutes, finalizes completed days after 04:15, and rotates through the previous seven days for corrections. Collection starts on the activation date, with no automatic historic backfill. A persistent completion cursor advances only after successful facts and narrative export. Source records are available for 28 days; an outage beyond that window requires an explicit operator decision about the unavailable period rather than silently advancing the cursor. Disable the helper to pause collection. The separate music exporter is gated off while automatic diary is enabled.

After 20:30, a successful refresh can reserve one daily review when Will is home, receptive and outside quiet hours. The context ledger enforces one claim per date across workers/retries and shares the baseline budget/cooldown with other context prompts. Reservation is durable before notification submission, so a delivery error does not cause repeated nags. Submission is not proof of phone receipt. Dismissal confirms no facts. If availability changes before submission, the claim is dismissed without a replacement that day.

Notification replies carry the exact prompt ID to the configured general assistant with the Backplane LLM API and [`assist-prompt.jinja`](../deploy/assist-prompt.jinja). `get_diary_review` returns the exact notification snapshot and prior responses; `save_diary_review` records explicit decisions and verbatim additions, then regenerates the note and narrative. Reply actions preserve the returned conversation ID for clarification turns. The notification tap opens the selected general pipeline as a separate conversation; Android cannot pass notification context through the native Assist intent. The three-tool Capture pipeline does not expose these review tools. General-agent prompt configuration uses HA's supported configuration flow, as described in [voice capture](voice-capture.md).

## Looking back

Collected snapshots preserve numeric mood scores and habit completion counts alongside their original display text. Period summaries report mood sample counts and covered days; an empty covered day has no mood average. Habit summaries identify stable sensor sources, count completion days and preserve recorded zeroes. Older snapshots without structured tracking remain missing for these aggregates. Obsidian properties `diary_mood_samples`, `diary_mood_average` and `diary_habit_counts` expose the same observations without parsing prose.

`get_diary_day(date)` and authenticated `GET /api/diary/days/{date}` read the latest collected automatic observations and explicit review notes without contacting Home Assistant or generating prose. A day with no collected snapshot returns null. Manual Diary and Journal sections remain available through `get_daily_note`.

`summarize_diary_period(start, end)` and `GET /api/diary/summary` cover inclusive ranges of up to 366 days. They use current snapshot revisions, report missing dates and source gaps, and include observed-day coverage for each metric. Missing measurements are excluded from averages rather than counted as zero. Steps, distance and listening minutes are additive; weight has first/last and average values without a total. Current-day measurements are marked partial.

## Configuration and verification

Backplane requires the existing context database, context API token, HA URL/token, Obsidian vault path and local model endpoint. HA uses the existing `backplane_context_authorization` secret. AppDaemon's dated exports must be available before enabling `input_boolean.automatic_diary`; it restores its state and defaults off on first creation. The start and completion date helpers persist across restarts.

Verify collection against the source dates and quantities, then inspect the generated daily note and preserved manual sections. Confirm that repeated collection does not duplicate content, source corrections refresh facts and invalidate prose, and the completed-day cursor stays put on a failed request. Submit one diary notification, confirm a specific scheduled event or outing through the general Assist agent, and read back both the stored response and the note. Phone receipt and Open Assist require a phone-side check.

Calendar entries use the source UID and recurrence ID when supplied by Home Assistant. A recurring source with a recurrence rule but no occurrence ID uses its start boundary to distinguish occurrences. Exact legacy identities are carried through snapshot revisions so existing confirmations remain linked after later title edits. Sources without a UID retain a conservative content-derived identity; edits to those records require confirmation again. A source edited before its first identity-bearing snapshot cannot be safely matched to an older differently worded record.

Phone notification replies use the [durable review inbox](review-inbox.md) before model processing. Its receipt status determines whether export completed; assistant speech alone does not confirm a save.
