from __future__ import annotations

import json

from typer.testing import CliRunner

from clawteam import __version__
from clawteam.cli.commands import app

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]


def test_version_output_is_fork_aware_and_consistent():
    pyproject = tomllib.loads(open("pyproject.toml", "rb").read().decode("utf-8"))
    project = pyproject["project"]

    assert project["dynamic"] == ["version"]
    assert pyproject["tool"]["hatch"]["version"]["path"] == "clawteam/version.py"

    runner = CliRunner()
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert f"clawteam v{__version__}" in result.stdout
    assert "fork: ClawTeam-OpenClaw" in result.stdout


def test_version_json_output_is_consistent():
    runner = CliRunner()
    result = runner.invoke(app, ["--json", "--version"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["version"] == __version__
    assert payload["fork"] == "ClawTeam-OpenClaw"
