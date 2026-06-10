# OpenCobalt Design Reference

UI reference for the CLI, TUI, and future dashboard. The canonical mockup
images live in `docs/design/assets/`. This document describes the visual
language and status model they encode; treat the images as direction, not
pixel-perfect specs.

## Reference assets

| File | What it shows |
|------|---------------|
| `docs/design/assets/chatgpt-cli-mockup.png` | CLI shell concept: startup header, highlighted input, slash palette |
| `docs/design/assets/chatgpt-tui-mockup.png` | 4-panel TUI dashboard concept |
| `docs/design/assets/chatgpt-gen-cli-working-demo-1.png` | CLI working session: routing and status rows |
| `docs/design/assets/chatgpt-gen-cli-working-demo-2.png` | CLI working session: execution and receipt output |
| `docs/design/assets/chatgpt-gen-cli-working-demo-3.png` | CLI working session: verification and summary |

## Product direction

OpenCobalt is a local-first AI orchestration control plane with receipt-backed
execution. The CLI is the primary surface. Every other surface (TUI, desktop,
web dashboard) is a control room over the same SQLite ledger, not a separate
product. The interface should feel calm, precise, and verifiable: the user can
always see what ran, why it was routed there, what it produced, and whether
the evidence still checks out.

## CLI/TUI visual language

- Dark neutral base, more graphite than pure black. Cobalt blue is the only
  dominant accent.
- Background `#080B10`, surface `#0E141D`, raised surface `#131C29`.
- Primary text `#F6F8FC`, secondary `#9AA7B8`, muted `#546070`.
- Cobalt `#2F6BFF`, cobalt bright `#7EA4FF`, success `#3DFFA0`,
  warning `#FFD166`, error `#FF5577`.
- Mono font for commands, ids, hashes, and terminal text. Compact headings,
  small uppercase labels.
- Dense rows over cards. Rails, tables, and open sections over nested boxes.
- Restrained glow only for active states and live telemetry. No decorative
  orbs, gradients, or marketing hero art.
- Status dots plus short lowercase words ("verified", "dry-run") rather than
  badges with long phrases.

## Status model

Canonical status vocabulary. CLI output, events, the TUI, and any future
dashboard must use these exact words.

| Dimension | States |
|-----------|--------|
| Router | healthy / degraded |
| Ledger | synced / pending / failed |
| Runtime | google-antigravity / claude-code / codex / ollama / noop |
| Task | planning / running / verifying / done / failed |
| Receipt | created / verified / failed |
| Risk | green / yellow / red / blocked |
| Mode | dry-run / supervised / autonomous |
| Context | compact / normal / saturated |
| Caffeinate | off / active |

Color mapping: green states use success, yellow/pending use warning, red and
failed use error, blocked uses error with a lock glyph, neutral/dim for
dry-run and off.

## Core panels

- Routing panel: task text, winning runtime highlighted in cobalt, runner-up
  routes dimmed, score chips, deterministic reasoning line.
- Execution panel: command argv (redacted), risk level, policy decision,
  live task status, exit code, duration.
- Receipt panel: receipt id, plan id, artifact count, verification status,
  SHA-256 prefixes in mono.
- Ledger strip: event count, last write, synced/pending/failed.

## Risk states

Risk is always visible before and during execution:

- green: read-only planning, summarization, analysis
- yellow: local edits, test runs, generated artifacts
- red: shell execution, credentials, deployment (requires explicit approval)
- blocked: black-risk tasks; never executable, shown with lock glyph

## Worker and runtime display

Each runtime gets a status slot in the header strip and TUI:

- google-antigravity: active / not on PATH
- claude-code: active / not on PATH
- codex: active / not on PATH
- ollama: running / stopped (worker tier only, on demand)
- noop: always available (dry-run target)

Slots show a status dot, runtime name, and tier. Inactive runtimes are dim,
never red; absence is normal, not an error.

## Use-limit display

Subscription tools (Claude Code, Codex, Gemini CLI) run via subprocess, so
spend is usage-window based, not per-token. Display remaining headroom as a
compact bar per tool when known, with the routing mode (economy / balanced /
performance) next to it. Never block on unknown limits; show "unknown" dim.

## Caffeinate indicator

When a long run holds the Mac awake (`--caffeinate`), show "caffeinate:
active" in the status strip and in `opencobalt run` output. Off is the
default and is shown dim or omitted.

## Future dashboard notes

- The desktop/web dashboard reads the same ledger; no separate state.
- Command Center view: command input with light cobalt block, recent route
  decisions as dense rows, system health strip.
- Telemetry view: average score, scored runs, top agent, category bars
  (quality, adherence, efficiency, tool fit, convergence).
- Routing graph view: input node, deterministic router node, candidate tools,
  winner in cobalt.
- Receipts view: evidence chain plan -> execution -> artifacts -> receipt,
  with re-verify action.
- Delegation view (future): parent/child subagent tree with per-node risk
  ceilings and result receipts.

## Copy rules

- Concise, lowercase status words. No marketing slogans, no hype.
- Use "local-first", "deterministic routing", "SQLite ledger",
  "work receipts", "telemetry scoring".
- Never claim cloud service, hosted agents, or API automation by default.
