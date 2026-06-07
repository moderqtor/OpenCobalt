"""Local capability discovery for skills, integrations, subagents, and CLIs."""

from __future__ import annotations

import shutil
from dataclasses import dataclass

from opencobalt.integrations.registry import REGISTRY as INTEGRATION_REGISTRY
from opencobalt.skills.registry import REGISTRY as SKILL_REGISTRY

from .subagent_registry import SubagentRegistry


@dataclass(frozen=True)
class CapabilityEntry:
    id: str
    provider: str
    type: str
    task_types: list[str]
    risk_level: str
    available: bool


_CLI_BINARIES = {
    "claude-code": "claude",
    "codex-cli": "codex",
}


class CapabilityIndex:
    """Build a deterministic inventory without invoking provider APIs."""

    def discover(self) -> list[CapabilityEntry]:
        entries: list[CapabilityEntry] = []
        entries.extend(self._discover_skills())
        entries.extend(self._discover_integrations())
        entries.extend(self._discover_subagents())
        entries.extend(self._discover_clis())
        return entries

    def _discover_skills(self) -> list[CapabilityEntry]:
        return [
            CapabilityEntry(
                id=f"skill:{name}",
                provider="local",
                type="skill",
                task_types=[name],
                risk_level="low",
                available=True,
            )
            for name in sorted(SKILL_REGISTRY)
        ]

    def _discover_integrations(self) -> list[CapabilityEntry]:
        entries: list[CapabilityEntry] = []
        for name, integration in sorted(INTEGRATION_REGISTRY.items()):
            entries.append(
                CapabilityEntry(
                    id=f"integration:{name}",
                    provider=name,
                    type="integration",
                    task_types=list(getattr(integration, "capabilities", [])),
                    risk_level=getattr(integration, "tier", "worker"),
                    available=integration.install_check(),
                )
            )
        return entries

    def _discover_subagents(self) -> list[CapabilityEntry]:
        entries: list[CapabilityEntry] = []
        for spec in SubagentRegistry().list_all():
            entries.append(
                CapabilityEntry(
                    id=f"subagent:{spec.agent_id}",
                    provider=spec.tool,
                    type="subagent",
                    task_types=list(spec.task_types),
                    risk_level=spec.tier,
                    available=self._tool_available(spec.tool),
                )
            )
        return entries

    def _discover_clis(self) -> list[CapabilityEntry]:
        return [
            CapabilityEntry(
                id=f"cli:{tool}",
                provider=tool,
                type="cli",
                task_types=["cli"],
                risk_level="manager",
                available=self._binary_available(binary),
            )
            for tool, binary in sorted(_CLI_BINARIES.items())
        ]

    def _tool_available(self, tool: str) -> bool:
        binary = _CLI_BINARIES.get(tool)
        if binary is None:
            return False
        return self._binary_available(binary)

    def _binary_available(self, binary: str) -> bool:
        return shutil.which(binary) is not None
