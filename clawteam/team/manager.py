"""Team manager for creating and managing teams."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from clawteam.team.models import TeamConfig, TeamMember, TeamReusePolicy, get_data_dir
from clawteam.team.plan import referenced_legacy_plan_paths, team_plans_path


def _teams_root() -> Path:
    p = get_data_dir() / "teams"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _team_dir(team_name: str) -> Path:
    return _teams_root() / team_name


def _config_path(team_name: str) -> Path:
    return _team_dir(team_name) / "config.json"


def _load_config(team_name: str) -> TeamConfig | None:
    path = _config_path(team_name)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return TeamConfig.model_validate(data)
    except (json.JSONDecodeError, Exception):
        return None


def _save_config(config: TeamConfig) -> None:
    path = _config_path(config.name)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        config.model_dump_json(indent=2, by_alias=True), encoding="utf-8"
    )
    tmp.rename(path)


class TeamManager:
    """Manages team lifecycle operations."""

    @staticmethod
    def _nickname_key(nickname: str) -> str:
        return nickname.strip().casefold()

    @staticmethod
    def _ensure_unique_nickname(
        config: TeamConfig,
        nickname: str,
        *,
        ignore_member_id: str | None = None,
    ) -> None:
        key = TeamManager._nickname_key(nickname)
        if not key:
            return
        for member in config.members:
            if ignore_member_id and member.member_id == ignore_member_id:
                continue
            existing = TeamManager._nickname_key(member.member_nickname or member.name)
            if existing == key:
                raise ValueError(f"Nickname '{nickname}' already exists in team '{config.name}'")

    @staticmethod
    def get_member(
        team_name: str,
        member_name: str,
        user: str = "",
    ) -> TeamMember | None:
        """Return a member by logical name, optionally scoped by user."""
        config = _load_config(team_name)
        if not config:
            return None
        if user:
            for member in config.members:
                if member.name == member_name and member.user == user:
                    return member
        matches = [member for member in config.members if member.name == member_name]
        if len(matches) == 1:
            return matches[0]
        return None

    @staticmethod
    def get_member_by_identity(
        team_name: str,
        *,
        member_id: str = "",
        agent_id: str = "",
        preferred_session_key: str = "",
        member_name: str = "",
        user: str = "",
    ) -> TeamMember | None:
        """Resolve one member by machine-facing identity first.

        Resolution order:
        1) member_id
        2) agent_id
        3) preferred_session_key
        4) member_name (+ user if provided, else only if unique)
        """
        config = _load_config(team_name)
        if not config:
            return None

        if member_id:
            matches = [member for member in config.members if member.member_id == member_id]
            return matches[0] if len(matches) == 1 else None

        if agent_id:
            matches = [member for member in config.members if member.agent_id == agent_id]
            return matches[0] if len(matches) == 1 else None

        if preferred_session_key:
            matches = [
                member
                for member in config.members
                if member.preferred_session_key == preferred_session_key
            ]
            return matches[0] if len(matches) == 1 else None

        if member_name:
            if user:
                matches = [
                    member
                    for member in config.members
                    if member.name == member_name and member.user == user
                ]
                return matches[0] if len(matches) == 1 else None
            matches = [member for member in config.members if member.name == member_name]
            return matches[0] if len(matches) == 1 else None

        return None

    @staticmethod
    def create_team(
        name: str,
        leader_name: str,
        leader_id: str,
        description: str = "",
        user: str = "",
        product_key: str = "",
        team_profile_id: str = "",
        team_reuse_policy: TeamReusePolicy | str = TeamReusePolicy.reuse_existing,
        leader_nickname: str = "",
        leader_display_name: str = "",
        leader_role: str = "leader",
        preferred_session_key: str = "",
    ) -> TeamConfig:
        if _config_path(name).exists():
            raise ValueError(f"Team '{name}' already exists")

        leader = TeamMember(
            name=leader_name,
            user=user,
            agent_id=leader_id,
            agent_type="leader",
            memberNickname=leader_nickname or leader_name,
            memberDisplayName=leader_display_name or leader_nickname or leader_name,
            memberRole=leader_role or "leader",
            preferredSessionKey=preferred_session_key or (f"{user}:{leader_name}" if user else leader_name),
        )
        config = TeamConfig(
            name=name,
            description=description,
            lead_agent_id=leader_id,
            teamProfileId=team_profile_id or f"teamprof-{name}",
            productKey=product_key or name,
            teamReusePolicy=team_reuse_policy,
            members=[leader],
        )
        _save_config(config)
        # Create inboxes dir and leader inbox
        inbox_name = f"{user}_{leader_name}" if user else leader_name
        inbox = _team_dir(name) / "inboxes" / inbox_name
        inbox.mkdir(parents=True, exist_ok=True)
        # Create tasks dir
        tasks_dir = get_data_dir() / "tasks" / name
        tasks_dir.mkdir(parents=True, exist_ok=True)
        return config

    @staticmethod
    def discover_teams() -> list[dict]:
        root = _teams_root()
        teams = []
        if not root.exists():
            return teams
        for d in sorted(root.iterdir()):
            if d.is_dir() and (d / "config.json").exists():
                config = _load_config(d.name)
                if config:
                    teams.append({
                        "name": config.name,
                        "description": config.description,
                        "leadAgentId": config.lead_agent_id,
                        "teamProfileId": config.team_profile_id,
                        "productKey": config.product_key,
                        "teamReusePolicy": config.team_reuse_policy.value,
                        "memberCount": len(config.members),
                    })
        return teams

    @staticmethod
    def get_team(name: str) -> TeamConfig | None:
        return _load_config(name)

    @staticmethod
    def add_member(
        team_name: str,
        member_name: str,
        agent_id: str,
        agent_type: str = "general-purpose",
        user: str = "",
        member_nickname: str = "",
        member_display_name: str = "",
        member_role: str = "",
        preferred_session_key: str = "",
        session_routing: dict | None = None,
    ) -> TeamMember:
        config = _load_config(team_name)
        if not config:
            raise ValueError(f"Team '{team_name}' not found")
        for m in config.members:
            if m.name == member_name and m.user == user:
                raise ValueError(f"Agent '{member_name}' (user={user or '(none)'}) already in team")
        resolved_nickname = member_nickname or member_name
        TeamManager._ensure_unique_nickname(config, resolved_nickname)
        member = TeamMember(
            name=member_name,
            user=user,
            agent_id=agent_id,
            agent_type=agent_type,
            memberNickname=resolved_nickname,
            memberDisplayName=member_display_name or resolved_nickname,
            memberRole=member_role or agent_type,
            preferredSessionKey=preferred_session_key or (f"{user}:{member_name}" if user else member_name),
            sessionRouting=session_routing or {
                "preferredSessionKey": preferred_session_key or (f"{user}:{member_name}" if user else member_name),
                "durableAuthority": "id_session_key",
                "liveNoticeEnabled": False,
            },
        )
        config.members.append(member)
        _save_config(config)
        inbox_name = f"{user}_{member_name}" if user else member_name
        inbox = _team_dir(team_name) / "inboxes" / inbox_name
        inbox.mkdir(parents=True, exist_ok=True)
        return member

    @staticmethod
    def remove_member(team_name: str, member_name: str, user: str = "") -> bool:
        config = _load_config(team_name)
        if not config:
            return False
        before = len(config.members)
        if user:
            config.members = [
                member
                for member in config.members
                if not (member.name == member_name and member.user == user)
            ]
        else:
            matches = [member for member in config.members if member.name == member_name]
            if len(matches) != 1:
                return False
            target_member_id = matches[0].member_id
            config.members = [
                member
                for member in config.members
                if member.member_id != target_member_id
            ]
        if len(config.members) < before:
            _save_config(config)
            return True
        return False

    @staticmethod
    def update_member_profile(
        team_name: str,
        member_name: str,
        *,
        user: str = "",
        member_nickname: str | None = None,
        member_display_name: str | None = None,
        member_role: str | None = None,
        preferred_session_key: str | None = None,
        session_routing: dict | None = None,
        external_channel: str | None = None,
    ) -> TeamMember | None:
        config = _load_config(team_name)
        if not config:
            return None
        candidates = [
            (i, member)
            for i, member in enumerate(config.members)
            if member.name == member_name and (not user or member.user == user)
        ]
        if len(candidates) != 1:
            return None
        index, member = candidates[0]
        updated_fields: dict = {}
        if member_nickname is not None:
            TeamManager._ensure_unique_nickname(
                config,
                member_nickname,
                ignore_member_id=member.member_id,
            )
            updated_fields["member_nickname"] = member_nickname
        if member_display_name is not None:
            updated_fields["member_display_name"] = member_display_name
        if member_role is not None:
            updated_fields["member_role"] = member_role
        if preferred_session_key is not None:
            updated_fields["preferred_session_key"] = preferred_session_key
            if session_routing is None:
                next_routing = dict(member.session_routing or {})
                next_routing["preferredSessionKey"] = preferred_session_key
                updated_fields["session_routing"] = next_routing
        if session_routing is not None:
            updated_fields["session_routing"] = session_routing
        if external_channel is not None:
            updated_fields["external_channel"] = external_channel
        if not updated_fields:
            return member

        updated_member = member.model_copy(update=updated_fields)
        config.members[index] = updated_member
        _save_config(config)
        return updated_member

    @staticmethod
    def get_leader_name(team_name: str) -> str | None:
        config = _load_config(team_name)
        if not config:
            return None
        for m in config.members:
            if m.agent_id == config.lead_agent_id:
                return m.name
        return config.members[0].name if config.members else None

    @staticmethod
    def cleanup(team_name: str) -> bool:
        # Best-effort cleanup of git workspaces before removing dirs
        try:
            from clawteam.workspace import get_workspace_manager
            ws_mgr = get_workspace_manager()
            if ws_mgr:
                ws_mgr.cleanup_team(team_name)
        except Exception:
            pass

        legacy_plan_paths = referenced_legacy_plan_paths(team_name)
        team_dir = _team_dir(team_name)
        tasks_dir = get_data_dir() / "tasks" / team_name
        costs_dir = get_data_dir() / "costs" / team_name
        sessions_dir = get_data_dir() / "sessions" / team_name
        plans_dir = team_plans_path(team_name)
        data_dir = get_data_dir()
        coding_dirs = (
            data_dir / "coding" / "jobs" / team_name,
            data_dir / "coding" / "results" / team_name,
            data_dir / "coding" / "events" / team_name,
            data_dir / "coding" / "artifacts" / team_name,
        )
        runtime_console_dirs = (
            data_dir / "runtime-console" / "provider-sessions" / team_name,
            data_dir / "runtime-console" / "callbacks" / team_name,
            data_dir / "runtime-console" / "faults" / team_name,
            data_dir / "runtime-console" / "timeline" / team_name,
            data_dir / "runtime-console" / "session-bridge" / team_name,
        )
        workspaces_dir = data_dir / "workspaces" / team_name
        cleaned = False
        for d in (team_dir, tasks_dir, costs_dir, sessions_dir, plans_dir, workspaces_dir, *coding_dirs, *runtime_console_dirs):
            if d.exists():
                shutil.rmtree(d)
                cleaned = True
        for path in legacy_plan_paths:
            try:
                if path.exists():
                    path.unlink()
                    cleaned = True
            except OSError:
                pass
        return cleaned

    @staticmethod
    def list_members(team_name: str) -> list[TeamMember]:
        config = _load_config(team_name)
        return config.members if config else []

    @staticmethod
    def inbox_name_for(member: TeamMember) -> str:
        """Return the inbox directory name for a member."""
        return f"{member.user}_{member.name}" if member.user else member.name

    @staticmethod
    def resolve_inbox(team_name: str, recipient: str, user: str = "") -> str:
        """Resolve a logical agent name to its on-disk inbox directory."""
        member = TeamManager.get_member(team_name, recipient, user=user)
        if member:
            return TeamManager.inbox_name_for(member)
        return recipient

    @staticmethod
    def get_leader_inbox(team_name: str) -> str | None:
        """Return the inbox name for the team leader."""
        config = _load_config(team_name)
        if not config:
            return None
        for m in config.members:
            if m.agent_id == config.lead_agent_id:
                return f"{m.user}_{m.name}" if m.user else m.name
        if config.members:
            m = config.members[0]
            return f"{m.user}_{m.name}" if m.user else m.name
        return None
