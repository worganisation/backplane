"""Task creation service for structured task note management."""

from __future__ import annotations

import asyncio
import datetime as dt
import io
import operator
from dataclasses import dataclass
from functools import cache
from typing import TYPE_CHECKING, Annotated, Final, Literal, cast, final

from loguru import logger
from pydantic import BaseModel, Field
from pydantic_ai import Agent, AgentRunResult
from rapidfuzz import fuzz

from backplane.services import ObsidianService
from backplane.services.vault_entities import VaultEntityService
from backplane.utils import (
    SETTINGS,
    VAULT_PATHS,
    YAML_LOADER,
    AsyncPath,
    MarkdownDocument,
    VaultNoteMetadata,
    atomic_write_text,
    build_entity_wikilink,
    build_obsidian_link,
    build_vault_note_metadata,
    enums,
    exc,
    note_filename,
    obsidian_link_target_from_path,
    resolve_under_root,
    safe_slug,
    today,
)
from backplane.utils.kanban import append_board_card
from backplane.utils.markdown import note_title_from_markdown

if TYPE_CHECKING:
    from pydantic_ai.usage import RunUsage


_INBOX_DAYS: Final = 30
_SCORE_AUTO: Final = 70.0
_SCORE_CANDIDATE: Final = 60.0
_MIN_AUTO_GAP: Final = 10.0
_LOG_TEXT_MAX_LEN: Final = 80
_MATCH_TOP_CANDIDATES: Final = 3
_STUB_NOTE_TYPES: Final = frozenset({"domain", "person", "project", "resource"})


@dataclass(frozen=True, slots=True)
class Capture:
    """A single timestamped entry from the idea inbox."""

    id: str
    date: str
    time: str
    text: str
    path: AsyncPath


@dataclass(frozen=True, slots=True)
class MatchOutcome:
    """Result of best-effort inbox capture matching."""

    matched: Capture | None
    candidates: list[Capture]


class CaptureCandidate(BaseModel, frozen=True):
    """Summary of an inbox capture offered for optional linking."""

    id: str
    text: str


class CreateTaskResult(BaseModel, frozen=True, arbitrary_types_allowed=True):
    """Outcome of creating a task note from a description or capture."""

    slug: str
    path: AsyncPath
    title: str
    metadata: VaultNoteMetadata
    matched_capture_id: str | None
    candidate_captures: list[CaptureCandidate]
    domains_created: list[str]
    resources_created: list[str]
    projects_created: list[str]
    people_created: list[str]


class TaskMetadata(BaseModel):
    """LLM-extracted metadata for a task."""

    title: str

    domains: Annotated[
        list[str],
        Field(
            default_factory=list,
            description=(
                "Platforms or broad knowledge areas the task belongs under "
                "(e.g. a home automation stack), not integrations or APIs."
            ),
        ),
    ]

    resources: Annotated[
        list[str],
        Field(
            default_factory=list,
            description=(
                "Specific integrations, APIs, vendors, or services to touch "
                "(e.g. a named API or device integration), not parent platforms."
            ),
        ),
    ]

    projects: Annotated[
        list[str],
        Field(
            default_factory=list,
            description=(
                "Scoped outcomes, initiatives, or ongoing efforts the task contributes "
                "to, not platforms, integrations, or people."
            ),
        ),
    ]

    people: Annotated[
        list[str],
        Field(
            default_factory=list,
            description=(
                "People named or clearly implied in the task, including from possessives "
                "(e.g. 'Jordan' from \"Jordan's laptop\") or pronouns when a name appears "
                "in the same sentence."
            ),
        ),
    ]

    priority: enums.Priority = enums.Priority.MEDIUM

    effort: enums.Effort = enums.Effort.MEDIUM

    next_action: Annotated[
        str,
        Field(
            description=(
                "One concrete first step as a short imperative sentence "
                "(e.g. 'Research available API authentication options')."
            ),
        ),
    ] = ""


