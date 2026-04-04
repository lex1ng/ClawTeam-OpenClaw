"""Claude CLI harness."""

from __future__ import annotations

from clawteam.coding.harness.base import BaseCliHarness
from clawteam.coding.models import CodingProvider


class ClaudeCliHarness(BaseCliHarness):
    provider = CodingProvider.claude
    binary_name = "claude"

    def append_prompt(self, command: list[str], prompt: str) -> list[str]:
        return [*command, "-p", prompt]
