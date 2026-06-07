from opencobalt.core.markdown_exporter import MarkdownExporter


def _run(run_id: str = "abc12345-0000-0000-0000-000000000000") -> dict:
    return {
        "id": run_id,
        "run_type": "route",
        "seed_prompt": "summarize logs",
        "agent_id": "claude-code",
        "model_used": "claude-sonnet-4-6",
        "started_at": 1749340800.0,
        "latency_ms": 3200,
        "retry_count": 0,
        "artifacts_produced": 1,
        "token_count_in": 200,
        "token_count_out": 800,
        "summary": "Summarized the log file.",
        "tool_calls_json": '["pytest", "git"]',
        "skills_used_json": '["tdd"]',
        "connectors_used_json": '[]',
    }


def _score(run_id: str = "abc12345-0000-0000-0000-000000000000") -> dict:
    return {
        "run_id": run_id,
        "overall": 78, "judge": "ollama:llama3",
        "output_quality": 80, "prompt_adherence": 85, "novel_ideation": 55,
        "context_handling": 70, "token_efficiency": 75, "latency_score": 90,
        "tool_appropriateness": 72, "task_decomposition": 65, "agent_selection": 70,
        "convergence_quality": 95, "judge_reasoning": "Solid output.",
    }


def test_export_creates_file(tmp_path):
    exporter = MarkdownExporter()
    path = exporter.export_run(_run(), _score(), tmp_path)
    assert path.exists()
    assert path.suffix == ".md"


def test_filename_contains_run_type_and_id(tmp_path):
    exporter = MarkdownExporter()
    path = exporter.export_run(_run(), _score(), tmp_path)
    assert "route" in path.stem
    assert "abc12345" in path.stem


def test_frontmatter_keys_present(tmp_path):
    exporter = MarkdownExporter()
    path = exporter.export_run(_run(), _score(), tmp_path)
    content = path.read_text()
    assert "overall_score: 78" in content
    assert "agent: claude-code" in content
    assert "run_type: route" in content


def test_score_table_present(tmp_path):
    exporter = MarkdownExporter()
    path = exporter.export_run(_run(), _score(), tmp_path)
    content = path.read_text()
    assert "| Output Quality |" in content
    assert "| 80 |" in content


def test_related_links_populated(tmp_path):
    exporter = MarkdownExporter()
    run1_id = "aaaaaaaa-0000-0000-0000-000000000000"
    run2_id = "bbbbbbbb-0000-0000-0000-000000000000"
    # Write two older files first
    path1 = exporter.export_run({**_run(run1_id), "started_at": 1749340700.0}, _score(run1_id), tmp_path)
    path2 = exporter.export_run({**_run(run2_id), "started_at": 1749340750.0}, _score(run2_id), tmp_path)
    # Now write a third -- should reference the two above
    path3 = exporter.export_run({**_run(), "started_at": 1749340800.0}, _score(), tmp_path)
    content = path3.read_text()
    assert path1.stem in content or path2.stem in content