class TaskFrontmatter(BaseModel, frozen=True):
    """YAML frontmatter contract for task notes."""

    id: Annotated[
        str,
        Field(description="Stable task identifier, e.g. task-20260525-211500."),
    ]
    type: Annotated[
        Literal["task"],
        Field(description="Note kind; always `task` for structured task notes."),
    ] = "task"
    status: Annotated[
        Literal["backlog"],
        Field(description="Workflow status; newly created tasks start in `backlog`."),
    ] = "backlog"
    created: Annotated[
        str,
        Field(description="ISO 8601 local timestamp when the note was first created."),
    ]
    updated: Annotated[
        str,
        Field(description="ISO 8601 local timestamp of the last frontmatter update."),
    ]
    source_capture: Annotated[
        str | None,
        Field(
            description=(
                "Inbox capture ID used as provenance, e.g. 2026-05-25T21:15, "
                "or null when created from free-text description."
            ),
        ),
    ] = None
    domains: Annotated[
        list[str],
        Field(
            description=(
                "Obsidian wikilinks to domain notes (platforms or broad knowledge areas), "
                "e.g. [[Domains/Home - Property|Home / Property]]."
            ),
        ),
    ]
    resources: Annotated[
        list[str],
        Field(
            description=(
                "Obsidian wikilinks to resource notes (integrations, APIs, vendors, or "
                "services), e.g. [[Resources/Frigate|Frigate]]."
            ),
        ),
    ]
    projects: Annotated[
        list[str],
        Field(
            description=(
                "Obsidian wikilinks to project notes (scoped outcomes or ongoing "
                "initiatives), e.g. [[Projects/Rented Home Formal Complaint|Rented Home "
                "Formal Complaint]]."
            ),
        ),
    ]
    people: Annotated[
        list[str],
        Field(
            description=(
                "Obsidian wikilinks to person notes for people involved or referenced, "
                "e.g. [[People/Will|Will]]."
            ),
        ),
    ]
    priority: Annotated[
        enums.Priority,
        Field(description="Relative urgency: `low`, `medium`, or `high`."),
    ]
    effort: Annotated[
        enums.Effort,
        Field(
            description=(
                "Estimated effort: `small` (under 1 hour), `medium` (1-4 hours), or "
                "`large` (over 4 hours)."
            ),
        ),
    ]
    due: Annotated[
        str | None,
        Field(description="Optional due date as YYYY-MM-DD, or null when unset."),
    ]
    completed: Annotated[
        str | None,
        Field(
            description=(
                "ISO 8601 local timestamp when the task was marked done, or null while "
                "open."
            ),
        ),
    ] = None
    tags: list[str] = Field(
        default_factory=lambda: ["task"],
        description="Obsidian tags for filtering; new tasks include `task`.",
    )

    def model_dump_yaml(self) -> str:
        """Serialize the frontmatter as YAML.

        Returns:
            YAML frontmatter content without closing delimiters.
        """
        buf = io.StringIO()
        YAML_LOADER.dump(self.model_dump(mode="python"), buf)  # pyright: ignore[reportUnknownMemberType]
        return buf.getvalue()


@cache
def _metadata_agent() -> Agent[None, TaskMetadata]:
    """Provide a configured agent for extracting structured task metadata.

    Returns:
        Agent configured to produce ``TaskMetadata`` from task descriptions.
    """
    return Agent(
        SETTINGS.task_metadata_model,
        output_type=TaskMetadata,
        system_prompt=(
            "Extract structured task metadata from the user's description. "
            "Return concise, actionable values. "
            "Domains are platforms or broad areas the work lives under "
            "(e.g. 'Home Assistant', 'Inventory'). "
            "Resources are specific integrations, APIs, vendors, or services you will "
            "configure or call (e.g. 'Acme API', 'MQTT'). "
            "Projects are scoped outcomes or ongoing efforts the task contributes to "
            "(e.g. 'Garage Migration', 'Kitchen Dashboard'). "
            "Never put the same name in both domains and resources. "
            "If a task mentions adding or updating an integration inside a platform, "
            "put the platform in domains and the integration in resources only — "
            "e.g. 'Add the Acme API to the automation platform' → domains: "
            "['Home Assistant'], resources: ['Acme API']. "
            "For people: every person named or clearly implied in the task (e.g. 'Jordan' from "
            "\"Jordan's laptop\", or the person behind 'their' when a name appears in the same "
            "sentence). "
            "When the user message lists existing domains, resources, projects, or people, "
            "prefer those exact spellings when they clearly apply; add new names when the "
            "task mentions someone or something not in the list. "
            "For title: a concise imperative phrase under 60 characters. "
            "For next_action: one concrete first step as an imperative sentence. "
            "For effort: 'small' under 1 hour, 'medium' 1-4 hours, 'large' over 4 hours."
        ),
    )


def _truncate_for_log(text: str, *, max_len: int = _LOG_TEXT_MAX_LEN) -> str:
    """Return a single-line snippet safe for debug logs."""
    if len(normalized := " ".join(text.split())) <= max_len:
        return normalized

    return f"{normalized[: max_len - 1]}…"


