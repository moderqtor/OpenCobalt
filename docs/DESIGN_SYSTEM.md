# Design System

Visual tokens for OpenCobalt surfaces. Product identity is in
[OPENCOBALT.md](../OPENCOBALT.md). The web workspace is the canonical user
surface; the CLI is a control plane over the same ledger.

## Principles

1. Dark-native by default, with an explicit light/system theme in Settings.
2. Typographic hierarchy does the work. No unnecessary borders, shadows, or gradients.
3. One accent color used sparingly: active state, CTA, system identity only.
4. Breathing room where focus matters. Density only where it carries information.
5. Status at a glance when trust is at stake. Failures stay visible.
6. Progressive disclosure. Chat is the default surface. Routing, receipts, and
   execution details appear when the user inspects them.

Live CSS tokens in `ui/src/index.css` are authoritative. Older GitHub-dark hex
values and "monospace throughout" guidance below this file's previous revisions
are stale.

## Color Palette

Current workspace tokens:

| Token | Dark | Use |
|-------|------|-----|
| `--canvas` / `--iron` | `#0b0e12` | Page background |
| `--surface` / `--graphite` | `#151a21` | Nav, composer, cards |
| `--surface-raised` | `#1b222b` | Hover, elevated |
| `--ink` / `--fog` | `#e8edf2` | Primary text |
| `--muted` | `#9aa6b5` | Secondary text |
| `--quiet` | `#8592a1` | Captions |
| `--line` | `#2a333e` | Borders |
| `--cobalt` | `#5b7fff` | Accent |
| `--amber` | `#d6a84b` | Warning |
| `--green` | `#66b88a` | Healthy / complete |
| `--coral` | `#df7272` | Error |

## Typography

Interface copy uses `--sans`: `"Avenir Next", Avenir, "Helvetica Neue", Arial, sans-serif`.

Use `--mono` (`"SF Mono", "Cascadia Code", "Roboto Mono", ui-monospace, monospace`) for IDs, receipts, routes, timestamps, model identifiers, and code.

Do not set the whole product in Times New Roman or in monospace.

| Scale | Size | Use |
|-------|------|-----|
| Page title | 22-28px | Settings and collection pages |
| Chat title | 17-18px | Conversation header |
| Body | 15px | Conversation and forms |
| Caption | 11-12px | Status, helper text |
| Meta | 10px mono | IDs and timestamps |

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
- [ ] Composer can be focused from the keyboard

## Screenshot Capture Instructions

For employer demos and README screenshots:

1. Set terminal to 140 columns, 45 rows
2. Run `opencobalt status` (shows real local state)
3. Run `opencobalt route "design the ledger schema"` (shows routing output)
4. Capture at 2x (Retina) resolution
5. Crop to content, no browser chrome
6. Save to `assets/screenshots/` with descriptive name
7. Do not add watermarks or annotations -- the output speaks for itself
