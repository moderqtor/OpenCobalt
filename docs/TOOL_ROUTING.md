# Tool Routing

## Doctrine

OpenCobalt routes tasks to runtimes based on task type, risk level, context, and verification needs. The router is deterministic -- it uses keyword scoring, not LLM inference.

The router never makes autonomous decisions about what to build or how to build it. It recommends. The human decides.

Routing separates runtime from model policy. A runtime is the local tool that does work, such as `google-antigravity`, `claude-code`, `codex-cli`, `aider`, or `ollama`. A model policy describes the kind of model or reasoning budget that runtime should use, such as `gemini-pro`, `gemini-flash`, `claude-sonnet`, `claude-opus`, `gpt-oss`, or `local`.

## Routing Tiers

### Executive tier

**Tools:** Google Antigravity CLI, Claude Code

**Use for:**
- Multi-agent runtime workflows
- Artifact-producing validation workflows when local runtime support is discovered
- Workspace-level coding tasks where terminal, browser, and editor context matter together
- Google ecosystem tasks
- Architecture decisions
- Final code generation intended for production or public visibility
- Security review
- Public-facing documentation (README, QUICKSTART, employer notes)
- Resume or portfolio language
- Major refactors that cross multiple modules
- Product strategy
- Complex debugging with unclear root cause

**Do not use local Ollama for any of the above.**

Antigravity should not be preferred for tiny deterministic edits, cheap summaries, credential handling, destructive operations, or deployment and package publishing without explicit approval.

### Manager tier

**Tools:** Codex CLI, Cursor

**Use for:**
- Structured cleanup and formatting
- Test generation (with human review of output)
- Type annotations
- Intermediate code review
- UI and frontend work (Cursor)
- Editor-integrated refactors

### Worker tier

**Tools:** local Ollama models only (llama3, mistral, or whatever is installed)

**Use for:**
- Summarization of logs or long documents
- Tagging and labeling
- Entity extraction
- Rough draft generation for internal use
- Filename suggestions
- Context compression (reducing long text before sending to executive tier)
- Local fallback when API budget is exhausted

**Never use worker-tier models for:**
- Final code output
- Security review
- Any employer-facing or public content
- Architecture decisions
- Strategy or planning

## Autonomy Zones

### Green lane (read-only or local bookkeeping)
- Read repo files
- Create local artifacts (.opencobalt/*)
- Create local SQLite log entries
- Build context packs
- Inspect public documentation

### Yellow lane (local changes and generated artifacts)
- Copy selected code from another repo after manual audit
- Install dependencies
- Run longer-running commands
- Create git worktrees
- Launch local CLI tools without credentials or external account automation
- Run tests
- Write docs inside the repo
- Generate screenshots, diffs, logs, reports, and other work artifacts
- Write to configured Obsidian mirror path (disabled by default)

### Red lane (requires explicit human instruction)
- Shell execution with broad filesystem access
- Push to GitHub
- Publish packages to PyPI or npm
- Deploy to any hosted environment
- Delete folders or branches
- Read `.env` file contents
- Submit forms or send messages
- Automate logged-in web accounts
- Access billing or account settings
- Execute browser automation on sensitive sessions

### Black lane (blocked without explicit recovery plan)
- Destructive filesystem operations
- Credential export
- External network automation without explicit approval
- Any task that attempts to bypass policy or hide provenance

Agent runtimes with terminal, browser, and file access are powerful but risky. OpenCobalt's role is to add visibility, receipts, policy, and approval boundaries around those runtimes.

## Route Output

Route decisions include:

```json
{
  "runtime": "google-antigravity",
  "runtime_command": "agy",
  "model_policy": "high_reasoning_or_browser_capable",
  "reason": "Task requires artifact-producing validation workflow.",
  "risk_level": "yellow",
  "approval_required": true
}
```

Gemini CLI integration is deprecated. Legacy Gemini CLI aliases resolve to `google-antigravity` temporarily. Gemini remains a model-family name where appropriate.

## Cost Control (Planned)

Optional API adapters will include:
- Per-provider model registry with estimated token costs
- Monthly budget cap (configurable in `.env`)
- Per-run maximum cost limit
- Cheap / standard / frontier routing modes
- Automatic local fallback when API budget is exhausted

Until the cost control module is implemented, API usage is entirely manual. Configure API keys in `.env` if you want optional API routing; the default is local-only.