def _log_metadata_agent_run(result: AgentRunResult[TaskMetadata]) -> None:
    """Log token usage and estimated cost for a metadata extraction run."""
    usage = cast("RunUsage", result.usage)
    model_name = result.response.model_name or SETTINGS.task_metadata_model
    logger.info(
        (
            "Task metadata agent usage (model={}): requests={} input_tokens={} "
            "output_tokens={} total_tokens={}"
        ),
        model_name,
        usage.requests,
        usage.input_tokens,
        usage.output_tokens,
        usage.total_tokens,
    )

    if usage.cache_read_tokens or usage.cache_write_tokens:
        logger.info(
            "Task metadata agent cache tokens: read={} write={}",
            usage.cache_read_tokens,
            usage.cache_write_tokens,
        )

    try:
        cost = result.response.cost()
    except Exception as exc:  # ruff:ignore[blind-except]
        logger.warning("Task metadata agent cost unavailable: {}", exc)
        return

    logger.info(
        "Task metadata agent cost (model={}): input=${} output=${} total=${}",
        model_name,
        cost.input_price,
        cost.output_price,
        cost.total_price,
    )


def _parse_inbox(doc: MarkdownDocument, days: int | None = _INBOX_DAYS) -> list[Capture]:
    """Parse captures from the inbox document.

    Args:
        doc: Loaded inbox MarkdownDocument.
        days: How many calendar days back to search, or None for all captures.

    Returns:
        List of captures within the lookback window, in document order.
    """
    cutoff = today() - dt.timedelta(days=days) if days is not None else None
    captures: list[Capture] = []

    for date_section in doc.body:
        try:
            section_date = dt.date.fromisoformat(date_section.heading)
        except ValueError:
            continue

        if cutoff is not None and section_date < cutoff:
            continue

        for time_section in date_section.sections:
            capture_text = _clean_capture_text(time_section.content)
            if not capture_text:
                continue

            captures.append(
                Capture(
                    id=f"{date_section.heading}T{time_section.heading}",
                    date=date_section.heading,
                    time=time_section.heading,
                    text=capture_text,
                    path=ObsidianService.IDEA_INBOX_PATH,
                ),
            )

    return captures


def _is_task_backlink_line(line: str) -> bool:
    """Return whether a line is an appended task back-link annotation."""
    normalized = line.strip().replace("\\", "")
    return normalized.startswith("↗ [[") and normalized.endswith("]]")


def _clean_capture_text(text: str | None) -> str:
    """Return capture text without generated task back-link annotations."""
    if text is None:
        return ""

    return "\n".join(
        line.rstrip()
        for line in text.strip().splitlines()
        if not _is_task_backlink_line(line)
    ).strip()


def _fuzzy_score(query: str, text: str) -> float:
    """Return a conservative fuzzy score between query and text."""
    return max(fuzz.token_set_ratio(query, text), fuzz.partial_ratio(query, text))


def _log_match_candidates(
    description: str,
    scored: list[tuple[Capture, float]],
) -> None:
    """Log top fuzzy-match candidates at DEBUG for investigation."""
    if not scored:
        return

    logger.debug(
        "Fuzzy match query (len={}): {}",
        len(description),
        _truncate_for_log(description),
    )
    for capture, score in scored[:_MATCH_TOP_CANDIDATES]:
        logger.debug(
            "Fuzzy match candidate id={} score={:.0f} text={}",
            capture.id,
            score,
            _truncate_for_log(capture.text),
        )


def _runner_up_gap(scored: list[tuple[Capture, float]]) -> float | None:
    """Return score gap between best and second-best candidates."""
    if len(scored) <= 1:
        return None
    return scored[0][1] - scored[1][1]


