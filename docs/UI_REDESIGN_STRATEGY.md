# OpenCobalt UI and CLI Redesign Strategy

## Recommendation

Treat the CLI as the flagship interface and redesign it first. The desktop dashboard should follow the CLI visual language, not the other way around.

Best route:

1. Use `STITCH.md` in Google Stitch for fast visual exploration.
2. Pick one direction for CLI and one for dashboard.
3. Convert the accepted direction into a formal implementation spec.
4. Implement in this repo with Codex or Claude Code using tests and rendered screenshots.
5. Validate with Playwright screenshots on desktop and mobile.

Stitch is useful for taste and layout exploration. It should not be treated as production code.

## Tool Roles

| Tool | Best use | Notes |
|---|---|---|
| Google Stitch | Visual concepts and component direction | Good for fast dashboard and CLI mood boards. Use output as reference only. |
| Claude Design or Claude Code | Broad UI ideation and larger refactors | Strong for interaction copy and app structure. Verify carefully. |
| Codex | Repo-integrated implementation, tests, CI, polish | Best for disciplined changes inside OpenCobalt. |
| Cursor | Manual front-end iteration | Good when you want direct visual editing. |
| Gemini CLI | Alternative design critique and docs review | Useful as a second opinion, not the sole implementer. |
| Google AI Studio | UI prototypes and prompt-driven variants | Useful for experiments, but keep production inside the repo. |

## CLI Redesign Scope

The CLI should feel like a modern coding-agent shell:

- Strong startup identity.
- Clear command input area.
- Slash command discovery.
- Better visual grouping of route, telemetry, memory, and verification status.
- Command palette with grouped commands.
- Mode indicators for route, converge, auto, mission, telemetry, and shell.
- A bottom toolbar that communicates useful state without noise.

Concrete changes:

- Replace the small `opencobalt >` prompt with a highlighted input row.
- Add `/` command palette groups: Routing, Automation, Telemetry, Memory, System, UI.
- Add recent command suggestions.
- Add optional compact startup mode for repeated use.
- Add `opencobalt shell --no-brief` or config to skip startup brief.
- Make telemetry status visible in the startup header.
- Improve low-color terminal rendering.

## Dashboard Redesign Scope

The dashboard should become a compact operations console:

- Wider main content.
- Stronger command-center first screen.
- Better telemetry category visualization.
- More coherent nav and status strip.
- Fewer empty dark areas.
- Cobalt-blue accent system.
- No screenshots in README until this is visually mature.

Do not build a marketing landing page. Build the actual control surface.

## Implementation Plan

Recommended sequence:

1. CLI shell redesign.
2. Dashboard design-system cleanup.
3. Telemetry and routing graph polish.
4. README screenshots regenerated from the final UI.
5. TUI visual alignment.
6. Optional desktop wrapper polish.

Each step should have:

- Test coverage for command behavior.
- Screenshot capture for rendered UI.
- `python3 -m pytest -q`.
- `ruff check src/ tests/`.
- `npm run build` for dashboard work.
- `opencobalt public-check`.

## Connector Recommendations

### Worth Adding

- Browser or Playwright workflow: high value for dashboard and README screenshot validation.
- GitHub Actions inspection: useful for CI failure triage.
- Figma or Stitch only as design-reference connectors, not as production data stores.
- Vercel only for a public docs or demo site if you want one later.

### Not Recommended For Core OpenCobalt

- Supabase Studio as a core backend. OpenCobalt's source of truth is SQLite and should stay local-first.
- Postgres, Redis, Qdrant, or hosted vector stores for core state.
- Vercel as a product runtime. It conflicts with the local-first CLI identity unless used only for docs or demos.

### Maybe Useful Later

- Supabase for an optional public demo sandbox, separate from core state.
- Sentry for the dashboard if you publish a hosted demo.
- Figma MCP for polished mockups and handoff.
- GitHub connector for issues, PRs, and CI triage.

## Decision

Use Stitch for concepts, but implement the accepted direction in this repo with Codex or Claude Code. For this codebase, production changes need local tests, CI parity, public safety checks, and screenshots. That makes repo-integrated implementation safer than accepting generated UI code directly.
