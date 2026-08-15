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

| Area | Page | Purpose |
|---|---|---|
| Work | Chat | Durable conversations and the default goal surface |
| Work | Missions | Research and coding Missions |
| Context | Memory | Explicit saved facts, distinct from chat history |
| System | Routes | Inspectable routing history |
| System | Ledger | Execution receipts |
| System | Skills | Local skill inventory |
| System | Providers | Installation, health, and execution evidence |
| System | Settings | Local defaults and persona editing |

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
