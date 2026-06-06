# Phase 11: Multi-Agent Orchestration DSL

**Date:** 2026-06-05  
**Status:** Approved  
**Scope:** Multi-agent simultaneous routing with orchestration DSL, parallel executor, specialized subagent registry, and subagent benchmarking

---

## 1. Product goal

Route a single complex task to multiple specialized agents simultaneously, collect their outputs, synthesize a result, and log the full fan-out as a `MultiRouteDecision` in the ledger. The user gains real parallelism across their installed AI subscriptions (Claude Code, Codex CLI, Gemini CLI, Ollama) without writing a pipeline manually.

---

## 2. Architecture

```
User input (shell /orch)
       |
  TaskDecomposer          -- keyword-based, no LLM required
       |
  [SubTask, SubTask, ...]  -- typed: impl, tests, docs, review, analyze, summarize
       |
  SubagentRegistry         -- best specialized agent per task type
       |
  OrchestrationExecutor    -- DAG executor using BackgroundRunner
  |         |         |
impl-agent  test-gen  analyst-agent   (all run simultaneously)
  |         |         |
  ResultSynthesizer        -- merges outputs with attribution headers
       |
  /verify (optional terminal step)
       |
  MultiRouteDecision       -- persisted to ledger
```

---

## 3. DSL syntax

Explicit form:

```
/orch "implement OAuth2 with tests and docs" -> [claude:impl, codex:tests, gemini:analyze] -> merge -> /verify
```

Auto-decompose shorthand (just supply the task):

```
/orch "implement OAuth2 with tests and docs"
```

In auto mode, `TaskDecomposer` splits the task into typed subtasks, `SubagentRegistry` picks the best agent per type, and `OrchestrationExecutor` fans out in parallel.

Auto-detection hint: if a task's keyword scores exceed threshold on two or more tool profiles from different tiers, the shell surfaces a `[multi]` badge and suggests `/orch`.

---

## 4. New files

| File | Responsibility |
|---|---|
| `src/opencobalt/core/orchestrator.py` | `OrchestrationSession`, `OrchestrationExecutor`, `ResultSynthesizer`, DSL parser |
| `src/opencobalt/core/decomposer.py` | `TaskDecomposer` -- keyword split into typed subtasks |
| `src/opencobalt/core/subagent_registry.py` | `SubagentRegistry` with specialized agent declarations |

---

## 5. New models (added to `core/models.py`)

```python
class SubTask(BaseModel):
    id: str = Field(default_factory=_uid)
    task_type: str          # "impl", "tests", "docs", "review", "analyze", "summarize"
    prompt: str
    preferred_tool: str
    preferred_agent: str | None = None

class OrchestrationResult(BaseModel):
    id: str = Field(default_factory=_uid)
    timestamp: datetime = Field(default_factory=_now)
    task: str
    subtasks: list[SubTask]
    outputs: dict[str, str]   # subtask_id -> output text
    synthesis: str
    elapsed_s: float
    success: bool
    errors: list[str] = Field(default_factory=list)

class MultiRouteDecision(BaseModel):
    id: str = Field(default_factory=_uid)
    timestamp: datetime = Field(default_factory=_now)
    task: str
    subtasks: list[SubTask]
    tools_used: list[str]
    result_id: str
    metadata: dict[str, Any] = Field(default_factory=dict)
```

---

## 6. Subagent registry

| agent_id | specialization | tier | tool |
|---|---|---|---|
| `impl-agent` | code implementation | executive | claude-code |
| `test-gen` | test generation | manager | codex-cli |
| `doc-writer` | documentation | manager | codex-cli |
| `security-reviewer` | security audit | executive | claude-code |
| `analyst-agent` | long-context analysis, audit, cross-file search | executive | gemini-cli |
| `summarizer` | summarization | worker | ollama |

Gemini CLI (`analyst-agent`) is dispatched for subtasks typed as `audit`, `analyze`, or `search`. This distributes load across executive-tier subscriptions and takes advantage of Gemini's large context window.

Each subagent declares: `agent_id`, `specialization`, `tier`, `tool`, `task_types: list[str]`, `prompt_template: str`.

---

## 7. Ledger extension

New method on `Ledger`:

```python
def insert_multi_route_decision(self, decision: MultiRouteDecision) -> None: ...
def list_multi_route_decisions(self, limit: int = 20) -> list[MultiRouteDecision]: ...
```

Schema: new `multi_route_decisions` table with columns mirroring `MultiRouteDecision` fields. `subtasks` and `tools_used` stored as JSON blobs. No breaking change to existing tables.

---

## 8. BenchmarkRecord extension

Two new nullable columns added to `benchmark_records`:

- `subagent_id TEXT` -- which specialized agent produced this result
- `prompt_style TEXT` -- short label for the prompt form used (e.g. "bullet", "imperative", "narrative")

These allow `benchmark status` to break down win rates per subagent type and per prompt style, not just per top-level tool.

---

## 9. Shell integration

New slash command registered in `CobaltShell._CLI_COMMANDS`:

```
/orch   -- run orchestration DSL expression or auto-decompose a task
```

`_run_command` dispatches to `self._run_orch(args)`. `_route_and_open` gains a multi-route hint: when keyword scores span two or more tiers above threshold, it prints `[multi] try /orch` before opening the single-tool recommendation.

---

## 10. Execution and error handling

`OrchestrationExecutor.run()`:
1. Dispatches all subtasks via `BackgroundRunner` simultaneously
2. Waits for all futures with a configurable timeout (default 120s per subtask)
3. If a subtask's tool binary is not on PATH, marks that slot `[skipped]` and continues
4. `OrchestrationResult.success = True` if at least one subtask completed without error
5. `merge` stage: `ResultSynthesizer` concatenates outputs with `## [agent_id]` attribution headers
6. `verify` stage (optional): calls existing `verify_async()`

---

## 11. Tests

| File | What it covers |
|---|---|
| `tests/test_decomposer.py` | Keyword split produces correct task types for representative inputs |
| `tests/test_orchestrator.py` | Executor fans out in parallel, handles skipped agents, returns `OrchestrationResult` |
| `tests/test_subagent_registry.py` | Registry lookup by task type, graceful miss on unknown type |
| `tests/test_multi_route_ledger.py` | `insert_multi_route_decision()` persists and round-trips correctly |
| `tests/test_shell_orch.py` | `/orch` dispatch parses DSL expression and calls executor |

All tests use `tmp_path` for SQLite isolation. Subprocess calls to real binaries are patched in unit tests. Baseline test count must remain passing; new tests are required for all new code.

---

## 12. What is NOT in scope for Phase 11

- Autonomous multi-agent loops (agents spawning agents without user direction)
- LLM-based task decomposition (decomposer is keyword-only)
- Cross-agent real-time communication (outputs are merged post-completion, not streamed between agents)
- Remote/hosted orchestration
- Changes to existing Pipeline, CouncilSession, or DebateSession APIs
