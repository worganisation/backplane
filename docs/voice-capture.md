# Assist voice capture

Backplane provides diary, idea, and task capture tools to Home Assistant through the Backplane MCP integration. The conversation agent must select that integration under its LLM APIs; installing the MCP integration alone does not expose tools to every agent.

The general-purpose agent prompt is [`deploy/assist-prompt.jinja`](../deploy/assist-prompt.jinja). Set it as the conversation subentry's `prompt` through Home Assistant's supported configuration flow. Home Assistant renders its date/time expressions for each conversation request. Agent configuration is storage-backed. Release CI reconciles the dedicated capture assistant through the supported HA configuration API; the general-purpose agents retain their own settings. Do not edit `.storage` directly.

For the existing Qwen 3 4B Instruct agent, select both Assist and Backplane, use `qwen3:4b-instruct`, disable thinking, and use a 16384-token context for the prompt, tools and conversation. Preserve the other agent options. The default GPT agent can use the same prompt with its existing model and tool selections. Selecting a pipeline on the phone determines which conversation model handles that request; Backplane's task metadata model is a separate setting. The system's preferred pipeline does not change when enabling tools for Qwen.

`record_diary` appends to `Diary`, creating the section or daily note as needed. The server adds a capture timestamp with its local UTC offset, separately from any event time supplied by the user. Explicit dates select that day's note; ambiguous dates require clarification. The tool confirms the save without returning the entire growing note to the model.

Loose ideas use `record_idea`. Committed actions use `capture_task`, which saves the original description, explicit deadline/priority and a board card without model-based metadata extraction or inbox matching. No project is required. A task capture is complete as saved; it does not schedule enrichment or a notification. Use `create_task` for requests that need metadata extraction and capture linking. A stable idempotency key makes task retries safe; reuse it with identical arguments.

Verify three distinct requests through Assist: a completed activity reaches the daily note, a speculative idea reaches the inbox, and a committed action creates a task. Read the saved content back instead of relying on the spoken confirmation. Test a past-day diary capture, preservation of existing entries, and a normal question that must not create a note. Use clearly labelled test text for any live probes. Phone microphone, speech recognition and playback require a final test on the phone itself.

## Dedicated capture pipeline

Select **Capture** in Home Assistant Assist or the phone's Assist pipeline selector. It uses the **Qwen Capture** conversation agent with Ollama `qwen3:4b-instruct`, thinking disabled, a 4096-token context, four history messages and a ten-minute keep-alive. Its sole LLM API is **Backplane Capture**, served privately at `/mcp-capture`, with `record_diary`, `record_idea` and `capture_task`. It has no device-control API or general vault tools. Use the general assistant for device control, searches and project design.

[`deploy/capture-assist.json`](../deploy/capture-assist.json) and [`deploy/capture-prompt.jinja`](../deploy/capture-prompt.jinja) own the dedicated agent and pipeline. `just _deploy-current` reconciles them after restarting Backplane. The reconciler creates missing objects, updates only the named capture objects, and refuses ambiguous duplicates. A new pipeline inherits the preferred pipeline's speech engines; subsequent releases preserve its speech settings and the system's preferred pipeline. Re-running release deployment reuses the same objects. No `.storage` files are read or edited.

Capture confirms persisted writes, including warnings. The three-tool surface cannot check the vault after a timeout, so it reports uncertainty instead of retrying blindly. Task retries can reuse the same idempotency key and identical input. Diary and idea writes must not be automatically replayed after an uncertain response.
