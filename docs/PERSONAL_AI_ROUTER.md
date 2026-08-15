# Personal AI workspace

The local React and FastAPI workspace is the primary OpenCobalt surface. Give
OpenCobalt a goal in Chat. Routing, provider selection, research, coding
staging, memory, and receipts happen behind that interaction and remain
inspectable.

This is not a hosted account, credential broker, or unrestricted agent
runtime. Product identity lives in [OPENCOBALT.md](../OPENCOBALT.md). Routing
details are in [routing.md](routing.md). Research and coding paths are in
[research.md](research.md) and [coding.md](coding.md).

## Start the local workspace

Prerequisites:

- Python 3.11 or newer.
- Node.js with `npm` available on `PATH`.
- A checkout of this repository. Run the UI command from its root because it expects the local `ui/` directory and uses paths relative to the current directory.

Set up Python and start the UI:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[dev,server]"
opencobalt ui
```

The command starts the local API on `http://localhost:8000` and Vite on `http://localhost:5173`, opens a browser by default, and stops both processes on Ctrl+C. Use `opencobalt ui --no-browser` when you want to open the URL yourself. If `ui/node_modules` or the required icon package is missing, the command runs `npm install`; that setup step can require network access.

Starting the UI and inspecting existing records requires no provider credential. Sending a request through a cloud CLI may require that CLI's own network access and authentication.

## Pages

Chat is the default page. Primary navigation is Work, then Context, then
System behind a disclosure.

| Area | Page | Purpose |
|---|---|---|
| Work | Chat | The daily surface. Write a goal. Automatic routing is the default. Manual provider, persona, privacy, and local-only controls stay under Controls. |
| Work | Missions | Durable research and coding work that can resume later. Ordinary Chat does not become a Mission. |
| Context | Memory | Saved facts you chose to keep. This is not conversation history. A chat request beginning with `Remember that ...` creates a proposal for review. |
| System | Routes | Route history and the inspector for why a provider was selected, fallback, receipt integrity, and reruns. |
| System | Ledger | Execution records kept on this machine. Receipt integrity is not a proof of factual truth. |
| System | Skills | Installed local skill records. Listing or inspecting a skill does not execute it. |
| System | Providers | Separate evidence for installation, authentication, health, models, and execution support. |
| System | Settings | Local defaults for Chat, privacy, approvals, and personas. These defaults do not grant authority. |

Pages remain hash-linkable, such as `http://localhost:5173/#providers`. System pages stay available; they are no longer equal primary destinations.

New Chat work starts locally: the plus control focuses the composer without creating an empty record. The conversation is stored when the first message is sent. The title starts as "New conversation" and is replaced by that first message unless you already named it. A repository path is optional under Controls after the conversation exists. The path is still canonicalized and cannot escape the startup workspace.

## Shared local state

The UI, personal-AI store, execution receipts, and the legacy CLI use:

```text
.opencobalt/ledger.db
```

That path is relative to the directory where `opencobalt ui` is started. Use the same repository root when you want the CLI and UI to see the same records. SQLite remains the source of truth; the browser is not a second store, and OpenCobalt does not sync this ledger to a hosted service.

The shared database means a reset affects more than chat: conversations, personal-AI routes, missions, approvals, receipts, and other ledger-backed state can live in the same file. A conversation workspace path is canonicalized when it is created and must be the startup workspace or one of its existing subdirectories; it cannot escape that boundary and become an arbitrary provider working directory.

## Conversation routing presets

Chat keeps Automatic vs Manual mode, the last manual provider/model, reasoning effort, fallback, privacy, and local-only on the conversation record (`metadata.routing` in SQLite). The browser is a cache. Switching to Automatic does not destroy the last manual preset for that conversation. New conversations follow Settings defaults, normally Automatic, and do not inherit another chat's provider. If a stored provider or model later becomes unavailable, OpenCobalt keeps the stored values and labels them stale instead of substituting another model.

Persona and approach stay under Controls. They are not part of the routing preset.

Desktop Chat layout is a horizontal grid: primary navigation, a bounded conversation column, then the active chat. The optional route inspector remains an overlay. Collapsing the conversation column gives that space to chat. Below 1180px the conversation list is a drawer over chat. Below 1024px primary navigation is also a drawer.

Provider prompts concatenate a system policy and the current user message. The policy includes persona controls, execution constraints, at most the last ten prior messages truncated to 3000 characters each, and attachment excerpts. The current user message is not repeated inside that history. A first short request therefore has a small OpenCobalt-owned payload; large input-token reports on such requests are mostly provider/runtime baseline context.

## Provider evidence and boundaries

The Providers page deliberately keeps four questions separate:

1. Is an executable installed?
2. Did local capability discovery prove the bounded invocation OpenCobalt requires?
3. Is authentication known?
4. Has a successful invocation actually produced a receipt?

