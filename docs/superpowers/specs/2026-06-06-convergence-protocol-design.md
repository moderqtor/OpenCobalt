# Phase 13: Convergence Protocol

**Date:** 2026-06-06
**Status:** Approved for implementation

---

## Overview

A full artifact protocol for agent-to-agent communication, DAG-based task execution, and autonomous convergence with structured git commits. Agents produce and consume typed artifacts via a SQLite-backed pub/sub bus. A convergence checker applies automatically selected gates (tests, verifier, or both) after each execution wave. When all gates pass, an auto-committer generates a structured commit from session metadata. Sessions checkpoint to SQLite and are resumable.

This replaces `AutonomousRunner` for structured work and extends `OrchestrationExecutor` with artifact-awareness. Both continue to exist; `ConvergenceOrchestrator` is the new top-level coordinator.

---

## 1. Artifact Schema and ArtifactBus

### `ArtifactType` enum

```
impl_code       output from an implementation agent
test_code       output from a test-generation agent
diff            git diff of changes made
review_score    JSON score + feedback from a critic agent
doc_text        documentation or README output
analysis        security, performance, or structural analysis
summary         session or output summary
error_context   failure context fed back to a producing agent on retry
```

### `AgentArtifact` dataclass

```python
@dataclass
class AgentArtifact:
    id: str                     # uuid4
    session_id: str
    iteration: int
    wave: int
    producer: str               # agent id: "claude-impl", "codex-tests", etc.
    type: str                   # ArtifactType value
    content: str
    metadata: dict              # file_paths, language, confidence, score, etc.
    timestamp: float
```

### `ArtifactBus`

SQLite-backed, stored in `.opencobalt/artifacts.db`.

```python
class ArtifactBus:
    def publish(artifact: AgentArtifact) -> None
    def subscribe(types: list[str], session_id: str) -> list[AgentArtifact]
    def latest(type: str, session_id: str) -> AgentArtifact | None
    def context_for(consumes: list[str], session_id: str) -> str
        # builds a prompt context block from all published artifacts matching
        # the given type list for this session
        # each artifact rendered as: "--- <type> from <producer> ---\n<content>"
```

Each `DAGSubTask` declares `produces: list[str]` and `consumes: list[str]`. The orchestrator passes `subtask.consumes` directly to `context_for` -- the bus has no dependency on the agent registry.

**`error_context` artifact:** when tests fail or a verifier rejects output, the failure is published as an `error_context` artifact. All subtasks declare `consumes = [..., "error_context"]`. Since `error_context` artifacts are only published on failure, the context block is empty on first attempt and populated automatically on retry -- no mode-switching required.

---

## 2. DAG Decomposition

### `DAGSubTask` dataclass

Extends the existing `SubTask` with dependency and artifact declarations:

```python
@dataclass
class DAGSubTask:
    id: str
    prompt: str
    task_type: str
    preferred_tool: str
    depends_on: list[str]           # IDs of subtasks that must complete first
    produces: list[str]             # ArtifactType values
    consumes: list[str]             # ArtifactType values
```

### `DAGDecomposer`

Extends existing `TaskDecomposer`. Dependency and artifact declarations are inferred from task type -- no user input required:

| task_type | depends_on           | consumes                        | produces                  |
|-----------|----------------------|---------------------------------|---------------------------|
| impl      | (nothing)            | []                              | [impl_code, diff]         |
| tests     | impl subtasks        | [impl_code]                     | [test_code]               |
| docs      | impl subtasks        | [impl_code]                     | [doc_text]                |
| review    | impl + test subtasks | [impl_code, test_code]          | [review_score]            |
| analyze   | impl subtasks        | [impl_code]                     | [analysis]                |
| summarize | all subtasks         | [impl_code, test_code, doc_text] | [summary]                |

Topological sort produces execution waves. Subtasks with no unresolved dependencies form the next wave and run in parallel.

Example for "implement login with JWT auth":
```
Wave 1 (parallel):  impl-agent [claude]
Wave 2 (parallel):  test-gen [codex] + doc-writer [gemini]
Wave 3:             security-reviewer [claude]
ConvergenceCheck → AutoCommit
```

---

## 3. ConvergenceChecker

### Automatic gate selection

Gate selection is derived from the task types present in the session. No user configuration required:

