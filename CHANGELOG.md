# Changelog

All notable changes to this project are documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

---

## [0.2.0] - 2026-05-29

### Added

- Cost control module with routing modes (cheap, standard, frontier) and per-run and monthly budget caps
- Agent system: BaseAgent ABC, registry, and 4 concrete agents (summarizer, tagger, code-reviewer, context-builder)
- Skill system: BaseSkill ABC, file-reader skill, diff-writer skill
- Integration system: BaseIntegration ABC, aider stub, ollama stub
- UI dashboard shell (React + Tailwind, Vite) at `ui/`; run with `cd ui && npm run dev`
- GitHub Actions CI workflow (ubuntu-latest, Python 3.11)
- `opencobalt history` command: view route decision log from the ledger, with `--limit` option
- `opencobalt benchmark` command: routes 10 representative tasks and prints a tier breakdown table
- `opencobalt config get/set/list`: SQLite-backed config store for persistent settings
- `opencobalt export`: exports the full ledger to a timestamped markdown report in `.opencobalt/exports/`
- 4-panel TUI: status, route decisions, events, and cost control panels
- Real Ollama subprocess integration in the summarizer and tagger agents
- Route decisions are now logged to the ledger by default on every `opencobalt route` call
- `opencobalt route --verbose`: shows per-tool keyword matches alongside scores
- `opencobalt route --estimate`: shows estimated API cost per tier (~2K input / 500 output tokens)
- `opencobalt stats`: ledger analytics with tier breakdown bar chart, top tools, and recent activity
- `opencobalt memory add TEXT`: write a memory record from the CLI with optional namespace
- `opencobalt history`: paginated view of past route decisions with timestamps
- `opencobalt log-list`: list recent session events from the ledger with optional project filter
- Config module (`core/config.py`): SQLite-backed key-value store
- Programmatic examples in `examples/`: route_example.py, context_example.py, batch_route.py
- 167 tests (up from 58 at 0.1.0)
- CLI integration tests using Typer's CliRunner: 23 tests covering all major commands (tests/test_cli.py)
- CHANGELOG.md and updated QUICKSTART.md

### Changed

- `node_modules` directories are now silently skipped in the public safety scanner (gitignored, never committed to results)

---

## [0.1.0] - 2026-05-28

### Added

- CLI with commands: status, models, route, log, memory, context, verify, doctor, public-check, tui, design brief
- Deterministic keyword-based router with tier scoring across five tools (claude-code, codex-cli, gemini-cli, cursor, ollama)
- SQLite ledger for events, route decisions, verification results, and memory records
- Ollama model discovery with graceful fallback when Ollama is not available
- Context pack compiler: combines docs and src files into a single markdown file with token estimate
- Public safety scanner: detects secrets, private vault paths, oversized files, and .env files before push
- 58 passing tests at launch

---

[Unreleased]: https://github.com/moderqtor/OpenCobalt/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/moderqtor/OpenCobalt/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/moderqtor/OpenCobalt/releases/tag/v0.1.0