An installed executable or a provider health check does not by itself prove authentication, subscription access, quota, model availability, or a successful completion.

| Provider | Current personal-AI boundary |
|---|---|
| Codex CLI | The adapter is enabled only when local help evidence proves the non-interactive `exec` path, a read-only sandbox, and an approval policy of `never`. It does not enable dangerous bypass, web search, remote control, credential management, MCP management, or repository mutation paths. Because read-only Codex can still inspect files, answer-only Chat routing excludes it until approval-and-resume exists; explicit receipt-backed execution surfaces can use it under their own approval policy. Codex may still require network access and credentials managed outside OpenCobalt. |
| Google Antigravity | Chat admission requires a discovered non-interactive print path (`agy --print`), JSON output, and Antigravity's `--sandbox`. Each invocation runs in an atomically created, unpredictable private mode-0700 OS-temporary workspace outside the attached repository, never enables `--dangerously-skip-permissions`, and still flows through `ExecutionEngine`; this is not a claim of an OpenCobalt-provided OS sandbox. Authenticated models come from `agy --output-format json models`; disappeared models are not kept available. Local-only requests exclude Antigravity before invocation. Network access and externally managed authentication are required. |
| Ollama | The local provider requires a loopback endpoint, defaulting to `127.0.0.1:11434`, plus structured `/api/tags` evidence that each admitted model has catalog-reported positive size, a SHA-256-shaped digest, a local format, and no `remote_host` or `remote_model`. Discovery and the immediate pre-execution recheck run through `ExecutionEngine`. Completion uses the loopback `/api/generate` endpoint with Ollama's `:local` source constraint, which rejects remote manifests; it does not use the CLI's pull-capable `run` path. Remote/cloud and ambiguous catalog entries are excluded in every routing mode, and unknown overrides cannot trigger a pull. A remote or non-loopback endpoint is never local-only eligible. |
| Claude Code | A real execution adapter exists, but no Claude subscription or authenticated session is assumed. Execution requires local help evidence for non-interactive print, text output, and plan permission mode. The adapter does not enable unsafe bypass, browser control, automatic MCP access, deploy, publish, spend, or messaging paths. Because plan mode can still inspect files, answer-only Chat routing excludes it until approval-and-resume exists. Network access and externally managed authentication may be required. |
| Cursor ACP | Cursor is a coding runtime, not a default general Chat provider. Personal AI uses the official `agent acp` stdio JSON-RPC interface with `cursor_login`. `coding_analysis` uses ask/plan-style read-only behavior; `coding_agent` requires an explicit repository path and maps `session/request_permission` into the Approval Bridge. OpenCobalt never sends `--force`, `--yolo`, `--api-key`, or `allow-always`. Local-only requests exclude Cursor. Ordinary Chat cannot grant repository mutation. |
| Gemini CLI | Executable presence is discovery-only in the Personal AI Router. It has no current completion boundary, even if the CLI is installed or separately authenticated. Google Antigravity remains the executable Google provider in this workflow. |
| Mock | A deterministic local development provider backed by the noop adapter. It is not a live model and uses simulated chunks. Normal API/UI initialization disables it, so absence of a real eligible provider produces an inspectable route failure. Tests or explicit development sessions may opt in with `OPENCOBALT_ENABLE_DEVELOPMENT_MOCK=1`; its work still crosses `ExecutionEngine` and produces clearly labeled development receipts. |

Routing profiles are OpenCobalt adapter contracts and heuristics, not statistically calibrated provider quality, latency, pricing, entitlement, or billing evidence.

### Credentials and subscriptions

OpenCobalt does not provision provider accounts, turn a subscription into an API key, or treat those two forms of access as interchangeable. It also does not store or manage provider login state for this UI.

If a selected CLI requires authentication, configure it with that provider's supported local CLI flow outside OpenCobalt, then refresh the Providers page. Do not paste credentials into Chat or commit them to the repository. Authentication can remain `unknown` after a refresh; a successful receipt proves only that bounded invocation, while executable detection alone proves neither authentication nor entitlement.

## Routing, local-only, and fallback

Automatic routing is deterministic over a recorded snapshot. It considers the request class, discovered execution support, declared task capabilities, privacy and local-only constraints, cost category, provider preference, and persona affinity. Route points are transparent heuristics, not probabilities or benchmarked quality scores.

A manual provider or model choice is a routing constraint, not a safety bypass. If that choice is unavailable or disallowed, OpenCobalt records a denied route and does not silently choose another provider.

Local-only is strict:

- providers that require network access are excluded;
- providers not proven local-eligible are excluded;
- a manual cloud-provider override does not weaken the rule; and
- when no eligible local route exists, the request ends with an inspectable route failure and no completion attempt or fabricated route receipt. Independent capability or model discovery can retain its own discovery receipt.

