# Quickstart -- be useful in 5 minutes

## What this does

You use multiple AI tools and agent runtimes (Google Antigravity CLI, Claude Code,
Codex, Cursor, Ollama) and lose context between sessions. OpenCobalt routes your
tasks to the right runtime, logs everything to a local SQLite ledger, and lets you
search your own history.

No API calls by default. No cloud services. Runs and exits like a normal CLI.

---

## Install

```bash
git clone https://github.com/moderqtor/OpenCobalt
cd OpenCobalt
pip install -e ".[dev]"
```

Requires Python 3.11+. Ollama is optional -- the router and ledger work without it.

---

## Your first 5 minutes

### Step 1 -- build a context pack

```bash
opencobalt context
```

Compiles README, docs, and source files into `.opencobalt/context/latest.md`.
Paste that file (or pipe it) into any agent session as your project briefing:

```bash
cat .opencobalt/context/latest.md | pbcopy   # macOS -- now paste into Claude Code
```

This is the first tangible artifact. It replaces the mental overhead of re-explaining
your project every session.

### Step 2 -- check what is running

```bash
opencobalt status
```

Shows Python version, Ollama availability, ledger row counts, docs, and a safety scan.
All green means everything is ready.

### Step 3 -- route a real task

```bash
opencobalt route "refactor the authentication module"
```

Prints a score table across all tools and recommends the best one. No LLM calls --
routing is deterministic and free. Route decisions log to the ledger automatically.

### Step 4 -- log what you did

```bash
opencobalt note "refactored auth, used Claude Code, split into 3 functions"
```

Stores a timestamped note in the memory bridge. Searchable later.
Add optional tags: `--tags auth,refactor` or agent attribution: `--agent claude-code`.

### Step 5 -- review your day

```bash
opencobalt day
```

Shows routes taken, notes logged, estimated cost, and session time range for today.
Pass `--date 2026-06-01` to review any past date.

### Step 6 -- search your memory

```bash
opencobalt memory search "auth"
```

Finds everything you logged about auth across all sessions.

### Step 7 -- open the dashboard

```bash
opencobalt ui
```

Starts a FastAPI server (port 8000) and React dashboard (port 5173). Opens in browser.
Shows session history, agent stats, route decisions, and cost. Ctrl+C to stop.

---

## The loop

```
opencobalt route "your task"    # find the right tool
[do the work in that tool]
opencobalt note "what you did"  # log the result
opencobalt day                  # review today
opencobalt memory search "..."  # find it later
```

Route, work, log, search. That's it.

---

## The session loop (for longer work)

```bash
opencobalt session start "auth-refactor"
# ... work across Google Antigravity, Claude Code, Codex ...
opencobalt note "split auth into 3 modules, decided against JWT"
opencobalt session end
```

Session decisions are tagged and grouped. `opencobalt history` and `opencobalt stats`
show breakdowns by session, tier, and tool.

---

## All commands

```
# Routing
opencobalt route TASK              Route a task -- deterministic, no LLM calls
opencobalt route TASK --verbose    Show matched keywords per tool
opencobalt route TASK --estimate   Show estimated API cost per tier
opencobalt history                 Show recent route decisions
opencobalt stats                   Ledger analytics: tier breakdown, top tools
opencobalt benchmark               Route 10 representative tasks, show breakdown

# Logging
opencobalt note TEXT               Log a free-text note with timestamp
opencobalt note TEXT --agent NAME  Attribute to a specific agent
opencobalt note TEXT --tags a,b    Tag the note
opencobalt day                     Summary of today's routes, notes, cost
opencobalt day --date YYYY-MM-DD   Summary for a specific date
opencobalt log --summary TEXT      Write a session event to the ledger
opencobalt log-list                List recent ledger events

# Memory
opencobalt memory status           Memory store info and row counts
opencobalt memory add TEXT         Write a memory record to the ledger
opencobalt memory search QUERY     Search the bridge memory store
opencobalt memory export           Export memory to markdown

# Context
opencobalt context                 Build context pack to .opencobalt/context/latest.md
opencobalt context-diff            Show what changed since the last build

# Sessions
opencobalt session start NAME      Start a named work session
opencobalt session show            Show active session and its decisions
opencobalt session end             End the active session

# Verification
opencobalt verify                  Run pytest + public-check, record results
opencobalt public-check            Pre-push safety scan
opencobalt lint                    Ruff lint on src/ and tests/

# Agents and skills
opencobalt agents list             List registered agents
opencobalt agents run NAME TASK    Run an agent against a task
opencobalt skills list             List registered skills

# Integrations
opencobalt integrations list       List all integrations with tier and status
opencobalt integrations check      Check which tools are installed and on PATH

# Cost
opencobalt cost status             Monthly spend, cap, routing mode
opencobalt cost set-mode MODE      Set mode: cheap, standard, frontier
opencobalt cost reset              Clear monthly cost records

# Config
opencobalt config set KEY VALUE    Set a config value
opencobalt config get KEY          Get a config value
opencobalt config list             List all config keys

# System
opencobalt status                  Full system health check
opencobalt doctor                  Extended health check with CI and examples
opencobalt doctor antigravity      Inspect local agy runtime discovery
opencobalt tui                     Live 4-panel terminal dashboard
opencobalt ui                      Start React dashboard + FastAPI server
opencobalt export                  Export full ledger to markdown
opencobalt benchmark status        Agent leaderboard
opencobalt benchmark record        Record a benchmark result manually
```

---

## Optional: Ollama (local model agents)

Install from [ollama.ai](https://ollama.ai), then:

```bash
ollama pull llama3
```

With Ollama running, the summarizer and tagger agents use it for worker-tier tasks.
The router and ledger work without Ollama.

---

## What is next

- Full architecture: `docs/ARCHITECTURE.md`
- How routing works: `docs/TOOL_ROUTING.md`
- Integration setup: `docs/INTEGRATIONS.md`
- Google Antigravity migration: `docs/ANTIGRAVITY.md`
- Khoj second brain: `docs/KHOJ_INTEGRATION.md`
