"""Renders board data using Rich tables, panels, and columns."""

from __future__ import annotations

import signal
import time

from rich.columns import Columns
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text


class BoardRenderer:
    """Renders board data using Rich."""

    def __init__(self, console: Console | None = None):
        self.console = console or Console()

    def render_team_board(self, data: dict) -> None:
        """Render a full team board to the console."""
        self.console.print(self._build_team_board(data))

    def render_overview(self, teams: list[dict]) -> None:
        """Render a multi-team overview table."""
        if not teams:
            self.console.print("[dim]No teams found[/dim]")
            return

        table = Table(title="Team Overview")
        table.add_column("Team", style="cyan")
        table.add_column("Leader")
        table.add_column("Members", justify="right")
        table.add_column("Tasks", justify="right")
        table.add_column("Pending Msgs", justify="right")
        table.add_column("Active Coding", justify="right")

        for t in teams:
            table.add_row(
                t["name"],
                t.get("leader", ""),
                str(t["members"]),
                str(t["tasks"]),
                str(t["pendingMessages"]),
                str(t.get("activeCodingJobs", 0)),
            )
        self.console.print(table)

    def render_team_board_live(self, collector, team_name: str, interval: float = 2.0) -> None:
        """Render a live-refreshing team board. Ctrl+C to stop."""
        running = True

        def _handle_signal(signum, frame):
            nonlocal running
            running = False

        old_sigint = signal.getsignal(signal.SIGINT)
        old_sigterm = signal.getsignal(signal.SIGTERM)
        signal.signal(signal.SIGINT, _handle_signal)
        signal.signal(signal.SIGTERM, _handle_signal)

        try:
            with Live(console=self.console, refresh_per_second=1, screen=False) as live:
                while running:
                    try:
                        data = collector.collect_team(team_name)
                        renderable = self._build_team_board(data)
                    except ValueError as e:
                        renderable = Text(str(e), style="red")
                        live.update(renderable)
                        break
                    live.update(renderable)
                    time.sleep(interval)
        finally:
            signal.signal(signal.SIGINT, old_sigint)
            signal.signal(signal.SIGTERM, old_sigterm)

    # ------------------------------------------------------------------
    # Internal builders
    # ------------------------------------------------------------------

    def _build_team_board(self, data: dict) -> Group:
        """Build the full team board as a Rich Group of renderables."""
        team = data["team"]
        members = data["members"]
        tasks = data["tasks"]
        summary = data["taskSummary"]
        coding = data.get("coding", {})
        runtime = data.get("runtimeConsole", {})

        parts = []

        # 1. Team header panel
        header_text = (
            f"Leader: [cyan]{team.get('leaderName', team.get('leadAgentId', ''))}[/cyan]  |  "
            f"Members: [cyan]{len(members)}[/cyan]  |  "
            f"Created: [dim]{team['createdAt'][:19]}[/dim]"
        )
        cost = data.get("cost", {})
        total_cents = cost.get("totalCostCents", 0)
        active_coding = coding.get("summary", {}).get("active", 0)
        if total_cents > 0:
            budget_cents = team.get("budgetCents", 0)
            if budget_cents > 0:
                header_text += f"  |  Cost: [yellow]${total_cents / 100:.2f} / ${budget_cents / 100:.2f}[/yellow]"
            else:
                header_text += f"  |  Cost: [yellow]${total_cents / 100:.2f}[/yellow]"
        desc = team.get("description", "")
        if desc:
            header_text = f"{desc}\n{header_text}"
        if active_coding > 0:
            header_text += f"  |  Active coding jobs: [magenta]{active_coding}[/magenta]"
        parts.append(Panel(header_text, title=f"Team: {team['name']}", border_style="bright_blue"))

        # 2. Members table
        has_user = any(m.get("user") for m in members)
        mem_table = Table(title="Members")
        mem_table.add_column("Name", style="cyan")
        mem_table.add_column("Nickname", style="magenta")
        mem_table.add_column("Role")
        if has_user:
            mem_table.add_column("User", style="magenta")
        mem_table.add_column("Type")
        mem_table.add_column("Session Key", style="dim")
        mem_table.add_column("Joined", style="dim")
        mem_table.add_column("Inbox", justify="right")
        for m in members:
            inbox_style = "red" if m["inboxCount"] > 0 else "dim"
            row = [
                m["name"],
                m.get("memberNickname", m["name"]),
                m.get("memberRole", m["agentType"]),
            ]
            if has_user:
                row.append(m.get("user", ""))
            row.extend([
                m["agentType"],
                m.get("preferredSessionKey", ""),
                m["joinedAt"][:19],
                f"[{inbox_style}]{m['inboxCount']}[/{inbox_style}]",
            ])
            mem_table.add_row(*row)
        parts.append(mem_table)

        # 3. Coding jobs summary
        parts.append(self._build_coding_panel(coding))

        # 4. Explicit fault surfaces
        parts.append(self._build_fault_surfaces_panel(data))

        # 5. Callback operator semantics
        parts.append(self._build_callback_chain_panel(runtime))
        parts.append(self._build_evidence_panel(runtime))

        # 6. Task board (4-column kanban)
        parts.append(self._build_task_kanban(tasks, summary))

        return Group(*parts)

    def _build_coding_panel(self, coding: dict) -> Panel:
        summary = coding.get("summary", {})
        jobs = coding.get("recentJobs", [])
        faults = coding.get("faults", [])
        storage = coding.get("storage", {})
        lines = [
            (
                f"active={summary.get('active', 0)}  queued={summary.get('queued', 0)}  "
                f"running={summary.get('running', 0)}  completed={summary.get('completed', 0)}  "
                f"failed={summary.get('failed', 0)}  timeout={summary.get('timeout', 0)}  "
                f"cancelled={summary.get('cancelled', 0)}"
            ),
        ]
        if faults:
            lines.append(f"[red]faults={len(faults)}[/red]")
            for fault in faults[:3]:
                lines.append(f"[red]- {fault.get('faultType', 'fault')}[/red] {fault.get('message', '')}")
        if jobs:
            lines.append("")
            for job in jobs[:5]:
                lines.append(
                    f"[bold]{job['jobId']}[/bold]  {job['workerName']}  "
                    f"{job['provider']}  [{self._coding_state_style(job['state'])}]{job['state']}[/]  "
                    f"{job['effectiveCwd']}"
                )
                if job.get("summary"):
                    lines.append(f"  {job['summary']}")
                lines.append(f"  updated: {job['updatedAt'][:19]}")
        else:
            lines.append("")
            lines.append("[dim]No coding jobs recorded[/dim]")
        if storage:
            lines.append("")
            lines.append(f"[dim]jobs: {storage.get('jobsRoot', '')}[/dim]")
            lines.append(f"[dim]results: {storage.get('resultsRoot', '')}[/dim]")
            lines.append(f"[dim]artifacts: {storage.get('artifactsRoot', '')}[/dim]")
        return Panel("\n".join(lines), title="Coding Runtime", border_style="magenta")

    def _coding_state_style(self, state: str) -> str:
        mapping = {
            "queued": "yellow",
            "running": "cyan",
            "completed": "green",
            "failed": "red",
            "timeout": "red",
            "cancelled": "dim",
        }
        return mapping.get(state, "white")

    def _build_fault_surfaces_panel(self, data: dict) -> Panel:
        task_faults = data.get("taskReadFaults", [])
        coding_faults = data.get("coding", {}).get("faults", [])
        runtime_faults = data.get("runtimeConsole", {}).get("faults", [])
        surfaces = [
            ("Task Read Faults", task_faults, "yellow"),
            ("Coding Read Faults", coding_faults, "yellow"),
            ("Runtime Faults", runtime_faults, "red"),
        ]

        lines = []
        for title, faults, color in surfaces:
            if not faults:
                lines.append(f"[green]{title}: 0[/green]")
                continue
            lines.append(f"[{color}]{title}: {len(faults)}[/{color}]")
            for fault in faults[:3]:
                lines.append(
                    "  - "
                    f"{fault.get('faultId') or fault.get('recordId') or fault.get('faultType', 'fault')}  "
                    f"{self._fault_scope_label(fault)}  "
                    f"{fault.get('message', '')}"
                )
            if len(faults) > 3:
                lines.append(f"  [dim]+ {len(faults) - 3} more[/dim]")

        lines.append("")
        lines.append("[dim]Healthy records continue to render; unreadable or corrupted records remain explicit.[/dim]")
        return Panel("\n".join(lines), title="Fault Surfaces", border_style="yellow")

    def _build_callback_chain_panel(self, runtime: dict) -> Panel:
        callback_chain = runtime.get("callbackChain", {})
        workers = callback_chain.get("workers", [])
        team_row = callback_chain.get("team", {})
        lines = []
        if not workers and not team_row:
            lines.append("[dim]No callback chain records yet[/dim]")
        else:
            for row in workers[:8]:
                lines.append(
                    f"[bold]{row.get('workerName', '-')}[/bold] -> team_leader  "
                    f"state={row.get('callbackState', '-')}  "
                    f"health={row.get('health', '-')}  "
                    f"progress={row.get('progressState', '-')}  "
                    f"wait={row.get('waitingFor', '-')}"
                )
                lines.append(
                    "  lifecycle: "
                    f"task={row.get('taskLifecyclePhase', '-') or '-'}  "
                    f"callback={row.get('callbackLifecyclePhase', '-') or '-'}  "
                    f"review={row.get('reviewLifecyclePhase', '-') or '-'}"
                )
                if row.get("handoffMissingFields"):
                    lines.append(
                        "  handoff missing: "
                        + ", ".join(row.get("handoffMissingFields", []))
                    )
            if team_row:
                lines.append("")
                lines.append(
                    "team_leader -> main_leader  "
                    f"state={team_row.get('callbackState', '-')}  "
                    f"workers={team_row.get('workersReported', 0)}/{team_row.get('workersTotal', 0)}  "
                    f"pending={team_row.get('workersPending', 0)}  "
                    f"faulted={team_row.get('workersFaulted', 0)}"
                )
        return Panel(
            "\n".join(lines),
            title="Callback Flow (Durable State)",
            border_style="cyan",
        )

    def _build_evidence_panel(self, runtime: dict) -> Panel:
        evidence = runtime.get("evidence", {})
        records = evidence.get("records", [])
        summary = evidence.get("summary", {})
        lines = [
            "[dim]Evidence is non-authoritative; durable state remains source of truth.[/dim]",
            (
                f"total={summary.get('total', len(records))}  "
                f"truncated={summary.get('truncated', 0)}  "
                f"unavailable={summary.get('unavailable', 0)}"
            ),
            "",
        ]
        if not records:
            lines.append("[dim]No bounded evidence records yet[/dim]")
        else:
            for record in records[:6]:
                lines.append(
                    f"{record.get('evidenceType', '-')}  "
                    f"source={record.get('sourceType', '-')}/{record.get('sourceId', '-')}  "
                    f"worker={record.get('workerName', '-') or '-'}  "
                    f"truncated={'yes' if record.get('truncated') else 'no'}"
                )
                if record.get("unavailableReason"):
                    lines.append(f"  unavailable={record['unavailableReason']}")
        return Panel("\n".join(lines), title="Bounded Evidence View", border_style="blue")

    def _fault_scope_label(self, fault: dict) -> str:
        if fault.get("scopeType"):
            return f"{fault.get('scopeType')}:{fault.get('scopeId', '-')}"
        record_kind = fault.get("recordKind", "durable_state")
        record_id = fault.get("recordId")
        return f"{record_kind}:{record_id}" if record_id else record_kind

    def _build_task_kanban(self, tasks: dict, summary: dict) -> Panel:
        """Build the 4-column kanban task board."""
        columns_cfg = [
            ("PENDING", "pending", "yellow"),
            ("IN PROGRESS", "in_progress", "cyan"),
            ("COMPLETED", "completed", "green"),
            ("BLOCKED", "blocked", "red"),
        ]

        panels = []
        for label, key, color in columns_cfg:
            count = summary.get(key, 0)
            items = tasks.get(key, [])
            lines = []
            for t in items:
                task_id = t.get("id", "")[:8]
                subject = t.get("subject", "")
                owner = t.get("owner", "") or "-"
                lines.append(f"[bold]#{task_id}[/bold] {subject}")
                lines.append(f"  owner: {owner}")
                if key == "in_progress" and t.get("lockedBy"):
                    lines.append(f"  locked by: [yellow]{t['lockedBy']}[/yellow]")
                if key == "blocked" and t.get("blockedBy"):
                    lines.append(f"  blocked by: {', '.join(t['blockedBy'])}")
                coding = t.get("metadata", {}).get("coding")
                if coding:
                    lines.append(
                        f"  coding: [magenta]{coding.get('provider', '-')}[/magenta] "
                        f"{coding.get('status', '-')}  job={coding.get('latestJobId', '-')}"
                    )
                    if coding.get("summary"):
                        lines.append(f"  summary: {coding['summary']}")
                lines.append(
                    "  lifecycle: "
                    f"task={t.get('taskLifecyclePhase', '-')}  "
                    f"callback={t.get('callbackLifecyclePhase', '-')}  "
                    f"review={t.get('reviewLifecyclePhase', '-')}"
                )
                if t.get("handoffMissingFields"):
                    lines.append(f"  handoff missing: {', '.join(t['handoffMissingFields'])}")
                lines.append("")

            body = "\n".join(lines).rstrip() if lines else "[dim]  (none)[/dim]"
            panels.append(
                Panel(
                    body,
                    title=f"{label} ({count})",
                    border_style=color,
                    expand=True,
                )
            )

        total = summary.get("total", 0)
        return Panel(
            Columns(panels, equal=True, expand=True),
            title=f"Task Board ({total} total)",
        )
