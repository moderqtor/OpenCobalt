# OpenCobalt Design Reference

Visual language for the CLI, TUI, and web workspace. Mockup images in
`docs/design/assets/` are direction, not pixel-perfect specs. Product identity
lives in [OPENCOBALT.md](OPENCOBALT.md). The web workspace is the canonical
user surface; the CLI is a full control plane over the same ledger.

## Reference assets

| File | What it shows |
|------|---------------|
| `docs/design/assets/chatgpt-cli-mockup.png` | CLI shell concept: startup header, highlighted input, slash palette |
| `docs/design/assets/chatgpt-tui-mockup.png` | 4-panel TUI dashboard concept |
| `docs/design/assets/chatgpt-gen-cli-working-demo-1.png` | CLI working session: routing and status rows |
| `docs/design/assets/chatgpt-gen-cli-working-demo-2.png` | CLI working session: execution and receipt output |
| `docs/design/assets/chatgpt-gen-cli-working-demo-3.png` | CLI working session: verification and summary |

## Visual language

- Dark neutral base, more graphite than pure black. Cobalt blue is the only
  dominant accent.
- Background `#080B10`, surface `#0E141D`, raised surface `#131C29`.
- Primary text `#F6F8FC`, secondary `#9AA7B8`, muted `#546070`.
- Cobalt `#2F6BFF`, cobalt bright `#7EA4FF`, success `#3DFFA0`,
  warning `#FFD166`, error `#FF5577`.
- Mono font for commands, ids, hashes, and terminal text. Compact headings,
  small uppercase labels.
- Dense rows over cards. Rails, tables, and open sections over nested boxes.
- Restrained glow only for active states. No decorative orbs, gradients, or
  marketing hero art.

## Status model

| Dimension | States |
|-----------|--------|
| Router | healthy / degraded |
| Ledger | synced / pending / failed |
| Runtime | google-antigravity / claude-code / codex / ollama / cursor / noop |
| Task | planning / running / verifying / done / failed |
| Receipt | created / verified / failed |
| Risk | green / yellow / red / blocked |
| Mode | dry-run / supervised / autonomous |

## Copy rules

- Concise, literal labels. No marketing slogans.
- Prefer words the UI already uses: Chat, Routes, Missions, Skills, Memory,
  Ledger, Providers, Settings.
- Never claim a hosted service, complete sandboxing, or factual proof from
  receipts or citations.
