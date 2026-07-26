"""CLI entrypoint for regenerating the MCP catalog section in README.md."""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
README_PATH = REPO_ROOT / "README.md"
FIXTURE_VAULT = REPO_ROOT / "scripts" / "fixtures" / "readme-vault"


def main() -> int:
    """Regenerate the MCP catalog section in README.md.

    Returns:
        1 if README.md was changed, 0 if it was already up to date.
    """
    os.environ["OBSIDIAN_VAULT_PATH"] = str(FIXTURE_VAULT)
    if "LOCAL_TIMEZONE" not in os.environ:
        os.environ["LOCAL_TIMEZONE"] = "UTC"

    from .mcp_catalog import (  # ruff:ignore[import-outside-top-level]
        refresh_readme_catalog,
    )

    changed = refresh_readme_catalog(README_PATH)
    return 1 if changed else 0


if __name__ == "__main__":
    sys.exit(main())
