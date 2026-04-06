"""Version and fork identity for ClawTeam-OpenClaw."""

from __future__ import annotations

FORK_NAME = "ClawTeam-OpenClaw"
PACKAGE_NAME = "clawteam"
__version__ = "0.3.1+openclaw.1"


def version_info() -> dict[str, str]:
    return {
        "package": PACKAGE_NAME,
        "version": __version__,
        "fork": FORK_NAME,
    }
