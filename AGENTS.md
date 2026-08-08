# Agent notes

This file provides guidance to AI coding agents working in this repository.

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

MCP support is planned as an adapter layer on top of the REST API — not as the core architecture. This keeps Home Assistant integration, debugging, and testing simpler.

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

Run the server locally:

```bash
python src/backplane/api/main.py
# or
python -m uvicorn backplane.api.main:app --host 0.0.0.0 --port 8000
```

Run via Docker:

```bash
docker-compose up
```

No test suite is configured yet.

## Architecture

### Planned module layout

```text
src/backplane/
├── api/           # FastAPI app and route handlers (semantic HTTP interface)
├── core/          # Shared internals
├── services/      # Low-level service wrappers (file I/O, HTTP clients, etc.)
├── documents/     # Semantic markdown abstractions (MarkdownDocument, sections)
├── integrations/  # Per-service integration logic (Obsidian, Home Assistant, …)
├── tools/         # Reusable LLM-facing tool definitions
├── mcp/           # MCP adapter (wraps REST operations into MCP tools)
├── automations/   # Automation workflows
└── agents/        # Multi-agent orchestration
```

### Current state

```text
src/backplane/
├── api/
│   ├── main.py              # FastAPI app, health check, router inclusion
│   ├── Dockerfile           # Multi-stage build
│   └── routes/
│       └── obsidian/
│           └── route.py     # GET/PATCH /obsidian/daily-note
├── services/
│   └── obsidian.py          # ObsidianService — daily note context manager,
│                            # template loading, moment.js date substitution
└── utils/
    ├── markdown.py          # MarkdownDocument, MarkdownSection, frontmatter parsing
    ├── helpers.py           # today(), format_human_date(), format_obsidian_moment_date()
    └── settings.py          # pydantic-settings config (OBSIDIAN_VAULT_PATH)
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

| Method  | Path                    | Description                                    |
| ------- | ----------------------- | ---------------------------------------------- |
| `GET`   | `/health/check`         | Container health check                         |
| `GET`   | `/obsidian/daily-note`  | Read today's (or a given date's) daily note    |
| `PATCH` | `/obsidian/daily-note`  | Update a section (append / prepend / replace)  |

## Tooling Notes

- **Python ≥ 3.14** required; `from __future__ import annotations` is enforced in every file by ruff/isort.
- **basedpyright** runs in `"all"` (strictest) mode — all type errors must be resolved.
- **Ruff** has almost all rule sets enabled (except CPY, TD002). Line length is 90. Docstrings use Google style.
- **Prek** enforces conventional commits, dependency sync (`uv-lock`), and all of the above linters.
- **Semantic release** drives version bumps from conventional commit messages.

## Agent Guidelines

### Type-Checker Fix Discipline

When fixing basedpyright/pyright errors, do not patch the first error in isolation. Trace the
full path first: **definition → assignment → use** (e.g. factory return type → call-site
variable → `**kwargs` spread → test assertions).

Pick **one** approach and verify it at **all** sites before moving on. If a follow-up fix
undoes or replaces the first approach, revert the first change instead of layering both.

#### Prefer the smallest fix

- Fix tests with `.get()`, explicit guards, or assertions on public outputs — not new
  production types created only to satisfy tests.
- Do not introduce parallel types (e.g. `ConfiguredFoo` vs `PartialFoo`) unless every
  assignment and spread site type-checks without casts.
- One TypedDict with `NotRequired` fields plus `{}` at optional call sites is often
  enough; bracket access in tests may need `.get()` instead of a second TypedDict.

#### When a new type is justified

Add a new type only when it models a real API distinction callers rely on, not when a
single diagnostic can be fixed locally.

```python
# Bad: new return type fixes tests, breaks call-site assignment, leads to cast churn
class ConfiguredKwargs(TypedDict): ...
def factory() -> ConfiguredKwargs: ...

auth_kwargs: PartialKwargs = {}
auth_kwargs = factory()  # basedpyright: not assignable

