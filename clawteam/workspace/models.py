"""Data models for workspace management."""

from __future__ import annotations

from pydantic import BaseModel, Field


class WorkspaceInfo(BaseModel):
    """Information about a single agent workspace (git worktree)."""

    agent_name: str
    agent_id: str
    team_name: str
    branch_name: str        # "clawteam/{team}/{agent}"
    worktree_path: str      # "{data_dir}/workspaces/{team}/{agent}"
    repo_root: str
    repo_subpath: str = ""
    base_branch: str        # branch from which the worktree was created
    created_at: str


class WorkspaceRegistry(BaseModel):
    """Tracks all active workspaces for a team."""

    team_name: str
    repo_root: str
    workspaces: list[WorkspaceInfo] = []


class WorkspacePreflight(BaseModel):
    """Structured workspace diagnostics for spawn/operator flows."""

    status: str
    workspace_mode: str
    requested_path: str
    repo_root: str = ""
    is_git_repo: bool = False
    head_valid: bool = False
    current_branch: str = ""
    resolved_base_ref: str = ""
    base_ref_source: str = ""
    worktree_capable: bool = False
    reason: str = ""
    detail: str = ""
    recommendations: list[str] = Field(default_factory=list)
    git_error: str = ""

    def to_payload(self) -> dict:
        return {
            "status": self.status,
            "workspaceMode": self.workspace_mode,
            "requestedPath": self.requested_path,
            "repoRoot": self.repo_root or None,
            "isGitRepo": self.is_git_repo,
            "headValid": self.head_valid,
            "currentBranch": self.current_branch or None,
            "resolvedBaseRef": self.resolved_base_ref or None,
            "baseRefSource": self.base_ref_source or None,
            "worktreeCapable": self.worktree_capable,
            "reason": self.reason or None,
            "detail": self.detail or None,
            "recommendations": self.recommendations,
            "gitError": self.git_error or None,
            "recommendedSpawnMode": "workspace" if self.status == "ready" else "no-workspace",
        }
