"""CLI commands for clawteam - framework-agnostic multi-agent coordination."""

from __future__ import annotations

import json
import subprocess
import sys
import time
import uuid
import os
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from clawteam import __version__
from clawteam.version import FORK_NAME, PACKAGE_NAME, version_info
from clawteam.team.manager import TeamManager

app = typer.Typer(
    name="clawteam",
    help="Framework-agnostic multi-agent coordination CLI",
    no_args_is_help=True,
    invoke_without_command=True,
)
console = Console()


# ---------------------------------------------------------------------------
# Global options via callback
# ---------------------------------------------------------------------------

_json_output: bool = False
_data_dir: str | None = None


@app.callback()
def main(
    version: bool = typer.Option(
        False, "--version", "-v", is_eager=True,
        help="Show version and exit.",
    ),
    json_out: bool = typer.Option(
        False, "--json", help="Output JSON instead of human-readable text.",
    ),
    data_dir: Optional[str] = typer.Option(
        None, "--data-dir", help="Override data directory (default: ~/.clawteam).",
    ),
    transport: Optional[str] = typer.Option(
        None, "--transport", help="Transport backend: file or p2p.",
    ),
):
    """clawteam - Framework-agnostic multi-agent coordination CLI."""
    global _json_output, _data_dir
    _json_output = json_out
    if version:
        payload = version_info()
        if _json_output:
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        else:
            console.print(f"{PACKAGE_NAME} v{payload['version']}")
            console.print(f"fork: {payload['fork']}")
        raise typer.Exit()
    if data_dir:
        os.environ["CLAWTEAM_DATA_DIR"] = data_dir
        _data_dir = data_dir
    if transport:
        os.environ["CLAWTEAM_TRANSPORT"] = transport


def _dump(model) -> dict:
    """Dump a pydantic model to dict with by_alias and exclude_none."""
    return json.loads(model.model_dump_json(by_alias=True, exclude_none=True))


def _output(data: dict | list, human_fn=None):
    """Output data as JSON or human-readable."""
    if _json_output:
        print(json.dumps(data, indent=2, ensure_ascii=False))
    elif human_fn:
        human_fn(data)
    else:
        print(json.dumps(data, indent=2, ensure_ascii=False))


# ============================================================================
# Config Commands
# ============================================================================

config_app = typer.Typer(help="Configuration management")
app.add_typer(config_app, name="config")


@config_app.command("show")
def config_show():
    """Show all configuration settings and their sources."""
    from clawteam.config import get_effective

    keys = [
        "data_dir", "user", "default_team",
        "transport", "workspace", "workspace_base_ref", "default_backend", "skip_permissions",
    ]
    data = {}
    for k in keys:
        val, source = get_effective(k)
        data[k] = {"value": val, "source": source}

    def _human(d):
        table = Table(title="Configuration")
        table.add_column("Key", style="cyan")
        table.add_column("Value")
        table.add_column("Source", style="dim")
        for k in keys:
            v = d[k]["value"]
            table.add_row(k, str(v) if v != "" else "(empty)", d[k]["source"])
        console.print(table)

    _output(data, _human)


@config_app.command("set")
def config_set(
    key: str = typer.Argument(..., help="Config key (e.g. data_dir, user, transport, workspace, default_backend, skip_permissions)"),
    value: str = typer.Argument(..., help="Config value"),
):
    """Persistently set a configuration value."""
    from clawteam.config import ClawTeamConfig, load_config, save_config

    valid_keys = set(ClawTeamConfig.model_fields.keys())
    if key not in valid_keys:
        console.print(f"[red]Invalid key '{key}'. Valid: {', '.join(sorted(valid_keys))}[/red]")
        raise typer.Exit(1)

    cfg = load_config()
    # Handle boolean fields (skip_permissions)
    field_info = ClawTeamConfig.model_fields[key]
    if field_info.annotation is bool:
        setattr(cfg, key, value.lower() in ("true", "1", "yes"))
    else:
        setattr(cfg, key, value)
    save_config(cfg)

    _output(
        {"status": "saved", "key": key, "value": value},
        lambda d: console.print(f"[green]OK[/green] {key} = {value}"),
    )


@config_app.command("get")
def config_get(
    key: str = typer.Argument(..., help="Config key (e.g. data_dir, user, transport, workspace, default_backend, skip_permissions)"),
):
    """Get the effective value of a config key."""
    from clawteam.config import ClawTeamConfig, get_effective

    valid_keys = set(ClawTeamConfig.model_fields.keys())
    if key not in valid_keys:
        console.print(f"[red]Invalid key '{key}'. Valid: {', '.join(sorted(valid_keys))}[/red]")
        raise typer.Exit(1)

    val, source = get_effective(key)
    _output(
        {"key": key, "value": val, "source": source},
        lambda d: console.print(f"{key} = {val or '(empty)'}  [dim]({source})[/dim]"),
    )


@config_app.command("health")
def config_health():
    """Health check for the data directory (shared directory diagnostics)."""
    import os
    import time as _time

    from clawteam.config import get_effective
    from clawteam.team.manager import TeamManager
    from clawteam.team.models import get_data_dir

    checks = {}

    # Data directory
    data_dir = get_data_dir()
    val, source = get_effective("data_dir")
    checks["data_dir"] = str(data_dir)
    checks["data_dir_source"] = source

    # Exists
    checks["exists"] = data_dir.exists()

    # Writable
    try:
        test_file = data_dir / ".health-check"
        start = _time.monotonic()
        test_file.write_text("ok", encoding="utf-8")
        content = test_file.read_text(encoding="utf-8")
        elapsed = (_time.monotonic() - start) * 1000
        test_file.unlink()
        checks["writable"] = content == "ok"
        checks["latency_ms"] = round(elapsed, 2)
    except Exception as e:
        checks["writable"] = False
        checks["latency_ms"] = -1
        checks["write_error"] = str(e)

    # Mount point check
    try:
        checks["is_mount"] = os.path.ismount(str(data_dir))
    except Exception:
        checks["is_mount"] = False

    # Teams count
    try:
        teams = TeamManager.discover_teams()
        checks["teams_count"] = len(teams)
    except Exception:
        checks["teams_count"] = 0

    # User
    user_val, user_source = get_effective("user")
    checks["user"] = user_val
    checks["user_source"] = user_source

    def _human(d):
        console.print(f"\nData Directory: [cyan]{d['data_dir']}[/cyan]  [dim]({d['data_dir_source']})[/dim]")
        console.print(f"  Exists:     {'[green]yes[/green]' if d['exists'] else '[red]no[/red]'}")
        console.print(f"  Writable:   {'[green]yes[/green]' if d['writable'] else '[red]no[/red]'}")
        if d['latency_ms'] >= 0:
            color = "green" if d['latency_ms'] < 50 else "yellow" if d['latency_ms'] < 200 else "red"
            console.print(f"  Latency:    [{color}]{d['latency_ms']:.1f} ms[/{color}]")
        console.print(f"  Mount point: {'[yellow]yes (remote/shared)[/yellow]' if d['is_mount'] else '[dim]no (local)[/dim]'}")
        console.print(f"  Teams:      {d['teams_count']}")
        console.print(f"  User:       {d['user'] or '(not set)'}  [dim]({d['user_source']})[/dim]")

    _output(checks, _human)


# ============================================================================
# Team Commands
# ============================================================================

team_app = typer.Typer(help="Team management commands")
app.add_typer(team_app, name="team")


@team_app.command("spawn-team")
def team_spawn_team(
    name: str = typer.Argument(..., help="Team name"),
    description: str = typer.Option("", "--description", "-d", help="Team description"),
    agent_name: str = typer.Option("leader", "--agent-name", "-n", help="Leader agent name"),
    agent_type: str = typer.Option("leader", "--agent-type", help="Leader agent type"),
):
    """Create a new team and register the leader (spawnTeam)."""
    from clawteam.identity import AgentIdentity
    from clawteam.team.manager import TeamManager

    identity = AgentIdentity.from_env()
    leader_id = identity.agent_id
    leader_name = agent_name or identity.agent_name

    try:
        TeamManager.create_team(
            name=name,
            leader_name=leader_name,
            leader_id=leader_id,
            description=description,
            user=identity.user,
        )
        result = {
            "status": "created",
            "team": name,
            "leadAgentId": leader_id,
            "leaderName": leader_name,
        }
        if identity.user:
            result["user"] = identity.user
        _output(result, lambda d: (
            console.print(f"[green]OK[/green] Team '{name}' created"),
            console.print(f"  Leader: {leader_name} (id: {leader_id})"),
        ))
    except ValueError as e:
        if _json_output:
            print(json.dumps({"error": str(e)}))
        else:
            console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)


@team_app.command("discover")
def team_discover():
    """List all teams (discoverTeams)."""
    from clawteam.team.manager import TeamManager

    teams = TeamManager.discover_teams()

    def _human(data):
        if not data:
            console.print("[dim]No teams found[/dim]")
            return
        table = Table(title="Teams")
        table.add_column("Name", style="cyan")
        table.add_column("Description")
        table.add_column("Members", justify="right")
        for t in data:
            table.add_row(t["name"], t["description"], str(t["memberCount"]))
        console.print(table)

    _output(teams, _human)


@team_app.command("request-join")
def team_request_join(
    team: str = typer.Argument(..., help="Team name"),
    proposed_name: str = typer.Argument(..., help="Proposed agent name"),
    capabilities: str = typer.Option("", "--capabilities", "-c", help="Agent capabilities"),
    timeout: int = typer.Option(60, "--timeout", "-t", help="Timeout in seconds"),
):
    """Request to join a team (requestJoin). Blocks waiting for leader response."""
    from clawteam.identity import AgentIdentity
    from clawteam.team.mailbox import MailboxManager
    from clawteam.team.manager import TeamManager
    from clawteam.team.models import MessageType

    AgentIdentity.from_env()
    config = TeamManager.get_team(team)
    if not config:
        _output({"error": f"Team '{team}' not found"}, lambda d: console.print(f"[red]{d['error']}[/red]"))
        raise typer.Exit(1)

    leader_inbox = TeamManager.get_leader_inbox(team)
    leader_name = TeamManager.get_leader_name(team)
    if not leader_name or not leader_inbox:
        _output({"error": "No leader found"}, lambda d: console.print(f"[red]{d['error']}[/red]"))
        raise typer.Exit(1)

    mailbox = MailboxManager(team)
    request_id = f"join-{uuid.uuid4().hex[:12]}"
    temp_inbox_name = f"_pending_{proposed_name}"

    mailbox.send(
        from_agent=proposed_name,
        to=leader_inbox,
        msg_type=MessageType.join_request,
        request_id=request_id,
        proposed_name=proposed_name,
        capabilities=capabilities or None,
    )

    if not _json_output:
        console.print(f"Join request sent to leader '{leader_name}'. Waiting for response...")

    start = time.time()
    while time.time() - start < timeout:
        messages = mailbox.receive(temp_inbox_name, limit=10)
        for msg in messages:
            if msg.request_id == request_id:
                if msg.type == MessageType.join_approved:
                    result = {
                        "status": "approved",
                        "requestId": request_id,
                        "assignedName": msg.assigned_name or proposed_name,
                        "agentId": msg.agent_id or "",
                        "teamName": team,
                    }
                    _output(result, lambda d: console.print(
                        f"[green]Approved![/green] Joined as '{d['assignedName']}'"
                    ))
                    return
                elif msg.type == MessageType.join_rejected:
                    reason = msg.reason or msg.content or ""
                    _output(
                        {"status": "rejected", "requestId": request_id, "reason": reason},
                        lambda d: console.print(f"[red]Rejected.[/red] {reason}"),
                    )
                    raise typer.Exit(1)
        time.sleep(1.0)

    _output(
        {"status": "timeout", "requestId": request_id},
        lambda d: console.print("[yellow]Timeout waiting for response.[/yellow]"),
    )
    raise typer.Exit(1)


@team_app.command("approve-join")
def team_approve_join(
    team: str = typer.Argument(..., help="Team name"),
    request_id: str = typer.Argument(..., help="Join request ID"),
    assigned_name: Optional[str] = typer.Option(None, "--assigned-name", help="Override proposed name"),
):
    """Approve a join request (approveJoin)."""
    from clawteam.identity import AgentIdentity
    from clawteam.team.mailbox import MailboxManager
    from clawteam.team.manager import TeamManager
    from clawteam.team.models import MessageType

    identity = AgentIdentity.from_env()
    mailbox = MailboxManager(team)

    leader_inbox = TeamManager.get_leader_inbox(team) or identity.agent_name
    messages = mailbox.peek(leader_inbox)
    join_req = None
    for msg in messages:
        if msg.request_id == request_id and msg.type == MessageType.join_request:
            join_req = msg
            break

    proposed_name = join_req.proposed_name if join_req else f"agent-{request_id[:6]}"
    final_name = assigned_name or proposed_name
    new_agent_id = uuid.uuid4().hex[:12]

    try:
        TeamManager.add_member(
            team_name=team,
            member_name=final_name,
            agent_id=new_agent_id,
            agent_type="general-purpose",
            user=identity.user,
        )
    except ValueError:
        pass  # already a member

    temp_inbox_name = f"_pending_{proposed_name}"
    mailbox.send(
        from_agent=identity.agent_name,
        to=temp_inbox_name,
        msg_type=MessageType.join_approved,
        request_id=request_id,
        assigned_name=final_name,
        agent_id=new_agent_id,
        team_name=team,
    )

    # Schedule cleanup of the _pending_ inbox directory after the joining agent
    # has had time to consume the approval message. We do a best-effort immediate
    # cleanup here since the message was just delivered; the joining agent will
    # pick it up from the permanent inbox if it misses the temp one.
    import shutil
    from clawteam.team.models import get_data_dir
    pending_dir = get_data_dir() / "teams" / team / "inboxes" / temp_inbox_name
    if pending_dir.exists():
        try:
            shutil.rmtree(pending_dir)
        except OSError:
            pass

    _output(
        {"status": "approved", "requestId": request_id, "assignedName": final_name, "agentId": new_agent_id, "teamName": team},
        lambda d: console.print(f"[green]OK[/green] Approved '{final_name}' (id: {new_agent_id})"),
    )


@team_app.command("reject-join")
def team_reject_join(
    team: str = typer.Argument(..., help="Team name"),
    request_id: str = typer.Argument(..., help="Join request ID"),
    reason: str = typer.Option("", "--reason", "-r", help="Rejection reason"),
):
    """Reject a join request (rejectJoin)."""
    from clawteam.identity import AgentIdentity
    from clawteam.team.mailbox import MailboxManager
    from clawteam.team.manager import TeamManager
    from clawteam.team.models import MessageType

    identity = AgentIdentity.from_env()
    mailbox = MailboxManager(team)

    leader_inbox = TeamManager.get_leader_inbox(team) or identity.agent_name
    messages = mailbox.peek(leader_inbox)
    proposed_name = None
    for msg in messages:
        if msg.request_id == request_id and msg.type == MessageType.join_request:
            proposed_name = msg.proposed_name
            break

    proposed_name = proposed_name or f"agent-{request_id[:6]}"
    temp_inbox_name = f"_pending_{proposed_name}"

    mailbox.send(
        from_agent=identity.agent_name,
        to=temp_inbox_name,
        msg_type=MessageType.join_rejected,
        request_id=request_id,
        reason=reason or None,
    )

    # Clean up the _pending_ inbox directory
    import shutil
    from clawteam.team.models import get_data_dir
    pending_dir = get_data_dir() / "teams" / team / "inboxes" / temp_inbox_name
    if pending_dir.exists():
        try:
            shutil.rmtree(pending_dir)
        except OSError:
            pass

    _output(
        {"status": "rejected", "requestId": request_id, "reason": reason},
        lambda d: console.print(f"[green]OK[/green] Rejected request {request_id}"),
    )