def _find_match(description: str, captures: list[Capture]) -> MatchOutcome:
    """Find the best matching inbox capture for a task description.

    Args:
        description: Task description to match against.
        captures: Candidate captures to score.

    Returns:
        A match outcome containing the best-matched capture if it exceeds a high
        threshold, borderline candidates if they meet a lower threshold, or
        neither. Task creation always proceeds regardless of match strength.
    """
    if not captures:
        logger.debug("Fuzzy match skipped: no inbox captures in lookback window")
        return MatchOutcome(matched=None, candidates=[])

    scored: list[tuple[Capture, float]] = sorted(
        ((c, _fuzzy_score(description, c.text)) for c in captures),
        key=operator.itemgetter(1),
        reverse=True,
    )
    _log_match_candidates(description, scored)

    best_capture, best_score = scored[0]
    gap = _runner_up_gap(scored)

    if best_score >= _SCORE_AUTO and (gap is None or gap >= _MIN_AUTO_GAP):
        logger.info(
            "Fuzzy match accepted (score={:.0f}, runner_up_gap={}): {}",
            best_score,
            f"{gap:.0f}" if gap is not None else "n/a",
            best_capture.id,
        )
        return MatchOutcome(matched=best_capture, candidates=[])

    if best_score >= _SCORE_CANDIDATE:
        candidates = [capture for capture, score in scored if score >= _SCORE_CANDIDATE][
            :_MATCH_TOP_CANDIDATES
        ]
        top_ids = [capture.id for capture in candidates]
        logger.info(
            "Fuzzy match candidates surfaced (score={:.0f}, runner_up_gap={}, candidates={}): {}",
            best_score,
            f"{gap:.0f}" if gap is not None else "n/a",
            top_ids,
            best_capture.id,
        )
        return MatchOutcome(matched=None, candidates=candidates)

    logger.info(
        "Fuzzy match rejected (best_score={:.0f}, best_id={})",
        best_score,
        best_capture.id,
    )
    return MatchOutcome(matched=None, candidates=[])


async def _load_recent_captures() -> list[Capture]:
    """Parse captures from the inbox within a default lookback window.

    Returns:
        List of parsed captures; an empty list if the inbox file is absent.
    """
    try:
        async with ObsidianService().idea_inbox(read_only=True) as inbox:
            captures = _parse_inbox(inbox)
    except FileNotFoundError:
        logger.error("Idea inbox not found; skipping capture matching")
        return []

    logger.info(
        "Parsed {} inbox captures (lookback_days={})",
        len(captures),
        _INBOX_DAYS,
    )
    return captures


async def _load_all_captures() -> list[Capture]:
    """Load all inbox captures for exact-ID linking.

    Returns:
        All inbox captures, or an empty list when the inbox is absent.
    """
    try:
        async with ObsidianService().idea_inbox(read_only=True) as inbox:
            captures = _parse_inbox(inbox, days=None)
    except FileNotFoundError:
        logger.error("Idea inbox not found; skipping capture linking")
        return []

    logger.info("Parsed {} inbox captures for exact lookup", len(captures))
    return captures


def _find_capture_by_id(captures: list[Capture], capture_id: str) -> Capture | None:
    """Return a capture with the given stable ID."""
    return next((capture for capture in captures if capture.id == capture_id), None)


def _capture_payload(capture: Capture) -> CaptureCandidate:
    """Convert a capture to a public payload for optional linking.

    Returns:
        CaptureCandidate: A public representation of the capture containing its id and text.
    """
    return CaptureCandidate(id=capture.id, text=capture.text)


async def _metadata_catalog_prompt() -> str:
    """Build a prompt section listing existing vault entity names.

    Returns:
        A newline-separated string of existing domains, resources, projects, and
        people, or an empty string if no entities exist.
    """
    domains, resources, projects, people = await asyncio.gather(
        VaultEntityService.list_entities(enums.VaultEntityKind.DOMAIN),
        VaultEntityService.list_entities(enums.VaultEntityKind.RESOURCE),
        VaultEntityService.list_entities(enums.VaultEntityKind.PROJECT),
        VaultEntityService.list_entities(enums.VaultEntityKind.PERSON),
    )

    lines: list[str] = []
    if domains:
        lines.append(
            "Existing domains (prefer exact spelling when applicable): "
            + ", ".join(domains),
        )

    if resources:
        lines.append(
            "Existing resources (prefer exact spelling when applicable): "
            + ", ".join(resources),
        )

    if projects:
        lines.append(
            "Existing projects (prefer exact spelling when applicable): "
            + ", ".join(projects),
        )

    if people:
        lines.append(
            "Existing people (prefer exact spelling when applicable): "
            + ", ".join(people),
        )

    if not lines:
        logger.debug("Metadata catalog empty (no domain/resource/project/person notes)")
        return ""

    logger.debug(
        "Metadata catalog: domains={} resources={} projects={} people={}",
        len(domains),
        len(resources),
        len(projects),
        len(people),
    )
    return "\n".join(lines)