# Good: one TypedDict; tests use .get() on NotRequired keys
def factory() -> PartialKwargs: ...
assert factory().get("meta") == expected
```

After typing changes, run the type checker on **every module you touched** (production and
tests) before finishing — not just the file that reported the original error.

### MCP Instructions Sync

*(Applies when creating, updating, or removing anything under `src/backplane/mcp/**`.)*

When creating, updating, or removing MCP tools or resources, keep
`BACKPLANE_MCP_INSTRUCTIONS` in `src/backplane/mcp/instructions.py` up to date
in the same change.

`instructions.py` is the server-level routing guide passed to FastMCP in
`server.py`. Agents read it before choosing a tool.

#### What to update

- **Add a tool or resource** → add a `Tool routing` bullet naming the tool and
  when to use it. Register the tool in the appropriate `register_*_tools` module
  and, for a new module, wire it up in `server.py`.
- **Remove or rename a tool** → update or delete the matching routing bullet.
- **Change when a tool should be chosen** → revise the routing bullet and any
  related `General rules` guidance.
- **Change tool parameters or behavior only** → update the module-level
  `_DESCRIPTION` constant passed to `mcp.tool(...)`, not `instructions.py`,
  unless routing between tools also changed.

#### Content guidelines

- Keep `instructions.py` concise: routing and cross-tool rules only.
- Do not hardcode vault-template specifics (headings, section paths, folder
  layouts). Point agents at discovery tools such as `get_daily_note` or
  `list_vault_entity_sections` instead.
- Match existing style: one bullet per tool, backtick tool names, short
  when-to-use phrasing.

#### Example

Adding `list_daily_note_sections`:

```python
# instructions.py — add routing
- Use `list_daily_note_sections` before `add_to_daily_note` when the available
  daily-note sections are unknown.

# obsidian.py — tool-specific detail stays here
_LIST_SECTIONS_DESCRIPTION = """List sections in a daily note..."""
```

### Pydantic Field Validators

*(Applies to Python files generally.)*

Keep `@field_validator(..., mode="before")` methods inside the model/settings
class by default, near the fields they validate.

Only extract validator logic to a module-level helper when it is reused in
multiple places or is complex enough that naming it separately clearly improves
readability.

```python
# Preferred for one-off field parsing.
class Settings(BaseSettings):
    obsidian_vault_path: AsyncPath

    @field_validator("obsidian_vault_path", mode="before")
    @classmethod
    def _parse_obsidian_vault_path(cls, v: AsyncPath | str) -> AsyncPath:
        if isinstance(v, AsyncPath):
            return v
        return AsyncPath(v)
```

```python
# Use a helper only when it is genuinely shared or materially clearer.
def _parse_timezone(v: object) -> zoneinfo.ZoneInfo:
    ...


class Settings(BaseSettings):
    local_timezone: Annotated[zoneinfo.ZoneInfo, BeforeValidator(_parse_timezone)]
```

### Python Unit Tests

Always use pytest.

#### Test Layout

Mirror the code path with a `test__` prefix:

- Function `original_function` in `original_module.py` -> `tests/path/to/original_module/test__original_function.py`
- Method `MyClass.original_method` in `original_module.py` -> `tests/path/to/original_module/my_class/test__original_method.py`
- Resolve duplicate module names by adding `__init__.py` in the test directory.

#### Expectations

- Test one thing per unit test. Keep each test as simple as possible and use fixtures for setup and teardown.
- Cover both happy and unhappy paths for new changes.
- Define tests as single, top-level functions in the module.
- Give each test a short one-sentence docstring describing what it tests.
- Do not define module-private sample/factory helpers in test modules, such as `_sample_email()` or `_make_foo()`. Promote them to the nearest reusable `conftest.py`.
- Use `@pytest.mark.parametrize` for repetitive cases instead of copy-pasting or bespoke helpers.

#### Fixtures

- Define fixtures in the nearest reusable `conftest.py`.
- Name sample object fixtures `sample_<object_name>`.
- Name factories that build objects `make_<thing>` or `create_<thing>`.
- Type factories with a `Protocol` and a `TypedDict` of overrides, following existing factory patterns.
- Before writing a new factory, check the nearest `conftest.py` chain first.

#### Real Types And DB-backed Factories

- When a type has a DB representation, build it with the existing `create_*` factory, even for pure-logic tests.
- Do not stand in for DB-backed models with `SimpleNamespace`, ad-hoc `MagicMock(spec=Model)`, or bespoke stub fixtures when a `create_*` factory exists.
- Reserve `make_*` factories for types without a DB representation, such as Pydantic models, dataclasses, SDK types, and similar value objects.
- Switching a test to `async def` because it now awaits a DB factory is expected when `asyncio_mode = "auto"` is configured.

#### Mocking And Async

- Use the `mocker` fixture from pytest-mock: `mocker.patch()`, `mocker.MagicMock()`, and `mocker.AsyncMock()`.
- Name mocks `mock_<name_of_thing>`.
- Do not use `@pytest.mark.asyncio` when the project configures `asyncio_mode = "auto"`.

#### Assertions

- Prefer whole-object assertions over asserting fields one by one.

### Test And Production Boundaries

Do not change production code just to make tests pass.

When tests fail because they depend on private aliases, obsolete helpers, or incidental
implementation details, update the tests to use the intended production API instead.

Production code should change only when:

- The production behavior or public API is actually wrong.
- The user explicitly asks for a production change.
- A production type/signature must change to support the requested feature.

Concrete example:

```python
# Bad: reintroducing private aliases only because tests import them
_TASKS_DIR = VAULT_PATHS.task_notes_dir

# Good: tests use the same supported API as production callers
task_path = VAULT_PATHS.task_notes_dir / "example.md"
```

### Agent Editing Autonomy

When the user asks for a clear, local code or documentation change, make the edit directly instead of asking for approval first.

Do not pause to run proposed wording, small schema/documentation tweaks, or obvious follow-up edits by the user. The user will review diffs in the IDE.

Ask before editing only when:

- The request is ambiguous enough that multiple materially different outcomes are likely.
- The change is destructive, broad, or hard to unwind.
- The edit crosses into credentials, production configuration, external services, or user data outside the requested scope.
- A required implementation choice has meaningful product or architectural trade-offs.

For narrow improvements discovered while working, apply the same judgment: if the fix is local and clearly aligned with the user's goal, do it and report it afterward.
