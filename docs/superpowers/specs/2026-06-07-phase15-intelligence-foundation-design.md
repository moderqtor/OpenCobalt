# Phase 15: Intelligence Foundation -- Telemetry, Scoring, and Export

**Date:** 2026-06-07
**Status:** Approved design, pending implementation plan
**Depends on:** Phase 14 Autonomy Overlay

---

## 1. Product Goal

Phase 15 gives OpenCobalt memory of its own performance. Every run -- shell prompt,
convergence session, autonomy run, mission -- is captured as a telemetry record,
scored across ten dimensions by Ollama-as-judge, and optionally exported to a
configurable markdown directory.

The result is a growing intelligence substrate. Phase 16 will read from it to optimize
routing, prompt style, tool selection, and orchestration order. Phase 15 builds the
foundation that makes that loop possible.

No run is blocked on scoring. Ollama is optional. If unavailable, mechanical dimensions
are computed from heuristics and qualitative dimensions default to 50.

---

## 2. Phase 14 Baseline

Phase 14 shipped:

- `OverlayController` -- classifies and dispatches shell prompts
- `AutonomyEngine` -- long-run task queue with checkpointing
- `MissionPlanner` -- open-ended goal planning and execution
- `UsageOptimizer` -- profile-based tool selection (stub, 56 lines)
- `CapabilityIndex` -- local capability discovery
- `CouncilProtocol` -- typed council artifact modes
- `autonomy_runs`, `autonomy_tasks`, `usage_observations` tables

Phase 15 wraps these entry points with telemetry capture. It does not replace or
refactor them.

The existing `benchmark.py` (`BenchmarkStore`, `BenchmarkRecord`) remains in place for
backward compatibility. Phase 15 introduces a richer parallel store in `telemetry.db`.

---

## 3. Architecture and Data Flow

```
run starts
  -> TelemetrySession created, stored in telemetry.db (status: running)
  -> components call session.record_*(...) during run
run ends
  -> ScoringEngine reads session events
  -> computes heuristic signals
  -> OllamaJudge called with: prompt + output (truncated) + heuristics JSON
  -> Ollama returns: category scores + reasoning + summary
  -> scores written to telemetry_scores
  -> telemetry_runs updated (status: scored, summary set)
  -> (optional) MarkdownExporter writes timestamped .md to configured path
```

`TelemetrySession` is a thin event accumulator -- no business logic. `ScoringEngine`
and `OllamaJudge` are separate so scoring can be triggered independently via
`opencobalt telemetry score <run_id>`.

---

## 4. Schema

New database: `.opencobalt/telemetry.db`

```sql
CREATE TABLE IF NOT EXISTS telemetry_runs (
    id                   TEXT PRIMARY KEY,
    run_type             TEXT NOT NULL,
    seed_prompt          TEXT NOT NULL,
    agent_id             TEXT NOT NULL,
    subagent_id          TEXT,
    model_used           TEXT NOT NULL DEFAULT '',
    started_at           REAL NOT NULL,
    finished_at          REAL,
    status               TEXT NOT NULL,
    raw_output           TEXT,
    token_count_in       INTEGER,
    token_count_out      INTEGER,
    tool_calls_json      TEXT NOT NULL DEFAULT '[]',
    skills_used_json     TEXT NOT NULL DEFAULT '[]',
    connectors_used_json TEXT NOT NULL DEFAULT '[]',
    artifacts_produced   INTEGER NOT NULL DEFAULT 0,
    retry_count          INTEGER NOT NULL DEFAULT 0,
    latency_ms           INTEGER,
    summary              TEXT
);

CREATE TABLE IF NOT EXISTS telemetry_events (
    id           TEXT PRIMARY KEY,
    run_id       TEXT NOT NULL,
    event_type   TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    timestamp    REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS telemetry_scores (
    id                   TEXT PRIMARY KEY,
    run_id               TEXT NOT NULL UNIQUE,
    scored_at            TEXT NOT NULL,
    judge                TEXT NOT NULL,
    overall              INTEGER NOT NULL,
    output_quality       INTEGER,
    prompt_adherence     INTEGER,
    novel_ideation       INTEGER,
    context_handling     INTEGER,
    token_efficiency     INTEGER,
    latency_score        INTEGER,
    tool_appropriateness INTEGER,
    task_decomposition   INTEGER,
    agent_selection      INTEGER,
    convergence_quality  INTEGER,
    judge_reasoning      TEXT,
    heuristics_json      TEXT NOT NULL DEFAULT '{}'
);
```

