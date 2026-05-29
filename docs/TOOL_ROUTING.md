# Tool Routing

## Doctrine

OpenCobalt routes tasks to tools based on task type, risk level, context, and verification needs. The router is deterministic -- it uses keyword scoring, not LLM inference.

The router never makes autonomous decisions about what to build or how to build it. It recommends. The human decides.

## Routing Tiers

### Executive tier

**Tools:** Claude Code, Gemini CLI (long-context audit), GPT-4o via API (optional)

**Use for:**
- Architecture decisions
- Final code generation intended for production or public visibility
- Security review
- Public-facing documentation (README, QUICKSTART, employer notes)
- Resume or portfolio language
- Major refactors that cross multiple modules
- Product strategy
- Complex debugging with unclear root cause

**Do not use local Ollama for any of the above.**

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

### Green lane (proceed without confirmation)
- Read repo files
- Create local artifacts (.opencobalt/*)
- Run tests
- Write docs inside the repo
- Create local SQLite log entries
- Build context packs
- Inspect public documentation

### Yellow lane (proceed with care, document the action)
- Copy selected code from another repo after manual audit
- Install dependencies
- Run longer-running commands
- Create git worktrees
- Launch local CLI tools (Ollama, Codex, Gemini)
- Write to configured Obsidian mirror path (disabled by default)

### Red lane (requires explicit human instruction)
- Push to GitHub
- Publish packages to PyPI or npm
- Deploy to any hosted environment
- Delete folders or branches
- Read `.env` file contents
- Submit forms or send messages
- Automate logged-in web accounts
- Access billing or account settings
- Execute browser automation on sensitive sessions

## Cost Control (Planned)

Optional API adapters will include:
- Per-provider model registry with estimated token costs
- Monthly budget cap (configurable in `.env`)
- Per-run maximum cost limit
- Cheap / standard / frontier routing modes
- Automatic local fallback when API budget is exhausted

Until the cost control module is implemented, API usage is entirely manual. Configure API keys in `.env` if you want optional API routing; the default is local-only.
