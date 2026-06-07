from unittest.mock import MagicMock
from opencobalt.core.telemetry import TelemetryStore
from opencobalt.core.scoring_engine import ScoringEngine
from opencobalt.core.ollama_judge import OllamaJudge


def _make_store(tmp_path):
    store = TelemetryStore(tmp_path / "t.db")
    session = store.start_run(run_type="route", seed_prompt="build auth module", agent_id="claude-code")
    session.record_tool_use("pytest")
    session.record_tool_use("git")
    session.record_artifact("code", "art-1")
    session.record_retry("gate failed")
    session.record_output("auth module built", token_count=500)
    session.record_gate_pass("tests")
    session.finish("complete")
    return store, session.run_id


def test_score_produces_all_categories(tmp_path):
    store, run_id = _make_store(tmp_path)
    judge = MagicMock(spec=OllamaJudge)
    judge.judge_name = "ollama:llama3"
    judge.judge.return_value = {
        "output_quality": 80, "prompt_adherence": 85, "novel_ideation": 55,
        "context_handling": 70, "tool_appropriateness": 75, "task_decomposition": 65,
        "agent_selection": 72, "reasoning": "Good work.", "summary": "Built auth.",
        "_judge": "ollama:llama3",
    }
    engine = ScoringEngine(store, judge=judge)
    score = engine.score(run_id)
    assert score["run_id"] == run_id
    assert 1 <= score["overall"] <= 100
    assert score["token_efficiency"] is not None
    assert score["latency_score"] is not None
    assert score["convergence_quality"] is not None
    result = store.get_score(run_id)
    assert result is not None
    assert result["overall"] == score["overall"]


def test_overall_weighted_correctly(tmp_path):
    store, run_id = _make_store(tmp_path)
    judge = MagicMock(spec=OllamaJudge)
    judge.judge_name = "ollama:llama3"
    judge.judge.return_value = {
        "output_quality": 100, "prompt_adherence": 100, "novel_ideation": 100,
        "context_handling": 100, "tool_appropriateness": 100, "task_decomposition": 100,
        "agent_selection": 100, "reasoning": "", "summary": "", "_judge": "ollama:llama3",
    }
    engine = ScoringEngine(store, judge=judge)
    score = engine.score(run_id)
    assert score["overall"] >= 90


def test_fallback_judge_produces_valid_score(tmp_path):
    store, run_id = _make_store(tmp_path)
    judge = MagicMock(spec=OllamaJudge)
    judge.judge_name = "heuristic"
    judge.judge.return_value = {
        "output_quality": 50, "prompt_adherence": 50, "novel_ideation": 50,
        "context_handling": 50, "tool_appropriateness": 50, "task_decomposition": 50,
        "agent_selection": 50, "reasoning": "", "summary": "", "_judge": "heuristic",
    }
    engine = ScoringEngine(store, judge=judge)
    score = engine.score(run_id)
    assert score["judge"] == "heuristic"
    assert 1 <= score["overall"] <= 100


def test_summary_saved_to_run(tmp_path):
    store, run_id = _make_store(tmp_path)
    judge = MagicMock(spec=OllamaJudge)
    judge.judge_name = "ollama:llama3"
    judge.judge.return_value = {
        **{k: 70 for k in ["output_quality","prompt_adherence","novel_ideation",
                            "context_handling","tool_appropriateness","task_decomposition","agent_selection"]},
        "reasoning": "r", "summary": "Built the auth module successfully.", "_judge": "ollama:llama3",
    }
    engine = ScoringEngine(store, judge=judge)
    engine.score(run_id)
    run = store.get_run(run_id)
    assert run["summary"] == "Built the auth module successfully."
