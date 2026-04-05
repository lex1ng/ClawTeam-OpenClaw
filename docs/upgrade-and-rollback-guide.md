# Upgrade and Rollback Guide

This guide explains how to upgrade, verify, and roll back a local `ClawTeam-OpenClaw` installation safely.

## Who This Is For

Use this guide when:

- you installed the project from this repository with `pip install -e .`
- you want to move from one tested branch/commit to another
- you want to preserve durable state under `~/.clawteam/`
- you need a controlled rollback path if the upgrade is unsatisfactory

## Core Principles

- stop active work before upgrading
- back up durable state before changing code
- upgrade code first, then re-run installation
- treat `~/.clawteam/` as important runtime state
- treat the Web board as convenience UI, not authority
- use CLI and durable files for post-upgrade verification

## What Persists Across Upgrades

Durable runtime state is stored under `~/.clawteam/`.

This may include:

- teams
- tasks
- inbox/mailbox state
- coding jobs
- coding results
- coding artifacts
- runtime-console provider sessions
- callback reports
- runtime faults
- timeline data

Git worktrees, tmux sessions, and local repo branches may also exist outside `~/.clawteam/` depending on how the team has been used.

## Standard Upgrade Procedure

### 1. Stop active work

Before upgrading, stop or finish:

- active agent teams
- long-running coding jobs
- live board sessions
- manual tmux-driven agent runs that should not be interrupted

### 2. Back up durable state

Create a timestamped backup before changing code:

```bash
tar -czf ~/clawteam-backup-$(date +%Y%m%d-%H%M%S).tar.gz ~/.clawteam
```

Optional but recommended: record current repo/worktree state.

```bash
git -C /root/github.com/ClawTeam-OpenClaw log --oneline -1
git -C /root/github.com/ClawTeam-OpenClaw status
git -C /root/github.com/ClawTeam-OpenClaw worktree list
```

### 3. Update the repository

Move to the target branch, tag, or commit.

Example:

```bash
cd /root/github.com/ClawTeam-OpenClaw
git fetch --all
git checkout <target-branch-or-commit>
git pull
```

### 4. Re-run installation

If you installed with editable mode, many Python changes may already be visible.

Still, the recommended upgrade procedure is to re-run installation explicitly:

```bash
cd /root/github.com/ClawTeam-OpenClaw
pip install -e .
```

If you use the optional P2P transport extras:

```bash
pip install -e ".[p2p]"
```

### 5. Re-sync the OpenClaw skill if needed

If the repository updated `skills/openclaw/SKILL.md`, re-copy it for OpenClaw users:

```bash
mkdir -p ~/.openclaw/workspace/skills/clawteam
cp /root/github.com/ClawTeam-OpenClaw/skills/openclaw/SKILL.md ~/.openclaw/workspace/skills/clawteam/SKILL.md
```

If you are not using OpenClaw, skip this step.

### 6. Run smoke checks

Recommended post-upgrade checks:

```bash
clawteam --version
clawteam config health
clawteam board show <team>
clawteam --json board show <team>
clawteam coding list --team <team>
clawteam faults list --team <team>
```

If you use OpenClaw, also verify the skill is still visible:

```bash
openclaw skills list | grep clawteam
```

## What To Check After Upgrade

Minimum expectations:

- the CLI starts
- `config health` remains green or expected
- existing team data still renders
- board output is readable
- coding jobs remain inspectable
- runtime faults remain inspectable
- no durable-state corruption is introduced by the upgrade

## Rollback Procedure

If the upgraded version is unsatisfactory, roll back both code and, if needed, durable state.

### Roll back code

```bash
cd /root/github.com/ClawTeam-OpenClaw
git checkout <previous-known-good-commit>
pip install -e .
```

### Roll back durable state

Only do this if the upgrade changed runtime state in a way you do not want to keep.

```bash
rm -rf ~/.clawteam
tar -xzf ~/clawteam-backup-YYYYMMDD-HHMMSS.tar.gz -C ~
```

## Controlled Cleanup Instead Of Full Rollback

If you do not want to restore everything, clean up selectively.

You may need to remove or stop:

- tmux sessions created for agents
- git worktrees created for agents
- clawteam branches no longer needed
- specific team state under `~/.clawteam/`
- copied OpenClaw skill files
- OpenClaw approvals/allowlist entries if you want to undo integration-specific setup

Do not delete git worktrees or branches blindly if they may contain unmerged work.

## Notes On Editable Installs

The recommended install mode for this project is:

```bash
pip install -e .
```

Editable installs are convenient for development and upgrades, but they do not remove the need for:

- a durable-state backup
- a controlled reinstall step
- a smoke-check step after upgrade

## Recommended Operating Habit

For every upgrade:

1. stop active work
2. back up `~/.clawteam`
3. update the repo to the target revision
4. re-run `pip install -e .`
5. re-sync the OpenClaw skill if applicable
6. run smoke checks
7. resume usage only after the checks pass