def _dedupe_entity_names(names: list[str]) -> list[str]:
    """Return unique entity names, preserving first-seen order (case-insensitive)."""
    seen: set[str] = set()
    unique: list[str] = []
    for name in names:
        stripped = name.strip()
        if not stripped:
            continue
        key = stripped.casefold()
        if key in seen:
            continue
        seen.add(key)
        unique.append(stripped)
    return unique


def _normalize_domains_and_resources(
    domains: list[str],
    resources: list[str],
) -> None:
    """Dedupe lists and resolve cross-list duplicates in favour of resources.

    Integrations/APIs should not also appear as domains when the model assigns both.

    Args:
        domains: Domain names to normalize in place.
        resources: Resource names to normalize in place.
    """
    normalized_resources = _dedupe_entity_names(resources)
    resource_keys = {name.casefold() for name in normalized_resources}
    deduped_domains = _dedupe_entity_names(domains)
    normalized_domains = [
        name for name in deduped_domains if name.casefold() not in resource_keys
    ]
    removed_domains = [
        name for name in deduped_domains if name.casefold() in resource_keys
    ]
    if removed_domains:
        logger.info(
            "Metadata normalization removed domains also listed as resources: {}",
            removed_domains,
        )
    resources[:] = normalized_resources
    domains[:] = normalized_domains


def _log_task_metadata(metadata: TaskMetadata, *, context: str) -> None:
    """Log extracted task metadata fields at INFO."""
    logger.info(
        (
            "Task metadata {}: title={!r} domains={} resources={} projects={} people={} "
            "priority={} effort={} next_action_len={}"
        ),
        context,
        metadata.title,
        metadata.domains,
        metadata.resources,
        metadata.projects,
        metadata.people,
        metadata.priority,
        metadata.effort,
        len(metadata.next_action),
    )


async def _extract_metadata(
    description: str,
    title: str | None,
    priority: enums.Priority | None,
) -> TaskMetadata:
    """Extract structured metadata fields from a task description, with optional title and priority overrides.

    Args:
        description: Raw task description text.
        title: Pre-supplied title to use unchanged; if provided, skips title extraction.
        priority: Pre-supplied priority to use unchanged; if provided, skips priority extraction.

    Returns:
        TaskMetadata with extracted fields, or fallback defaults if extraction fails.
    """
    prompt_parts = [f"Task description: {description}"]
    catalog = await _metadata_catalog_prompt()
    if catalog:
        prompt_parts.append(catalog)

    if title:
        prompt_parts.append(f"Title already provided: {title!r} - keep it unchanged.")
        logger.debug("Metadata extraction title override supplied")

    if priority:
        prompt_parts.append(
            f"Priority already provided: {priority!r} - keep it unchanged.",
        )
        logger.debug("Metadata extraction priority override supplied: {}", priority)

    prompt = "\n".join(prompt_parts)

    logger.debug(
        "Metadata extraction prompt: description_len={} catalog_present={} prompt_len={}",
        len(description),
        bool(catalog),
        len(prompt),
    )

    try:
        result = await _metadata_agent().run(prompt)
        _log_metadata_agent_run(result)
        metadata = result.output
        _log_task_metadata(metadata, context="extracted")
    except Exception:  # ruff:ignore[blind-except]
        logger.exception("Metadata extraction failed; using defaults")
        fallback = TaskMetadata(
            title=title or description[:60],
            domains=[],
            resources=[],
            projects=[],
            people=[],
        )
        _log_task_metadata(fallback, context="fallback")
        return fallback

    _normalize_domains_and_resources(metadata.domains, metadata.resources)

    if title:
        metadata.title = title

    if priority:
        metadata.priority = priority

    _log_task_metadata(metadata, context="final")

    return metadata


def _entity_wikilinks(kind: enums.VaultEntityKind, names: list[str]) -> list[str]:
    """Convert entity display names to Obsidian wikilinks for task frontmatter.

    Args:
        kind: Entity kind determining the vault subdirectory for each link.
        names: Human-readable display names to convert.

    Returns:
        Wikilink strings in the same order as ``names``.
    """
    return [build_entity_wikilink(kind, name) for name in names]


