"""Codex CLI harness."""

from __future__ import annotations

from clawteam.coding.harness.base import BaseCliHarness
from clawteam.coding.models import CodingProvider


class CodexCliHarness(BaseCliHarness):
    provider = CodingProvider.codex
    binary_name = "codex"

    def append_prompt(self, command: list[str], prompt: str) -> list[str]:
        return [*command, prompt]
