# Phase 14: Autonomy Overlay and Long-Run Mission Runtime

**Date:** 2026-06-06
**Status:** Finalized design, pending implementation plan
**Depends on:** Phase 13 Convergence Protocol

## 1. Product Goal

OpenCobalt becomes the primary local-first CLI overlay for long-running AI work.
The user opens the interactive shell with:

```bash
opencobalt
```

Then they type plain prompts and slash commands. OpenCobalt decides whether the prompt
should be a single route, an orchestrated convergence run, a long-run autonomous session,
or an open-ended mission. The system decomposes work, assigns it to Claude Code, Codex CLI,
Gemini CLI, Ollama, specialized subagents, local skills, integrations, connectors, and
plugin surfaces, then coordinates progress through SQLite-backed artifacts.

The product goal is not just "run yolo flags." OpenCobalt should provide a durable autonomy
runtime that gets high value from the user's paid CLI usage limits while remaining local
first, inspectable, resumable, and policy controlled.

No provider API is used by default. OpenCobalt uses local CLI overlays and deterministic
routing unless API adapters are explicitly enabled with:

```bash
opencobalt config set api_enabled true
```

## 2. Phase 13 Baseline

Phase 13 introduced the right substrate for Phase 14:

- `ArtifactBus` in `.opencobalt/artifacts.db`
- `DAGDecomposer`
- `ConvergenceChecker`
- `ConvergenceOrchestrator`
- convergence session and wave tables in the ledger
- `opencobalt converge`
- `/converge`
- auto-commit after convergence
- optional push support in the active working tree

Phase 14 should wrap and extend these pieces. It should not replace them.

The Phase 13 artifact bus becomes the coordination substrate. The Phase 13 convergence
loop becomes the completion primitive. Phase 14 adds the default shell overlay, autonomy
profiles, long-run scheduling, usage-limit optimization, council coordination, and mission
planning around those primitives.

## 3. Phase 13 Stabilization Required First

Before Phase 14 implementation planning starts, the Phase 13 surface should be tightened.
The review after commit `bdc4a06` found these concrete issues:

1. `ruff check src/ tests/` currently fails on Phase 13 files and tests.
2. `tests/test_shell.py::test_dispatch_plain_prompt_calls_router` leaks background pytest
   processes because plain prompt dispatch schedules `verify_async` without patching it.
3. `ConvergenceOrchestrator` sets `session.commit_sha` after commit but does not persist the
   updated session, so `converge history` and `converge show` may omit the commit SHA.
4. `AutoCommitter._fallback_files()` uses `git diff --name-only HEAD`, which misses untracked
   files. Since Phase 13 artifacts currently do not publish `file_paths`, new generated files
   may not be committed.
5. Resume currently reuses a session id and reruns from the beginning. It does not reconstruct
   completed waves or continue from the next unfinished wave.
6. `AutoCommitter` does not check `git add` or `git commit` return codes before reading `HEAD`.
   A failed commit can be reported as if it produced a new commit.

These are Phase 13 stabilization tasks, not Phase 14 scope. Phase 14 should depend on them
being fixed or explicitly accepted as known limitations.

## 4. Primary Interface

The interactive shell is the main product surface.

Shell examples:

```text
build the auth module with tests and docs
/auto --hours 5 --use-limits aggressive finish this feature end to end
/mission --hours 5 make me money
/council coordinate
/limits status
/agents status
/policy show
/commit
/push
```

Exec-style commands still exist for scripting, tests, and CI:

```bash
opencobalt overlay "build the auth module with tests and docs"
opencobalt auto "finish this feature" --hours 5 --use-limits aggressive
opencobalt mission "make me money" --hours 5 --profile max
opencobalt limits status
```

The shell should feel closer to Codex CLI or Claude Code than to a collection of one-off
subcommands. Plain prompts should be first-class inputs.

## 5. Default Prompt Flow

