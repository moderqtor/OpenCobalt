import json
import subprocess
from unittest.mock import patch

from opencobalt.core.ollama_judge import _QUALITATIVE_KEYS, OllamaJudge


def test_judge_returns_all_keys_on_good_response():
    good_json = json.dumps({
        "output_quality": 85, "prompt_adherence": 90, "novel_ideation": 60,
        "context_handling": 70, "tool_appropriateness": 75, "task_decomposition": 65,
        "agent_selection": 80, "reasoning": "Solid.", "summary": "Did the thing.",
    })
    judge = OllamaJudge(model="llama3")
    with patch.object(judge, "_call_ollama", return_value=good_json):
        result = judge.judge(prompt="summarize logs", output="log summary here", heuristics={})
    for key in _QUALITATIVE_KEYS:
        assert key in result
        assert isinstance(result[key], int)
        assert 1 <= result[key] <= 100
    assert result["reasoning"] == "Solid."
    assert result["summary"] == "Did the thing."
    assert result["_judge"] == "ollama:llama3"


def test_judge_falls_back_on_bad_json():
    judge = OllamaJudge(model="llama3")
    with patch.object(judge, "_call_ollama", return_value="not json at all"):
        result = judge.judge(prompt="x", output="y", heuristics={})
    for key in _QUALITATIVE_KEYS:
        assert result[key] == 50
    assert result["_judge"] == "heuristic"


def test_judge_falls_back_when_ollama_unavailable():
    judge = OllamaJudge(model="llama3")
    with patch.object(judge, "_call_ollama", return_value=None):
        result = judge.judge(prompt="x", output="y", heuristics={})
    assert result["_judge"] == "heuristic"


def test_output_truncated_to_4000_chars():
    captured = {}
    def fake_call(prompt: str) -> str | None:
        captured["prompt"] = prompt
        return None
    judge = OllamaJudge()
    with patch.object(judge, "_call_ollama", side_effect=fake_call):
        judge.judge(prompt="p", output="x" * 5000, heuristics={})
    assert "x" * 4000 in captured["prompt"]
    assert "x" * 4001 not in captured["prompt"]


def test_judge_name_property():
    assert OllamaJudge(model="mistral").judge_name == "ollama:mistral"


def test_out_of_range_scores_clamped():
    bad_range_json = json.dumps({
        "output_quality": 999, "prompt_adherence": -5, "novel_ideation": 0,
        "context_handling": 101, "tool_appropriateness": 50, "task_decomposition": 50,
        "agent_selection": 50, "reasoning": "r", "summary": "s",
    })
    judge = OllamaJudge()
    with patch.object(judge, "_call_ollama", return_value=bad_range_json):
        result = judge.judge(prompt="p", output="o", heuristics={})
    assert result["output_quality"] == 100
    assert result["prompt_adherence"] == 1
    assert result["novel_ideation"] == 1


def test_prose_before_json_extracts_first_json_object():
    prose_prefix = 'Here is my analysis {not valid}. Result: ' + json.dumps({
        "output_quality": 75, "prompt_adherence": 80, "novel_ideation": 55,
        "context_handling": 65, "tool_appropriateness": 70, "task_decomposition": 60,
        "agent_selection": 72, "reasoning": "Good.", "summary": "Done.",
    })
    judge = OllamaJudge()
    with patch.object(judge, "_call_ollama", return_value=prose_prefix):
        result = judge.judge(prompt="p", output="o", heuristics={})
    assert result["output_quality"] == 75
    assert result["_judge"] == "ollama:llama3"


def test_call_ollama_returns_none_without_subprocess(monkeypatch):
    judge = OllamaJudge()
    called = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: called.append(True))
    result = judge._call_ollama("prompt")
    assert result is None
    assert called == []


def test_call_ollama_is_boundary_blocked():
    judge = OllamaJudge()
    result = judge._call_ollama("prompt")
    assert result is None
