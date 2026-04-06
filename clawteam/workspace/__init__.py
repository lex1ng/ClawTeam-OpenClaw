"""Git worktree workspace isolation for ClawTeam agents."""

from __future__ import annotations

from pathlib import Path

from clawteam.workspace.manager import WorkspaceManager
from clawteam.workspace.models import WorkspacePreflight


def get_workspace_manager(
    repo_path: str | None = None,
    *,
    base_ref: str | None = None,
) -> WorkspaceManager | None:
    """Return a WorkspaceManager if inside a git repo, else None."""
    path = Path(repo_path) if repo_path else None
    return WorkspaceManager.try_create(path, base_ref=base_ref)


def inspect_workspace(
    repo_path: str | None = None,
    *,
    workspace_mode: str = "auto",
    base_ref: str | None = None,
) -> WorkspacePreflight:
    """Return structured workspace diagnostics for spawn/operator flows."""
    path = Path(repo_path) if repo_path else None
    return WorkspaceManager.diagnose(path, workspace_mode=workspace_mode, base_ref=base_ref)
