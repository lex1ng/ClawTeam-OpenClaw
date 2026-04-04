from clawteam.spawn.prompt import build_agent_prompt


def test_openclaw_prompt_mentions_allowlisted_absolute_clawteam_path():
    prompt = build_agent_prompt(
        agent_name="worker1",
        agent_id="agent-1",
        agent_type="general-purpose",
        team_name="demo-team",
        leader_name="leader",
        task="do work",
    )
    assert "$CLAWTEAM_BIN" in prompt
    assert "$CLAWTEAM_CMD" not in prompt
    assert "allowlist" in prompt.lower()


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