| task_type        | gates applied                    |
|------------------|----------------------------------|
| impl             | TestsGate + VerifierGate (both)  |
| refactor         | TestsGate only                   |
| tests            | TestsGate only                   |
| docs             | VerifierGate only                |
| review / analyze | VerifierGate only                |
| summarize        | VerifierGate only                |

Sessions with mixed task types apply the union of required gates.

### Gate 1 -- `TestsGate`

```
run: pytest -q
on pass:  gate_ok = True
on fail:  gate_ok = False
          publish error_context artifact:
            content = failing test names + assertion errors + trimmed traceback (50 lines)
          consuming agents see this automatically on retry
```

### Gate 2 -- `VerifierGate`

```
send to critic agent (Gemini if available, else second Claude instance):
  prompt: "Review this diff against the task description.
           Score 0.0-1.0. Reply with JSON only:
           {score: float, approved: bool, feedback: str}"

threshold: 0.75 (stored in .opencobalt config, not per-run)

on score >= 0.75:  gate_ok = True
on score < 0.75:   gate_ok = False
                   publish error_context artifact:
                     content = verifier feedback
                   producing agents see this on retry
```

### `ConvergenceResult` dataclass

```python
@dataclass
class ConvergenceResult:
    passed: bool
    tests_ok: bool | None           # None if gate not applicable
    verifier_ok: bool | None
    verifier_score: float | None
    retry_count: int
    feedback: str                   # human-readable summary for log/display
```

### Retry behavior

- Maximum 3 retries per wave.
- On each retry, `error_context` artifacts from all gate failures are injected into failing agents via `ArtifactBus.context_for()`.
- After 3 failed retries, the subtask is marked `failed`. The session continues with remaining subtasks.
- Partial convergence (some subtasks converged, some failed) still triggers `AutoCommitter` for the converged subset.

---

## 4. AutoCommitter

Runs only when `ConvergenceResult.passed = True`.

### Staging strategy

1. Read `file_paths` from `impl_code` and `test_code` artifact metadata.
2. Stage only files listed in artifact metadata.
3. Fall back to `git diff --name-only` (untracked + modified) if metadata has no paths.
4. Never stage: `.env`, `*.db`, `.opencobalt/`, `__pycache__/`, `*.pyc`.

### Commit message format

```
feat(converge): <seed task truncated to 60 chars>

Convergence session <session_id[:8]>
  waves:      <N>
  retries:    <total retries across all waves>
  agents:     <comma-separated tools used>
  tests:      <N passed> / <N total>
  verifier:   <score>/1.0 (<critic agent>)

Artifacts produced:
  - impl_code    by claude    wave 1
  - test_code    by codex     wave 2
  - doc_text     by gemini    wave 2
  - review_score by claude    wave 3

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
```

### `CommitResult` dataclass

```python
@dataclass
class CommitResult:
    sha: str
    message: str
    files_staged: list[str]
    pushed: bool                    # False unless --push-on-converge
```

The commit SHA is written back to the convergence session record in SQLite. Push to remote requires `--push-on-converge` flag, which is off by default. Pushing is irreversible; the flag must be explicit each time.

---

## 5. ConvergenceOrchestrator

Top-level coordinator. Replaces `AutonomousRunner` for structured work; both continue to exist.

### Execution loop

```
1. Decompose seed task via DAGDecomposer → list[DAGSubTask]
2. Topological sort → execution waves
3. Checkpoint initial session state to SQLite
4. For each wave:
   a. For each subtask in wave:
      - call ArtifactBus.context_for(subtask.consumes, session_id)
      - prepend context to agent prompt
   b. Execute all subtasks in wave in parallel (ThreadPoolExecutor)
   c. Publish each output as typed artifact via ArtifactBus
   d. Run ConvergenceChecker → ConvergenceResult
   e. Checkpoint wave result to SQLite
   f. If passed: run AutoCommitter → done
   g. If failed and retry_count < 3:
      - publish error_context artifacts
      - re-run failing subtasks (not the full wave)
   h. If failed and retry_count == 3: mark subtasks failed, continue
5. After all waves: print summary, write log
```

### `ConvergenceSession` dataclass

```python
@dataclass
class ConvergenceSession:
    id: str
    seed_task: str
    status: str             # queued | running | converged | failed | interrupted
    started_at: float
    finished_at: float | None
    total_waves: int
    total_retries: int
    commit_sha: str | None
    log_path: Path | None
```

