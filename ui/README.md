# OpenCobalt UI

A web dashboard for OpenCobalt. Built with React, Tailwind CSS, and a FastAPI backend.

## Run

From the project root:

```bash
opencobalt ui
```

This starts the FastAPI backend on port 8000 and the Vite dev server on port 5173. Both stop when the command exits.

To run the frontend alone (development):

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
| Context Pack Viewer | Live view of the compiled context pack |
| Session Ledger | Live event feed from SQLite |
| Agent Router | Shows routing tiers and tool assignments |
| Verification Receipts | Live test and public-check results |
| DesignLab | Planned: design token engine (see docs/DESIGNLAB.md) |

## Tech

- React 18
- Tailwind CSS 3
- Vite 5
- FastAPI (Python backend, port 8000)

No component libraries. No Next.js. Portable and minimal.
