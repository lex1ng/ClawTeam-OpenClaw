from clawteam.spawn.prompt import build_agent_prompt


def test_openclaw_prompt_uses_plain_clawteam_cli_protocol():
    prompt = build_agent_prompt(
        agent_name="worker1",
        agent_id="agent-1",
        agent_type="general-purpose",
        team_name="demo-team",
        leader_name="leader",
        task="do work",
    )
    assert "$CLAWTEAM_BIN" not in prompt
    assert "$CLAWTEAM_CMD" not in prompt
    assert "allowlist" in prompt.lower()
    assert "Use the standard `clawteam ...` CLI commands below" in prompt
    assert "First action: run `clawteam task list demo-team --owner worker1`" in prompt


def test_openclaw_prompt_documents_coding_callback_loop():
    prompt = build_agent_prompt(
        agent_name="worker1",
        agent_id="agent-1",
        agent_type="general-purpose",
        team_name="demo-team",
        leader_name="leader",
        task="do work",
    )
    assert "clawteam coding exec" in prompt
    assert "continue, report_progress, escalate, complete, or blocked" in prompt
    assert "Do not paste raw provider stdout/stderr/transcript into the mailbox" in prompt