`run_type` values: `route` | `converge` | `auto` | `mission`

`status` values: `running` | `complete` | `failed` | `scored`

`event_type` values: `tool_use` | `artifact` | `retry` | `output` | `agent_switch` |
`skill_use` | `connector_use` | `gate_pass` | `gate_fail`

`judge` values: `ollama:<model_name>` | `heuristic`

---

## 5. Scoring Categories

Ten categories, each 1-100. `overall` is the weighted composite.

| Category | Weight | Primary signal | Ollama? |
|---|---|---|---|
| `output_quality` | 25% | Correctness, completeness, coherence | yes |
| `prompt_adherence` | 15% | Output addressed what was asked (creative deviation can still score high) | yes |
| `token_efficiency` | 12% | Output value relative to tokens consumed | heuristic only |
| `tool_appropriateness` | 10% | Right tools, skills, connectors for this task type | yes |
| `novel_ideation` | 10% | Useful ideas surfaced beyond the explicit ask | yes |
| `context_handling` | 8% | Available artifacts, files, history well used | yes |
| `latency_score` | 8% | Speed relative to task complexity | heuristic only |
| `task_decomposition` | 6% | Task broken into sensible, well-bounded subtasks | yes |
| `agent_selection` | 5% | Best available agent matched to each subtask | yes |
| `convergence_quality` | 1% | Clean convergence: retries, gate failures, wave count | heuristic only |

`overall` = round(sum(category * weight for each category))

**Heuristics fed to Ollama as context (not scored independently):**

- input/output token ratio
- distinct tool call count
- retry count
- total latency ms
- convergence wave count and gate pass rate
- distinct agents and subagents used

**Fallback scoring when Ollama is unavailable:**

Qualitative categories (`output_quality`, `prompt_adherence`, `novel_ideation`,
`context_handling`, `tool_appropriateness`, `task_decomposition`, `agent_selection`)
default to 50. Mechanical categories (`token_efficiency`, `latency_score`,
`convergence_quality`) are computed from heuristics. `judge` is set to `heuristic`.

---

## 6. OllamaJudge Design

Ollama is called via subprocess, consistent with how OpenCobalt calls all CLIs.

**Model selection:** `opencobalt config set ollama_judge_model <name>`, default `llama3`.

**Output truncation:** raw output capped at 4000 characters before inclusion in prompt.

**Scoring prompt structure:**

```
You are a precise AI output evaluator. Score the following AI task run.

## Original Prompt
{prompt}

## Output
{output_truncated}

## Heuristic Signals
{heuristics_json}

## Instructions
Return ONLY valid JSON with these exact keys. Each value is an integer 1-100.
"reasoning" is a 2-3 sentence explanation of the overall score.
"summary" is a 2-3 sentence description of what was done and the result.

{
  "output_quality": <int>,
  "prompt_adherence": <int>,
  "novel_ideation": <int>,
  "context_handling": <int>,
  "tool_appropriateness": <int>,
  "task_decomposition": <int>,
  "agent_selection": <int>,
  "reasoning": "<string>",
  "summary": "<string>"
}

`token_efficiency`, `latency_score`, and `convergence_quality` are not in the Ollama
prompt -- they are computed from heuristics and merged into the score record after
parsing.

Score strictly. 50 = average. 80+ = genuinely good. 95+ = exceptional.
```

**Response parsing:** extract first `{...}` JSON block from Ollama stdout with
`json.loads`. Missing qualitative keys fall back to 50. Raw Ollama response stored in
`judge_reasoning` regardless of parse result. `summary` goes into
`telemetry_runs.summary`.

---

## 7. MarkdownExporter

Writes one `.md` file per scored run to a configurable directory.

**Configuration:** `opencobalt config set telemetry_export_path <dir>`

If unset, export is skipped with a warning. Export is triggered automatically after
scoring if the path is set, or manually via `opencobalt telemetry export`.

**File naming:** `YYYY-MM-DD_HHMMSS_<run_type>_<run_id[:8]>.md`

**File format:**