@team_app.command("cleanup")
def team_cleanup(
    team: str = typer.Argument(..., help="Team name"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation"),
):
    """Delete a team and all its data (cleanup)."""
    from clawteam.team.manager import TeamManager

    if not force and not _json_output:
        if not typer.confirm(f"Delete team '{team}' and all its data?"):
            raise typer.Abort()

    if TeamManager.cleanup(team):
        _output({"status": "cleaned", "team": team}, lambda d: console.print(f"[green]OK[/green] Team '{team}' deleted"))
    else:
        _output({"status": "not_found", "team": team}, lambda d: console.print(f"[yellow]Team '{team}' not found[/yellow]"))


def _workspace_cwd_from_info(repo: str | None, ws_info) -> str:
    from pathlib import Path as _Path

    cwd = ws_info.worktree_path
    subpath = getattr(ws_info, "repo_subpath", "") or ""
    if subpath:
        return str((_Path(ws_info.worktree_path) / subpath).resolve())
    if repo:
        requested_repo = _Path(repo).expanduser().resolve()
        repo_root = _Path(ws_info.repo_root).resolve()
        try:
            relative_repo = requested_repo.relative_to(repo_root)
        except ValueError:
            relative_repo = None
        if relative_repo and str(relative_repo) != ".":
            return str((_Path(ws_info.worktree_path) / relative_repo).resolve())
    return cwd


def _default_spawn_cwd(repo: str | None) -> str:
    return str(Path(repo).expanduser().resolve()) if repo else str(Path.cwd().resolve())


def _workspace_human_label(status: str) -> str:
    if status == "created":
        return "[green]Workspace created[/green]"
    if status == "ready":
        return "[green]Workspace ready[/green]"
    if status == "skipped":
        return "[yellow]Workspace skipped[/yellow]"
    return "[red]Workspace failed[/red]"


def _print_workspace_diagnostic(data: dict) -> None:
    if _json_output:
        return
    console.print(f"{_workspace_human_label(data['status'])}")
    console.print(f"  Requested path: {data.get('requestedPath') or '-'}")
    console.print(f"  Repo root: {data.get('repoRoot') or '-'}")
    console.print(f"  Workspace mode: {data.get('workspaceMode') or '-'}")
    console.print(f"  Current branch: {data.get('currentBranch') or '-'}")
    console.print(f"  Resolved base ref: {data.get('resolvedBaseRef') or '-'}")
    console.print(f"  HEAD valid: {'yes' if data.get('headValid') else 'no'}")
    console.print(f"  Worktree capable: {'yes' if data.get('worktreeCapable') else 'no'}")
    if data.get("detail"):
        console.print(f"  Detail: {data['detail']}")
    if data.get("gitError"):
        console.print(f"  Git error: {data['gitError']}")
    if data.get("recommendations"):
        console.print("  Recommended actions:")
        for rec in data["recommendations"]:
            console.print(f"    - {rec}")


@team_app.command("status")
def team_status(
    team: str = typer.Argument(..., help="Team name"),
):
    """Show team status and members."""
    from clawteam.spawn.registry import is_agent_alive
    from clawteam.team.manager import TeamManager

    config = TeamManager.get_team(team)
    if not config:
        _output({"error": f"Team '{team}' not found"}, lambda d: console.print(f"[red]{d['error']}[/red]"))
        raise typer.Exit(1)

    data = {
        "name": config.name,
        "description": config.description,
        "leadAgentId": config.lead_agent_id,
        "createdAt": config.created_at,
        "members": [
            {
                **m.model_dump(by_alias=True),
                "alive": is_agent_alive(team, m.name),
            }
            for m in config.members
        ],
    }

    def _human(d):
        console.print(f"\nTeam: [cyan]{d['name']}[/cyan]")
        if d['description']:
            console.print(f"  {d['description']}")
        console.print(f"  Created: {d['createdAt'][:19]}")
        has_user = any(m.get("user") for m in d["members"])
        table = Table(title="Members")
        table.add_column("Name", style="cyan")
        if has_user:
            table.add_column("User", style="magenta")
        table.add_column("ID", style="dim")
        table.add_column("Type")
        table.add_column("Alive")
        table.add_column("Joined", style="dim")
        for m in d["members"]:
            row = [m.get("name", "")]
            if has_user:
                row.append(m.get("user", ""))
            alive = m.get("alive")
            alive_label = "yes" if alive is True else "no" if alive is False else "unknown"
            row.extend([
                m.get("agentId", ""),
                m.get("agentType", ""),
                alive_label,
                (m.get("joinedAt") or "")[:19],
            ])
            table.add_row(*row)
        console.print(table)

    _output(data, _human)


# ============================================================================
# Inbox Commands
# ============================================================================

inbox_app = typer.Typer(help="Inbox / messaging commands")
app.add_typer(inbox_app, name="inbox")


@inbox_app.command("send")
def inbox_send(
    team: str = typer.Argument(..., help="Team name"),
    to: str = typer.Argument(..., help="Recipient agent name"),
    content: str = typer.Argument(..., help="Message content"),
    key: Optional[str] = typer.Option(None, "--key", "-k", help="Optional routing key"),
    msg_type: str = typer.Option("message", "--type", help="Message type"),
    from_agent: Optional[str] = typer.Option(None, "--from", "-f", help="Override sender name (default: from env identity)"),
):
    """Send a point-to-point message (write)."""
    from clawteam.identity import AgentIdentity
    from clawteam.team.mailbox import MailboxManager
    from clawteam.team.models import MessageType

    sender = from_agent or AgentIdentity.from_env().agent_name
    mailbox = MailboxManager(team)
    mt = MessageType(msg_type)
    msg = mailbox.send(
        from_agent=sender,
        to=to,
        content=content,
        msg_type=mt,
        key=key,
    )
    data = _dump(msg)
    _output(data, lambda d: console.print(f"[green]OK[/green] Message sent to '{to}'"))


@inbox_app.command("broadcast")
def inbox_broadcast(
    team: str = typer.Argument(..., help="Team name"),
    content: str = typer.Argument(..., help="Message content"),
    key: Optional[str] = typer.Option(None, "--key", "-k", help="Optional routing key"),
    msg_type: str = typer.Option("broadcast", "--type", help="Message type"),
    from_agent: Optional[str] = typer.Option(None, "--from", "-f", help="Override sender name (default: from env identity)"),
):
    """Broadcast a message to all team members (broadcast)."""
    from clawteam.identity import AgentIdentity
    from clawteam.team.mailbox import MailboxManager
    from clawteam.team.models import MessageType

    sender = from_agent or AgentIdentity.from_env().agent_name
    mailbox = MailboxManager(team)
    mt = MessageType(msg_type)
    messages = mailbox.broadcast(
        from_agent=sender,
        content=content,
        msg_type=mt,
        key=key,
    )
    data = {"count": len(messages), "recipients": [m.to for m in messages]}
    _output(data, lambda d: console.print(f"[green]OK[/green] Broadcast to {d['count']} agents"))


@inbox_app.command("receive")
def inbox_receive(
    team: str = typer.Argument(..., help="Team name"),
    agent: Optional[str] = typer.Option(None, "--agent", "-a", help="Agent name (default: from env)"),
    limit: int = typer.Option(10, "--limit", "-l", help="Max messages to receive"),
):
    """Receive and consume messages from inbox."""
    from clawteam.identity import AgentIdentity
    from clawteam.team.mailbox import MailboxManager
    from clawteam.team.manager import TeamManager

    identity = AgentIdentity.from_env()
    agent_name = TeamManager.resolve_inbox(team, agent or identity.agent_name, identity.user)
    mailbox = MailboxManager(team)
    messages = mailbox.receive(agent_name, limit=limit)

    data = [_dump(m) for m in messages]

    def _human(msgs):
        if not msgs:
            console.print("[dim]No messages[/dim]")
            return
        for m in msgs:
            console.print(
                f"[{m.get('timestamp', '')[:19]}] "
                f"[cyan]{m.get('type', '')}[/cyan] "
                f"from={m.get('from', '')} : {m.get('content', '')}"
            )

    _output(data, _human)


@inbox_app.command("peek")
def inbox_peek(
    team: str = typer.Argument(..., help="Team name"),
    agent: Optional[str] = typer.Option(None, "--agent", "-a", help="Agent name (default: from env)"),
):
    """Peek at messages without consuming them."""
    from clawteam.identity import AgentIdentity
    from clawteam.team.mailbox import MailboxManager
    from clawteam.team.manager import TeamManager

    identity = AgentIdentity.from_env()
    agent_name = TeamManager.resolve_inbox(team, agent or identity.agent_name, identity.user)
    mailbox = MailboxManager(team)
    messages = mailbox.peek(agent_name)

    data = {"count": len(messages), "messages": [_dump(m) for m in messages]}

    def _human(d):
        console.print(f"Pending messages: {d['count']}")
        for m in d["messages"]:
            console.print(
                f"  [{m.get('timestamp', '')[:19]}] "
                f"[cyan]{m.get('type', '')}[/cyan] "
                f"from={m.get('from', '')} : {(m.get('content') or '')[:80]}"
            )

    _output(data, _human)


@inbox_app.command("log")
def inbox_log(
    team: str = typer.Argument(..., help="Team name"),
    limit: int = typer.Option(50, "--limit", "-l", help="Max messages to show"),
    agent: Optional[str] = typer.Option(None, "--agent", "-a", help="Filter by sender agent name"),
):
    """View message history (event log). Non-destructive, shows all sent messages."""
    from clawteam.team.mailbox import MailboxManager

    mailbox = MailboxManager(team)
    messages = mailbox.get_event_log(limit=limit)

    if agent:
        messages = [m for m in messages if m.from_agent == agent]

    # Reverse to show oldest first (event log returns newest first)
    messages.reverse()

    data = {"count": len(messages), "messages": [_dump(m) for m in messages]}

    def _human(d):
        console.print(f"Message history: {d['count']} message(s)")
        for m in d["messages"]:
            fr = m.get("from", "?")
            to = m.get("to", "all")
            ts = (m.get("timestamp") or "")[:19]
            mtype = m.get("type", "message")
            content = (m.get("content") or "")[:120]
            console.print(f"  [{ts}] [cyan]{fr}[/cyan] → {to} ({mtype}): {content}")

    _output(data, _human)


@inbox_app.command("watch")
def inbox_watch(
    team: str = typer.Argument(..., help="Team name"),
    agent: Optional[str] = typer.Option(None, "--agent", "-a", help="Agent name (default: from env)"),
    poll_interval: float = typer.Option(1.0, "--poll-interval", "-p", help="Poll interval in seconds"),
    exec_cmd: Optional[str] = typer.Option(None, "--exec", "-e", help="Shell command to run for each new message (msg data in env vars)"),
):
    """Watch inbox for new messages (blocking, Ctrl+C to stop).

    With --exec, runs a shell command for each message. Message data is passed
    via env vars: CLAWTEAM_MSG_FROM, CLAWTEAM_MSG_TO, CLAWTEAM_MSG_CONTENT,
    CLAWTEAM_MSG_TYPE, CLAWTEAM_MSG_TIMESTAMP, CLAWTEAM_MSG_JSON.
    """
    from clawteam.identity import AgentIdentity
    from clawteam.team.mailbox import MailboxManager
    from clawteam.team.manager import TeamManager
    from clawteam.team.watcher import InboxWatcher

    identity = AgentIdentity.from_env()
    agent_name = TeamManager.resolve_inbox(team, agent or identity.agent_name, identity.user)
    mailbox = MailboxManager(team)

    if not _json_output:
        console.print(f"Watching inbox for '{agent_name}' in team '{team}'... (Ctrl+C to stop)")
        if exec_cmd:
            console.print(f"  exec: {exec_cmd}")

    watcher = InboxWatcher(
        team_name=team,
        agent_name=agent_name,
        mailbox=mailbox,
        poll_interval=poll_interval,
        json_output=_json_output,
        exec_cmd=exec_cmd,
    )
    watcher.watch()


# ============================================================================
# Task Commands
# ============================================================================

task_app = typer.Typer(help="Task management commands")
app.add_typer(task_app, name="task")


@task_app.command("create")
def task_create(
    team: str = typer.Argument(..., help="Team name"),
    subject: str = typer.Argument(..., help="Task subject"),
    description: str = typer.Option("", "--description", "-d", help="Task description"),
    owner: Optional[str] = typer.Option(None, "--owner", "-o", help="Owner agent name"),
    blocks: Optional[str] = typer.Option(None, "--blocks", help="Comma-separated task IDs this blocks"),
    blocked_by: Optional[str] = typer.Option(None, "--blocked-by", help="Comma-separated task IDs this is blocked by"),
):
    """Create a new task (TaskCreate)."""
    from clawteam.team.tasks import TaskStore

    store = TaskStore(team)
    blocks_list = [b.strip() for b in blocks.split(",") if b.strip()] if blocks else []
    blocked_by_list = [b.strip() for b in blocked_by.split(",") if b.strip()] if blocked_by else []

    task = store.create(
        subject=subject,
        description=description,
        owner=owner or "",
        blocks=blocks_list,
        blocked_by=blocked_by_list,
    )

    data = _dump(task)
    _output(data, lambda d: (
        console.print(f"[green]OK[/green] Task created: {d['id']}"),
        console.print(f"  Subject: {d['subject']}"),
        console.print(f"  Status: {d['status']}"),
        console.print(f"  Owner: {d.get('owner', '')}") if d.get('owner') else None,
    ))


@task_app.command("get")
def task_get(
    team: str = typer.Argument(..., help="Team name"),
    task_id: str = typer.Argument(..., help="Task ID"),
):
    """Get a single task (TaskGet)."""
    from clawteam.team.tasks import TaskStore

    store = TaskStore(team)
    task = store.get(task_id)
    if not task:
        _output({"error": f"Task '{task_id}' not found"}, lambda d: console.print(f"[red]{d['error']}[/red]"))
        raise typer.Exit(1)

    data = _dump(task)

    def _human(d):
        console.print(f"Task: [cyan]{d['id']}[/cyan]")
        console.print(f"  Subject: {d['subject']}")
        console.print(f"  Status: {d['status']}")
        if d.get('owner'):
            console.print(f"  Owner: {d['owner']}")
        if d.get('lockedBy'):
            console.print(f"  Locked by: [yellow]{d['lockedBy']}[/yellow] (since {d.get('lockedAt', '')[:19]})")
        if d.get('description'):
            console.print(f"  Description: {d['description']}")
        if d.get('blocks'):
            console.print(f"  Blocks: {', '.join(d['blocks'])}")
        if d.get('blockedBy'):
            console.print(f"  Blocked by: {', '.join(d['blockedBy'])}")

    _output(data, _human)


@task_app.command("update")
def task_update(
    team: str = typer.Argument(..., help="Team name"),
    task_id: str = typer.Argument(..., help="Task ID"),
    status: Optional[str] = typer.Option(None, "--status", "-s", help="New status: pending, in_progress, completed, blocked"),
    owner: Optional[str] = typer.Option(None, "--owner", "-o", help="New owner"),
    subject: Optional[str] = typer.Option(None, "--subject", help="New subject"),
    description: Optional[str] = typer.Option(None, "--description", "-d", help="New description"),
    add_blocks: Optional[str] = typer.Option(None, "--add-blocks", help="Comma-separated task IDs this blocks"),
    add_blocked_by: Optional[str] = typer.Option(None, "--add-blocked-by", help="Comma-separated task IDs blocking this"),
    force: bool = typer.Option(False, "--force", "-f", help="Force override task lock"),
):
    """Update a task (TaskUpdate)."""
    from clawteam.identity import AgentIdentity
    from clawteam.team.models import TaskStatus
    from clawteam.team.tasks import TaskLockError, TaskStore

    store = TaskStore(team)
    ts = TaskStatus(status) if status else None
    blocks_list = [b.strip() for b in add_blocks.split(",") if b.strip()] if add_blocks else None
    blocked_by_list = [b.strip() for b in add_blocked_by.split(",") if b.strip()] if add_blocked_by else None

    caller = AgentIdentity.from_env().agent_name

    try:
        task = store.update(
            task_id,
            status=ts,
            owner=owner,
            subject=subject,
            description=description,
            add_blocks=blocks_list,
            add_blocked_by=blocked_by_list,
            caller=caller,
            force=force,
        )
    except TaskLockError as e:
        _output({"error": str(e)}, lambda d: console.print(f"[red]Lock conflict: {d['error']}[/red]"))
        raise typer.Exit(1)

    if not task:
        _output({"error": f"Task '{task_id}' not found"}, lambda d: console.print(f"[red]{d['error']}[/red]"))
        raise typer.Exit(1)

    data = _dump(task)
    _output(data, lambda d: console.print(f"[green]OK[/green] Task {d['id']} updated"))


@task_app.command("list")
def task_list(
    team: str = typer.Argument(..., help="Team name"),
    status: Optional[str] = typer.Option(None, "--status", "-s", help="Filter by status"),
    owner: Optional[str] = typer.Option(None, "--owner", "-o", help="Filter by owner"),
):
    """List tasks for a team (TaskList)."""
    from clawteam.team.models import TaskStatus
    from clawteam.team.tasks import TaskStore

    store = TaskStore(team)
    ts = TaskStatus(status) if status else None
    tasks, read_faults = store.inspect_tasks(status=ts, owner=owner)

    data = {
        "teamName": team,
        "tasks": [_dump(t) for t in tasks],
        "readFaults": read_faults,
    }

    def _human(items):
        tasks_payload = items["tasks"]
        if not tasks_payload:
            console.print("[dim]No tasks found[/dim]")
            _print_read_faults(items)
            return
        table = Table(title=f"Tasks - {team}")
        table.add_column("ID", style="dim")
        table.add_column("Subject", style="cyan")
        table.add_column("Status")
        table.add_column("Owner")
        table.add_column("Lock", style="yellow")
        table.add_column("Blocked By", style="dim")
        for t in tasks_payload:
            st = t.get("status", "")
            style = {"pending": "white", "in_progress": "yellow", "completed": "green", "blocked": "red"}.get(st, "")
            table.add_row(
                t["id"],
                t["subject"],
                f"[{style}]{st}[/{style}]" if style else st,
                t.get("owner") or "",
                t.get("lockedBy") or "",
                ", ".join(t.get("blockedBy", [])),
            )
        console.print(table)
        _print_read_faults(items)

    _output(data, _human)


@task_app.command("stats")
def task_stats(
    team: str = typer.Argument(..., help="Team name"),
):
    """Show task timing statistics for a team."""
    from clawteam.team.tasks import TaskStore

    store = TaskStore(team)
    stats = store.get_stats()

    def _human(d):
        table = Table(title=f"Task Stats - {team}")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", justify="right")
        table.add_row("Total tasks", str(d["total"]))
        table.add_row("Completed", str(d["completed"]))
        table.add_row("In progress", str(d["in_progress"]))
        table.add_row("Pending", str(d["pending"]))
        table.add_row("Blocked", str(d["blocked"]))
        table.add_row("With timing data", str(d["timed_completed"]))
        avg = d["avg_duration_seconds"]
        if avg > 0:
            # Show in a readable format
            if avg < 60:
                table.add_row("Avg completion time", f"{avg:.1f}s")
            elif avg < 3600:
                table.add_row("Avg completion time", f"{avg / 60:.1f}m")
            else:
                table.add_row("Avg completion time", f"{avg / 3600:.1f}h")
        else:
            table.add_row("Avg completion time", "-")
        console.print(table)
        _print_read_faults(d)

    _output(stats, _human)


# ============================================================================
# Cost Commands
# ============================================================================

cost_app = typer.Typer(help="Cost tracking and budget management")
app.add_typer(cost_app, name="cost")


@cost_app.command("report")
def cost_report(
    team: str = typer.Argument(..., help="Team name"),
    input_tokens: int = typer.Option(0, "--input-tokens", help="Input tokens consumed"),
    output_tokens: int = typer.Option(0, "--output-tokens", help="Output tokens consumed"),
    cost_cents: float = typer.Option(0.0, "--cost-cents", help="Cost in cents"),
    provider: str = typer.Option("", "--provider", help="Provider name (e.g. anthropic)"),
    model: str = typer.Option("", "--model", help="Model name"),
    agent: Optional[str] = typer.Option(None, "--agent", "-a", help="Agent name (default: from env)"),
):
    """Report token usage and cost for an agent."""
    from clawteam.identity import AgentIdentity
    from clawteam.team.costs import CostStore
    from clawteam.team.manager import TeamManager

    agent_name = agent or AgentIdentity.from_env().agent_name
    store = CostStore(team)
    event = store.report(
        agent_name=agent_name,
        provider=provider,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_cents=cost_cents,
    )
    data = _dump(event)

    def _human(d):
        console.print(f"[green]OK[/green] Cost reported: ${d.get('costCents', 0) / 100:.4f}")

    _output(data, _human)

    # Check budget
    config = TeamManager.get_team(team)
    if config and config.budget_cents > 0:
        summary = store.summary()
        if summary.total_cost_cents > config.budget_cents:
            budget_dollars = config.budget_cents / 100
            spent_dollars = summary.total_cost_cents / 100
            if not _json_output:
                console.print(
                    f"[yellow]WARNING: Budget exceeded! "
                    f"Spent ${spent_dollars:.2f} / ${budget_dollars:.2f}[/yellow]"
                )


@cost_app.command("show")
def cost_show(
    team: str = typer.Argument(..., help="Team name"),
    agent: Optional[str] = typer.Option(None, "--agent", "-a", help="Filter by agent"),
):
    """Show cost summary and event history."""
    from clawteam.team.costs import CostStore
    from clawteam.team.manager import TeamManager

    store = CostStore(team)
    summary = store.summary()
    events = store.list_events(agent_name=agent or "")
    config = TeamManager.get_team(team)
    budget = config.budget_cents if config else 0.0

    data = {
        "summary": _dump(summary),
        "budget_cents": budget,
        "events": [_dump(e) for e in events],
    }

    def _human(d):
        s = d["summary"]
        total = s.get("totalCostCents", 0)
        console.print(f"\nCost Summary — [cyan]{team}[/cyan]")
        if budget > 0:
            console.print(f"  Total: ${total / 100:.4f} / ${budget / 100:.2f}")
        else:
            console.print(f"  Total: ${total / 100:.4f}")
        console.print(f"  Input tokens:  {s.get('totalInputTokens', 0):,}")
        console.print(f"  Output tokens: {s.get('totalOutputTokens', 0):,}")
        console.print(f"  Events: {s.get('eventCount', 0)}")
        by_agent = s.get("byAgent", {})
        if by_agent:
            console.print("  By agent:")
            for a, c in sorted(by_agent.items()):
                console.print(f"    {a}: ${c / 100:.4f}")

        evts = d["events"]
        if evts:
            table = Table(title="Recent Events")
            table.add_column("Time", style="dim")
            table.add_column("Agent", style="cyan")
            table.add_column("In Tokens", justify="right")
            table.add_column("Out Tokens", justify="right")
            table.add_column("Cost", justify="right")
            table.add_column("Model", style="dim")
            for e in evts[-20:]:  # show last 20
                table.add_row(
                    (e.get("reportedAt") or "")[:19],
                    e.get("agentName", ""),
                    f"{e.get('inputTokens', 0):,}",
                    f"{e.get('outputTokens', 0):,}",
                    f"${e.get('costCents', 0) / 100:.4f}",
                    e.get("model", ""),
                )
            console.print(table)

    _output(data, _human)


@cost_app.command("budget")
def cost_budget(
    team: str = typer.Argument(..., help="Team name"),
    dollars: float = typer.Argument(..., help="Budget in dollars (0 = unlimited)"),
):
    """Set team budget in dollars."""
    from clawteam.team.manager import TeamManager

    config = TeamManager.get_team(team)
    if not config:
        _output({"error": f"Team '{team}' not found"}, lambda d: console.print(f"[red]{d['error']}[/red]"))
        raise typer.Exit(1)

    config.budget_cents = dollars * 100
    # Save config back
    from clawteam.team.manager import _save_config
    _save_config(config)

    _output(
        {"status": "set", "team": team, "budgetDollars": dollars},
        lambda d: console.print(
            f"[green]OK[/green] Budget set to ${dollars:.2f}" if dollars > 0
            else "[green]OK[/green] Budget removed (unlimited)"
        ),
    )


@task_app.command("wait")
def task_wait(
    team: str = typer.Argument(..., help="Team name"),
    agent: Optional[str] = typer.Option(None, "--agent", "-a", help="Agent inbox to monitor (default: leader from team config)"),
    poll_interval: float = typer.Option(5.0, "--poll-interval", "-p", help="Seconds between polls"),
    timeout: Optional[float] = typer.Option(None, "--timeout", "-t", help="Max seconds to wait (default: no limit)"),
):
    """Block until all tasks in a team are completed."""
    from clawteam.team.mailbox import MailboxManager
    from clawteam.team.manager import TeamManager
    from clawteam.team.tasks import TaskStore
    from clawteam.team.waiter import TaskWaiter

    # Resolve agent name for inbox monitoring
    agent_name = agent
    if not agent_name:
        agent_name = TeamManager.get_leader_inbox(team)
    if not agent_name:
        from clawteam.identity import AgentIdentity
        identity = AgentIdentity.from_env()
        agent_name = TeamManager.resolve_inbox(team, identity.agent_name, identity.user)
    elif agent:
        from clawteam.identity import AgentIdentity
        identity = AgentIdentity.from_env()
        agent_name = TeamManager.resolve_inbox(team, agent_name, identity.user)

    mailbox = MailboxManager(team)
    store = TaskStore(team)

    def _on_message(msg):
        ts = msg.timestamp
        if ts and "T" in ts:
            ts = ts.split("T")[1][:8]
        from_agent = msg.from_agent or "?"
        content = msg.content or ""
        if _json_output:
            print(json.dumps({
                "event": "message",
                "from": from_agent,
                "content": content,
                "timestamp": msg.timestamp,
            }), flush=True)
        else:
            console.print(f"  {ts}  message from={from_agent}: {content}")

    last_progress = ""

    def _on_progress(completed, total, in_progress, pending, blocked):
        nonlocal last_progress
        summary = f"{completed}/{total}"
        if summary == last_progress:
            return
        last_progress = summary
        if _json_output:
            print(json.dumps({
                "event": "progress",
                "completed": completed,
                "total": total,
                "in_progress": in_progress,
                "pending": pending,
                "blocked": blocked,
            }), flush=True)
        else:
            console.print(
                f"  {completed}/{total} tasks completed"
                f"  ({in_progress} in progress, {pending} pending, {blocked} blocked)"
            )

    if not _json_output:
        timeout_str = f"{timeout:.0f}s" if timeout else "none"
        console.print(f"Waiting for all tasks in team '[cyan]{team}[/cyan]' to complete...")
        console.print(
            f"  Agent inbox: {agent_name}  |  Poll interval: {poll_interval}s  |  Timeout: {timeout_str}"
        )
        console.print()

    def _on_agent_dead(dead_agent, abandoned_tasks):
        task_subjects = ", ".join(t.subject for t in abandoned_tasks)
        if _json_output:
            print(json.dumps({
                "event": "agent_dead",
                "agent": dead_agent,
                "abandoned_tasks": [{"id": t.id, "subject": t.subject} for t in abandoned_tasks],
            }), flush=True)
        else:
            console.print(
                f"  [yellow]Agent '{dead_agent}' is dead.[/yellow]"
                f" Reset {len(abandoned_tasks)} task(s) to pending: {task_subjects}"
            )

    waiter = TaskWaiter(
        team_name=team,
        agent_name=agent_name,
        mailbox=mailbox,
        task_store=store,
        poll_interval=poll_interval,
        timeout=timeout,
        on_message=_on_message,
        on_progress=_on_progress,
        on_agent_dead=_on_agent_dead,
    )
    result = waiter.wait()

    if _json_output:
        print(json.dumps({
            "event": "result",
            "status": result.status,
            "elapsed": round(result.elapsed, 1),
            "total": result.total,
            "completed": result.completed,
            "in_progress": result.in_progress,
            "pending": result.pending,
            "blocked": result.blocked,
            "messages_received": result.messages_received,
            "task_details": result.task_details,
            "readFaults": result.read_faults,
        }), flush=True)
    else:
        console.print()
        if result.status == "completed":
            console.print(
                f"[green]All {result.total} tasks completed![/green]"
                f" ({result.elapsed:.1f}s, {result.messages_received} messages)"
            )
        elif result.status == "timeout":
            console.print(
                f"[yellow]Timeout[/yellow] after {result.elapsed:.1f}s."
                f" {result.completed}/{result.total} completed."
            )
            _print_incomplete_tasks(result.task_details)
        else:
            console.print(
                f"[yellow]Interrupted[/yellow] after {result.elapsed:.1f}s."
                f" {result.completed}/{result.total} completed."
            )
            _print_incomplete_tasks(result.task_details)
        _print_read_faults({"readFaults": result.read_faults})

    if result.status != "completed":
        raise typer.Exit(1)


def _print_incomplete_tasks(task_details: list[dict]):
    """Print tasks that are not completed."""
    incomplete = [t for t in task_details if t["status"] != "completed"]
    if incomplete:
        console.print("  Incomplete tasks:")
        for t in incomplete:
            console.print(f"    [{t['status']}] {t['id']}  {t['subject']}  (owner: {t['owner'] or '-'})")


# ============================================================================
# Coding Runtime Commands
# ============================================================================

coding_app = typer.Typer(help="Coding callback runtime commands")
app.add_typer(coding_app, name="coding")


def _resolve_coding_team(team: Optional[str]) -> str:
    from clawteam.identity import AgentIdentity

    identity = AgentIdentity.from_env()
    team_name = team or identity.team_name
    if not team_name:
        raise typer.BadParameter(
            "Team name is required. Pass --team or set CLAWTEAM_TEAM_NAME."
        )
    return team_name


def _print_error(message: str) -> None:
    _output({"error": message}, lambda d: console.print(f"[red]{d['error']}[/red]"))


def _display_or(value, fallback: str = "unavailable") -> str:
    if value in (None, "", [], {}):
        return fallback
    return str(value)


def _bool_label(value: bool) -> str:
    return "yes" if value else "no"


def _coding_result_human(data: dict):
    console.print(
        f"Job: [cyan]{data['jobId']}[/cyan]  "
        f"Provider: {data['provider']}  "
        f"Status: [bold]{data['status']}[/bold]"
    )
    console.print(f"CWD: {data['effectiveCwd']}")
    if data.get("summary"):
        console.print(f"Summary: {data['summary']}")
    if data.get("error"):
        console.print(f"Error: [red]{data['error']}[/red]")
    if data.get("artifacts"):
        console.print(f"Artifacts: {json.dumps(data['artifacts'], ensure_ascii=False)}")


def _coding_record_human(data: dict):
    startup_policy = data.get("startupPolicy") or {}
    applied_flags = startup_policy.get("appliedFlags", [])
    extra_args = startup_policy.get("extraArgs", [])
    skip_permissions = startup_policy.get("skipProviderPermissions")
    dangerous_skip_enabled = "--dangerously-skip-permissions" in applied_flags
    console.print(
        f"Job: [cyan]{data['jobId']}[/cyan]  "
        f"Provider: {data['provider']}  "
        f"State: [bold]{data['state']}[/bold]"
    )
    console.print(f"Worker: {data['workerName']} ({data['workerId']})")
    console.print(f"Task: {data.get('taskId') or '-'}")
    console.print(f"Leader: {data.get('leaderName') or '-'}")
    console.print(f"Provider Session Ref: {data.get('providerSessionRef') or '-'}")
    console.print(f"Provider Session ID: {_display_or(data.get('providerSessionId'))}")
    console.print(f"Session Mode: {data.get('sessionMode') or 'unknown'}")
    console.print(
        "Attempt: "
        f"{data.get('attemptKind', '-')}  "
        f"retry={data.get('retryCount', 0)}  "
        f"replay={data.get('replayCount', 0)}"
    )
    console.print(f"Requested CWD: {data.get('requestedCwd') or '-'}")
    console.print(f"Effective CWD: {data['effectiveCwd']}")
    console.print(
        "Startup Policy: "
        f"source={startup_policy.get('source', '-')}  "
        f"skipProviderPermissions={skip_permissions}"
    )
    console.print(
        "--dangerously-skip-permissions: "
        f"{'enabled' if dangerous_skip_enabled else 'disabled'}"
    )
    console.print(f"Applied Flags: {json.dumps(applied_flags, ensure_ascii=False)}")
    console.print(f"Extra Args: {json.dumps(extra_args, ensure_ascii=False)}")
    console.print(f"Callback Status: {data.get('callbackStatus') or 'not_applicable'}")
    console.print(f"Callback Decision: {data.get('callbackDecision') or '-'}")
    console.print(f"Callback Reported At: {data.get('callbackReportedAt') or '-'}")
    console.print(
        f"Created: {data['createdAt']}  "
        f"Started: {data.get('startedAt') or '-'}  "
        f"Updated: {data['updatedAt']}  "
        f"Finished: {data.get('finishedAt') or '-'}"
    )
    if data.get("summary"):
        console.print(f"Summary: {data['summary']}")
    if data.get("error"):
        console.print(f"Error: [red]{data['error']}[/red]")
    if data.get("artifactPaths"):
        console.print(f"Artifacts: {json.dumps(data['artifactPaths'], ensure_ascii=False)}")


def _coding_list_human(data: dict):
    table = Table(title=f"Coding Jobs ({data['teamName']})")
    table.add_column("Job", style="cyan")
    table.add_column("State")
    table.add_column("Task")
    table.add_column("Worker")
    table.add_column("Provider")
    table.add_column("Attempt")
    table.add_column("Session")
    table.add_column("Callback")
    table.add_column("Updated", style="dim")
    for record in data["jobs"]:
        table.add_row(
            record["jobId"],
            record["state"],
            record.get("taskId") or "-",
            record["workerName"],
            record["provider"],
            f"{record.get('attemptKind', '-')}"
            f" r{record.get('retryCount', 0)}"
            f"/p{record.get('replayCount', 0)}",
            _display_or(record.get("providerSessionId"), record.get("sessionMode", "unavailable")),
            record.get("callbackStatus") or "not_applicable",
            record["updatedAt"],
        )
    console.print(table)
    if data.get("faults"):
        console.print(f"[yellow]Faults: {len(data['faults'])} durable read issue(s) detected[/yellow]")


def _coding_events_human(data: dict):
    table = Table(title=f"Coding Events ({data['jobId']})")
    table.add_column("Time", style="dim")
    table.add_column("Type")
    table.add_column("State")
    table.add_column("Attempt")
    table.add_column("Summary")
    for event in data["events"]:
        table.add_row(
            event["createdAt"],
            event["eventType"],
            event.get("state") or "-",
            f"{event.get('attemptKind', '-')}"
            f" r{event.get('retryCount', 0)}"
            f"/p{event.get('replayCount', 0)}",
            event.get("summary") or "-",
        )
    console.print(table)


def _coding_callback_report_human(data: dict):
    console.print(
        f"Callback recorded for job [cyan]{data['jobId']}[/cyan] "
        f"task={data.get('taskId') or '-'} decision={data['decision']}"
    )
    console.print(f"Summary: {data['summary']}")
    if data.get("nextStep"):
        console.print(f"Next Step: {data['nextStep']}")
    if data.get("escalationReason"):
        console.print(f"Escalation: {data['escalationReason']}")


def _coding_artifacts_human(data: dict):
    table = Table(title=f"Coding Artifacts ({data['jobId']})")
    table.add_column("Name", style="cyan")
    table.add_column("Exists")
    table.add_column("Bytes")
    table.add_column("Path")
    for artifact in data["artifacts"]:
        table.add_row(
            artifact["name"],
            _bool_label(artifact["exists"]),
            str(artifact["sizeBytes"]) if artifact["sizeBytes"] is not None else "-",
            artifact["path"],
        )
    console.print(table)


def _coding_artifact_human(data: dict):
    console.print(f"Artifact: [cyan]{data['name']}[/cyan]  Exists: {_bool_label(data['exists'])}")
    console.print(f"Path: {data['path']}")
    if data.get("sizeBytes") is not None:
        console.print(f"Bytes: {data['sizeBytes']}")
    console.print(f"Binary: {_bool_label(data.get('isBinary', False))}")
    if data.get("content") is not None:
        console.print(data["content"], end="" if data["content"].endswith("\n") else "\n")


def _coding_session_list_human(data: dict):
    table = Table(title=f"Provider Sessions ({data['teamName']})")
    table.add_column("Session", style="cyan")
    table.add_column("Provider")
    table.add_column("State")
    table.add_column("Mode")
    table.add_column("Provider ID")
    table.add_column("Worker")
    table.add_column("Current Job")
    table.add_column("Callback")
    for record in data["sessions"]:
        table.add_row(
            record["sessionId"],
            record["provider"],
            record["state"],
            record["sessionMode"],
            _display_or(record.get("providerSessionId")),
            record["workerName"],
            record.get("currentJobId") or "-",
            record.get("callbackStatus") or "not_applicable",
        )
    console.print(table)
    _print_read_faults(data)


def _coding_session_human(data: dict):
    console.print(f"Session: [cyan]{data['sessionId']}[/cyan]")
    console.print(f"Provider: {data['provider']}")
    console.print(f"State: {data['state']}")
    console.print(f"Provider Session ID: {_display_or(data.get('providerSessionId'))}")
    console.print(f"Session Mode: {data['sessionMode']}")
    console.print(f"Resume Supported: {_bool_label(data.get('resumeSupported', False))}")
    console.print(f"Worker: {data['workerName']} ({data['workerId']})")
    console.print(f"Agent Session: {data.get('agentSessionId') or '-'}")
    console.print(f"Current Task: {data.get('currentTaskId') or '-'}")
    console.print(f"Current Job: {data.get('currentJobId') or '-'}")
    console.print(f"Last Job: {data.get('lastJobId') or '-'}")
    console.print(f"Effective CWD: {data.get('effectiveCwd') or '-'}")
    console.print(f"Worktree: {data.get('worktreePath') or '-'}")
    console.print(f"Runtime CWD: {data.get('runtimeCwd') or '-'}")
    console.print(f"Callback Status: {data.get('callbackStatus') or 'not_applicable'}")
    console.print(f"Last Callback: {data.get('lastCallbackAt') or '-'}")
    console.print(f"Last Activity: {data.get('lastActivityAt') or '-'}")
    console.print(f"Updated: {data['updatedAt']}")


def _faults_human(data: dict):
    table = Table(title=f"Runtime Faults ({data['teamName']})")
    table.add_column("Fault", style="cyan")
    table.add_column("Severity")
    table.add_column("Scope")
    table.add_column("Status")
    table.add_column("Message")
    for fault in data["faults"]:
        table.add_row(
            fault.get("faultId", fault.get("recordId", "-")),
            fault.get("severity", "warning"),
            (
                f"{fault.get('scopeType')}:{fault.get('scopeId')}"
                if fault.get("scopeType")
                else fault.get("recordKind", "-")
            ),
            fault.get("status", "open"),
            fault["message"],
        )
    console.print(table)
    _print_read_faults(data)


def _fault_human(data: dict):
    console.print(f"Fault: [cyan]{data['faultId']}[/cyan]")
    console.print(f"Type: {data['faultType']}")
    console.print(f"Severity: {data['severity']}")
    console.print(f"Scope: {data['scopeType']}:{data['scopeId']}")
    console.print(f"Status: {data['status']}")
    console.print(f"Detected At: {data['detectedAt']}")
    console.print(f"Message: {data['message']}")
    if data.get("detail"):
        console.print(f"Detail: {data['detail']}")
    if data.get("suggestedAction"):
        console.print(f"Suggested Action: {data['suggestedAction']}")


def _timeline_human(data: dict):
    table = Table(title=f"Runtime Timeline ({data['teamName']})")
    table.add_column("Time", style="dim")
    table.add_column("Type")
    table.add_column("Scope")
    table.add_column("Actor")
    table.add_column("Summary")
    for event in data["events"]:
        table.add_row(
            event["timestamp"],
            event["eventType"],
            f"{event['scopeType']}:{event['scopeId']}",
            f"{event['actorType']}:{event['actorId']}",
            event["summary"],
        )
    console.print(table)
    _print_read_faults(data)


def _artifact_entries(data: dict) -> list[dict]:
    entries = []
    for name, raw_path in sorted((data.get("artifactPaths") or {}).items()):
        path = Path(raw_path)
        exists = path.exists()
        size_bytes = path.stat().st_size if exists else None
        entries.append(
            {
                "name": name,
                "path": str(path),
                "exists": exists,
                "sizeBytes": size_bytes,
            }
        )
    return entries


def _print_read_faults(data: dict) -> None:
    if not data.get("readFaults"):
        return
    table = Table(title="Durable Read Faults")
    table.add_column("Kind", style="cyan")
    table.add_column("Record")
    table.add_column("Message")
    for fault in data["readFaults"]:
        table.add_row(
            fault.get("faultType", "-"),
            fault.get("recordKind", "-"),
            fault.get("message", "-"),
        )
    console.print(table)


@coding_app.command("exec")
def coding_exec(
    provider: str = typer.Argument(..., help="Provider name: claude or codex"),
    prompt: str = typer.Argument(..., help="Prompt to send to the coding provider"),
    team: Optional[str] = typer.Option(None, "--team", help="Team name (defaults from env)"),
    worker_name: Optional[str] = typer.Option(
        None,
        "--worker-name",
        help="Worker name (defaults from env)",
    ),
    worker_id: Optional[str] = typer.Option(
        None,
        "--worker-id",
        help="Worker id (defaults from env)",
    ),
    leader_name: Optional[str] = typer.Option(None, "--leader-name", help="Leader name"),
    task_id: Optional[str] = typer.Option(None, "--task-id", help="Optional task id"),
    mode: str = typer.Option("implement", "--mode", help="Execution mode"),
    cwd: Optional[str] = typer.Option(None, "--cwd", help="Per-call cwd override"),
    worker_workspace_cwd: Optional[str] = typer.Option(
        None,
        "--worker-workspace-cwd",
        help="Worker workspace/worktree cwd",
    ),
    worker_runtime_cwd: Optional[str] = typer.Option(
        None,
        "--worker-runtime-cwd",
        help="Worker runtime cwd",
    ),
    timeout_sec: int = typer.Option(1800, "--timeout-sec", help="Provider timeout in seconds"),
    allow_cwd_escape: bool = typer.Option(
        False,
        "--allow-cwd-escape",
        help="Explicitly allow cwd override outside the worker workspace boundary.",
    ),
    skip_provider_permissions: Optional[bool] = typer.Option(
        None,
        "--skip-provider-permissions/--no-skip-provider-permissions",
        help="Override provider permission-skip startup policy",
    ),
    provider_args: Optional[list[str]] = typer.Option(
        None,
        "--provider-arg",
        help="Extra provider arg; repeat for multiple values.",
    ),
):
    """Execute a coding callback job; V1 allows one active job per worker and per task."""
    import os

    from clawteam.coding import CodingExecRequest, CodingService
    from clawteam.identity import AgentIdentity
    from clawteam.team.manager import TeamManager

    identity = AgentIdentity.from_env()
    team_name = _resolve_coding_team(team)
    leader = leader_name or TeamManager.get_leader_name(team_name)
    request = CodingExecRequest(
        teamName=team_name,
        workerName=worker_name or identity.agent_name,
        workerId=worker_id or identity.agent_id,
        leaderName=leader,
        taskId=task_id,
        provider=provider,
        mode=mode,
        prompt=prompt,
        cwd=cwd,
        workerWorkspaceCwd=worker_workspace_cwd or os.environ.get("CLAWTEAM_WORKSPACE_DIR"),
        workerRuntimeCwd=worker_runtime_cwd or os.getcwd(),
        allowCwdEscape=allow_cwd_escape,
        timeoutSec=timeout_sec,
        skipProviderPermissions=skip_provider_permissions,
        providerArgs=provider_args or [],
    )
    try:
        result = CodingService().execute(request)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)
    _output(_dump(result), _coding_result_human)