Plain prompts should pass through `OverlayController`.

```text
plain prompt
  -> OverlayController
  -> PromptClassifier
  -> AutonomyPolicy
  -> AssignmentPlanner
  -> single route, convergence run, auto run, or mission run
```

Default decision rules:

- Low-risk single-action prompts use the existing deterministic router.
- Multi-part implementation prompts use convergence by default.
- Long-running prompts with time or usage directives use autonomous mode.
- Open-ended outcome prompts use mission mode.
- Prompts involving external-world actions require a permission envelope.

Example classifications:

| Prompt | Default handling |
|--------|------------------|
| `summarize this log` | single route |
| `build auth with tests and docs` | convergence |
| `/auto --hours 5 finish the app` | long-run autonomy |
| `/mission make me money` | mission planning plus permission checks |

## 6. Autonomy Policy

Autonomy is a core subsystem. It decides what OpenCobalt may do without asking again during
a run.

Default policy:

- Auto-test: on
- Auto-retry: on
- Auto-commit: on after convergence passes
- Auto-push: off unless explicitly enabled for that run
- Auto-ideate next tasks: on in long-run modes
- Auto-use relevant local skills, connectors, integrations, and plugin surfaces: on
- API usage: off unless explicitly configured
- External-world actions: controlled by a run-level permission envelope

Auto-commit should be default-on after gates pass. Push remains explicit for each run.

The policy engine should be data driven, stored in SQLite-backed config, and inspectable:

```text
/policy show
/policy set auto_commit true
/policy set push_requires_explicit true
```

## 7. Autonomy Profiles

Phase 14 introduces run profiles. Profiles tune risk, tool usage, retry behavior, and how
aggressively OpenCobalt keeps paid CLI tools busy.

| Profile | Behavior |
|---------|----------|
| `balanced` | Spread work across tools and avoid exhausting one provider early |
| `aggressive` | Keep high-value tools busy when useful work exists |
| `max` | Use every available paid CLI heavily for the chosen run window |
| `cheap` | Prefer local/Ollama and manager-tier tasks |
| `executive` | Bias Claude and Gemini for architecture, review, strategy, and high-risk work |

Example:

```text
/auto --hours 5 --use-limits max build the best version of this app
```

Profile behavior should be explicit in the run summary so the user can inspect why a tool
was or was not used.

## 8. Long-Run Runtime

Long-run mode should be able to use several hours of paid CLI usage limits on one goal when
the user chooses that profile.

Runtime responsibilities:

- keep useful available agents busy
- maintain a durable task queue
- detect stalls, crashes, prompts, throttling, and missing binaries
- checkpoint all state to SQLite
- resume interrupted sessions
- compress context between waves
- route subtasks to the best available primary tool and subagent
- run convergence gates after meaningful work
- auto-commit converged increments
- generate next tasks until the mission completes or the time limit expires

Long-run state should include:

- run id
- seed goal
- profile
- allowed actions
- denied actions
- active tasks
- completed tasks
- failed tasks
- artifacts produced
- tools used
- usage observations
- commits created
- next-task candidates

## 9. Usage-Limit Optimizer

The usage-limit optimizer should maximize value from paid CLI plans without wasteful
duplication.

It should track:

- tool availability
- observed latency
- success rate by task type
- retry rate
- verifier score
- current usage pressure
- cooldown and throttle signals
- context size
- output quality
- benchmark ranking by primary agent
- benchmark ranking by subagent

The optimizer does not need direct account scraping in Phase 14. It can start with observed
runtime signals:

- command exits indicating rate limit or usage limit
- long idle periods
- repeated failures from one tool
- manual user notes in config
- time since last successful call per tool

Routing should combine:

- deterministic router scores
- task type
- risk tier
- benchmark history
- current availability
- profile preference
- context size

## 10. Token Efficiency

The overlay should avoid sending the whole repo or whole session history to every tool.

Context strategy:

