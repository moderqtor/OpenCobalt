"""Skill registry for OpenCobalt."""

from __future__ import annotations

from opencobalt.skills.base_skill import BaseSkill
from opencobalt.skills.diff_writer import DiffWriter
from opencobalt.skills.file_reader import FileReader

REGISTRY: dict[str, BaseSkill] = {
    "file-reader": FileReader(),
    "diff-writer": DiffWriter(),
}


def list_skills() -> list[dict[str, str]]:
    """Return name and description for every registered skill."""
    return [{"name": skill.name, "description": skill.description} for skill in REGISTRY.values()]


def get_skill(name: str) -> BaseSkill | None:
    """Return the skill instance for the given name, or None if not found."""
    return REGISTRY.get(name)