```markdown
---
id: <run_id>
date: <ISO timestamp>
run_type: <run_type>
agent: <agent_id>
model: <model_used>
task_type: <run_type>
overall_score: <int>
tags: [<run_type>, <agent_id>]
related: [[<sibling_filename_1>], [[<sibling_filename_2>]]
---

# Run: <seed_prompt>

**Score:** <overall>/100 | **Judge:** <judge>

## Summary
<Ollama-generated summary>

## Scores
| Category | Score |
|---|---|
| Output Quality | <int> |
| Prompt Adherence | <int> |
| Novel Ideation | <int> |
| Context Handling | <int> |
| Tool Appropriateness | <int> |
| Token Efficiency | <int> |
| Latency | <int> |
| Task Decomposition | <int> |
| Agent Selection | <int> |
| Convergence Quality | <int> |

## Reasoning
<judge_reasoning>

## Run Details
- **Tools used:** <tool_calls_json parsed>
- **Skills used:** <skills_used_json parsed>
- **Connectors used:** <connectors_used_json parsed>
- **Retries:** <retry_count> | **Latency:** <latency_ms>ms
- **Tokens:** <token_count_in> in / <token_count_out> out
```

**Related links:** `related` frontmatter lists the 3 most recent files in the same
export directory with the same `run_type`. Computed at export time by scanning existing
filenames -- no external index required. Works natively in Obsidian, Logseq, and any
wikilink-aware markdown tool.

---

## 8. CLI Surface

New `telemetry` command group:

```
opencobalt telemetry status
```
Total scored runs, average overall score, top agent, runs in last 24h, Ollama-scored
vs heuristic-only count.

```
opencobalt telemetry show <run_id>
```
Full breakdown: all 10 category scores, heuristic signals, judge reasoning, tools,
skills, connectors used.

```
opencobalt telemetry scores
```
Leaderboard by agent, broken down by category. Shows which agent leads on output
quality, token efficiency, etc. This is the Phase 16 routing table -- readable now,
actionable in the next phase.

```
opencobalt telemetry score <run_id>
```
Retroactively score a run that has no score yet, or rescore with the current Ollama
model.

```
opencobalt telemetry export [--output <dir>]
```
Export all scored runs to markdown. Uses configured path if `--output` is not given.

```
opencobalt telemetry runs [--limit N] [--agent <id>] [--type <run_type>]
```
List recent telemetry runs with their overall score. Filterable.

**Existing command integration:**

`opencobalt benchmark status` gains a `--telemetry` flag that pulls from
`telemetry_scores` instead of `benchmark_records`, giving category-level detail.
The two stores coexist; `benchmark_records` remains for backward compatibility.

---

## 9. Entry Point Integration

`TelemetrySession` is created at every run boundary. Internals call `record_*` at key
moments. The session is an optional parameter throughout -- existing call paths that
pass `None` are unaffected.

**Primary entry point:** `OverlayController.handle_prompt()` creates the session before
dispatch and triggers `ScoringEngine.score()` after the run ends.

**Direct CLI entry points** (`opencobalt converge`, `opencobalt auto`,
`opencobalt overlay`) create their own session in the CLI handler so telemetry is
captured even when bypassing the interactive shell.

**What records what:**

| Event | Recorder |
|---|---|
| Tool invocation | `OverlayController`, `ConvergenceOrchestrator` |
| Artifact produced | `ArtifactBus.publish()` (one line) |
| Retry | `ConvergenceOrchestrator` |
| Gate pass / fail | `ConvergenceChecker` (one line each) |
| Agent switch | `UsageOptimizer` when it reassigns |
| Skill / connector use | `CapabilityIndex` when it selects a capability |
| Final output | Overlay after run completes |

`ArtifactBus` and `ConvergenceChecker` changes are one-line additions with the session
as an optional parameter. No existing behavior changes.

---

## 10. Proposed Modules

New files:

| File | Responsibility |
|---|---|
| `src/opencobalt/core/telemetry.py` | `TelemetrySession`, `TelemetryStore`, schema |
| `src/opencobalt/core/scoring_engine.py` | `ScoringEngine`, heuristic computation, score assembly |
| `src/opencobalt/core/ollama_judge.py` | `OllamaJudge`, prompt construction, subprocess call, parse + fallback |
| `src/opencobalt/core/markdown_exporter.py` | `MarkdownExporter`, file naming, related-link scan |

