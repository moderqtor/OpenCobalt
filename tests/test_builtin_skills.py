"""Built-in skill contracts are declarative and routing-only."""

from __future__ import annotations

from opencobalt.personal_ai.builtin_skills import (
    list_builtin_skills,
    recommend_builtin_skill,
    skill_policy_addendum,
)


def test_builtin_skills_are_a_small_declarative_set():
    skills = list_builtin_skills()
    assert 6 <= len(skills) <= 12
    for skill in skills:
        assert skill.tools_required == []
        assert skill.mutation_authority in {"none", "observe", "staged"}
        assert skill.system_addendum.strip()
        assert skill.inputs
        assert skill.outputs


def test_recommend_builtin_skill_is_conservative():
    assert recommend_builtin_skill(
        task_class="research", capability_role="research", citations_required=True
    ).skill_id == "research-claim-verification"
    assert recommend_builtin_skill(
        task_class="planning", capability_role="strong_reasoning"
    ).skill_id == "structured-planning"
    assert recommend_builtin_skill(
        task_class="coding", capability_role="strong_reasoning"
    ).skill_id == "architectural-review"
    assert (
        recommend_builtin_skill(
            task_class="general_reasoning", capability_role="cheap_local"
        )
        is None
    )
    addendum = skill_policy_addendum(["structured-planning"])
    assert "Selected skill contract" in addendum