Loopback alone is not treated as proof of local Ollama inference because Ollama can expose cloud-backed models through its local API. OpenCobalt admits only model records with bounded local-catalog evidence, rechecks admission immediately before execution, and requests the model with Ollama's explicit `:local` source qualifier. Ollama 0.20.5 parses that qualifier as a local-source constraint and its generation handler rejects a remote manifest for such a request. Catalog size, digest, and format remain runtime-reported evidence rather than an independent blob audit. For additional daemon-wide protection, Ollama documents `disable_ollama_cloud: true` in `~/.ollama/server.json` or `OLLAMA_NO_CLOUD=1` followed by a daemon restart: <https://docs.ollama.com/faq#how-do-i-disable-ollamas-cloud-features>.

There is no silent fallback. New requests and reruns default to fallback disabled; the UI exposes an explicit toggle. The service can fall back only when the user enables it, an eligible second candidate exists, and the failure belongs to a supported provider category. Each failed attempt keeps its provider, status, error, and receipt; the route records the visible transition and final provider metadata.

Chat is currently answer-only. Requested tool or skill execution is rejected at the API boundary instead of being silently attempted. The `always_ask` setting also blocks chat model execution because approval-and-resume is not yet implemented; this is an explicit policy denial, not an implicit approval. Other policies allow bounded provider inference while route records retain any human-review requirement before acting on consequential output. Ollama and Mock have inference-only adapter contracts, so harmless discussion of a sensitive topic is distinct from process authority. Codex and Claude remain agent runtimes without a proven answer-only isolation boundary, so Personal AI chat currently fails closed for those providers until approval-and-resume exists. Antigravity Chat is admitted only through the isolated print boundary above; it does not grant repository or shell authority to ordinary Chat. Explicit receipt-backed execution surfaces can still use the generic Antigravity adapter under their own approval policy.

Selecting the Research or Research synthesis cognitive policy launches an evidence-backed Research Mission instead of ordinary Chat. OpenCobalt decomposes the question, retrieves public HTTPS sources itself (HTML, PDF, PubMed, DOI/Crossref, and government hosts), can include conversation attachments as sources, stores structured evidence, optionally reviews important claims with a distinct stronger model, synthesizes from that evidence set, and marks citations as `verified_link` only when they point at retrieved mission evidence. Retrieved source text is untrusted data, cannot grant tools or authority, and is explicitly labeled as potentially adversarial in extraction, review, and synthesis prompts. These controls do not guarantee perfect semantic prompt-injection resistance. Citation linkage is not a proof of factual truth. Ordinary Chat messages are not turned into Missions automatically.

Chat can attach PDF, Markdown, plain text, HTML, or CSV files. Attachments are stored under `.opencobalt/attachments/`, treated as untrusted data rather than instructions, and supplied to the model as bounded excerpts.

When fallback is enabled, OpenCobalt skips remaining models from the same failed provider and tries the next eligible different provider. It does not ask every Antigravity model the same question.

## Personas, routes, and receipts

The built-in persona set is Analytical, Reflective, Exploratory, Builder, Provider Native, ChatGPT Native, Claude Native, and Gemini Native. Personas are versioned interaction policies and routing priors. They do not reproduce hidden prompts or turn one provider into another. When a native-family persona runs on a different provider family, the route records an approximation disclosure. Settings can duplicate a built-in, edit the custom profile's bounded controls and affinities, render a sample policy without provider execution, and identify every later version separately.

Each routed request persists its user message, candidates, and route. Once an execution attempt exists, OpenCobalt also persists the attempt and execution lifecycle events; a successful attempt adds the assistant message and receipt linkage. Chat shows a compact used-provider line on the response. The inspector summary shows why the route was chosen, the provider and model actually used, privacy, cost class, fallback, outcome, and whether an execution was recorded. Routing internals, authority, lifecycle events, and record IDs remain behind disclosure. Route records also retain any explicit fallback transitions for provenance.

Every real or simulated completion is delegated through `ExecutionEngine`. A successful execution links a work receipt; a provider or policy failure can also carry a failure receipt when the engine was reached. A request rejected before execution has a route record but no fabricated receipt. The route inspector can rerun with a different persona, executable provider, reasoning effort, or strict local-only constraint; the new attempt receives a new route record rather than rewriting history.

The current response-integrity verification checks only that a non-empty response and execution receipt are linked. It does not prove factual correctness, clinical or legal validity, provider identity, or full task success.

## Export, backup, and reset

