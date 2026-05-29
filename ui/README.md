# OpenCobalt UI

A web dashboard shell for OpenCobalt. Built with React and Tailwind CSS.

## Status

This is a layout skeleton. It shows the planned panel structure and placeholder data.
The Python backend is not wired yet -- that is a future phase.

## Run

```bash
cd ui
npm install
npm run dev
```

Then open http://localhost:5173.

## Panels

| Panel | Description |
|-------|-------------|
| Command Center | Common CLI commands with copy-friendly display |
| Context Pack Viewer | Planned: live view of the compiled context pack |
| Session Ledger | Planned: live event feed from SQLite |
| Agent Router | Shows routing tiers and tool assignments |
| Verification Receipts | Planned: live test and public-check results |
| DesignLab | Planned: design token engine (see docs/DESIGNLAB.md) |

## Tech

- React 18
- Tailwind CSS 3
- Vite 5

No component libraries. No Next.js. Portable and minimal.

## Future

A future phase will add a REST or WebSocket bridge from the Python CLI to this UI.
See the main README for the architecture overview.