def _build_task_note(
    *,
    title: str,
    now: dt.datetime,
    metadata: TaskMetadata,
    capture: Capture | None,
    description: str,
    due: str | None,
) -> str:
    """Build the full markdown string for a new task note.

    Args:
        title: Task title.
        now: Creation timestamp (local time).
        metadata: Extracted task metadata.
        capture: Linked inbox entry, or None if the task was created directly.
        description: Task description (used when no inbox entry is linked).
        due: Optional due date string (YYYY-MM-DD).

    Returns:
        Complete markdown string including YAML frontmatter.
    """
    timestamp = now.strftime("%Y-%m-%dT%H:%M:%S")
    fm = TaskFrontmatter(
        id=f"task-{now.strftime('%Y%m%d')}-{now.strftime('%H%M%S')}",
        created=timestamp,
        updated=timestamp,
        source_capture=capture.id if capture else None,
        domains=_entity_wikilinks(enums.VaultEntityKind.DOMAIN, metadata.domains),
        resources=_entity_wikilinks(enums.VaultEntityKind.RESOURCE, metadata.resources),
        projects=_entity_wikilinks(enums.VaultEntityKind.PROJECT, metadata.projects),
        people=_entity_wikilinks(enums.VaultEntityKind.PERSON, metadata.people),
        priority=metadata.priority,
        effort=metadata.effort,
        due=due,
    )

    description_text = (capture.text if capture else description).strip()
    blockquote = "\n".join(
        f"> {line}" if line.strip() else ">"
        for line in (description_text.splitlines() or [""])
    )

    body = (
        f"# {title}\n\n"
        f"## Description\n\n{blockquote}\n\n"
        f"## Next Action\n\n{metadata.next_action.strip()}\n\n"
        "## Notes\n\n"
    )
    return f"---\n{fm.model_dump_yaml()}---\n{body}"


async def _ensure_stub(
    name: str,
    note_type: Literal["domain", "person", "project", "resource"],
    source_task_link: str,
) -> bool:
    """Create a vault entity note from template if it does not already exist.

    Args:
        name: Human-readable name (used as heading and for filename generation).
        note_type: Value for the ``type`` frontmatter field.
        source_task_link: Canonical wikilink to the task that caused this stub.

    Returns:
        True if the note was created, False if it already existed.

    Raises:
        ValueError: If ``note_type`` is not a supported stub type.
    """
    if note_type not in _STUB_NOTE_TYPES:
        msg = f"Unsupported stub note type: {note_type!r}"
        raise ValueError(msg)

    kind = enums.VaultEntityKind(note_type)
    if await VaultEntityService.resolve_entity_path(kind, name) is not None:
        logger.debug("Stub note already exists: {} {}", note_type, name)
        return False

    provenance_note = f"Created automatically from task intake for {source_task_link}."
    _ = await VaultEntityService.create_entity(
        kind,
        name,
        provenance_note=provenance_note,
    )
    logger.info("Created stub note for {}: {}", note_type, name)
    return True


async def _create_stubs(
    names: list[str],
    note_type: Literal["domain", "person", "project", "resource"],
    source_task_link: str,
) -> list[str]:
    """Create stub notes for each name that doesn't exist.

    Args:
        names: Human-readable names to stub out.
        note_type: Value for the ``type`` frontmatter field.
        source_task_link: Canonical wikilink to the task that caused these stubs.

    Returns:
        Names of notes that were newly created.
    """
    if not names:
        return []

    stubs_created = await asyncio.gather(
        *(
            _ensure_stub(
                name,
                note_type,
                source_task_link,
            )
            for name in names
        ),
    )
    created = [
        name
        for name, was_created in zip(names, stubs_created, strict=True)
        if was_created
    ]
    skipped = len(names) - len(created)
    logger.info(
        "Stub notes for {}: created={} skipped_existing={} names={}",
        note_type,
        len(created),
        skipped,
        created or names,
    )
    return created


async def _annotate_capture(match: Capture, task_link: str) -> None:
    """Best-effort: append a task back-link to the matched inbox capture.

    Args:
        match: The inbox capture to annotate.
        task_link: Canonical wikilink to the task note.
    """
    try:
        async with ObsidianService().idea_inbox() as inbox:
            section = inbox.get_section((match.date, match.time))
            section.append_content(f"\n↗ {task_link}")
        logger.debug("Annotated inbox capture {} with task {}", match.id, task_link)
    except (ValueError, FileNotFoundError) as exc:
        logger.warning("Could not annotate inbox capture: {}", exc)


