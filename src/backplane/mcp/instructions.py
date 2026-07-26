"""Shared MCP server instructions for Backplane."""

from __future__ import annotations

BACKPLANE_MCP_INSTRUCTIONS = """Backplane manages the user's Obsidian vault.

Tool routing:
- Use `add_to_daily_note` when the user wants to capture something in today's note or a daily-note section.
- Use `create_task` for actionable things the user needs, wants, or intends to do.
- Use `record_idea` for loose, speculative, non-committal ideas.
- Use `get_daily_note` when the user asks what is in today's note or a specific daily note,
  or before `add_to_daily_note` when the available sections are unknown.
- Use `create_vault_entity` to create a Domain, Project, Resource, or Person note.
- Use `list_vault_entities` when the user wants a full catalog of existing Domains,
  Projects, Resources, or People for one kind.
- Use `find_vault_notes` when the user knows an approximate note name.
- Use `search_vault_notes` when the user asks what notes mention a topic or phrase.
- Use `get_vault_entity` to read a whole entity note.
- Use `list_vault_entity_sections` before reading or updating a specific entity section
  if the available headings are unknown.
- Use `get_vault_entity_section` to read one known entity section.
- Use `update_vault_entity` to append/prepend/replace content in an entity section.
- Use `link_task_to_capture` after the user confirms which prior capture belongs to an existing task.
- Use `move_note` to rename, move, or reorganise an Obsidian note.
- Use namespaced `ha_*` tools for Home Assistant state, control, and configuration
  requests when those tools are available to the current client.

General rules:
- Prefer `find_vault_notes` for name-like queries and `search_vault_notes` for topical
  or phrase queries. Use `list_vault_entities` only when the user wants every note of
  one entity kind.
- Prefer human-readable Obsidian names and paths. Kebab-case slugs are internal IDs only.
- When a tool response includes `canonical_link`, use that exact value for markdown links.
- Entity associations are stored as Obsidian wikilinks, not plain names.
- Prefer `append` for captures. Use `replace` only when the user explicitly asks to overwrite.
- Do not ask for confirmation when the user's intent is clear.
- Daily note date headings are handled automatically; never include the top-level date
  heading in `heading_path`.

Keep tool outputs concise — a short confirmation is usually enough."""
