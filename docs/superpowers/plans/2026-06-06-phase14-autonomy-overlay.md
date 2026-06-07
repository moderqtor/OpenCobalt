# Phase 14 Autonomy Overlay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the Phase 14 autonomy overlay around the existing Phase 13 convergence runtime.

**Architecture:** Add small core modules for policy, usage optimization, durable autonomy state, capability discovery, council artifacts, mission planning, and overlay dispatch. Keep SQLite as source of truth through `Ledger` and `ArtifactBus`; reuse `ConvergenceOrchestrator` for implementation prompts and `AutonomousRunner` only as legacy runtime behavior where helpful.

**Tech Stack:** Python 3.11+, Typer, Rich, SQLite via stdlib `sqlite3`, pytest, ruff.

---

### File Structure

- Create `src/opencobalt/core/autonomy_policy.py`: profile defaults, permission envelopes, config-backed policy get/set.
- Create `src/opencobalt/core/usage_optimizer.py`: profile-aware assignment scoring from router scores, benchmark ranking, and usage observations.
- Create `src/opencobalt/core/autonomy_engine.py`: durable long-run runs and task checkpointing.
- Create `src/opencobalt/core/capability_index.py`: local skills, integrations, subagents, and CLI availability discovery.
- Create `src/opencobalt/core/council_protocol.py`: typed council artifact publishing for coordinate, review, ideate, and resolve modes.
- Create `src/opencobalt/core/mission.py`: mission planning, permission validation, ranked plan artifacts, and local checkpointed execution.
- Create `src/opencobalt/core/overlay.py`: `OverlayController`, prompt classification, and dispatch to route, converge, auto, or mission paths.
- Modify `src/opencobalt/core/ledger.py`: add autonomy run, task, and usage observation tables plus access methods.
- Modify `src/opencobalt/core/artifact_bus.py`: add Phase 14 council artifact type constants.
- Modify `src/opencobalt/shell.py`: route plain prompts through `OverlayController`; add `/mission`, `/limits`, and `/policy`.
- Modify `src/opencobalt/cli.py`: add `overlay`, `auto`, `mission`, `limits status`, `policy show`, and `policy set`.
- Add focused tests under `tests/test_autonomy_policy.py`, `tests/test_usage_optimizer.py`, `tests/test_autonomy_engine.py`, `tests/test_capability_index.py`, `tests/test_council_protocol.py`, `tests/test_mission.py`, and `tests/test_overlay.py`; extend shell and CLI tests.

### Task 1: Policy, Usage Optimizer, and Ledger State

**Files:**
- Create: `src/opencobalt/core/autonomy_policy.py`
- Create: `src/opencobalt/core/usage_optimizer.py`
- Modify: `src/opencobalt/core/ledger.py`
- Test: `tests/test_autonomy_policy.py`
- Test: `tests/test_usage_optimizer.py`
- Test: `tests/test_autonomy_tables.py`

- [ ] Write failing tests for default policy, profile behavior, permission envelopes, usage observation persistence, and profile-aware assignment.
- [ ] Run targeted tests and verify they fail because modules and ledger methods do not exist.
- [ ] Add ledger autonomy tables and methods.
- [ ] Add policy and optimizer modules.
- [ ] Run targeted tests and verify they pass.

### Task 2: Capability Index and Council Protocol

**Files:**
- Create: `src/opencobalt/core/capability_index.py`
- Create: `src/opencobalt/core/council_protocol.py`
- Modify: `src/opencobalt/core/artifact_bus.py`
- Test: `tests/test_capability_index.py`
- Test: `tests/test_council_protocol.py`

- [ ] Write failing tests for capability discovery and typed council artifacts.
- [ ] Run targeted tests and verify they fail because modules and artifact constants do not exist.
- [ ] Add capability discovery from registries, subagents, and PATH checks.
- [ ] Add council protocol modes and artifact publishing.
- [ ] Run targeted tests and verify they pass.

### Task 3: Autonomy Engine and Mission Mode

**Files:**
- Create: `src/opencobalt/core/autonomy_engine.py`
- Create: `src/opencobalt/core/mission.py`
- Test: `tests/test_autonomy_engine.py`
- Test: `tests/test_mission.py`

- [ ] Write failing tests for run creation, task checkpointing, resume without rerunning completed tasks, mission permissions, ranked plans, and local allowed actions.
- [ ] Run targeted tests and verify they fail because modules do not exist.
- [ ] Add checkpointed engine using the ledger methods from Task 1.
- [ ] Add mission planner using `CouncilProtocol` and permission envelope checks.
- [ ] Run targeted tests and verify they pass.

### Task 4: Overlay, Shell, and CLI Surfaces

**Files:**
- Create: `src/opencobalt/core/overlay.py`
- Modify: `src/opencobalt/shell.py`
- Modify: `src/opencobalt/cli.py`
- Test: `tests/test_overlay.py`
- Modify: `tests/test_shell.py`
- Modify: `tests/test_cli.py`

- [ ] Write failing tests for prompt classification, overlay dispatch, shell plain prompt routing, `/auto`, `/mission`, `/limits`, `/policy`, and CLI command registration.
- [ ] Run targeted tests and verify they fail because overlay and command surfaces do not exist.
- [ ] Add `OverlayController` with deterministic prompt classification.
- [ ] Wire plain shell prompts and slash commands through overlay surfaces.
- [ ] Add Typer command surfaces with no API calls by default.
- [ ] Run targeted tests and verify they pass.

### Task 5: Integration Verification and Commit

**Files:**
- All Phase 14 files above.

- [ ] Run `.venv/bin/ruff check src/ tests/`.
- [ ] Run `.venv/bin/pytest`.
- [ ] Run `.venv/bin/opencobalt public-check`.
- [ ] Review `git diff` for private paths, credentials, docs em dashes, and unrelated changes.
- [ ] Stage only Phase 14 files and commit with a concise message.