- send only task-relevant files and artifacts
- summarize older artifacts into durable memory
- pass artifact ids and concise summaries where possible
- include full content only when an agent needs it
- prefer Gemini for long-context analysis when appropriate
- prefer Codex for tests, lint, and structured cleanup
- prefer Claude for architecture, high-risk implementation, and final review
- keep Ollama limited to summaries, tagging, extraction, and rough internal drafts

The artifact bus should be the canonical intermediate state. Prompt text should be rebuilt
from relevant artifacts, not copied forward wholesale.

## 11. Council Protocol

Phase 13 provides artifact-based retry context, but it does not fully overhaul `council`.
Phase 14 should define the council protocol as the structured coordination layer.

Current council behavior:

- ask multiple models in parallel
- synthesize agreements and disagreements
- optionally save a result

Target council behavior:

- coordinate active agents during a run
- publish typed claims, objections, risks, decisions, handoffs, approvals, and ideas
- let later waves consume council artifacts
- resolve conflicts through critic and synthesis agents
- support ideation for follow-up task generation

Council should not become unlogged free-form chat between CLIs. OpenCobalt mediates
communication through SQLite artifacts so the run remains inspectable, resumable, and
auditable.

New artifact types:

```text
proposal
objection
question
answer
claim
decision
handoff
blocked
approval
risk
idea
ranked_plan
```

Council modes:

| Mode | Purpose |
|------|---------|
| `advise` | Existing parallel advice plus synthesis |
| `coordinate` | Active run coordination between agents |
| `review` | Critic agents inspect outputs and publish objections |
| `ideate` | Agents generate, compare, and rank next tasks or business ideas |
| `resolve` | Settle conflicts between artifacts or agent recommendations |

## 12. Mission Mode

Mission mode handles open-ended goals such as:

```text
/mission --hours 5 make me money
```

Mission flow:

```text
seed goal
  -> ideation council
  -> candidate plans
  -> deterministic ranking
  -> selected mission plan
  -> DAG execution
  -> convergence checks
  -> auto-commit
  -> next-step ideation
  -> repeat
```

OpenCobalt may autonomously:

- brainstorm ideas
- research public web pages if browser tools are allowed
- build local code
- draft content
- generate landing pages
- create local assets
- produce outreach drafts
- prepare launch plans
- commit local code after verification

External-world actions require a run-level permission envelope.

Restrictive example:

```text
/mission --hours 5 "make me money" \
  --allow web-research,local-build,draft-content,github-commit \
  --deny purchases,messages,account-actions,billing,publish
```

More permissive example:

```text
/mission --hours 5 "launch a micro-SaaS landing page" \
  --allow web-research,local-build,github-commit,deploy-preview \
  --deny purchases,messages,billing
```

Actions requiring explicit run-level permission:

- submitting forms
- sending messages
- publishing public content
- creating or modifying hosted deployments
- spending money
- account settings changes
- billing actions
- logged-in browser automation

## 13. Capability Discovery

OpenCobalt should maintain a local capability index across agents, skills, integrations,
connectors, and plugins.

Example model:

```python
Capability(
    id="codex:superpowers:test-driven-development",
    provider="codex-cli",
    type="skill",
    task_types=["tests", "impl"],
    risk_level="manager",
    available=True,
)
```

Discovery sources:

- OpenCobalt `skills/registry.py`
- OpenCobalt `integrations/registry.py`
- OpenCobalt `SubagentRegistry`
- installed Claude Code agents and local config if discoverable
- installed Codex skills and plugins if discoverable
- installed Gemini CLI capabilities if discoverable
- PATH checks for CLI tools
- configured MCP connectors and local app connectors

Execution rule: OpenCobalt should not call provider APIs by default. It passes prompts to
local CLI tools and instructs each tool to use the relevant capabilities available inside
that tool.

## 14. Proposed Modules

New modules:

