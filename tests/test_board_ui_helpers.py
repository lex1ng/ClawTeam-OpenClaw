from __future__ import annotations

import json
import subprocess


def _run_node(script: str) -> dict:
    result = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def test_runtime_console_helper_preserves_selection_when_object_still_exists():
    script = r"""
const helpers = require('./clawteam/board/static/runtime_console_helpers.js');
const runtime = {
  faults: [{ faultId: 'fault-1', message: 'fault' }],
  sessions: [{ sessionId: 'psess-1' }],
  jobs: [{ jobId: 'job-1', summary: 'new summary' }],
  tasks: [{ id: 'task-1' }],
  workers: [{ name: 'worker-1' }],
  timeline: [{ eventId: 'evt-1' }]
};
process.stdout.write(JSON.stringify(helpers.resolveSelection({ type: 'job', id: 'job-1', data: { summary: 'old' } }, runtime)));
"""
    payload = _run_node(script)

    assert payload["type"] == "job"
    assert payload["id"] == "job-1"
    assert payload["data"]["summary"] == "new summary"


def test_runtime_console_helper_reselects_default_when_previous_selection_disappears():
    script = r"""
const helpers = require('./clawteam/board/static/runtime_console_helpers.js');
const runtime = {
  faults: [{ faultId: 'fault-1', message: 'fault' }],
  sessions: [{ sessionId: 'psess-1' }],
  jobs: [{ jobId: 'job-1' }],
  tasks: [{ id: 'task-1' }],
  workers: [{ name: 'worker-1' }],
  timeline: [{ eventId: 'evt-1' }]
};
process.stdout.write(JSON.stringify(helpers.resolveSelection({ type: 'job', id: 'job-missing', data: {} }, runtime)));
"""
    payload = _run_node(script)

    assert payload["type"] == "fault"
    assert payload["id"] == "fault-1"


def test_runtime_console_helper_builds_artifact_preview_route():
    script = r"""
const helpers = require('./clawteam/board/static/runtime_console_helpers.js');
process.stdout.write(JSON.stringify({ route: helpers.artifactPreviewRoute('demo team', 'job-1', 'stdout log') }));
"""
    payload = _run_node(script)

    assert payload["route"] == "/api/teams/demo%20team/coding/jobs/job-1/artifacts/stdout%20log"