@coding_app.command("list")
def coding_list(
    team: Optional[str] = typer.Option(None, "--team", help="Team name (defaults from env)"),
):
    """List persisted coding jobs with durable read faults surfaced explicitly."""
    from clawteam.coding import CodingJobStore

    team_name = _resolve_coding_team(team)
    jobs, faults = CodingJobStore().inspect_jobs(team_name)
    jobs_payload = sorted(
        (_dump(job) for job in jobs),
        key=lambda job: job.get("updatedAt", ""),
        reverse=True,
    )
    _output(
        {
            "teamName": team_name,
            "jobs": jobs_payload,
            "faults": faults,
        },
        _coding_list_human,
    )


@coding_app.command("status")
def coding_status(
    job_id: str = typer.Argument(..., help="Coding job id"),
    team: Optional[str] = typer.Option(None, "--team", help="Team name (defaults from env)"),
):
    """Show persisted coding job state."""
    from clawteam.coding import CodingService

    team_name = _resolve_coding_team(team)
    try:
        record = CodingService().require_job(team_name, job_id)
    except ValueError as exc:
        _output({"error": str(exc)}, lambda d: console.print(f"[red]{d['error']}[/red]"))
        raise typer.Exit(1)
    _output(_dump(record), _coding_record_human)


@coding_app.command("result")
def coding_result(
    job_id: str = typer.Argument(..., help="Coding job id"),
    team: Optional[str] = typer.Option(None, "--team", help="Team name (defaults from env)"),
):
    """Show the persisted normalized terminal result for a coding job."""
    from clawteam.coding import CodingService

    team_name = _resolve_coding_team(team)
    service = CodingService()
    try:
        service.require_job(team_name, job_id)
        result = service.store.load_result(team_name, job_id)
    except ValueError as exc:
        _print_error(str(exc))
        raise typer.Exit(1)
    if result is None:
        _print_error(f"Coding job '{job_id}' has no persisted result yet.")
        raise typer.Exit(1)
    _output(_dump(result), _coding_result_human)