async def _select_task_capture(
    description: str,
    link_capture_id: str | None,
) -> MatchOutcome:
    """Select the capture to link to a new task, if any.

    Returns:
        Matched capture and any candidates for optional manual linking.
    """
    if link_capture_id:
        captures = await _load_all_captures()
        matched_capture = _find_capture_by_id(captures, link_capture_id)
        if matched_capture is None:
            logger.warning(
                "Requested capture link not found: {}; creating task unlinked",
                link_capture_id,
            )
        return MatchOutcome(matched=matched_capture, candidates=[])

    captures = await _load_recent_captures()
    if not captures:
        return MatchOutcome(matched=None, candidates=[])

    return _find_match(description, captures)


def _metadata_source(description: str, capture: Capture | None) -> str:
    """Selects the text source for metadata extraction and logs the source choice.

    Returns:
        The selected text (from capture if available, otherwise from description).
    """
    if capture is not None:
        logger.info(
            "Task metadata source: capture {} (description_len={} capture_len={})",
            capture.id,
            len(description),
            len(capture.text),
        )
        return capture.text

    logger.info(
        "Task metadata source: description only (len={})",
        len(description),
    )
    return description


async def _unique_task_filename(title: str) -> tuple[str, str]:
    """Generate a unique task filename stem and corresponding slug.

    Returns:
        A tuple of (stem, slug) where stem does not collide with existing task note files.
    """
    base_stem = note_filename(title)
    slug = safe_slug(title)
    stem = base_stem
    counter = 2
    while await (
        await resolve_under_root(VAULT_PATHS.task_notes_dir / f"{stem}.md")
    ).exists():
        logger.debug(
            "Task filename collision: {} already exists, trying {}",
            stem,
            f"{base_stem} {counter}",
        )
        stem = f"{base_stem} {counter}"
        counter += 1
    return stem, slug


async def _resolve_task_reference(
    task_ref: str,
) -> tuple[AsyncPath, str] | None:
    """Find a task note matching a reference, filename, or title.

    Returns:
        A tuple containing the vault-relative task note path and filename stem,
        or ``None`` if no matching task is found.
    """
    tasks_dir = await resolve_under_root(VAULT_PATHS.task_notes_dir)

    candidates = [
        tasks_dir / f"{note_filename(task_ref)}.md",
        tasks_dir / f"{safe_slug(task_ref)}.md",
    ]
    for candidate in candidates:
        if await candidate.exists():
            rel_path = VAULT_PATHS.task_notes_dir / candidate.name
            return rel_path, candidate.stem

    if not await tasks_dir.is_dir():
        return None

    target = task_ref.casefold()
    async for entry in tasks_dir.iterdir():
        if entry.suffix != ".md" or not await entry.is_file():
            continue
        if entry.stem.casefold() == target:
            rel_path = VAULT_PATHS.task_notes_dir / entry.name
            return rel_path, entry.stem

        text = await entry.read_text(encoding="utf-8")
        title = note_title_from_markdown(text)
        if title is not None and title.casefold() == target:
            rel_path = VAULT_PATHS.task_notes_dir / entry.name
            return rel_path, entry.stem

    return None


async def _create_task_note(
    *,
    filename_stem: str,
    metadata: TaskMetadata,
    capture: Capture | None,
    description: str,
    due: str | None,
) -> AsyncPath:
    """Create the markdown task note for a new task.

    Returns:
        Relative path to the created task note within the vault.
    """
    note_content = _build_task_note(
        title=metadata.title,
        now=dt.datetime.now(tz=dt.UTC).astimezone(),
        metadata=metadata,
        capture=capture,
        description=description,
        due=due,
    )

    path_in_vault = VAULT_PATHS.task_notes_dir / f"{filename_stem}.md"
    task_path = await resolve_under_root(path_in_vault)

    await atomic_write_text(task_path, note_content)
    logger.info("Created task note: {}", task_path)

    return path_in_vault


async def _create_linked_stubs(
    metadata: TaskMetadata,
    source_task_link: str,
) -> tuple[list[str], list[str], list[str], list[str]]:
    """Creates stub notes for domains, resources, projects, and people from task metadata.

    Returns:
        A tuple of four lists containing newly created domain, resource, project, and people names, respectively.
    """
    return await asyncio.gather(
        _create_stubs(
            metadata.domains,
            "domain",
            source_task_link,
        ),
        _create_stubs(
            metadata.resources,
            "resource",
            source_task_link,
        ),
        _create_stubs(
            metadata.projects,
            "project",
            source_task_link,
        ),
        _create_stubs(
            metadata.people,
            "person",
            source_task_link,
        ),
    )


