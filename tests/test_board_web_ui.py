from __future__ import annotations

from pathlib import Path


def test_runtime_console_web_board_static_shell_includes_operator_sections():
    html = Path("clawteam/board/static/index.html").read_text(encoding="utf-8")

    assert "Runtime Console" in html
    assert "Provider Sessions" in html
    assert "Coding Runtime" in html
    assert "Event Timeline" in html
    assert "Detail Drawer" in html
    assert "ephemeral" in html
    assert "unavailable" in html
    assert "source of truth" in html
    assert "/runtime_console_helpers.js" in html
    assert "artifactPreviewRoute" in html
    assert "Loading stdout preview" in html


def test_runtime_console_web_board_detail_drawer_keeps_hooks_before_empty_return():
    html = Path("clawteam/board/static/index.html").read_text(encoding="utf-8")

    drawer_start = html.index("function DetailDrawer({ data, selected }) {")
    empty_return = html.index("  if (!selected) {", drawer_start)
    artifact_effect = html.index("  useEffect(() => {\n    const artifact = activeTab === \"stdout\"", drawer_start)

    assert artifact_effect < empty_return


def test_runtime_console_web_board_artifact_preview_effect_uses_stable_dependencies():
    html = Path("clawteam/board/static/index.html").read_text(encoding="utf-8")

    assert "const stdoutArtifactKey = stdoutArtifact ? `${stdoutArtifact.name}:${stdoutArtifact.path}` : \"\";" in html
    assert "const stderrArtifactKey = stderrArtifact ? `${stderrArtifact.name}:${stderrArtifact.path}` : \"\";" in html
    assert "stdoutArtifactKey, stderrArtifactKey" in html
    assert "stdoutArtifact, stderrArtifact" not in html