@coding_app.command("events")
def coding_events(
    job_id: str = typer.Argument(..., help="Coding job id"),
    team: Optional[str] = typer.Option(None, "--team", help="Team name (defaults from env)"),
):
    """Show durable lifecycle events for a coding job."""
    from clawteam.coding import CodingService

    team_name = _resolve_coding_team(team)
    service = CodingService()
    try:
        service.require_job(team_name, job_id)
        events = service.store.list_events(team_name, job_id)
    except ValueError as exc:
        _print_error(str(exc))
        raise typer.Exit(1)
    _output(
        {
            "teamName": team_name,
            "jobId": job_id,
            "events": [_dump(event) for event in events],
        },
        _coding_events_human,
    )


@coding_app.command("artifacts")
def coding_artifacts(
    job_id: str = typer.Argument(..., help="Coding job id"),
    team: Optional[str] = typer.Option(None, "--team", help="Team name (defaults from env)"),
):
    """List persisted artifact paths for a coding job."""
    from clawteam.coding import CodingService

    team_name = _resolve_coding_team(team)
    try:
        record = CodingService().require_job(team_name, job_id)
    except ValueError as exc:
        _print_error(str(exc))
        raise typer.Exit(1)
    _output(
        {
            "teamName": team_name,
            "jobId": job_id,
            "artifacts": _artifact_entries(_dump(record)),
        },
        _coding_artifacts_human,
    )