### Resumability

On interruption (KeyboardInterrupt, crash), the current wave state is already checkpointed. On `--resume <session_id>`, the orchestrator reads the last completed wave from SQLite, reconstructs the artifact bus state, and continues from the next wave.

---

## 6. CLI and Shell Surface

### CLI commands

```bash
# Single-pass convergence
opencobalt converge "implement login with JWT auth"
opencobalt converge "implement login with JWT auth" --push-on-converge
opencobalt converge --resume <session_id>

# Inspect convergence history
opencobalt converge history
opencobalt converge history --limit 10
opencobalt converge show <session_id>       # artifact tree + wave results

# /auto with convergence mode
opencobalt auto "build a REST API" --converge
```

### Shell slash commands

```
/converge <task>             single-pass convergence with live DAG display
/converge --resume           resume last interrupted session
/auto --converge <task>      long-running convergence loop
```

### Live display format

```
/converge implement login with JWT auth

  ┌─ wave 1 ───────────────────────────────────────────┐
  │ impl     claude    ✓ done    1:12   impl_code       │
  └─────────────────────────────────────────────────────┘
  ┌─ wave 2 ───────────────────────────────────────────┐
  │ tests    codex     ✓ done    0:58   test_code       │
  │ docs     gemini    ⟳ running 0:41   ...             │
  └─────────────────────────────────────────────────────┘
  ┌─ convergence check ────────────────────────────────┐
  │ tests     ✓  47 passed                             │
  │ verifier  ✓  0.87/1.0  (gemini)                   │
  │                                                     │
  │ ✓ converged  →  committing                         │
  └─────────────────────────────────────────────────────┘
```

---

## 7. SQLite Schema

Three new tables. No changes to existing schema.

```sql
CREATE TABLE convergence_sessions (
    id TEXT PRIMARY KEY,
    seed_task TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    started_at REAL NOT NULL,
    finished_at REAL,
    total_waves INTEGER NOT NULL DEFAULT 0,
    total_retries INTEGER NOT NULL DEFAULT 0,
    commit_sha TEXT,
    log_path TEXT
);

CREATE TABLE convergence_artifacts (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    iteration INTEGER NOT NULL DEFAULT 0,
    wave INTEGER NOT NULL DEFAULT 0,
    producer TEXT NOT NULL,
    type TEXT NOT NULL,
    content TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    timestamp REAL NOT NULL,
    FOREIGN KEY (session_id) REFERENCES convergence_sessions(id)
);

CREATE TABLE convergence_wave_results (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    wave INTEGER NOT NULL,
    tests_ok INTEGER,           -- NULL if gate not applicable; 1/0 otherwise
    verifier_score REAL,
    verifier_ok INTEGER,
    passed INTEGER NOT NULL DEFAULT 0,
    retry_count INTEGER NOT NULL DEFAULT 0,
    feedback TEXT NOT NULL DEFAULT '',
    FOREIGN KEY (session_id) REFERENCES convergence_sessions(id)
);
```

---

## 8. New Files

```
src/opencobalt/core/
  artifact_bus.py          ArtifactType, AgentArtifact, ArtifactBus
  dag_decomposer.py        DAGSubTask, DAGDecomposer (extends TaskDecomposer)
  convergence_checker.py   TestsGate, VerifierGate, ConvergenceChecker, ConvergenceResult
  auto_committer.py        AutoCommitter, CommitResult
  convergence_orchestrator.py  ConvergenceOrchestrator, ConvergenceSession

tests/
  test_artifact_bus.py
  test_dag_decomposer.py
  test_convergence_checker.py
  test_auto_committer.py
  test_convergence_orchestrator.py
```

### Modified files

```
src/opencobalt/cli.py              add converge command + --converge flag on auto
src/opencobalt/shell.py            add /converge slash command + --converge on /auto
src/opencobalt/core/ledger.py      create_convergence_tables() called on init
src/opencobalt/core/decomposer.py  DAGDecomposer extends TaskDecomposer here
```

---

## 9. Out of Scope

- LLM-based dependency inference (DAGDecomposer uses keyword rules for now)
- Multi-user or networked artifact bus
- Artifact content diffing or versioning
- Automatic branch creation (commits land on current branch)
- Verifier agent training or fine-tuning
