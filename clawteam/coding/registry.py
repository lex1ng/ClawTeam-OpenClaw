"""Provider registry for coding harness implementations."""

from __future__ import annotations

from typing import Any

from clawteam.coding.harness.claude_cli import ClaudeCliHarness
from clawteam.coding.harness.codex_cli import CodexCliHarness
from clawteam.coding.models import CodingProvider


class CodingHarnessRegistry:
    """Simple provider registry kept separate from the durable job service."""

    def __init__(self):
        self._harnesses: dict[CodingProvider, Any] = {}

    def register(self, provider: CodingProvider, harness: Any) -> None:
        self._harnesses[provider] = harness

    def get(self, provider: CodingProvider) -> Any:
        if provider not in self._harnesses:
            raise KeyError(f"No coding harness registered for provider '{provider.value}'")
        return self._harnesses[provider]

    def has(self, provider: CodingProvider) -> bool:
        return provider in self._harnesses


def build_default_registry() -> CodingHarnessRegistry:
    """Register the built-in Claude and Codex harnesses."""

    registry = CodingHarnessRegistry()
    registry.register(CodingProvider.claude, ClaudeCliHarness())
    registry.register(CodingProvider.codex, CodexCliHarness())
    return registry