@coding_app.command("artifact")
def coding_artifact(
    job_id: str = typer.Argument(..., help="Coding job id"),
    name: str = typer.Option(..., "--name", help="Artifact name"),
    team: Optional[str] = typer.Option(None, "--team", help="Team name (defaults from env)"),
):
    """Show artifact metadata and content when the artifact is text."""
    from clawteam.coding import CodingService

    team_name = _resolve_coding_team(team)
    try:
        record = CodingService().require_job(team_name, job_id)
    except ValueError as exc:
        _print_error(str(exc))
        raise typer.Exit(1)
    artifact_path = (record.artifact_paths or {}).get(name)
    if not artifact_path:
        _print_error(f"Coding job '{job_id}' has no artifact named '{name}'.")
        raise typer.Exit(1)
    path = Path(artifact_path)
    exists = path.exists()
    is_binary = False
    content = None
    if exists:
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            is_binary = True
    payload = {
        "teamName": team_name,
        "jobId": job_id,
        "name": name,
        "path": str(path),
        "exists": exists,
        "sizeBytes": path.stat().st_size if exists else None,
        "isBinary": is_binary,
        "content": content,
    }
    _output(payload, _coding_artifact_human)


@coding_app.command("wait")
def coding_wait(
    job_id: str = typer.Argument(..., help="Coding job id"),
    team: Optional[str] = typer.Option(None, "--team", help="Team name (defaults from env)"),
    poll_interval: float = typer.Option(1.0, "--poll-interval", help="Seconds between polls"),
    timeout: Optional[float] = typer.Option(None, "--timeout", help="Max seconds to wait"),
):
    """Wait for a coding job to reach a terminal state using persisted job state."""
    from clawteam.coding import CodingService, TERMINAL_CODING_JOB_STATES

    team_name = _resolve_coding_team(team)
    service = CodingService()
    started_at = time.monotonic()
    while True:
        try:
            record = service.require_job(team_name, job_id)
        except ValueError as exc:
            _output({"error": str(exc)}, lambda d: console.print(f"[red]{d['error']}[/red]"))
            raise typer.Exit(1)
        if record.state in TERMINAL_CODING_JOB_STATES:
            _output(_dump(record), _coding_record_human)
            return
        if timeout is not None and (time.monotonic() - started_at) >= timeout:
            _output(_dump(record), _coding_record_human)
            raise typer.Exit(1)
        time.sleep(poll_interval)


@coding_app.command("callback-report")
def coding_callback_report(
    job_id: str = typer.Argument(..., help="Coding job id"),
    team: Optional[str] = typer.Option(None, "--team", help="Team name (defaults from env)"),
    task_id: Optional[str] = typer.Option(None, "--task-id", help="Override task id when the job record has none"),
    decision: str = typer.Option(..., "--decision", help="Worker decision: continue, report_progress, escalate, complete, blocked"),
    summary: Optional[str] = typer.Option(None, "--summary", help="Callback summary (defaults to normalized result or job summary)"),
    next_step: str = typer.Option("", "--next-step", help="Optional next-step summary"),
    escalation_reason: Optional[str] = typer.Option(None, "--escalation-reason", help="Required when decision is escalate"),
):
    """Persist a worker callback report via the durable coding/runtime-console path."""
    from clawteam.coding import CodingService, TERMINAL_CODING_JOB_STATES
    from clawteam.team.models import WorkerCodingCallbackReport, WorkerCodingDecision
    from clawteam.team.tasks import TaskStore

    team_name = _resolve_coding_team(team)
    service = CodingService()
    try:
        record = service.require_job(team_name, job_id)
    except ValueError as exc:
        _print_error(str(exc))
        raise typer.Exit(1)

    if record.state not in TERMINAL_CODING_JOB_STATES:
        _print_error(
            f"Coding job '{job_id}' is not terminal yet (state={record.state.value}); callback cannot be recorded."
        )
        raise typer.Exit(1)

    resolved_task_id = task_id or record.task_id
    if not resolved_task_id:
        _print_error(
            f"Coding job '{job_id}' has no task linkage; pass --task-id to record a callback."
        )
        raise typer.Exit(1)

    try:
        decision_value = WorkerCodingDecision(decision)
    except ValueError:
        _print_error(
            "Decision must be one of: continue, report_progress, escalate, complete, blocked."
        )
        raise typer.Exit(1)

    if decision_value == WorkerCodingDecision.escalate and not escalation_reason:
        _print_error("Escalation callbacks require --escalation-reason.")
        raise typer.Exit(1)

    result = service.store.load_result(team_name, job_id)
    resolved_summary = summary or (result.summary if result else "") or record.summary or f"Callback reported for {job_id}"
    report = WorkerCodingCallbackReport.from_coding_result(
        task_id=resolved_task_id,
        job_id=job_id,
        session_id=record.provider_session_ref,
        provider_session_id=record.provider_session_id,
        worker_name=record.worker_name,
        provider=record.provider.value,
        status=record.state.value,
        decision=decision_value,
        summary=resolved_summary,
        artifact_paths=record.artifact_paths,
        next_step=next_step,
        escalation_reason=escalation_reason,
    )
    try:
        updated_task = TaskStore(team_name).record_coding_callback(resolved_task_id, report)
    except ValueError as exc:
        _print_error(str(exc))
        raise typer.Exit(1)

    if updated_task is None:
        _print_error(f"Task '{resolved_task_id}' not found for team '{team_name}'.")
        raise typer.Exit(1)

    _output(
        {
            "teamName": team_name,
            "taskId": resolved_task_id,
            "jobId": job_id,
            "decision": report.decision.value,
            "summary": report.summary,
            "nextStep": report.next_step,
            "escalationReason": report.escalation_reason,
            "callback": _dump(report),
            "task": _dump(updated_task),
        },
        _coding_callback_report_human,
    )


@coding_app.command("cancel")
def coding_cancel(
    job_id: str = typer.Argument(..., help="Coding job id"),
    team: Optional[str] = typer.Option(None, "--team", help="Team name (defaults from env)"),
    reason: str = typer.Option("", "--reason", help="Cancellation reason"),
):
    """Cancel a queued or running coding job in durable state."""
    from clawteam.coding import CodingService

    team_name = _resolve_coding_team(team)
    try:
        record = CodingService().cancel_job(team_name, job_id, reason=reason)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)
    _output(_dump(record), _coding_record_human)


@coding_app.command("retry")
def coding_retry(
    job_id: str = typer.Argument(..., help="Source coding job id"),
    team: Optional[str] = typer.Option(None, "--team", help="Team name (defaults from env)"),
):
    """Retry a job from persisted request data after infrastructure failure."""
    from clawteam.coding import CodingService

    team_name = _resolve_coding_team(team)
    try:
        result = CodingService().retry_job(team_name, job_id)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)
    _output(_dump(result), _coding_result_human)


@coding_app.command("replay")
def coding_replay(
    job_id: str = typer.Argument(..., help="Source coding job id"),
    team: Optional[str] = typer.Option(None, "--team", help="Team name (defaults from env)"),
):
    """Replay a job from persisted request data with a fresh explicit execution."""
    from clawteam.coding import CodingService

    team_name = _resolve_coding_team(team)
    try:
        result = CodingService().replay_job(team_name, job_id)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)
    _output(_dump(result), _coding_result_human)


# Runtime Console session inspection lives under `clawteam coding session ...`
coding_session_app = typer.Typer(help="Provider session inspection commands")
coding_app.add_typer(coding_session_app, name="session")


@coding_session_app.command("list")
def coding_session_list(
    team: Optional[str] = typer.Option(None, "--team", help="Team name (defaults from env)"),
):
    """List durable provider session records for a team."""
    from clawteam.runtime_console import RuntimeConsoleStore

    team_name = _resolve_coding_team(team)
    sessions, read_faults = RuntimeConsoleStore().inspect_provider_sessions(team_name)
    _output(
        {
            "teamName": team_name,
            "sessions": [_dump(session) for session in sessions],
            "readFaults": read_faults,
        },
        _coding_session_list_human,
    )


@coding_session_app.command("show")
def coding_session_show(
    session_id: str = typer.Argument(..., help="Runtime provider session record id"),
    team: Optional[str] = typer.Option(None, "--team", help="Team name (defaults from env)"),
):
    """Show one durable provider session record."""
    from clawteam.runtime_console import RuntimeConsoleStore

    team_name = _resolve_coding_team(team)
    try:
        record = RuntimeConsoleStore().get_provider_session(team_name, session_id)
    except ValueError as exc:
        _print_error(str(exc))
        raise typer.Exit(1)
    if record is None:
        _print_error(f"Provider session '{session_id}' not found for team '{team_name}'.")
        raise typer.Exit(1)
    _output(_dump(record), _coding_session_human)


@coding_session_app.command("jobs")
def coding_session_jobs(
    session_id: str = typer.Argument(..., help="Runtime provider session record id"),
    team: Optional[str] = typer.Option(None, "--team", help="Team name (defaults from env)"),
):
    """List coding jobs linked to one provider session record."""
    from clawteam.coding import CodingJobStore

    team_name = _resolve_coding_team(team)
    jobs, faults = CodingJobStore().inspect_jobs(team_name)
    linked_jobs = [
        _dump(job)
        for job in sorted(jobs, key=lambda item: item.updated_at, reverse=True)
        if job.provider_session_ref == session_id
    ]
    _output(
        {
            "teamName": team_name,
            "sessionId": session_id,
            "jobs": linked_jobs,
            "faults": faults,
        },
        _coding_list_human,
    )


@coding_session_app.command("events")
def coding_session_events(
    session_id: str = typer.Argument(..., help="Runtime provider session record id"),
    team: Optional[str] = typer.Option(None, "--team", help="Team name (defaults from env)"),
):
    """Show runtime timeline events scoped to one provider session record."""
    from clawteam.runtime_console import RuntimeConsoleStore
    from clawteam.runtime_console.service import RuntimeConsoleService

    team_name = _resolve_coding_team(team)
    try:
        store = RuntimeConsoleStore()
        session = store.get_provider_session(team_name, session_id)
        if session is None:
            _print_error(f"Provider session '{session_id}' not found for team '{team_name}'.")
            raise typer.Exit(1)
        events, read_faults = RuntimeConsoleService(store=store).inspect_session_timeline(
            team_name=team_name,
            session_id=session_id,
        )
    except ValueError as exc:
        _print_error(str(exc))
        raise typer.Exit(1)
    _output(
        {
            "teamName": team_name,
            "sessionId": session_id,
            "events": [_dump(event) for event in events],
            "readFaults": read_faults,
        },
        _timeline_human,
    )


# ============================================================================
# Runtime Fault / Audit Commands
# ============================================================================

faults_app = typer.Typer(help="Runtime fault inspection commands")
app.add_typer(faults_app, name="faults")


@faults_app.command("list")
def faults_list(
    team: Optional[str] = typer.Option(None, "--team", help="Team name (defaults from env)"),
):
    """List explicit persisted runtime faults."""
    from clawteam.runtime_console import RuntimeConsoleStore

    team_name = _resolve_coding_team(team)
    faults, read_faults = RuntimeConsoleStore().inspect_faults(team_name)
    _output(
        {
            "teamName": team_name,
            "faults": [_dump(fault) for fault in faults],
            "readFaults": read_faults,
        },
        _faults_human,
    )


@faults_app.command("show")
def faults_show(
    fault_id: str = typer.Argument(..., help="Runtime fault id"),
    team: Optional[str] = typer.Option(None, "--team", help="Team name (defaults from env)"),
):
    """Show one explicit persisted runtime fault."""
    from clawteam.runtime_console import RuntimeConsoleStore

    team_name = _resolve_coding_team(team)
    try:
        fault = RuntimeConsoleStore().get_fault(team_name, fault_id)
    except ValueError as exc:
        _print_error(str(exc))
        raise typer.Exit(1)
    if fault is None:
        _print_error(f"Runtime fault '{fault_id}' not found for team '{team_name}'.")
        raise typer.Exit(1)
    _output(_dump(fault), _fault_human)