Modified files:

| File | Change |
|---|---|
| `src/opencobalt/core/overlay.py` | Create session in `handle_prompt()`, trigger scoring after run |
| `src/opencobalt/core/artifact_bus.py` | `publish()` calls `session.record_artifact()` if session present |
| `src/opencobalt/core/convergence_checker.py` | Gate pass/fail calls `session.record_event()` if session present |
| `src/opencobalt/core/convergence_orchestrator.py` | Accept optional session, record retries and tool calls |
| `src/opencobalt/core/autonomy_engine.py` | Accept optional session |
| `src/opencobalt/core/mission.py` | Accept optional session |
| `src/opencobalt/core/capability_index.py` | Record skill/connector selection if session present |
| `src/opencobalt/core/usage_optimizer.py` | Record agent switch if session present |
| `src/opencobalt/cli.py` | Add `telemetry` command group |

---

## 11. Testing

All tests use `tmp_path` for SQLite isolation. `OllamaJudge` is patched in all tests.

Coverage targets:

- `TelemetrySession`: record events, finish run, verify rows in all three tables
- `ScoringEngine`: seeded run + events produce correct weighted overall; fallback scores on malformed Ollama JSON
- `OllamaJudge`: scoring prompt construction; JSON parse with good output; fallback on parse failure; output truncation at 4000 chars
- `MarkdownExporter`: correct filename; expected frontmatter keys; score table present; related-link generation with sibling files
- `TelemetryStore`: CRUD for all three tables; retroactive scoring path
- CLI: `telemetry status`, `telemetry show`, `telemetry scores`, `telemetry runs` via `CliRunner`
- Integration: `OverlayController.handle_prompt()` with mocked runners creates a telemetry run and triggers scoring

Regression guard: all 508 existing tests must stay green. `ArtifactBus` and
`ConvergenceChecker` changes use optional parameters; existing tests pass `None`
implicitly.

---

## 12. Acceptance Criteria

Phase 15 is complete when:

1. Every `OverlayController.handle_prompt()` call produces a `telemetry_runs` row.
2. `ScoringEngine` produces a `telemetry_scores` row with all 10 categories after every run.
3. Ollama-judged runs include non-default qualitative scores and a reasoning paragraph.
4. Heuristic fallback produces a valid score record when Ollama is unavailable.
5. `MarkdownExporter` writes a correctly formatted `.md` file to the configured path.
6. Related links in exported files point to real sibling files of the same run type.
7. All six `opencobalt telemetry` subcommands work.
8. `opencobalt benchmark status --telemetry` shows category-level scores.
9. `ArtifactBus`, `ConvergenceChecker`, `ConvergenceOrchestrator`, `AutonomyEngine`,
   `MissionPlanner`, `CapabilityIndex`, and `UsageOptimizer` record events when a
   session is present and are unaffected when it is not.
10. All existing 508 tests remain green. New tests cover all modules listed above.

---

## 13. Known Gaps

**Token counting:** `token_count_in` and `token_count_out` in `telemetry_runs` depend
on CLI tools emitting token usage in parseable output. Claude Code, Codex, and Gemini
do not guarantee this in subprocess mode. In Phase 15, these fields are populated on a
best-effort basis: `TelemetrySession.record_output()` accepts an optional `token_count`
parameter, and callers populate it when available. When unavailable, the fields are
NULL and `token_efficiency` falls back to a proxy heuristic (output character length
divided by input character length). Accurate token counts are deferred to Phase 16 when
structured output parsing or API adapters may be enabled.

---

## 15. Out of Scope

- Phase 16 optimization loop (scores influencing routing, prompt style, tool selection)
- Prompt optimization algorithms
- Obsidian-specific features beyond generic wikilink frontmatter
- Real-time streaming telemetry
- Required Ollama dependency (always optional with graceful fallback)
- API-based LLM judging
- Cross-session trend analysis UI
- Fine-tuning on telemetry data

---

## 16. Guardrails

OpenCobalt policy still applies:

- SQLite is the source of truth for telemetry
- No background daemons; scoring runs synchronously at run end
- No required external database
- Ollama is optional; no run is blocked on its availability
- No credentials in exported markdown files
- `opencobalt public-check` must pass after any doc or config change
- No API usage by default
