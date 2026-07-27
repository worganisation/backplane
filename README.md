# Backplane

AI-facing gateway for local services and smart home orchestration

[![License: MIT](https://img.shields.io/github/license/worgarside/backplane)](LICENSE)
[![Release](https://img.shields.io/github/v/release/worgarside/backplane)](https://github.com/worgarside/backplane/releases)
![Python](https://img.shields.io/badge/python-3.14%2B-blue)
[![Pre-Commit Hooks](https://img.shields.io/github/actions/workflow/status/worgarside/backplane/pre-commit-hooks.yml?branch=main&label=pre-commit)](https://github.com/worgarside/backplane/actions/workflows/pre-commit-hooks.yml)
[![CodeRabbit Pull Request Reviews](https://img.shields.io/coderabbit/prs/github/worgarside/backplane?utm_source=oss&utm_medium=github&utm_campaign=worgarside%2Fbackplane&labelColor=171717&color=FF570A&link=https%3A%2F%2Fcoderabbit.ai&label=CodeRabbit+Reviews)](https://coderabbit.ai)

## Installation

Backplane is designed to run as a persistent service on a Linux host (tested on Debian 13 in a Proxmox LXC).

### Prerequisites

- Git
- [Node.js 22+](https://nodejs.org/) and `obsidian-headless` (`npm install -g obsidian-headless`)
- An [Obsidian Sync](https://obsidian.md/sync) subscription

### 1. Clone the repo

```bash
git clone https://github.com/worgarside/backplane.git /opt/backplane
cd /opt/backplane
```

### 2. Configure environment

```bash
cp .env.example .env
$EDITOR .env
```

Set `OBSIDIAN_VAULT_PATH` to the local path where the vault will be synced.

If you plan to run the public ChatGPT-facing MCP service, also configure the
OAuth variables documented in `.env.example` before running setup with
`INSTALL_PUBLIC_MCP=true`. See `deploy/authentik-backplane-mcp.env.example`
for Authentik provider setup.

### 3. Set up Obsidian Sync

Authenticate and do an initial sync before starting the service:

```bash
ob login
ob sync --vault "My Vault" /path/to/vault
```

By default `setup.sh` expects the vault at `/root/obsidian/vaults/my-vault`. Override with the `VAULT_DIR` environment variable if your path differs.

### 4. Run setup

Install the private `backplane` and `obsidian-sync` systemd services:

```bash
sudo VAULT_DIR=/path/to/vault bash deploy/setup.sh
```

This will:

- Install [uv](https://docs.astral.sh/uv/) if not present
- Install Python 3.14 and sync dependencies
- Install and enable the `backplane` and `obsidian-sync` systemd services

#### Optional: public ChatGPT MCP service

The public MCP server refuses to start without OAuth configuration. Configure
these in `.env` **before** enabling the service:

- `MCP_PUBLIC_BASE_URL`
- `MCP_OIDC_CONFIG_URL`
- `MCP_OIDC_CLIENT_ID`
- `MCP_OIDC_CLIENT_SECRET`

See `deploy/authentik-backplane-mcp.env.example` for Authentik provider setup.

Then install and start the public service:

```bash
sudo INSTALL_PUBLIC_MCP=true VAULT_DIR=/path/to/vault bash deploy/setup.sh
```

`setup.sh` validates the OAuth variables before installing or starting
`backplane-public`. The public service unit and logrotate config are only
installed when `INSTALL_PUBLIC_MCP=true`.

### Updating

```bash
bash scripts/update.sh
```

Pulls the latest code, syncs dependencies, and restarts the service.

### Service management

```bash
systemctl status backplane
systemctl status backplane-public
systemctl status obsidian-sync
journalctl -u backplane -f
journalctl -u backplane-public -f
journalctl -u obsidian-sync -f
```

## Development

All tooling runs via `uv`:

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
python -m backplane.mcp
```

This starts the private Home Assistant-compatible SSE server on port `8000`.

<!-- backplane:mcp-catalog:start -->
## MCP tools and resources

This section is generated automatically from the registered MCP surface. Run `prek run update-readme-mcp-catalog` to refresh it after changing tools or resources.

**Server:** `Backplane` v0.7.0

### Server instructions

Backplane manages the user's Obsidian vault.

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

Keep tool outputs concise — a short confirmation is usually enough.

### Tools

#### `add_to_daily_note`

Add content to a section of the user's Obsidian daily note.

Use when the user wants to capture something "today", "in my daily note", or into a daily-note section.

When the target section is unknown or ambiguous, call `get_daily_note` first to inspect the note's
headings. If a section lookup fails, the error includes available sections at that level.

If the user explicitly asks for another section, create it with `create_section_if_not_exists=true`.
If a section is missing and the tool returns available sections, retry with the closest
matching path or create the requested section when appropriate.

| Parameter | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `content` | `string` | yes | — | Text to add to the section. |
| `create_section_if_not_exists` | `boolean` | no | `false` | Create the requested section and any missing ancestors if they do not exist. |
| `date` | `date` (YYYY-MM-DD)? | no | `null` | Daily note date in YYYY-MM-DD. Defaults to today's local date. |
| `heading_path` | `string`[] | yes | — | Section path relative to the daily note body. Do not include the top-level date heading. |
| `mode` | `append` \| `prepend` \| `replace` | no | `append` | How to combine content with the existing section. Prefer `append`; use `replace` only when explicitly requested. |

#### `create_task`

Create a structured Obsidian task note for an actionable item.

Use when the user says they need to do something, wants something on their list, asks to make a
task, or uses phrasing like "I should…", "I need to…", "remind me to…", or "add this to my list".

Do not use for speculative ideas. Use `record_idea` for loose "maybe / could / worth
investigating" captures unless the user explicitly wants to turn the idea into a task.

Task creation always succeeds even without a prior inbox match. Confirmed prior captures can
be linked with `link_capture_id`; uncertain matches may be returned as candidates and linked
later with `link_task_to_capture`.

Only set:
- `due` when the user gives an explicit date or deadline.
- `priority` when urgency/importance is explicit.
- `title` when the user gives a clear title.

If timing is implied but not explicit, leave `due=null` and keep the timing words in `description`.

| Parameter | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `description` | `string` | yes | — | Natural-language task description. Include distinctive names, nouns, and context that may help matching and metadata extraction. |
| `due` | `string`? | no | `null` | Optional due date in YYYY-MM-DD. Only set when explicit. |
| `link_capture_id` | `string`? | no | `null` | Confirmed inbox capture ID to link. Omit unless the user confirmed the capture. |
| `priority` | `low` \| `medium` \| `high`? | no | `null` | Optional priority override. Only set when explicit. |
| `title` | `string`? | no | `null` | Optional title override. Omit unless the user supplied a clear title. |

#### `create_vault_entity`

Create a new Domain, Project, Resource, or Person note from the vault template.

Use for new durable entities:
- Domains: broad areas or platforms.
- Resources: specific integrations, APIs, vendors, services, or references.
- Projects: scoped outcomes or ongoing efforts.
- People: individuals referenced in related work.

Do not create duplicate Domain/Resource notes with the same meaning.
Fails if a note with the same name already exists.

| Parameter | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `kind` | `domain` \| `person` \| `project` \| `resource` | yes | — | Entity kind: `domain`, `person`, `project`, or `resource`. |
| `name` | `string` | yes | — | Human-readable note title. |

#### `find_vault_notes`

Find notes by approximate title or filename.

Use when the user knows a note name, such as a Domain, Project, Resource, Person,
task, or daily note — for example "Home Assistant", "garage migration", or
"2026-06-16".

Prefer this over `search_vault_notes` for name-like queries. Prefer this over
`list_vault_entities` when searching across note kinds or when the name is partial.

| Parameter | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `kinds` | `domain` \| `person` \| `project` \| `resource` \| `task` \| `daily_note`[]? | no | `null` | Note kinds to search. Omit to search all kinds. |
| `limit` | `integer` | no | `20` | Maximum number of hits to return. |
| `query` | `string` | yes | — | Approximate note title or filename to match. |

#### `get_daily_note`

Read the user's Obsidian daily note.

Use when the user asks what is in the daily note, wants to review captured tasks/ideas/notes,
or needs daily-note context for a follow-up.

| Parameter | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `date` | `date` (YYYY-MM-DD)? | no | `null` | Daily note date in YYYY-MM-DD. Defaults to today's local date. |

#### `get_vault_entity`

Read a Domain, Project, Resource, or Person note as rendered markdown.

Use when the user asks about an entity note's contents.

| Parameter | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `kind` | `domain` \| `person` \| `project` \| `resource` | yes | — | Entity kind: `domain`, `person`, `project`, or `resource`. |
| `name` | `string` | yes | — | Human-readable entity name. |

#### `get_vault_entity_section`

Read one section of a Domain, Project, Resource, or Person note as rendered markdown.

Use when only a specific section is needed. Pass the exact section path returned by
`list_vault_entity_sections`.

| Parameter | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `heading_path` | `string`[] | yes | — | Section path relative to the note title, e.g. `['Overview']`. |
| `kind` | `domain` \| `person` \| `project` \| `resource` | yes | — | Entity kind: `domain`, `person`, `project`, or `resource`. |
| `name` | `string` | yes | — | Human-readable entity name. |

#### `link_task_to_capture`

Link an existing task note to a confirmed prior inbox capture.

Use after `create_task` returned candidate captures and the user confirms which capture belongs to the task.

| Parameter | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `capture_id` | `string` | yes | — | Inbox capture ID, e.g. `2026-05-25T21:15`. |
| `task_slug` | `string` | yes | — | Task title, filename stem, or internal slug from the task creation response. |

#### `list_vault_entities`

List display names of vault entity notes for a given kind.

Use when the user asks what Domains, Projects, Resources, or People exist, or when
choosing from existing entities.

| Parameter | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `kind` | `domain` \| `person` \| `project` \| `resource` | yes | — | Entity kind to list: `domain`, `person`, `project`, or `resource`. |

#### `list_vault_entity_sections`

List sections in a Domain, Project, Resource, or Person note.

Use before reading or updating a specific section when the available headings are unknown.
Returned paths are relative to the note title.

| Parameter | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `kind` | `domain` \| `person` \| `project` \| `resource` | yes | — | Entity kind: `domain`, `person`, `project`, or `resource`. |
| `name` | `string` | yes | — | Human-readable entity name. |

#### `move_note`

Move or rename an Obsidian markdown note.

Use when the user wants to relocate, reorganise, or rename a note.

Paths are vault-relative. Missing destination parent folders are created automatically.
The source note must exist. The destination must not already exist.

| Parameter | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `destination_path` | `string` | yes | — | New vault-relative note path. |
| `source_path` | `string` | yes | — | Existing vault-relative note path. |

#### `record_idea`

Record a loose, non-actionable idea in the Obsidian idea inbox.

Use for speculative captures such as:
- "maybe…"
- "I could…"
- "I wonder if…"
- "worth investigating…"
- possible automations, improvements, or future projects the user has not committed to doing

Do not use this for tasks or action items. If the user says they need to do something, should do
something, wants to remember to act on something, or asks for a task/reminder/list item,
use `create_task`.

Convert spoken phrasing to a written sentence while preserving the user's wording as closely as possible.

| Parameter | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `idea` | `string` | yes | — | The loose, non-actionable idea to record. Preserve the user's wording as closely as possible. |

#### `search_vault_notes`

Search vault note contents for a topic or phrase.

Use when the user asks what notes mention a topic, integration, or phrase — for
example "MQTT broker", "rain alert", or "backup verification".

Prefer this over `find_vault_notes` when the query is topical rather than a note name.
After finding a hit, read entity notes with `get_vault_entity`, daily notes with
`get_daily_note`, or follow `canonical_link` in responses.

| Parameter | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `kinds` | `domain` \| `person` \| `project` \| `resource` \| `task` \| `daily_note`[]? | no | `null` | Note kinds to search. Omit to search all kinds. |
| `limit` | `integer` | no | `20` | Maximum number of hits to return. |
| `query` | `string` | yes | — | Topic or phrase to match in note content. |

#### `update_vault_entity`

Update a section of a Domain, Project, Resource, or Person note.

Use `append` for most captures. Use `replace` only when the user explicitly asks to overwrite.

Common entity sections include:
- Overview
- Notes
- Related Tasks

Some entity kinds may also have more specific sections, such as Goals, Links, Context,
Key Resources, or Active Projects.

When the target section is obvious, use the most appropriate existing/common section, usually
`["Overview"]`, `["Notes"]`, or `["Related Tasks"]`.

When the available headings are unknown or the target section is ambiguous, call
`list_vault_entity_sections` first and pass an exact returned path.

Only set `create_section_if_not_exists=true` when the user explicitly asks for a new section,
or when no existing section is appropriate.

| Parameter | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `content` | `string` | yes | — | Markdown content to add or replace. |
| `create_section_if_not_exists` | `boolean` | no | `false` | Create the requested section and any missing ancestors if they do not exist. |
| `heading_path` | `string`[] | yes | — | Section path relative to the note title. Prefer exact paths from `list_vault_entity_sections` when available. |
| `kind` | `domain` \| `person` \| `project` \| `resource` | yes | — | Entity kind: `domain`, `person`, `project`, or `resource`. |
| `mode` | `append` \| `prepend` \| `replace` | no | `append` | How to combine content with existing section text. Prefer `append`; use `replace` only when explicitly requested. |
| `name` | `string` | yes | — | Human-readable entity name. |

### Resources

#### `Today's Daily Note`

- **URI:** `obsidian://daily-note/today` (`text/markdown`)
- **Description:** The user's Obsidian daily note for today's local date.

### Resource templates

#### `Daily Note by Date`

- **URI template:** `obsidian://daily-note/{date}` (`text/markdown`)
- **Description:** The user's Obsidian daily note for a given ISO date.

| Parameter | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `date` | `date` (YYYY-MM-DD) | yes | — | Daily note date in YYYY-MM-DD. |
<!-- backplane:mcp-catalog:end -->

### Public MCP (ChatGPT)

Backplane can also run a separate public streamable HTTP MCP server:

```bash
python -m backplane.mcp.public
```

This starts the authenticated public streamable HTTP MCP server on port `8001`.
The MCP OAuth environment variables in `.env.example` are required; the server
refuses to start without them. It uses FastMCP's `OIDCProxy` against Authentik.
See `deploy/authentik-backplane-mcp.env.example` for Authentik provider setup.
Terminate TLS at your reverse proxy (for example NGINX Proxy Manager) and forward
`backplane-mcp.example.com` to port `8001`.

Keep the private SSE server on your LAN only.

#### Home Assistant MCP upstream (optional)

Backplane can proxy your private Home Assistant MCP add-on so clients never
reach the add-on URL on `:9583` directly.

| Variable | Description |
| --- | --- |
| `BACKPLANE_HA_MCP_ENABLED` | Set to `true` to mount the HA MCP add-on upstream |
| `BACKPLANE_HA_MCP_URL` | Private LAN URL from the add-on logs, e.g. `http://10.0.0.x:9583/<secret-path>` |
| `BACKPLANE_HA_MCP_NAMESPACE` | Tool namespace prefix (default: `ha`) |
| `BACKPLANE_HA_MCP_CLIENT_REDIRECT_URI_PATTERNS` | JSON list of downstream OAuth redirect patterns allowed to receive the HA scope (defaults to ChatGPT only) |

When enabled:

- **Public server (`:8001`)** — ChatGPT keeps using `/mcp`. HA tools are mounted on
  that same endpoint and all HA tools, resources, templates, and prompts are only
  visible when the access token includes the
  **`backplane.home-assistant`** scope. During dynamic client registration,
  Backplane grants that scope only when every registered redirect URI matches
  `BACKPLANE_HA_MCP_CLIENT_REDIRECT_URI_PATTERNS`.
  Other public MCP clients with just `openid` keep Backplane components without
  contacting the HA add-on.
- **Private server (`:8000`)** — switches from SSE to streamable HTTP and serves
  `/mcp` (Backplane only) plus `/mcp-ha` (Backplane + HA). Update any LAN MCP
  client URLs accordingly.

Rollout: deploy with `BACKPLANE_HA_MCP_ENABLED=false` first, confirm the add-on
URL is reachable from the Backplane host (for example with `curl`), then set
`BACKPLANE_HA_MCP_ENABLED=true` and restart. Roll back by setting
`BACKPLANE_HA_MCP_ENABLED=false`.

Do **not** expose the HA MCP add-on port `:9583` on your public reverse proxy.

#### OAuth scope model (current)

The public MCP server requires authentication for all tools and resources. Core
components use baseline scope **`openid`**. Every Home Assistant upstream
component also requires **`backplane.home-assistant`**. The scope gate wraps the
upstream provider itself, so unauthorised clients cannot list, invoke, or cause
Backplane to fetch HA components. Authorize also requests **`offline_access`**
so ChatGPT can refresh tokens. There is no `mcp.read` / `mcp.write` split yet —
see the design note in `src/backplane/mcp/auth.py`.

Create `backplane.home-assistant` under Authentik **Customization → Scopes** and
add it to the Backplane MCP OIDC provider. Authentik sees Backplane's single
fixed upstream OAuth client, so per-downstream-client entitlement is enforced by
Backplane before authorization: DCR clients outside the configured redirect
allowlist have the HA scope stripped from their registration. Clients that skip
DCR and use the upstream client ID directly receive baseline scopes only. After
changing scopes, delete and reconnect the ChatGPT connector so it receives a new
token.

#### Public route policy (`:8001`)

| Route | Policy |
| --- | --- |
| `POST /mcp` | Bearer token required |
| `/.well-known/oauth-protected-resource/*` | Public |
| FastMCP OAuth routes (`/authorize`, `/token`, `/register`, `/auth/callback`, …) | Public (state/PKCE validated by FastMCP) |

The private server on port `8000` is unauthenticated and must stay on your LAN.
Keep the Home Assistant MCP integration pointed at `/mcp`, not `/mcp-ha`, to
avoid proxying HA back into itself.

Additional internal MCP passthroughs should follow the same model: one namespace
and one Authentik scope per upstream, mounted on the existing public `/mcp`
endpoint. Clients do not need a new URL or connector when an upstream is added.

#### Future: `mcp.read` / `mcp.write`

Per-tool read/write scopes may be added later. Before enabling them, verify the
live ChatGPT → FastMCP → Authentik flow and confirm which scopes are requested,
issued, preserved, and visible during tool execution. Do not configure
`mcp.read` or `mcp.write` in Authentik until that mapping is understood.

#### ChatGPT custom connector

Your server already exposes the discovery documents ChatGPT expects:

- `GET /.well-known/oauth-protected-resource/mcp`
- `GET /.well-known/oauth-authorization-server`
- `POST /register` (dynamic client registration)

**In ChatGPT (chat.openai.com):**

1. Enable **Developer mode** (Settings → Apps → Advanced, or equivalent for your plan).
2. **Create** a custom connector / app.
3. **MCP server URL:** `https://backplane-mcp.example.com/mcp` (no trailing spaces).
4. **Authentication:** OAuth with **server discovery** (let ChatGPT discover from the MCP URL).
   Do **not** paste the Authentik `MCP_OIDC_CLIENT_ID` / `MCP_OIDC_CLIENT_SECRET` here — those
   are only for Backplane’s upstream link to Authentik. ChatGPT registers its own client via
   `/register` and signs users in through Backplane → Authentik.
5. Complete the browser login when ChatGPT redirects you (Authentik must allow your user on the
   `backplane-mcp` application).

**Authentik:** upstream redirect URI stays a single fixed callback:

```text
https://backplane-mcp.example.com/auth/callback
```

On the **Backplane MCP** OAuth2/OpenID provider (`Applications` → `Providers` → edit),
include scopes **`openid`** and **`offline_access`**. ChatGPT custom connectors need a
`refresh_token` from the upstream IdP; without `offline_access` in Authentik, OAuth can
succeed in the browser but ChatGPT reports *"There was a problem connecting …"*. Add
**`backplane.home-assistant`** when HA upstream is enabled. Backplane, rather
than Authentik, decides which downstream DCR clients may request that optional
scope. See `deploy/authentik-backplane-mcp.env.example` for the full provider checklist.

Backplane validates downstream client redirect URIs itself. Configure the JSON
`MCP_CLIENT_REDIRECT_URI_PATTERNS` allowlist for each client you intend to use
(for example, ChatGPT's connector redirects or Claude's
`https://claude.ai/api/mcp/auth_callback`); do not add them in Authentik.

**Plan limits:** Plus / Pro custom connectors are often **read-only**. Tool calls that write to
Obsidian may require Business, Enterprise, or Edu.

**Verify after connecting:** ask ChatGPT to list available tools, or run
`journalctl -u backplane-public -f` while connecting — a healthy flow shows
`/authorize` → `/auth/callback` → `POST /token` **200** (with `refresh_token`), then
`POST /mcp` **200** with a Bearer token.

**If ChatGPT says “There was a problem connecting to Backplane”:** OAuth may succeed in
the browser but `/token` lacks a `refresh_token`. Add **`offline_access`** on the Authentik
provider (see above), delete the connector, and reconnect. Confirm the MCP URL has no
trailing space: `https://backplane-mcp.example.com/mcp`.
