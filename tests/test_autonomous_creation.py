"""Tests for Autonomous Creation v0 (IntentContract, WorkGraph, Supervisor, and Store)."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from opencobalt.cli import app
from opencobalt.creation.intent_compiler import IntentCompiler
from opencobalt.creation.models import (
    IntentSource,
    WorkNodeType,
)
from opencobalt.creation.store import CreationStore
from opencobalt.creation.supervisor import AutonomousSupervisor
from opencobalt.creation.work_graph import WorkGraphPlanner


def test_intent_compiler_sparse_request():
    """Verify sparse intent compiles rich inferred dimensions and recognizes creative freedom."""
    prompt = "Build me a fun roguelike video game."
    contract = IntentCompiler.compile(prompt, autonomy="autonomous_lab", budget="4h")

    assert contract.literal_request == prompt
    assert contract.contract_id.startswith("intc-")
    assert len(contract.inferred_objectives) >= 3
    assert len(contract.open_creative_dimensions) >= 3

    # Check provenance
    for item in contract.inferred_objectives:
        assert item.source == IntentSource.INFERRED_OPENCOBALT
    for item in contract.open_creative_dimensions:
        assert item.source == IntentSource.INFERRED_OPENCOBALT


def test_intent_compiler_detailed_request():
    """Verify detailed intent strictly captures explicit constraints without confusing them with preferences."""
    prompt = (
        "Build a surreal exploration-first roguelike with no crafting, "
        "limited combat, and a strong emphasis on procedural ecosystems."
    )
    contract = IntentCompiler.compile(prompt, autonomy="autonomous_lab", budget="2h")

    assert contract.literal_request == prompt
    # Check that hard negative constraints are isolated
    constraint_texts = [c.text.lower() for c in contract.hard_constraints]
    assert any("no crafting" in t or "without crafting" in t for t in constraint_texts)
    for c in contract.hard_constraints:
        assert c.source == IntentSource.EXPLICIT_USER


def test_work_graph_planning_and_provider_neutrality():
    """Verify planned WorkGraph nodes model work to become true, not vendor calls."""
    prompt = "Build me a fun roguelike video game."
    contract = IntentCompiler.compile(prompt)
    graph = WorkGraphPlanner.plan(contract)

    assert graph.graph_id.startswith("wgr-")
    assert len(graph.nodes) >= 6

    # Node IDs and titles must NOT contain vendor names
    vendor_names = ["claude", "gemini", "codex", "antigravity", "cursor", "openai"]
    for node in graph.nodes.values():
        for vendor in vendor_names:
            assert vendor not in node.node_id.lower()
            assert vendor not in node.title.lower()

    # Initial ready nodes should be divergent exploration nodes
    ready = graph.get_ready_nodes()
    assert len(ready) == 2
    assert all(n.work_type == WorkNodeType.EXPLORATION for n in ready)


def test_creation_store_persistence(tmp_path: Path):
    """Verify SQLite persistence for IntentContract, WorkGraph, and artifacts."""
    db_path = tmp_path / "test_creation.db"
    store = CreationStore(db_path)

    contract = IntentCompiler.compile("Build me a fun roguelike video game.")
    store.save_intent(contract)
    loaded_contract = store.get_intent(contract.contract_id)
    assert loaded_contract is not None
    assert loaded_contract.contract_id == contract.contract_id
    assert loaded_contract.literal_request == contract.literal_request

    graph = WorkGraphPlanner.plan(contract)
    store.save_work_graph(graph)
    loaded_graph = store.get_work_graph(graph.graph_id)
    assert loaded_graph is not None
    assert loaded_graph.graph_id == graph.graph_id
    assert len(loaded_graph.nodes) == len(graph.nodes)

    # Save and load artifact
    store.save_artifact(
        artifact_id="art-test-1",
        graph_id=graph.graph_id,
        node_id="explore_mechanical_inversion",
        artifact_type="CandidateConcept",
        content={"title": "Abyssal Echoes", "score": 9.0},
        created_at=contract.created_at,
    )
    loaded_art = store.get_artifact("art-test-1")
    assert loaded_art is not None
    assert loaded_art["content"]["title"] == "Abyssal Echoes"


def test_autonomous_supervisor_loop(tmp_path: Path):
    """Verify complete end-to-end execution of AutonomousSupervisor with multi-agent divergence and synthesis."""
    db_path = tmp_path / "supervisor_test.db"
    store = CreationStore(db_path)
    supervisor = AutonomousSupervisor(store=store)

    contract = IntentCompiler.compile("Build me a fun roguelike video game.")
    events = []

    final_graph, summary = supervisor.run(
        intent=contract,
        progress_callback=lambda ev: events.append(ev),
    )

    assert final_graph.is_completed()
    assert len(events) > 5
    assert "artifacts" in summary
    assert "synthesize_game_design" in summary["artifacts"]
    assert "implement_playable_prototype" in summary["artifacts"]

    # Verify synthesized design content
    design_art = summary["artifacts"]["synthesize_game_design"]["content"]
    assert "ABYSSAL BIOLITH" in design_art["game_title"]
    assert len(design_art["critique_resolutions"]) >= 2

    # Verify implementation code bundle
    impl_art = summary["artifacts"]["implement_playable_prototype"]["content"]
    assert "game.py" in impl_art["files"]
    assert "test_game.py" in impl_art["files"]
    assert "AbyssalGame" in impl_art["files"]["game.py"]


def test_evidence_driven_graph_revision(tmp_path: Path):
    """Verify dynamic graph revision when an evaluation identifies issues."""
    db_path = tmp_path / "revision_test.db"
    store = CreationStore(db_path)
    supervisor = AutonomousSupervisor(store=store)

    contract = IntentCompiler.compile("Build me a fun roguelike video game.")
    graph = WorkGraphPlanner.plan(contract)

    # Initial node count
    initial_count = len(graph.nodes)

    # Run supervisor
    final_graph, summary = supervisor.run(intent=contract, graph=graph)

    # The evaluation node reports a minor issue, triggering graph expansion
    revision_nodes = [n for n in final_graph.nodes.values() if n.work_type == WorkNodeType.REVISION]
    assert len(revision_nodes) >= 1
    assert len(final_graph.nodes) > initial_count


def test_cli_do_command_plan_only(tmp_path: Path):
    """Test CLI 'opencobalt do' with --no-execute."""
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["do", "Build me a fun roguelike video game.", "--no-execute", "--json"],
    )
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert "intent" in data
    assert "graph" in data
    assert data["intent"]["literal_request"] == "Build me a fun roguelike video game."


def test_cli_do_command_execute_json(tmp_path: Path):
    """Test CLI 'opencobalt do' end-to-end with --json."""
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["do", "Build me a fun roguelike video game.", "--execute", "--json"],
    )
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["status"] in ("completed", "active", "revising")
    assert len(data["nodes_completed"]) >= 6
    assert "artifacts" in data
