# OpenCobalt Stitch Design Brief

## Product

OpenCobalt is a local-first AI orchestration control and provenance layer for developers. It routes tasks across Google Antigravity CLI, Claude Code, Codex CLI, Cursor, and Ollama, records decisions in SQLite, and scores completed runs with local telemetry.

The primary product surface is the CLI shell. The desktop and web dashboard should feel like a control room for the same system, not a marketing page.

## Design Goal

Create a professional, minimal, high-polish product interface that feels closer to a serious developer tool from a top platform team than a hobby dashboard. It should be calm, precise, and beautiful without decorative clutter.

Dominant accent: cobalt blue.

## Visual Direction

- Dark neutral base with cobalt blue as the primary accent.
- More graphite than pure black.
- Avoid purple-heavy gradients, beige, brown, orange, or one-note blue palettes.
- Use restrained glow only for active states, focus rings, and live telemetry.
- Prefer crisp lines, measured spacing, and strong type hierarchy.
- No decorative orbs, blobs, bokeh, marketing hero art, or generic SaaS cards.

## Palette

- Background: `#080B10`
- Surface: `#0E141D`
- Raised surface: `#131C29`
- Input surface: `#EAF1FF`
- Primary text: `#F6F8FC`
- Secondary text: `#9AA7B8`
- Muted text: `#546070`
- Border: `rgba(255,255,255,0.08)`
- Cobalt: `#2F6BFF`
- Cobalt bright: `#7EA4FF`
- Success: `#3DFFA0`
- Warning: `#FFD166`
- Error: `#FF5577`

## Typography

- UI font: Inter or SF Pro.
- Mono font: SF Mono or JetBrains Mono.
- Headings should be compact and confident.
- Labels should be small, uppercase, and spaced.
- Command text and terminal text should use mono.
- Do not use oversized hero typography inside dashboard panels.

## Layout

Design a desktop app first.

Canvas size: 1440 x 960.

Core layout:

- Left rail: icon-only navigation, 56 to 64 px wide.
- Main content: centered but wider than the current layout, around 920 to 1080 px.
- Top strip: product identity, active workspace, health status, and quick action.
- Primary panel: the command input or selected view.
- Secondary region: recent decisions, telemetry, route graph, and verification receipts.

Avoid nested cards. Use rails, rows, tables, panels, and open sections.

## Required Views

### 1. Command Center

Design the default first screen.

Elements:

- Cobalt logo mark in the left rail.
- Command input block with light-blue text area, not a dark input.
- Prompt prefix: `opencobalt >`
- Placeholder: `route a task, launch a workflow, or type / for commands`
- Recent route decisions as dense rows.
- Each row shows task, winning tool, score, tier, and time.
- Right side can include a compact "system health" strip.

The command block should feel like the highlighted typing area in modern CLI tools.

### 2. Telemetry

Design a scored run intelligence view.

Elements:

- Average score.
- Scored runs count.
- Top agent.
- Recent scored runs.
- Category bars for quality, adherence, efficiency, tool fit, and convergence.
- Judge label: heuristic or Ollama model.

Use cobalt for primary score, green only for high-confidence pass states.

### 3. Routing Graph

Design a clearer routing visualization.

Elements:

- Input prompt node.
- Deterministic router node.
- Candidate tools.
- Winning route highlighted in cobalt.
- Runner-up routes dimmed.
- Score chips or bars.

The graph should look like a developer operations diagram, not a decorative node toy.

### 4. CLI Shell Reference

Create a companion mockup for the terminal shell.

Elements:

- Startup header with logo, version, branch, local DB status, telemetry status.
- Highlighted input area using a subtle light cobalt block or inverse bar.
- Slash command palette with grouped commands.
- Bottom toolbar with memory count, watcher status, current mode, and active tool.
- Example prompt:

```text
opencobalt >
```

The CLI should feel comparable in polish to Claude Code, Codex CLI, and Google Antigravity CLI while keeping OpenCobalt's local-first identity.

## Interaction States

Include visible states for:

- Active nav item.
- Focused command input.
- Running route.
- Successful route decision.
- Empty telemetry.
- Scored telemetry row.
- Offline API warning.

## Components

- Icon rail button.
- Command input.
- Slash command palette.
- Dense route row.
- Telemetry score row.
- Category bar.
- Status dot.
- Compact metric strip.
- Route graph node.
- Verification receipt row.

## Copy Rules

- Keep copy concise.
- Do not add marketing slogans.
- Do not claim cloud service, autonomous hosted agent, or API automation by default.
- Use "local-first", "deterministic routing", "SQLite ledger", and "telemetry scoring".

## Output Requested From Stitch

Generate:

1. Desktop dashboard concept for Command Center.
2. Desktop dashboard concept for Telemetry.
3. Terminal shell concept.
4. Small component style sheet with tokens and component examples.

Do not generate a landing page.