audit_app = typer.Typer(help="Runtime audit and timeline commands")
app.add_typer(audit_app, name="audit")


@audit_app.command("timeline")
def audit_timeline(
    team: Optional[str] = typer.Option(None, "--team", help="Team name (defaults from env)"),
):
    """Show the unified runtime timeline derived from durable runtime-console events."""
    from clawteam.runtime_console import RuntimeConsoleStore

    team_name = _resolve_coding_team(team)
    events, read_faults = RuntimeConsoleStore().inspect_timeline(team_name)
    _output(
        {
            "teamName": team_name,
            "events": [_dump(event) for event in events],
            "readFaults": read_faults,
        },
        _timeline_human,
    )


# ============================================================================
# Session Commands
# ============================================================================

session_app = typer.Typer(help="Session persistence for agent resume")
app.add_typer(session_app, name="session")


@session_app.command("save")
def session_save(
    team: str = typer.Argument(..., help="Team name"),
    session_id: str = typer.Option("", "--session-id", "-s", help="Claude Code session ID"),
    last_task: str = typer.Option("", "--last-task", help="Last task ID worked on"),
    agent: Optional[str] = typer.Option(None, "--agent", "-a", help="Agent name (default: from env)"),
):
    """Save agent session for later resume."""
    from clawteam.identity import AgentIdentity
    from clawteam.spawn.sessions import SessionStore

    agent_name = agent or AgentIdentity.from_env().agent_name
    store = SessionStore(team)
    session = store.save(
        agent_name=agent_name,
        session_id=session_id,
        last_task_id=last_task,
    )
    data = _dump(session)
    _output(data, lambda d: console.print(f"[green]OK[/green] Session saved for '{agent_name}'"))


@session_app.command("show")
def session_show(
    team: str = typer.Argument(..., help="Team name"),
    agent: Optional[str] = typer.Option(None, "--agent", "-a", help="Filter by agent"),
):
    """Show saved sessions."""
    from clawteam.spawn.sessions import SessionStore

    store = SessionStore(team)
    if agent:
        session = store.load(agent)
        if not session:
            _output({"error": f"No session for '{agent}'"}, lambda d: console.print(f"[dim]{d['error']}[/dim]"))
            return
        data = _dump(session)
        _output(data, lambda d: (
            console.print(f"Session: [cyan]{d.get('agentName', '')}[/cyan]"),
            console.print(f"  Session ID: {d.get('sessionId', '')}"),
            console.print(f"  Last task:  {d.get('lastTaskId', '')}"),
            console.print(f"  Saved at:   {d.get('savedAt', '')[:19]}"),
        ))
    else:
        sessions = store.list_sessions()
        data = [_dump(s) for s in sessions]

        def _human(items):
            if not items:
                console.print("[dim]No saved sessions[/dim]")
                return
            table = Table(title=f"Sessions — {team}")
            table.add_column("Agent", style="cyan")
            table.add_column("Session ID")
            table.add_column("Last Task", style="dim")
            table.add_column("Saved At", style="dim")
            for s in items:
                table.add_row(
                    s.get("agentName", ""),
                    s.get("sessionId", ""),
                    s.get("lastTaskId", ""),
                    (s.get("savedAt") or "")[:19],
                )
            console.print(table)

        _output(data, _human)


@session_app.command("clear")
def session_clear(
    team: str = typer.Argument(..., help="Team name"),
    agent: Optional[str] = typer.Option(None, "--agent", "-a", help="Agent name (default: all)"),
):
    """Clear saved sessions."""
    from clawteam.spawn.sessions import SessionStore

    store = SessionStore(team)
    if agent:
        if store.clear(agent):
            _output({"status": "cleared", "agent": agent}, lambda d: console.print(f"[green]OK[/green] Session cleared for '{agent}'"))
        else:
            _output({"status": "not_found", "agent": agent}, lambda d: console.print(f"[dim]No session for '{agent}'[/dim]"))
    else:
        sessions = store.list_sessions()
        count = 0
        for s in sessions:
            if store.clear(s.agent_name):
                count += 1
        _output({"status": "cleared", "count": count}, lambda d: console.print(f"[green]OK[/green] Cleared {count} session(s)"))


# ============================================================================
# Plan Commands
# ============================================================================

plan_app = typer.Typer(help="Plan management commands")
app.add_typer(plan_app, name="plan")


@plan_app.command("submit")
def plan_submit(
    team: str = typer.Argument(..., help="Team name"),
    agent: str = typer.Argument(..., help="Agent name submitting the plan"),
    plan: str = typer.Argument(..., help="Plan content or path to a file"),
    summary: str = typer.Option("", "--summary", "-s", help="Brief plan summary"),
):
    """Submit a plan for leader approval (triggers plan_approval_request)."""
    from clawteam.team.mailbox import MailboxManager
    from clawteam.team.manager import TeamManager
    from clawteam.team.plan import PlanManager

    plan_content = plan
    p = Path(plan)
    if p.exists() and p.is_file():
        plan_content = p.read_text(encoding="utf-8")

    leader_name = TeamManager.get_leader_name(team)
    if not leader_name:
        _output({"error": "No leader found"}, lambda d: console.print(f"[red]{d['error']}[/red]"))
        raise typer.Exit(1)

    mailbox = MailboxManager(team)
    pm = PlanManager(team, mailbox)
    plan_id = pm.submit_plan(agent_name=agent, leader_name=leader_name, plan_content=plan_content, summary=summary)

    _output(
        {"status": "submitted", "planId": plan_id, "agent": agent},
        lambda d: console.print(f"[green]OK[/green] Plan {d['planId']} submitted by {d['agent']}"),
    )


@plan_app.command("approve")
def plan_approve(
    team: str = typer.Argument(..., help="Team name"),
    plan_id: str = typer.Argument(..., help="Plan ID (requestId from plan_approval_request)"),
    agent: str = typer.Argument(..., help="Agent who submitted the plan (target_agent_id)"),
    feedback: str = typer.Option("", "--feedback", "-f", help="Optional feedback"),
):
    """Approve a submitted plan (approvePlan)."""
    from clawteam.identity import AgentIdentity
    from clawteam.team.mailbox import MailboxManager
    from clawteam.team.plan import PlanManager

    identity = AgentIdentity.from_env()
    mailbox = MailboxManager(team)
    pm = PlanManager(team, mailbox)
    pm.approve_plan(leader_name=identity.agent_name, plan_id=plan_id, agent_name=agent, feedback=feedback)

    _output(
        {"status": "approved", "planId": plan_id},
        lambda d: console.print(f"[green]OK[/green] Plan {plan_id} approved"),
    )


@plan_app.command("reject")
def plan_reject(
    team: str = typer.Argument(..., help="Team name"),
    plan_id: str = typer.Argument(..., help="Plan ID (requestId from plan_approval_request)"),
    agent: str = typer.Argument(..., help="Agent who submitted the plan (target_agent_id)"),
    feedback: str = typer.Option("", "--feedback", "-f", help="Rejection feedback"),
):
    """Reject a submitted plan (rejectPlan)."""
    from clawteam.identity import AgentIdentity
    from clawteam.team.mailbox import MailboxManager
    from clawteam.team.plan import PlanManager

    identity = AgentIdentity.from_env()
    mailbox = MailboxManager(team)
    pm = PlanManager(team, mailbox)
    pm.reject_plan(leader_name=identity.agent_name, plan_id=plan_id, agent_name=agent, feedback=feedback)

    _output(
        {"status": "rejected", "planId": plan_id},
        lambda d: console.print(f"[green]OK[/green] Plan {plan_id} rejected"),
    )


# ============================================================================
# Lifecycle Commands
# ============================================================================

lifecycle_app = typer.Typer(help="Agent lifecycle commands (shutdown protocol)")
app.add_typer(lifecycle_app, name="lifecycle")


@lifecycle_app.command("request-shutdown")
def lifecycle_request_shutdown(
    team: str = typer.Argument(..., help="Team name"),
    from_agent: str = typer.Argument(..., help="Requesting agent name"),
    to_agent: str = typer.Argument(..., help="Target agent name"),
    reason: str = typer.Option("", "--reason", "-r", help="Shutdown reason"),
):
    """Request an agent to shut down (requestShutdown)."""
    from clawteam.team.lifecycle import LifecycleManager
    from clawteam.team.mailbox import MailboxManager

    mailbox = MailboxManager(team)
    lm = LifecycleManager(team, mailbox)
    request_id = lm.request_shutdown(from_agent=from_agent, to_agent=to_agent, reason=reason)

    _output(
        {"status": "requested", "requestId": request_id, "from": from_agent, "to": to_agent},
        lambda d: console.print(f"[green]OK[/green] Shutdown request sent to '{to_agent}' (id: {request_id})"),
    )


@lifecycle_app.command("approve-shutdown")
def lifecycle_approve_shutdown(
    team: str = typer.Argument(..., help="Team name"),
    request_id: str = typer.Argument(..., help="Shutdown request ID"),
    agent: str = typer.Argument(..., help="Agent approving shutdown (self)"),
):
    """Approve a shutdown request (approveShutdown). Agent agrees to shut down."""
    from clawteam.identity import AgentIdentity
    from clawteam.team.lifecycle import LifecycleManager
    from clawteam.team.mailbox import MailboxManager

    identity = AgentIdentity.from_env()
    mailbox = MailboxManager(team)
    lm = LifecycleManager(team, mailbox)
    leader_name = identity.agent_name
    lm.approve_shutdown(agent_name=agent, request_id=request_id, requester_name=leader_name)

    _output(
        {"status": "approved", "requestId": request_id, "agent": agent},
        lambda d: console.print(f"[green]OK[/green] {agent} approved shutdown"),
    )


@lifecycle_app.command("reject-shutdown")
def lifecycle_reject_shutdown(
    team: str = typer.Argument(..., help="Team name"),
    request_id: str = typer.Argument(..., help="Shutdown request ID"),
    agent: str = typer.Argument(..., help="Agent rejecting shutdown"),
    reason: str = typer.Option("", "--reason", "-r", help="Rejection reason"),
):
    """Reject a shutdown request (rejectShutdown)."""
    from clawteam.identity import AgentIdentity
    from clawteam.team.lifecycle import LifecycleManager
    from clawteam.team.mailbox import MailboxManager

    identity = AgentIdentity.from_env()
    mailbox = MailboxManager(team)
    lm = LifecycleManager(team, mailbox)
    lm.reject_shutdown(agent_name=agent, request_id=request_id, requester_name=identity.agent_name, reason=reason)

    _output(
        {"status": "rejected", "requestId": request_id, "agent": agent, "reason": reason},
        lambda d: console.print(f"[green]OK[/green] {agent} rejected shutdown"),
    )


@lifecycle_app.command("idle")
def lifecycle_idle(
    team: str = typer.Argument(..., help="Team name"),
    last_task: Optional[str] = typer.Option(None, "--last-task", help="Last task ID worked on"),
    task_status: Optional[str] = typer.Option(None, "--task-status", help="Status of last task"),
):
    """Send idle notification to leader."""
    from clawteam.identity import AgentIdentity
    from clawteam.team.lifecycle import LifecycleManager
    from clawteam.team.mailbox import MailboxManager
    from clawteam.team.manager import TeamManager

    identity = AgentIdentity.from_env()
    team_name = team
    leader_name = TeamManager.get_leader_name(team_name)
    if not leader_name:
        _output({"error": "No leader found"}, lambda d: console.print(f"[red]{d['error']}[/red]"))
        raise typer.Exit(1)

    mailbox = MailboxManager(team_name)
    lm = LifecycleManager(team_name, mailbox)
    lm.send_idle(
        agent_name=identity.agent_name,
        agent_id=identity.agent_id,
        leader_name=leader_name,
        last_task=last_task or "",
        task_status=task_status or "",
    )

    _output(
        {"status": "idle_sent", "agent": identity.agent_name, "leader": leader_name},
        lambda d: console.print(f"[green]OK[/green] Idle notification sent to '{leader_name}'"),
    )


