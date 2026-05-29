# Demo Script

Target: under 3 minutes. No slides. Just terminal and code.

---

## Opening (15 seconds)

"I built OpenCobalt because I was using five different AI tools every day -- Claude Code, Codex, Gemini, Cursor, and local Ollama -- and I had no memory of what happened, no log of what each tool produced, and no consistent way to decide which tool to use for a given task. This is what I built to solve that."

## What It Is (20 seconds)

Show: `opencobalt status`

"This is the status command. It shows me Python version, whether Ollama is running and what models are installed, the state of the local ledger, and a public safety scan -- whether there are any secrets or private paths in the repo."

"All of this is local. No cloud, no API calls, no setup beyond installing Python."

## Routing (40 seconds)

Show: `opencobalt route "design the architecture for the new auth module"`

"I tell it what I need to do. It returns a routing recommendation with a score and reasoning. This task is architecture work -- executive tier. It routes to Claude Code."

Show: `opencobalt route "summarize these session logs"`

"Now a summarization task. That routes to Ollama -- local model, worker tier. Cheap, fast, no API costs. The system distinguishes between tasks that need a serious model and tasks that don't."

"The router is deterministic. Keyword scoring, no LLM in the loop. That means it is fast, testable, and I can explain every decision."

## Ledger and Memory (30 seconds)

Show: `opencobalt log --summary "reviewed auth module design with Claude Code"`

Show: `opencobalt memory status`

"Every meaningful action gets logged to a local SQLite database. Session events, tool runs, route decisions, verification results. This is the memory spine -- it is the source of truth, not a markdown file I might delete."

## What AI Got Wrong (30 seconds)

"When I was building this, the first version of the public safety scanner was flagging its own source code -- the test file that checks for secret patterns was itself matching the secret pattern regex, and the scanner flagged it. The scanner was scanning itself."

Show: relevant test code briefly

"I caught it by reading the test output, tracing the path, and fixing the regex to be more specific about what counts as a path reference versus a string literal in a pattern list. This is what real AI-assisted development looks like -- not autonomous, verified."

## Why It Maps to AI-Native Work (20 seconds)

"What I am demonstrating here is not the AI tools themselves. It is infrastructure for working with AI tools: routing, logging, verification, public hygiene. That is the engineering problem that exists at any company using AI-assisted development at scale."

"The skills here are systems design, test discipline, and understanding what AI tools are good at versus where they need oversight."

## B2B Pitch (20 seconds)

"A procurement or contractor operations team using AI coding tools has the same problem I had: no audit trail of what AI agents did, no consistent routing policy, no pre-push safety check. OpenCobalt's ledger and routing tier system are the foundation for exactly that kind of governance infrastructure."