| File | Responsibility |
|------|----------------|
| `src/opencobalt/core/overlay.py` | `OverlayController`, prompt handling, default dispatch |
| `src/opencobalt/core/autonomy_policy.py` | run policy, permission envelopes, defaults |
| `src/opencobalt/core/autonomy_engine.py` | long-run task queue, watchdog, resume, checkpoints |
| `src/opencobalt/core/usage_optimizer.py` | profile-based tool selection and usage observations |
| `src/opencobalt/core/capability_index.py` | skills, connectors, plugins, integrations, subagents |
| `src/opencobalt/core/council_protocol.py` | typed council artifacts and modes |
| `src/opencobalt/core/mission.py` | open-ended mission planning and execution loop |

Modified files:

| File | Change |
|------|--------|
| `src/opencobalt/shell.py` | route plain prompts through `OverlayController`; add new slash commands |
| `src/opencobalt/cli.py` | add `overlay`, `mission`, `limits`, and policy command surfaces |
| `src/opencobalt/core/artifact_bus.py` | add council artifact types or generic artifact registration |
| `src/opencobalt/core/benchmark.py` | expose assignment ranking by task type and subagent |
| `src/opencobalt/core/ledger.py` | add long-run session tables if not stored in existing convergence tables |

## 15. Data Model Additions

Suggested SQLite-backed tables:

```sql
autonomy_runs (
    id TEXT PRIMARY KEY,
    seed_goal TEXT NOT NULL,
    profile TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at REAL NOT NULL,
    finished_at REAL,
    allowed_actions_json TEXT NOT NULL DEFAULT '[]',
    denied_actions_json TEXT NOT NULL DEFAULT '[]',
    active_session_id TEXT,
    summary TEXT NOT NULL DEFAULT ''
);

autonomy_tasks (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    parent_task_id TEXT,
    task_type TEXT NOT NULL,
    prompt TEXT NOT NULL,
    preferred_tool TEXT,
    preferred_subagent TEXT,
    status TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    started_at REAL,
    finished_at REAL,
    artifact_ids_json TEXT NOT NULL DEFAULT '[]'
);

usage_observations (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    tool TEXT NOT NULL,
    event_type TEXT NOT NULL,
    task_type TEXT,
    latency_ms INTEGER,
    success INTEGER,
    message TEXT NOT NULL DEFAULT '',
    timestamp REAL NOT NULL
);
```

## 16. Acceptance Criteria

Phase 14 is complete when:

1. Plain shell prompts pass through `OverlayController`.
2. Single-route behavior still works for simple prompts.
3. Multi-part implementation prompts default to convergence.
4. `/auto --hours N --use-limits PROFILE` runs through the long-run autonomy engine.
5. `/mission` can create a ranked plan, execute local allowed actions, and checkpoint state.
6. Auto-commit is default-on after passing gates.
7. Auto-push is still explicit per run.
8. Council coordinate, review, ideate, and resolve modes publish typed artifacts.
9. Capability discovery lists local agents, subagents, skills, integrations, and available CLI tools.
10. Usage observations influence assignment after benchmark data exists.
11. Long-run sessions can resume without rerunning completed work.
12. Tests cover policy gates, assignment decisions, council artifacts, mission permissions, and shell dispatch.

## 17. Out of Scope

- Hosted service mode
- Required API usage
- Direct account scraping for exact paid-plan quota
- Required browser automation
- Required Docker, Postgres, Redis, Qdrant, or external databases
- Silent purchases, messages, deployments, or account changes
- Fine-tuning verifier agents

## 18. Guardrails

OpenCobalt policy still applies:

- no API usage by default
- SQLite remains the source of truth
- no background daemons
- no required external database
- no required Ollama dependency
- no push without explicit instruction
- no credentials in output files
- no private vault paths in public-facing docs
- no irreversible external-world action without a run-level permission envelope

The system should be ambitious, but every autonomous action must be logged, resumable, and
explainable from SQLite state.
