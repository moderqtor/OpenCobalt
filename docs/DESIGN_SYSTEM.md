# Design System

Visual tokens for OpenCobalt surfaces. Product identity is in
[OPENCOBALT.md](../OPENCOBALT.md). The web workspace is the canonical user
surface; the CLI is a control plane over the same ledger.

## Principles

1. Dark-native. The primary mode is dark. Not a toggle -- the product lives in dark.
2. Typographic hierarchy does the work. No unnecessary borders, shadows, or gradients.
3. One accent color used sparingly: active state, CTA, system identity only.
4. Breathing room. Generous padding. Content does not feel cramped.
5. Status at a glance. The UI answers "what is running, what is healthy, what just happened" without interaction.
6. Progressive disclosure. Chat is the default surface. Routing, receipts, and
   execution details appear when the user inspects them.

## Color Palette

### Backgrounds

| Token | Hex | Use |
|-------|-----|-----|
| `bg.base` | `#0D1117` | Page and app background |
| `bg.surface` | `#161B22` | Cards, panels, sidebars |
| `bg.elevated` | `#1C2333` | Modals, dropdowns, hover states |
| `bg.subtle` | `#21262D` | Input fields, code blocks |

### Text

| Token | Hex | Use |
|-------|-----|-----|
| `text.primary` | `#E6EDF3` | Primary content |
| `text.secondary` | `#8B949E` | Labels, metadata, captions |
| `text.tertiary` | `#484F58` | Placeholders, disabled |
| `text.inverse` | `#0D1117` | Text on cobalt accent |

### Accent (use sparingly)

| Token | Hex | Use |
|-------|-----|-----|
| `cobalt.500` | `#3B7CF4` | Primary accent, active nav, CTA |
| `cobalt.400` | `#5A93F5` | Hover, focus ring |
| `cobalt.600` | `#2563EB` | Pressed state |
| `cobalt.900` | `#1E3A8A` | Accent background tints |
| `cobalt.muted` | `#1F3A5F` | Subtle borders on dark surfaces |

### Semantic

| Token | Hex | Use |
|-------|-----|-----|
| `status.up` | `#22C55E` | Service healthy, test passing |
| `status.down` | `#EF4444` | Error, offline, test failing |
| `status.warn` | `#F59E0B` | Warning, partial, unknown |
| `semantic.purple` | `#8B5CF6` | Agents, debate, multi-model |
| `semantic.teal` | `#06B6D4` | Synthesis, knowledge, context |

## Typography

Stack: `"Berkeley Mono", "JetBrains Mono", "Fira Code", monospace`

This is a tool for developers. Monospace throughout -- not Inter with monospace only in code blocks.

| Scale | Size | Weight | Use |
|-------|------|--------|-----|
| `type.display` | 28px | 700 | Page titles |
| `type.heading` | 20px | 600 | Section headings |
| `type.label` | 14px | 500 | Column headers, nav labels |
| `type.body` | 14px | 400 | Primary content |
| `type.caption` | 12px | 400 | Metadata, timestamps |
| `type.code` | 13px | 400 | Code, IDs, paths |

## Spacing

Base unit: 4px.

| Token | Value | Use |
|-------|-------|-----|
| `space.1` | 4px | Tight groupings |
| `space.2` | 8px | Component internal padding |
| `space.3` | 12px | Between related elements |
| `space.4` | 16px | Section padding |
| `space.6` | 24px | Panel gaps |
| `space.8` | 32px | Page-level spacing |

## Motion

- Prefer no animation for status updates and data changes
- If animating: 150ms ease-out for reveals, 100ms for state transitions
- No bouncy, springy, or playful motion
- Loading states use a simple opacity pulse, not a spinning gradient

## Anti-Slop Checklist

Before any UI screenshot or demo:

- [ ] No generic purple/blue gradient hero section
- [ ] No emoji in feature lists or marketing copy
- [ ] No glassmorphism (frosted glass backgrounds)
- [ ] No identical rounded cards for every feature
- [ ] No fake metric counters ("10x faster", "99.9% uptime")
- [ ] No vague benefit copy ("unlock your productivity")
- [ ] No Inter-only typography
- [ ] No default Tailwind color classes visible in the design
- [ ] Status fields show real local state, not hardcoded demo values
- [ ] Empty states have clear, honest messaging (not hidden)
- [ ] Command palette placeholder is visible and keyboard-accessible

## Screenshot Capture Instructions

For employer demos and README screenshots:

1. Set terminal to 140 columns, 45 rows
2. Run `opencobalt status` (shows real local state)
3. Run `opencobalt route "design the ledger schema"` (shows routing output)
4. Capture at 2x (Retina) resolution
5. Crop to content, no browser chrome
6. Save to `assets/screenshots/` with descriptive name
7. Do not add watermarks or annotations -- the output speaks for itself
