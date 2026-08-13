# OpenCobalt UI

Local React workspace for OpenCobalt. The web UI started with `opencobalt ui`
is the canonical user surface. The Tauri wrapper (`opencobalt desktop`) is
optional development packaging.

## Run

From the project root:

```bash
opencobalt ui
```

This starts the FastAPI backend on port 8000 and the Vite dev server on port
5173. Both stop when the command exits.

Frontend only:

```bash
cd ui
npm install
npm run dev
```

Then open http://localhost:5173. The UI still needs the local API.

## Pages

| Page | Purpose |
|---|---|
| Chat | Durable conversations and the default goal surface |
| Routes | Inspectable routing history |
| Missions | Research and coding Missions |
| Skills | Local skill inventory |
| Memory | Explicit memory records |
| Ledger | Execution receipts |
| Providers | Installation, health, and execution evidence |
| Settings | Local defaults and persona editing |

## Desktop

`opencobalt desktop` requires `npm`, `cargo`, and `cargo tauri`. It runs the
same FastAPI backend and launches `cargo tauri dev`. This is not a polished
standalone installer.

## Tech

- React 18
- Tailwind CSS 3
- Vite 5
- FastAPI on port 8000
- Optional Tauri 2 wrapper in `src-tauri/`
