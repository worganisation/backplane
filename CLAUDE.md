# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

**Backplane** is a self-hosted orchestration layer that sits between LLMs/agents and local services in a homelab environment. It exposes semantic, intent-driven HTTP APIs designed for LLM tool use, voice assistants (Home Assistant Assist), and automations — not generic CRUD.

The initial integration is an Obsidian vault (reading/writing daily notes with structured markdown manipulation). Future integrations include Home Assistant, Frigate, Immich, Plex, MQTT, and local LLMs.

## Architectural Philosophy

Backplane is a **semantic orchestration platform**, not a REST wrapper or filesystem API.

Good API design for this project:

```text
PATCH /obsidian/daily-note
POST  /frigate/events/summarise
POST  /home/scene/activate
```

Not:

```text
PUT /file/foo.md
POST /do_thing
```

MCP and REST are separate adapter layers over the shared service layer. REST handlers
must call services directly; they must not proxy the Home Assistant MCP passthrough.

## Commands

All Python tooling runs via `uv`:

```bash
uv sync                          # install dependencies
uv run ruff check src --fix      # lint
uv run ruff format src           # format
uv run basedpyright src          # type check
uv run yamllint .                # YAML lint
uv run codespell                 # spell check
```

Run the private server locally:

```bash
python -m backplane.mcp
```

This serves the private REST API under `/api`. The MCP transport remains SSE when HA
proxying is disabled, and remains streamable HTTP at `/mcp` with `/mcp-ha` when enabled.

## Architecture

### Current state

```text
src/backplane/
├── api/
│   └── app.py               # FastAPI vault API mounted at /api
├── mcp/
│   ├── __main__.py          # private ASGI server entrypoint
│   ├── asgi.py              # combines REST, private MCP SSE, and upstream routes
│   └── upstreams/           # optional HA MCP passthrough
├── services/
│   ├── obsidian.py          # daily notes, ideas, and note moves
│   ├── tasks.py             # structured task notes
│   ├── vault_entities.py    # Domains, People, Projects, and Resources
│   └── vault_search.py      # title and content discovery
└── utils/
    ├── markdown.py          # MarkdownDocument, MarkdownSection, frontmatter parsing
    └── settings.py          # pydantic-settings configuration
```

### Key design patterns

**ObsidianService** (`services/obsidian.py`) is an async context manager factory. `daily_note(date, create_if_not_exists, read_only)` resolves the vault path, optionally creates a missing note from the vault's configured template (read from `.obsidian/daily-notes.json`), and delegates to `MarkdownDocument`. Template `{{date}}` / `{{date:FORMAT}}` placeholders are expanded using Obsidian/moment.js token syntax (`YYYY`, `MMMM`, `Do`, etc.) via `substitute_obsidian_core_date_variables`.

**MarkdownDocument / MarkdownSection** (`utils/markdown.py`) parse a markdown file into front matter (via `ruamel.yaml`, preserving formatting) and a tree of `MarkdownSection` objects keyed by heading. Key constructor fields: `create_if_not_exists` (bool) and `initial_content` (str | None, written as the new file body when creating). Heading matching in `get_section()` is case- and format-insensitive (inline markdown stripped). `mdformat` normalizes content on serialization. On `__aexit__`, if `validate_file_content_unchanged` is true and the on-disk content differs from the rendered output, a `ValueError` is raised before writing.

**helpers.py** provides date utilities: `today()` (UTC date), `format_human_date()` (e.g. `Saturday, May 9th 2026`), `format_obsidian_moment_date(date, fmt)` (moment.js token expansion), and `ordinal_day_of_month` / `ordinal_suffix_for_day` helpers.

**Settings** (`utils/settings.py`) uses `pydantic-settings`; the only required env var is `OBSIDIAN_VAULT_PATH`. A `.env` file at the project root is used locally.

### Obsidian integration notes

- Backplane writes `.md` files directly to the vault filesystem; Obsidian picks up changes automatically.
- Daily notes have stable headings (e.g. `## Tasks`, `## Ideas`) enabling deterministic semantic editing.
- Missing daily notes are created automatically (from the vault's template if configured, otherwise empty). Missing headings are **not** yet auto-created — `get_section()` raises `ValueError` if the path doesn't exist.

### API endpoints

The private FastAPI app is mounted at `/api`; its OpenAPI documentation is available
at `/api/docs`. It exposes health, daily note, idea, note-move, task, vault entity, and
vault search operations. Route handlers call `services/` directly rather than MCP tool
wrappers.

The API deliberately has no Home Assistant passthrough endpoints. The optional
`/mcp-ha` route remains MCP-only; the core private MCP transport remains available
alongside `/api` in its configured SSE or streamable-HTTP mode.

## Tooling Notes

- **Python ≥ 3.14** required; `from __future__ import annotations` is enforced in every file by ruff/isort.
- **basedpyright** runs in `"all"` (strictest) mode — all type errors must be resolved.
- **Ruff** has almost all rule sets enabled (except CPY, TD002). Line length is 90. Docstrings use Google style.
- **Pre-commit** enforces conventional commits, dependency sync (`uv-lock`), and all of the above linters.
- **Semantic release** drives version bumps from conventional commit messages.
