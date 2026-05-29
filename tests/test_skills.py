"""Tests for the skills package."""

from __future__ import annotations

from opencobalt.skills.diff_writer import DiffWriter
from opencobalt.skills.file_reader import FileReader
from opencobalt.skills.registry import REGISTRY, get_skill, list_skills

# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_registry_has_two_skills():
    assert len(REGISTRY) == 2


def test_registry_contains_expected_names():
    assert "file-reader" in REGISTRY
    assert "diff-writer" in REGISTRY


def test_list_skills_returns_name_and_description():
    skills = list_skills()
    assert len(skills) == 2
    for entry in skills:
        assert "name" in entry
        assert "description" in entry


def test_get_skill_returns_instance():
    skill = get_skill("file-reader")
    assert skill is not None
    assert isinstance(skill, FileReader)


def test_get_skill_missing_returns_none():
    assert get_skill("no-such-skill") is None


# ---------------------------------------------------------------------------
# FileReader
# ---------------------------------------------------------------------------


def test_file_reader_success(tmp_path):
    target = tmp_path / "hello.txt"
    target.write_text("hello world", encoding="utf-8")

    skill = FileReader()
    result = skill.run(path=str(target))

    assert result.success is True
    assert result.error is None
    assert result.output["content"] == "hello world"
    assert result.output["path"] == str(target)
    assert result.output["size"] == len("hello world")


def test_file_reader_missing_file():
    skill = FileReader()
    result = skill.run(path="/tmp/does-not-exist-opencobalt-skills.txt")

    assert result.success is False
    assert result.error is not None
    assert "File not found" in result.error


def test_file_reader_result_has_skill_name():
    skill = FileReader()
    result = skill.run(path="/tmp/does-not-exist-opencobalt-skills.txt")
    assert result.skill_name == "file-reader"


# ---------------------------------------------------------------------------
# DiffWriter
# ---------------------------------------------------------------------------


def test_diff_writer_differing_strings():
    skill = DiffWriter()
    result = skill.run(original="foo\n", modified="bar\n")

    assert result.success is True
    assert result.output["diff"] != ""
    assert result.output["additions"] > 0
    assert result.output["deletions"] > 0


def test_diff_writer_identical_strings():
    skill = DiffWriter()
    result = skill.run(original="same\n", modified="same\n")

    assert result.success is True
    assert result.output["additions"] == 0
    assert result.output["deletions"] == 0


def test_diff_writer_empty_strings():
    skill = DiffWriter()
    result = skill.run(original="", modified="")

    assert result.success is True
    assert result.output["additions"] == 0
    assert result.output["deletions"] == 0


def test_diff_writer_invalid_input():
    skill = DiffWriter()
    result = skill.run(original=123, modified="foo")  # type: ignore[arg-type]

    assert result.success is False
    assert result.error is not None


def test_diff_writer_result_has_skill_name():
    skill = DiffWriter()
    result = skill.run(original="a", modified="b")
    assert result.skill_name == "diff-writer"


def test_diff_writer_custom_label():
    skill = DiffWriter()
    result = skill.run(original="x\n", modified="y\n", label="myfile")

    assert "a/myfile" in result.output["diff"]
    assert "b/myfile" in result.output["diff"]
