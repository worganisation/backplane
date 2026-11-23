# Task browsing

The general Backplane agent exposes `list_tasks` and `get_task`. Browse by exact project display name or stored wiki-link target, ignoring case; use an empty project filter for unassigned tasks. The status filter matches the stored status exactly. Results are ordered by title and stable ID, with a maximum page size of 100 and a default of 20.

Use the returned frontmatter `id` for subsequent retrieval. Renaming a note or changing its title does not change its identity. Duplicate IDs are reported as a conflict rather than selecting an arbitrary note. Non-task notes are ignored; invalid structured task metadata requires repair.

`GET /api/obsidian/tasks` exposes the same filters (`project`, `status`, `limit`, `offset`). `GET /api/obsidian/tasks/{task_id}` returns the exact task and its original Markdown body. These tools read the vault directly, so edits made in Obsidian remain authoritative.
