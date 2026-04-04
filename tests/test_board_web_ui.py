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
