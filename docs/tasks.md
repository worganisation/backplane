# Task browsing

The general Backplane agent exposes `list_tasks` and `get_task`. Browse by exact project display name or stored wiki-link target, ignoring case; use an empty project filter for unassigned tasks. The status filter matches the stored status exactly. Results are ordered by title and stable ID, with a maximum page size of 100 and a default of 20.

Use the returned frontmatter `id` for subsequent retrieval. Renaming a note or changing its title does not change its identity. Duplicate IDs are reported as a conflict rather than selecting an arbitrary note. Non-task notes are ignored; invalid structured task metadata requires repair.

`GET /api/obsidian/tasks` exposes the same filters (`project`, `status`, `limit`, `offset`). `GET /api/obsidian/tasks/{task_id}` returns the exact task and its original Markdown body. These tools read the vault directly, so edits made in Obsidian remain authoritative.

## Updating tasks

`update_task` and `PATCH /api/obsidian/tasks/{task_id}` accept explicit `status` (`backlog`, `doing`, `done`), an existing `project` name, or `clear_project: true`. Omitted fields stay unchanged. Create a new project explicitly before assigning it; supplying both a project and removal is rejected. The original Markdown body and stable ID are preserved. Completion sets a timestamp; reopening clears it.

Task metadata is authoritative. The existing Kanban board is projected into Backlog, Doing and Done sections, creating a missing section when needed. Existing card metadata, unrelated cards and board settings are retained. Each file is written atomically, but the note and board are separate writes: a board failure returns the saved task with a warning. Repeat the same update to repair its card without changing its completion time. Cooperating Backplane writers serialize through the vault lock; observed external edits abort the affected write.
