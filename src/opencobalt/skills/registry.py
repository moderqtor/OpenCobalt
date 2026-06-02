"""Skill registry for OpenCobalt."""

from __future__ import annotations

from opencobalt.skills.base_skill import BaseSkill
from opencobalt.skills.context_injector import ContextInjector
from opencobalt.skills.diff_writer import DiffWriter
from opencobalt.skills.file_reader import FileReader

REGISTRY: dict[str, BaseSkill] = {
    "file-reader": FileReader(),
    "diff-writer": DiffWriter(),
    "context-injector": ContextInjector(),
}


def list_skills(agent: str | None = None) -> list[dict[str, str]]:
    """Return name and description for every registered skill.

    If agent is given, filter to skills whose compatible_agents includes it.
    """
    results = []
    for skill in REGISTRY.values():
        compatible = getattr(skill, "compatible_agents", [])
        if agent is not None and agent not in compatible:
            continue
        results.append({"name": skill.name, "description": skill.description})
    return results


def get_skill(name: str) -> BaseSkill | None:
    """Return the skill instance for the given name, or None if not found."""
    return REGISTRY.get(name)
