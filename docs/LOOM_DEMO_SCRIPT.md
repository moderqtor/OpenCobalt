# Demo Script

Target: 3 to 5 minutes. No slides. Just terminal and code.

---

## Opening (15 seconds)

"I built OpenCobalt because I was using five different AI tools every day -- Claude Code, Codex, Gemini, Cursor, and local Ollama -- and I had no memory of what happened, no log of what each tool produced, and no consistent way to decide which tool to use for a given task. This is what I built to solve that."

---

## Status (20 seconds)

Show: `opencobalt status`

"This is the status command. It shows Python version, whether Ollama is running and what models are installed, the state of the local ledger, and a public safety scan. The health bar at the top gives you a quick visual read of system state."

"All of this is local. No cloud, no API calls beyond what you explicitly route."

---

## Routing: Executive Tier (30 seconds)

Show: `opencobalt route "design the auth module"`

"I tell it what I need to do. It returns a score table showing how each tool scored against this task. Architecture work scores as executive tier and routes to Claude Code."

Show: `opencobalt route "summarize the logs"`

"Now a summarization task. That routes to Ollama -- local model, worker tier. The system distinguishes between tasks that need a serious model and tasks that don't."

"The router is deterministic. Keyword scoring, no LLM in the loop. Fast, testable, and every decision is explainable."

---

## Benchmark (20 seconds)

Show: `opencobalt benchmark`

"Benchmark runs a standard set of tasks through the router and shows the tier breakdown. This is how I verify that routing behavior has not drifted as I add new task patterns."

---

## Agents (40 seconds)

Show: `opencobalt agents list`

"Four registered agents: code-reviewer, summarizer, tagger, and file-reader. Each has a tier assignment and a description."

Show: `opencobalt agents run code-reviewer src/opencobalt/core/router.py`

"This runs the code-reviewer agent against a real file. It uses the file-reader skill under the hood to extract actual metrics: line count, function count, and a complexity estimate from the source. Not stub output."

---

## Session Tracking (30 seconds)

Show: `opencobalt session start "demo"`

Show: `opencobalt route "refactor the ledger module"`

Show: `opencobalt route "write unit tests for the router"`

Show: `opencobalt session show`

"Sessions tag every route decision with a session ID. At the end of a session I can see exactly what was routed, in order, with scores and tool assignments. That is the audit trail."

---

## Analytics (20 seconds)

Show: `opencobalt stats`

"Stats pulls from the ledger. Tool usage breakdown, tier distribution, recent route decisions. This is what makes the ledger useful -- not just storage, but something you can query."

---

## Verification (20 seconds)

Show: `opencobalt verify`

"174 tests. Units, ledger integration, router logic, CLI commands. The verify command runs the full suite and shows pass or fail."

---

## Doctor (15 seconds)

Show: `opencobalt doctor`

"Doctor checks Python version, Ollama availability, ledger integrity, and public safety scan. All green."

---

## Close (20 seconds)

"What I am demonstrating is not the AI tools themselves. It is infrastructure for working with AI tools: routing, logging, session tracking, verification, public hygiene. That engineering problem exists at any company using AI-assisted development at scale."

"The skills here are systems design, test discipline, and understanding what AI tools are good at versus where they need oversight."