@final
class TaskService:
    """Service for creating structured task notes."""

    @staticmethod
    async def create_task(
        description: str,
        title: str | None = None,
        due: str | None = None,
        priority: enums.Priority | None = None,
        link_capture_id: str | None = None,
    ) -> CreateTaskResult:
        """Create a task note from a description and return its vault details.

        Also returns linked capture information and any created entity stubs.

        Parameters:
            description (str): Natural-language task description.
            title (str | None): Task title. Inferred via LLM if omitted.
            due (str | None): Due date in YYYY-MM-DD format.
            priority (enums.Priority | None): Priority override (low, medium, or high).
            link_capture_id (str | None): Exact capture ID to link when a specific inbox entry has been confirmed.

        Returns:
            CreateTaskResult: Task metadata and vault details including the note path,
                slug, title, vault note metadata, optional linked capture ID,
                candidate captures for manual linking, and lists of newly created
                domain, resource, project, and person entity stubs.
        """
        capture_selection = await _select_task_capture(description, link_capture_id)
        metadata = await _extract_metadata(
            _metadata_source(description, capture_selection.matched),
            title,
            priority,
        )
        filename_stem, slug = await _unique_task_filename(metadata.title)

        note_path = await _create_task_note(
            filename_stem=filename_stem,
            metadata=metadata,
            capture=capture_selection.matched,
            description=description,
            due=due,
        )
        note_metadata = build_vault_note_metadata(
            kind="task",
            title=metadata.title,
            path=note_path,
        )
        board_path = await resolve_under_root(VAULT_PATHS.task_board_path)
        await append_board_card(board_path, note_path)

        (
            domains_created,
            resources_created,
            projects_created,
            people_created,
        ) = await _create_linked_stubs(metadata, note_metadata.canonical_link)

        if capture_selection.matched is not None:
            await _annotate_capture(
                capture_selection.matched,
                note_metadata.canonical_link,
            )

        logger.info(
            (
                "Task intake complete: slug={} matched_capture_id={} "
                "domains_created={} resources_created={} projects_created={} "
                "people_created={}"
            ),
            slug,
            capture_selection.matched.id if capture_selection.matched else None,
            domains_created,
            resources_created,
            projects_created,
            people_created,
        )

        return CreateTaskResult(
            slug=slug,
            path=note_path,
            title=metadata.title,
            metadata=note_metadata,
            matched_capture_id=(
                capture_selection.matched.id if capture_selection.matched else None
            ),
            candidate_captures=[
                _capture_payload(capture) for capture in capture_selection.candidates
            ],
            domains_created=domains_created,
            resources_created=resources_created,
            projects_created=projects_created,
            people_created=people_created,
        )

    @staticmethod
    async def link_capture(task_slug: str, capture_id: str) -> str:
        """Link an existing task to a confirmed inbox capture.

        Args:
            task_slug: Slug of the task note in ``Tasks``.
            capture_id: Stable capture ID, e.g. ``2026-05-25T21:15``.

        Returns:
            Concise confirmation of the linking outcome.

        Raises:
            NotFoundError: If the capture or task cannot be found.
        """
        captures = await _load_all_captures()
        capture = _find_capture_by_id(captures, capture_id)
        if capture is None:
            logger.warning(
                "Capture {} not found; task {} unchanged",
                capture_id,
                task_slug,
            )
            msg = f"Capture {capture_id!r} not found."
            raise exc.NotFoundError(
                message=msg,
                detail={"resource": "capture", "id": capture_id},
            )

        resolved = await _resolve_task_reference(task_slug)
        if resolved is None:
            logger.warning(
                "Task {} not found while linking capture {}",
                task_slug,
                capture_id,
            )
            msg = f"Task {task_slug!r} not found."
            raise exc.NotFoundError(
                message=msg,
                detail={"resource": "task", "id": task_slug},
            )

        task_path, _link_target = resolved
        try:
            async with MarkdownDocument(vault_path=task_path) as task:
                task.frontmatter["source_capture"] = capture.id
        except FileNotFoundError as error:
            logger.warning(
                "Task {} not found while linking capture {}",
                task_path,
                capture_id,
            )
            msg = f"Task {task_slug!r} not found."
            raise exc.NotFoundError(
                message=msg,
                detail={"resource": "task", "id": task_slug},
            ) from error

        await _annotate_capture(capture, build_obsidian_link(task_path))
        logger.info("Linked task {} to capture {}", task_path, capture_id)
        return f"Task {obsidian_link_target_from_path(str(task_path))} linked to capture {capture_id}."