@lifecycle_app.command("on-exit")
def lifecycle_on_exit(
    team: str = typer.Option(..., "--team", "-t", help="Team name"),
    agent: str = typer.Option(..., "--agent", "-n", help="Agent name"),
):
    """Handle agent process exit: clean up session and reset in_progress tasks.

    This is called automatically as a post-exit hook when an agent process terminates.
    """
    import subprocess

    from clawteam.spawn.registry import get_agent_info
    from clawteam.spawn.sessions import SessionStore
    from clawteam.team.mailbox import MailboxManager
    from clawteam.team.manager import TeamManager
    from clawteam.team.models import TaskStatus
    from clawteam.team.tasks import TaskStore

    # Always clean up the agent's session file, regardless of task status.
    # Without this, session files accumulate indefinitely under
    # ~/.clawteam/sessions/{team}/ after every agent exit.
    SessionStore(team).clear(agent)

    store = TaskStore(team)
    tasks, read_faults = store.inspect_tasks()

    # Find this agent's in_progress tasks and reset them
    abandoned = [
        t for t in tasks
        if t.owner == agent and t.status == TaskStatus.in_progress
    ]

    if not abandoned:
        _output(
            {
                "status": "agent_exited",
                "agent": agent,
                "abandoned_tasks": [],
                "readFaults": read_faults,
            },
            lambda d: (
                console.print(
                    f"[yellow]Agent '{agent}' exited.[/yellow] "
                    "No in-progress tasks required recovery."
                ),
                _print_read_faults(d),
            ),
        )
        return

    for t in abandoned:
        store.update(t.id, status=TaskStatus.pending)

    exit_detail = ""
    info = get_agent_info(team, agent)
    if info and info.get("backend") == "tmux" and info.get("tmux_target"):
        try:
            pane = subprocess.run(
                ["tmux", "capture-pane", "-p", "-t", info["tmux_target"], "-S", "-80"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if pane.returncode == 0 and pane.stdout.strip():
                lines = [line.rstrip() for line in pane.stdout.splitlines() if line.strip()]
                tail = " | ".join(lines[-6:])
                if tail:
                    exit_detail = f" Last output: {tail[:700]}"
        except (subprocess.TimeoutExpired, OSError):
            exit_detail = ""

    # Notify leader
    leader_name = TeamManager.get_leader_name(team)
    if leader_name:
        mailbox = MailboxManager(team)
        task_subjects = ", ".join(t.subject for t in abandoned)
        mailbox.send(
            from_agent=agent,
            to=leader_name,
            content=f"Agent '{agent}' exited unexpectedly. "
                    f"Reset {len(abandoned)} task(s) to pending: {task_subjects}.{exit_detail}",
        )

    _output(
        {
            "status": "agent_exited",
            "agent": agent,
            "abandoned_tasks": [{"id": t.id, "subject": t.subject} for t in abandoned],
            "readFaults": read_faults,
        },
        lambda d: (
            console.print(
                f"[yellow]Agent '{agent}' exited.[/yellow] "
                f"Reset {len(d['abandoned_tasks'])} task(s) to pending."
            ),
            _print_read_faults(d),
        ),
    )


@lifecycle_app.command("check-zombies")
def lifecycle_check_zombies(
    team: str = typer.Option(..., "--team", "-t", help="Team name"),
    max_hours: float = typer.Option(2.0, "--max-hours", help="Warn if agent has been running longer than this many hours"),
):
    """Warn about agents that have been running unusually long (possible zombies).

    Agents that never called on-exit will accumulate as background processes.
    This command helps identify them so you can decide whether to stop them manually.
    """
    from clawteam.spawn.registry import list_zombie_agents

    zombies = list_zombie_agents(team, max_hours=max_hours)

    if not zombies:
        _output(
            {"team": team, "zombies": []},
            lambda d: console.print(f"[green]✓[/green] No zombie agents detected for team '{team}'"),
        )
        return

    def _fmt(d: dict) -> None:
        console.print(
            f"[bold yellow]⚠ {len(d['zombies'])} zombie agent(s) detected in team '{team}':[/bold yellow]"
        )
        for z in d["zombies"]:
            console.print(
                f"  [yellow]• {z['agent_name']}[/yellow]  "
                f"pid={z['pid']}  backend={z['backend']}  "
                f"running={z['running_hours']}h"
            )
        console.print(
            "\n[dim]These processes did not call lifecycle on-exit. "
            "Inspect them manually or run: clawteam lifecycle stop-agent --team <team> --agent <name>[/dim]"
        )

    _output({"team": team, "zombies": zombies}, _fmt)
    raise typer.Exit(1)


# ============================================================================
# Spawn Command
# ============================================================================

@app.command("spawn")
def spawn_agent(
    backend: Optional[str] = typer.Argument(None, help="Backend: tmux (default) or subprocess"),
    command: list[str] = typer.Argument(None, help="Command and arguments to run (default: claude)"),
    team: Optional[str] = typer.Option(None, "--team", "-t", help="Team name"),
    agent_name: Optional[str] = typer.Option(None, "--agent-name", "-n", help="Agent name"),
    agent_type: str = typer.Option("general-purpose", "--agent-type", help="Agent type"),
    task: Optional[str] = typer.Option(None, "--task", help="Task to assign (becomes the agent's initial prompt)"),
    workspace: Optional[bool] = typer.Option(None, "--workspace/--no-workspace", "-w", help="Create isolated git worktree (default: auto)"),
    repo: Optional[str] = typer.Option(None, "--repo", help="Git repo path (default: cwd)"),
    workspace_base_ref: Optional[str] = typer.Option(None, "--workspace-base-ref", help="Explicit git base ref for workspace creation"),
    skip_permissions: Optional[bool] = typer.Option(None, "--skip-permissions/--no-skip-permissions", help="Skip tool approval for claude (default: from config, true)"),
    resume: bool = typer.Option(False, "--resume", "-r", help="Resume previous session if available"),
):
    """Spawn a new agent process with identity + task as its initial prompt.

    Defaults: tmux backend, openclaw command, git worktree isolation, skip-permissions on.
    """
    from clawteam.config import get_effective
    from clawteam.spawn import get_backend

    # Resolve defaults from config
    if backend is None:
        backend, _ = get_effective("default_backend")
        backend = backend or "tmux"
    if not command:
        command = ["openclaw"]

    _team = team or "default"
    _name = agent_name or f"agent-{uuid.uuid4().hex[:6]}"
    _id = uuid.uuid4().hex[:12]

    # Resolve skip_permissions from config
    if skip_permissions is None:
        sp_val, _ = get_effective("skip_permissions")
        skip_permissions = str(sp_val).lower() not in ("false", "0", "no", "")

    try:
        be = get_backend(backend)
    except ValueError as e:
        _output({"error": str(e)}, lambda d: console.print(f"[red]{d['error']}[/red]"))
        raise typer.Exit(1)

    # Workspace: resolve from flag or config (default: auto)
    cwd = _default_spawn_cwd(repo)
    ws_branch = ""
    ws_mode = ""
    ws_mgr = None
    workspace_payload = {
        "status": "disabled",
        "workspaceMode": "never",
        "requestedPath": cwd,
        "repoRoot": None,
        "isGitRepo": False,
        "headValid": False,
        "currentBranch": None,
        "resolvedBaseRef": None,
        "baseRefSource": None,
        "worktreeCapable": False,
        "reason": None,
        "detail": None,
        "recommendations": [],
        "gitError": None,
        "recommendedSpawnMode": "no-workspace",
    }
    if workspace is None:
        ws_mode, _ = get_effective("workspace")
        ws_mode = ws_mode or "auto"
        workspace = ws_mode in ("auto", "always")
        if workspace_base_ref is None:
            base_ref_value, _ = get_effective("workspace_base_ref")
            workspace_base_ref = base_ref_value or None
    elif workspace is True:
        ws_mode = "always"
    elif workspace is False:
        ws_mode = "never"

    if workspace:
        from clawteam.workspace import get_workspace_manager, inspect_workspace
        from clawteam.workspace.git import GitError

        diagnostic = inspect_workspace(repo, workspace_mode=ws_mode, base_ref=workspace_base_ref)
        workspace_payload = diagnostic.to_payload()
        if diagnostic.status == "ready":
            ws_mgr = get_workspace_manager(repo, base_ref=diagnostic.resolved_base_ref)
            if ws_mgr is None:
                workspace_payload.update(
                    {
                        "status": "failed",
                        "reason": "workspace_manager_unavailable",
                        "detail": "Workspace manager could not be initialized after a successful preflight.",
                        "recommendedSpawnMode": "no-workspace",
                    }
                )
                _output(
                    {"error": "workspace_preflight_failed", "workspace": workspace_payload},
                    lambda d: _print_workspace_diagnostic(d["workspace"]),
                )
                raise typer.Exit(1)
            try:
                ws_info = ws_mgr.create_workspace(team_name=_team, agent_name=_name, agent_id=_id)
            except GitError as exc:
                workspace_payload.update(
                    {
                        "status": "failed",
                        "reason": "workspace_create_failed",
                        "detail": "Workspace preflight succeeded, but worktree creation failed.",
                        "gitError": str(exc),
                        "recommendedSpawnMode": "no-workspace",
                    }
                )
                _output(
                    {"error": "workspace_create_failed", "workspace": workspace_payload},
                    lambda d: _print_workspace_diagnostic(d["workspace"]),
                )
                raise typer.Exit(1)
            cwd = _workspace_cwd_from_info(repo, ws_info)
            ws_branch = ws_info.branch_name
            workspace_payload.update(
                {
                    "status": "created",
                    "worktreePath": ws_info.worktree_path,
                    "branch": ws_info.branch_name,
                    "repoRoot": ws_info.repo_root,
                    "resolvedBaseRef": ws_info.base_branch,
                    "worktreeCapable": True,
                    "recommendedSpawnMode": "workspace",
                }
            )
            if not _json_output:
                console.print(f"[dim]Workspace: {cwd} (branch: {ws_branch})[/dim]")
        elif ws_mode == "auto":
            if not _json_output:
                _print_workspace_diagnostic(workspace_payload)
        else:
            _output(
                {"error": "workspace_preflight_failed", "workspace": workspace_payload},
                lambda d: _print_workspace_diagnostic(d["workspace"]),
            )
            raise typer.Exit(1)

    # Build prompt: identity + task + clawteam coordination guide
    prompt = None
    if task:
        from clawteam.spawn.prompt import build_agent_prompt
        from clawteam.team.manager import TeamManager

        leader_name = TeamManager.get_leader_name(_team) or "leader"
        prompt = build_agent_prompt(
            agent_name=_name,
            agent_id=_id,
            agent_type=agent_type,
            team_name=_team,
            leader_name=leader_name,
            task=task,
            user=os.environ.get("CLAWTEAM_USER", ""),
            workspace_dir=cwd if ws_branch else "",
            workspace_branch=ws_branch,
            memory_scope=f"custom:team-{_team}",
        )

    # Session resume: inject --resume flag for claude commands
    if resume:
        from clawteam.spawn.sessions import SessionStore
        session_store = SessionStore(_team)
        session = session_store.load(_name)
        if session and session.session_id:
            # Add --resume to claude command
            if command and command[0] in ("claude",):
                command = list(command) + ["--resume", session.session_id]
                console.print(f"[dim]Resuming session: {session.session_id}[/dim]")
            if prompt:
                prompt += "\nYou are resuming a previous session."

    # Auto-register agent as team member
    from clawteam.team.manager import TeamManager
    member_added = False
    try:
        TeamManager.add_member(
            team_name=_team,
            member_name=_name,
            agent_id=_id,
            agent_type=agent_type,
            user=os.environ.get("CLAWTEAM_USER", ""),
        )
        member_added = True
    except ValueError:
        pass  # already a member, ignore

    try:
        result = be.spawn(
            command=command,
            agent_name=_name,
            agent_id=_id,
            agent_type=agent_type,
            team_name=_team,
            prompt=prompt,
            cwd=cwd,
            skip_permissions=skip_permissions,
        )
    except Exception as exc:
        if member_added:
            TeamManager.remove_member(_team, _name)
        if ws_mgr is not None and ws_branch:
            try:
                ws_mgr.cleanup_workspace(_team, _name, auto_checkpoint=False)
            except Exception:
                pass
        workspace_payload.update(
            {
                "status": "failed",
                "reason": "workspace_create_failed" if ws_branch else workspace_payload.get("reason"),
                "detail": str(exc),
            }
        )
        _output(
            {"error": "spawn_failed", "message": str(exc), "workspace": workspace_payload},
            lambda d: (console.print(f"[red]{d['message']}[/red]"), _print_workspace_diagnostic(d["workspace"])),
        )
        raise typer.Exit(1)

    if result.startswith("Error"):
        if member_added:
            TeamManager.remove_member(_team, _name)
        if ws_mgr is not None and ws_branch:
            try:
                ws_mgr.cleanup_workspace(_team, _name, auto_checkpoint=False)
            except Exception:
                pass
        _output(
            {"error": result, "workspace": workspace_payload},
            lambda d: (console.print(f"[red]{d['error']}[/red]"), _print_workspace_diagnostic(d["workspace"])),
        )
        raise typer.Exit(1)

    _output(
        {
            "status": "spawned",
            "backend": backend,
            "agentName": _name,
            "agentId": _id,
            "message": result,
            "workspace": workspace_payload,
        },
        lambda d: console.print(f"[green]OK[/green] {d['message']}"),
    )


# ============================================================================
# Identity Commands
# ============================================================================

identity_app = typer.Typer(help="Agent identity commands")
app.add_typer(identity_app, name="identity")


@identity_app.command("show")
def identity_show():
    """Show current agent identity (from environment variables)."""
    from clawteam.identity import AgentIdentity

    identity = AgentIdentity.from_env()
    data = {
        "agentId": identity.agent_id,
        "agentName": identity.agent_name,
        "user": identity.user,
        "agentType": identity.agent_type,
        "teamName": identity.team_name,
        "isLeader": identity.is_leader,
        "planModeRequired": identity.plan_mode_required,
    }

    def _human(d):
        console.print(f"Agent ID:   {d['agentId']}")
        console.print(f"Agent Name: {d['agentName']}")
        console.print(f"User:       {d['user'] or '(none)'}")
        console.print(f"Agent Type: {d['agentType']}")
        console.print(f"Team:       {d['teamName'] or '(none)'}")
        console.print(f"Is Leader:  {d['isLeader']}")
        console.print(f"Plan Mode:  {d['planModeRequired']}")

    _output(data, _human)


@identity_app.command("set")
def identity_set(
    agent_id: Optional[str] = typer.Option(None, "--agent-id", help="Agent ID"),
    agent_name: Optional[str] = typer.Option(None, "--agent-name", help="Agent name"),
    agent_type: Optional[str] = typer.Option(None, "--agent-type", help="Agent type"),
    team: Optional[str] = typer.Option(None, "--team", help="Team name"),
):
    """Print shell export commands to set identity environment variables."""
    lines = []
    if agent_id:
        lines.append(f'export CLAWTEAM_AGENT_ID="{agent_id}"')
    if agent_name:
        lines.append(f'export CLAWTEAM_AGENT_NAME="{agent_name}"')
    if agent_type:
        lines.append(f'export CLAWTEAM_AGENT_TYPE="{agent_type}"')
    if team:
        lines.append(f'export CLAWTEAM_TEAM_NAME="{team}"')

    if not lines:
        console.print("[yellow]No options specified. Use --agent-id, --agent-name, --agent-type, --team[/yellow]")
        raise typer.Exit(1)

    output = "\n".join(lines)
    if _json_output:
        print(json.dumps({"exports": lines}))
    else:
        console.print("Run the following to set your identity:\n")
        console.print(output)
        console.print(f"\nOr use: eval $(clawteam identity set {' '.join(sys.argv[3:])})")


# ============================================================================
# Board Commands
# ============================================================================

board_app = typer.Typer(help="Team dashboard and kanban board.")
app.add_typer(board_app, name="board")


@board_app.command("show")
def board_show(
    team: str = typer.Argument(..., help="Team name"),
):
    """Show detailed kanban board for a single team."""
    from clawteam.board.collector import BoardCollector
    from clawteam.board.renderer import BoardRenderer

    collector = BoardCollector()
    try:
        data = collector.collect_team(team)
    except ValueError as e:
        _output({"error": str(e)}, lambda d: console.print(f"[red]{d['error']}[/red]"))
        raise typer.Exit(1)

    _output(data, lambda d: BoardRenderer(console).render_team_board(d))


@board_app.command("overview")
def board_overview():
    """Show overview of all teams."""
    from clawteam.board.collector import BoardCollector
    from clawteam.board.renderer import BoardRenderer

    collector = BoardCollector()
    teams = collector.collect_overview()

    _output(teams, lambda d: BoardRenderer(console).render_overview(d))


@board_app.command("live")
def board_live(
    team: str = typer.Argument(..., help="Team name"),
    interval: float = typer.Option(2.0, "--interval", "-i", help="Refresh interval in seconds"),
):
    """Live-refreshing kanban board. Ctrl+C to stop."""
    from clawteam.board.collector import BoardCollector
    from clawteam.board.renderer import BoardRenderer

    collector = BoardCollector()

    # Validate team exists before starting live mode
    try:
        collector.collect_team(team)
    except ValueError as e:
        _output({"error": str(e)}, lambda d: console.print(f"[red]{d['error']}[/red]"))
        raise typer.Exit(1)

    if not _json_output:
        console.print(f"Live board for '{team}' (interval: {interval}s). Ctrl+C to stop.")

    renderer = BoardRenderer(console)
    renderer.render_team_board_live(collector, team, interval=interval)


@board_app.command("serve")
def board_serve(
    team: Optional[str] = typer.Argument(None, help="Team name (optional, shows all if omitted)"),
    port: int = typer.Option(8080, "--port", "-p", help="HTTP server port"),
    host: str = typer.Option("127.0.0.1", "--host", help="Bind address"),
    interval: float = typer.Option(2.0, "--interval", "-i", help="SSE push interval in seconds"),
):
    """Start the convenience Web UI; CLI/Rich board and persisted state remain authoritative."""
    from clawteam.board.server import serve

    console.print(f"Starting Web UI on http://{host}:{port}")
    if team:
        console.print(f"Default team: {team}")
    console.print("Press Ctrl+C to stop.")
    serve(host=host, port=port, default_team=team or "", interval=interval)


@board_app.command("attach")
def board_attach(
    team: str = typer.Argument(..., help="Team name"),
):
    """Attach to tmux session with all agent windows tiled side by side.

    Merges all agent tmux windows into a single tiled view so you can
    watch every agent working simultaneously.
    """
    from clawteam.spawn.tmux_backend import TmuxBackend

    result = TmuxBackend.attach_all(team)
    if result.startswith("Error"):
        console.print(f"[red]{result}[/red]")
        raise typer.Exit(1)
    console.print(f"[green]OK[/green] {result}")


# ============================================================================
# Workspace Commands
# ============================================================================

workspace_app = typer.Typer(help="Git worktree workspace management")
app.add_typer(workspace_app, name="workspace")


@workspace_app.command("list")
def workspace_list(
    team: str = typer.Argument(..., help="Team name"),
    repo: Optional[str] = typer.Option(None, "--repo", help="Git repo path"),
):
    """List all active worktree workspaces for a team."""
    from clawteam.workspace import get_workspace_manager

    ws_mgr = get_workspace_manager(repo)
    if ws_mgr is None:
        _output({"error": "Not in a git repo"}, lambda d: console.print(f"[red]{d['error']}[/red]"))
        raise typer.Exit(1)

    workspaces = ws_mgr.list_workspaces(team)
    if _json_output:
        _output(
            {"workspaces": [w.model_dump() for w in workspaces]},
            lambda d: None,
        )
        return

    if not workspaces:
        console.print(f"No active workspaces for team '{team}'.")
        return

    table = Table(title=f"Workspaces — {team}")
    table.add_column("Agent")
    table.add_column("Branch")
    table.add_column("Path")
    table.add_column("Created")
    for ws in workspaces:
        table.add_row(ws.agent_name, ws.branch_name, ws.worktree_path, ws.created_at[:19])
    console.print(table)


@workspace_app.command("checkpoint")
def workspace_checkpoint(
    team: str = typer.Argument(..., help="Team name"),
    agent: str = typer.Argument(..., help="Agent name"),
    repo: Optional[str] = typer.Option(None, "--repo", help="Git repo path"),
    message: Optional[str] = typer.Option(None, "--message", "-m", help="Commit message"),
):
    """Create a checkpoint (auto-commit) for an agent's workspace."""
    from clawteam.workspace import get_workspace_manager

    ws_mgr = get_workspace_manager(repo)
    if ws_mgr is None:
        console.print("[red]Not in a git repo.[/red]")
        raise typer.Exit(1)

    committed = ws_mgr.checkpoint(team, agent, message)
    if committed:
        _output(
            {"status": "checkpoint_created", "team": team, "agent": agent},
            lambda d: console.print(f"[green]OK[/green] Checkpoint created for '{agent}'."),
        )
    else:
        _output(
            {"status": "no_changes", "team": team, "agent": agent},
            lambda d: console.print(f"[dim]No changes to checkpoint for '{agent}'.[/dim]"),
        )


@workspace_app.command("merge")
def workspace_merge(
    team: str = typer.Argument(..., help="Team name"),
    agent: str = typer.Argument(..., help="Agent name"),
    repo: Optional[str] = typer.Option(None, "--repo", help="Git repo path"),
    target: Optional[str] = typer.Option(None, "--target", help="Target branch (default: base branch)"),
    no_cleanup: bool = typer.Option(False, "--no-cleanup", help="Keep worktree after merge"),
):
    """Merge an agent's workspace branch back to the base branch."""
    from clawteam.workspace import get_workspace_manager

    ws_mgr = get_workspace_manager(repo)
    if ws_mgr is None:
        console.print("[red]Not in a git repo.[/red]")
        raise typer.Exit(1)

    success, output = ws_mgr.merge_workspace(team, agent, target, cleanup_after=not no_cleanup)
    if success:
        _output(
            {"status": "merged", "team": team, "agent": agent, "output": output},
            lambda d: console.print(f"[green]OK[/green] Merged '{agent}' workspace.\n{output}"),
        )
    else:
        _output(
            {"status": "merge_failed", "team": team, "agent": agent, "output": output},
            lambda d: console.print(f"[red]Merge failed[/red] for '{agent}':\n{output}"),
        )
        raise typer.Exit(1)


@workspace_app.command("cleanup")
def workspace_cleanup(
    team: str = typer.Argument(..., help="Team name"),
    agent: Optional[str] = typer.Option(None, "--agent", "-a", help="Agent name (all if omitted)"),
    repo: Optional[str] = typer.Option(None, "--repo", help="Git repo path"),
):
    """Clean up worktree workspace(s) — removes worktree and branch."""
    from clawteam.workspace import get_workspace_manager

    ws_mgr = get_workspace_manager(repo)
    if ws_mgr is None:
        console.print("[red]Not in a git repo.[/red]")
        raise typer.Exit(1)

    if agent:
        ok = ws_mgr.cleanup_workspace(team, agent)
        if ok:
            console.print(f"[green]OK[/green] Cleaned up workspace for '{agent}'.")
        else:
            console.print(f"[yellow]No workspace found for '{agent}'.[/yellow]")
    else:
        count = ws_mgr.cleanup_team(team)
        console.print(f"[green]OK[/green] Cleaned up {count} workspace(s) for team '{team}'.")


@workspace_app.command("status")
def workspace_status(
    team: str = typer.Argument(..., help="Team name"),
    agent: str = typer.Argument(..., help="Agent name"),
    repo: Optional[str] = typer.Option(None, "--repo", help="Git repo path"),
):
    """Show git diff stat for an agent's workspace."""
    from clawteam.workspace import get_workspace_manager, git

    ws_mgr = get_workspace_manager(repo)
    if ws_mgr is None:
        console.print("[red]Not in a git repo.[/red]")
        raise typer.Exit(1)

    ws = ws_mgr.get_workspace(team, agent)
    if ws is None:
        console.print(f"[yellow]No workspace found for '{agent}'.[/yellow]")
        raise typer.Exit(1)

    stat = git.diff_stat(Path(ws.worktree_path))
    console.print(f"[bold]Workspace status — {agent}[/bold] (branch: {ws.branch_name})")
    console.print(stat)


@workspace_app.command("doctor")
def workspace_doctor(
    repo: Optional[str] = typer.Option(None, "--repo", help="Git repo path (default: cwd)"),
    workspace_mode: str = typer.Option("auto", "--workspace-mode", help="Interpretation mode: auto or always"),
    workspace_base_ref: Optional[str] = typer.Option(None, "--workspace-base-ref", help="Explicit base ref override"),
):
    """Diagnose whether a repository is safe for workspace-backed spawn."""
    from clawteam.workspace import inspect_workspace

    report = inspect_workspace(repo, workspace_mode=workspace_mode, base_ref=workspace_base_ref)
    payload = report.to_payload()
    if _json_output:
        _output(payload)
        return
    _print_workspace_diagnostic(payload)


# ============================================================================
# Template Commands
# ============================================================================

template_app = typer.Typer(help="Template management")
app.add_typer(template_app, name="template")


@template_app.command("list")
def template_list():
    """List all available templates (builtin + user)."""
    from clawteam.templates import list_templates

    templates = list_templates()

    def _human(data):
        if not data:
            console.print("[dim]No templates found[/dim]")
            return
        table = Table(title="Templates")
        table.add_column("Name", style="cyan")
        table.add_column("Description")
        table.add_column("Source", style="dim")
        for t in data:
            table.add_row(t["name"], t["description"], t["source"])
        console.print(table)

    _output(templates, _human)


@template_app.command("show")
def template_show(
    name: str = typer.Argument(..., help="Template name"),
):
    """Show details of a template."""
    from clawteam.templates import load_template

    try:
        tmpl = load_template(name)
    except FileNotFoundError as e:
        _output({"error": str(e)}, lambda d: console.print(f"[red]{d['error']}[/red]"))
        raise typer.Exit(1)

    data = json.loads(tmpl.model_dump_json(by_alias=True))

    def _human(_data):
        console.print(f"[bold cyan]{tmpl.name}[/bold cyan] — {tmpl.description}")
        console.print(f"  Command: {' '.join(tmpl.command)}")
        console.print(f"  Backend: {tmpl.backend}")
        console.print()

        console.print("[bold]Leader:[/bold]")
        console.print(f"  {tmpl.leader.name} (type: {tmpl.leader.type})")
        console.print()

        if tmpl.agents:
            table = Table(title="Agents")
            table.add_column("Name", style="cyan")
            table.add_column("Type")
            for a in tmpl.agents:
                table.add_row(a.name, a.type)
            console.print(table)

        if tmpl.tasks:
            table = Table(title="Tasks")
            table.add_column("Subject")
            table.add_column("Owner", style="cyan")
            for t in tmpl.tasks:
                table.add_row(t.subject, t.owner)
            console.print(table)

    _output(data, _human)


# ============================================================================
# Launch Command
# ============================================================================

@app.command("launch")
def launch_team(
    template: str = typer.Argument(..., help="Template name (e.g., hedge-fund)"),
    goal: str = typer.Option("", "--goal", "-g", help="Project goal injected into agent prompts"),
    backend: Optional[str] = typer.Option(None, "--backend", "-b", help="Override backend"),
    team_name: Optional[str] = typer.Option(None, "--team-name", "-t", help="Override team name"),
    workspace: bool = typer.Option(False, "--workspace/--no-workspace", "-w"),
    repo: Optional[str] = typer.Option(None, "--repo", help="Git repo path"),
    workspace_base_ref: Optional[str] = typer.Option(None, "--workspace-base-ref", help="Explicit git base ref for workspace creation"),
    command_override: Optional[list[str]] = typer.Option(None, "--command", help="Override agent command"),
):
    """Launch a full agent team from a template with one command."""
    import os as _os

    from clawteam.spawn import get_backend
    from clawteam.spawn.prompt import build_agent_prompt
    from clawteam.team.manager import TeamManager
    from clawteam.team.tasks import TaskStore
    from clawteam.templates import TemplateDef, load_template, render_task

    # 1. Load template
    try:
        tmpl: TemplateDef = load_template(template)
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    # 2. Determine team name
    t_name = team_name or f"{tmpl.name}-{uuid.uuid4().hex[:6]}"
    be_name = backend or tmpl.backend
    cmd = command_override or tmpl.command

    # 3. Create team
    leader_id = uuid.uuid4().hex[:12]
    try:
        TeamManager.create_team(
            name=t_name,
            leader_name=tmpl.leader.name,
            leader_id=leader_id,
            description=tmpl.description,
            user=_os.environ.get("CLAWTEAM_USER", ""),
        )
    except ValueError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)

    # 4. Add members
    agent_ids: dict[str, str] = {tmpl.leader.name: leader_id}
    for agent in tmpl.agents:
        aid = uuid.uuid4().hex[:12]
        agent_ids[agent.name] = aid
        TeamManager.add_member(
            team_name=t_name,
            member_name=agent.name,
            agent_id=aid,
            agent_type=agent.type,
            user=_os.environ.get("CLAWTEAM_USER", ""),
        )

    # 5. Create tasks
    ts = TaskStore(t_name)
    for task_def in tmpl.tasks:
        ts.create(
            subject=task_def.subject,
            description=task_def.description,
            owner=task_def.owner,
        )

    # 6. Get backend
    try:
        be = get_backend(be_name)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    # 7. Workspace setup (optional)
    ws_mgr = None
    if workspace:
        from clawteam.workspace import get_workspace_manager, inspect_workspace

        report = inspect_workspace(repo, workspace_mode="always", base_ref=workspace_base_ref)
        if report.status != "ready":
            _print_workspace_diagnostic(report.to_payload())
            raise typer.Exit(1)
        ws_mgr = get_workspace_manager(repo, base_ref=report.resolved_base_ref)
        if ws_mgr is None:
            console.print("[red]Workspace manager unavailable for the requested repository.[/red]")
            raise typer.Exit(1)

    # 8. Spawn all agents (leader first, then workers)
    all_agents = [tmpl.leader] + list(tmpl.agents)
    spawned: list[dict[str, str]] = []

    for agent in all_agents:
        a_id = agent_ids[agent.name]
        a_cmd = agent.command or cmd

        # Variable substitution
        rendered = render_task(
            agent.task,
            goal=goal,
            team_name=t_name,
            agent_name=agent.name,
        )

        # Workspace
        cwd = _default_spawn_cwd(repo)
        ws_branch = ""
        if ws_mgr:
            ws_info = ws_mgr.create_workspace(
                team_name=t_name, agent_name=agent.name, agent_id=a_id,
            )
            cwd = _workspace_cwd_from_info(repo, ws_info)
            ws_branch = ws_info.branch_name

        # Build prompt
        prompt = build_agent_prompt(
            agent_name=agent.name,
            agent_id=a_id,
            agent_type=agent.type,
            team_name=t_name,
            leader_name=tmpl.leader.name,
            task=rendered,
            user=_os.environ.get("CLAWTEAM_USER", ""),
            workspace_dir=cwd if ws_branch else "",
            workspace_branch=ws_branch,
            memory_scope=f"custom:team-{t_name}",
        )

        # Resolve skip_permissions from config
        from clawteam.config import get_effective
        sp_val, _ = get_effective("skip_permissions")
        _skip = str(sp_val).lower() not in ("false", "0", "no", "")

        result = be.spawn(
            command=a_cmd,
            agent_name=agent.name,
            agent_id=a_id,
            agent_type=agent.type,
            team_name=t_name,
            prompt=prompt,
            cwd=cwd,
            skip_permissions=_skip,
        )
        spawned.append({"name": agent.name, "id": a_id, "type": agent.type, "result": result})

    # 9. Output summary
    out = {
        "status": "launched",
        "team": t_name,
        "template": tmpl.name,
        "backend": be_name,
        "agents": [{"name": s["name"], "id": s["id"], "type": s["type"]} for s in spawned],
    }

    def _human(_data):
        console.print(f"\n[green bold]Team '{t_name}' launched from template '{tmpl.name}'[/green bold]\n")
        table = Table(title="Agents")
        table.add_column("Name", style="cyan")
        table.add_column("Type")
        table.add_column("ID", style="dim")
        for s in spawned:
            table.add_row(s["name"], s["type"], s["id"])
        console.print(table)
        console.print()
        if be_name == "tmux":
            console.print(f"[bold]Attach:[/bold] tmux attach -t clawteam-{t_name}")
        console.print(f"[bold]Board:[/bold]  clawteam board show {t_name}")
        console.print(f"[bold]Inbox:[/bold]  clawteam inbox peek {t_name} --agent <name>")

    _output(out, _human)


if __name__ == "__main__":
    app()