Settings can download `/api/v1/data/export` as a private JSON snapshot without writing a server-side file. It includes conversation and memory text, so it must be handled as sensitive local data. Execution receipt fields are redacted. The MVP export is bounded to 500 conversations, routes, executions, missions, and receipts, 500 messages per exported conversation, and 1,000 memories; it is an inspection/export surface, not an unbounded backup.

The separate `opencobalt export` command writes a readable timestamped Markdown report under `.opencobalt/exports/`, but its scope is the legacy core ledger events, route decisions, and verification results. It is not a complete backup of conversations or all personal-AI tables.

For a complete backup, stop the UI with Ctrl+C and make a SQLite backup to a new filename. If the `sqlite3` command is installed:

```bash
mkdir -p .opencobalt/exports
backup_path=".opencobalt/exports/ledger-full-$(date +%Y%m%d-%H%M%S).db"
sqlite3 .opencobalt/ledger.db ".backup '$backup_path'"
```

Treat database and Markdown exports as potentially private: they can contain prompts, responses, memory, project paths, and receipt metadata.

OpenCobalt has no personal-AI command that silently deletes or resets the shared ledger. For an intentional fresh start, first stop every OpenCobalt process, create and verify a complete backup, then rename the original database rather than deleting it. Restarting the UI creates a new ledger. If `ledger.db-wal` or `ledger.db-shm` remains after shutdown, do not move files until you have confirmed no process is using the database and the backup is valid.

## Testing

Run the repository gates from the checkout root:

```bash
.venv/bin/ruff check .
.venv/bin/opencobalt public-check
.venv/bin/pytest
npm run build --prefix ui
```

For a manual smoke test, run `opencobalt ui --no-browser`, open `http://localhost:5173`, confirm the Providers page reports evidence rather than inferred availability, and treat Mock explicitly as development evidence rather than a live-model result.

## Troubleshooting

- **`npm not found`:** install Node.js/npm and retry from the repository root.
- **API server failed to start:** install the server extra with `python -m pip install -e ".[server]"` inside the active environment.
- **`ui/ directory not found`:** change to the OpenCobalt checkout root before running `opencobalt ui`.
- **Ports 5173 or 8000 are busy:** stop the conflicting local process before retrying. The documented UI origins use the default ports.
- **Provider is installed but unavailable:** review its limitations. The safe non-interactive capability boundary may not have been discovered from local help output, and installation does not prove authentication.
- **Codex or Claude stopped routing after a CLI update:** refresh provider evidence. OpenCobalt fails closed when the required read-only/plan-mode flags cannot be proven.
- **Ollama has no models:** verify the local Ollama runtime is available at the loopback endpoint and `/api/tags` reports at least one model with bounded size, digest, format, and non-remote metadata, then refresh provider discovery. The route inspector preserves the reason when catalog entries are rejected. OpenCobalt will not invent, pull, or admit a remote/ambiguous model for personal-AI routing.
- **Local-only route failed:** no discovered provider satisfied the strict local constraint. Make a loopback Ollama model available, deliberately disable local-only for that request, or leave the denial in place.
- **Records seem missing:** confirm the UI was started from the same working directory as the CLI; the ledger path is relative.
- **Cancellation looks delayed:** see the limitation below. Inspect the execution status and receipt instead of assuming the external command was terminated.

## Current limitations

- Real CLI providers are completion-only. They finish a one-shot command before OpenCobalt emits normalized response chunks; this is not native token streaming. Mock chunking is simulated.
- Cancellation is cooperative at the normalized service boundary. It can prevent a not-yet-started attempt or stop later chunk emission, but it does not currently guarantee termination of an already-running external provider process.
- Chat has no approval-and-resume endpoint. Tool and skill execution is denied, and the `always_ask` policy blocks provider execution rather than bypassing approval.
- Provider discovery and health are capability evidence, not proof of account entitlement, authentication, quota, or model quality.
- Route points, cost categories, quality tiers, and latency categories are declared heuristics rather than calibrated measurements.
- Gemini CLI remains discovery-only, while Mock remains development-only.
- Persona-native profiles preserve an observable style request only; hidden provider prompts and exact provider identities are neither known nor reproduced.
- Receipt-linked response integrity is not factual verification.
- The UI is local development infrastructure served by FastAPI and Vite; it is not a hosted multi-user service.
- Conversation workspaces are intentionally limited to the directory where OpenCobalt was started and its subdirectories; a broader trusted-workspace registry is not part of this MVP.

For the underlying execution boundary, see [Execution Layer](EXECUTION_LAYER.md). Provider-specific evidence is documented in [Codex Runtime Adapter](CODEX_RUNTIME_ADAPTER.md), [Claude Code Runtime Adapter](CLAUDE_CODE_RUNTIME_ADAPTER.md), and [Google Antigravity](ANTIGRAVITY.md). Mission behavior remains documented separately in [Missions](MISSIONS.md).
