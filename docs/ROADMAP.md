# Roadmap

## Current: Phase 1 -- Backend MVP

Status: complete (initial pass)

Completed:
- Clean public repo scaffold
- Pydantic models for all domain objects
- SQLite ledger: events, verification results, route decisions, memory records
- Deterministic keyword-based router with tier classification
- Ollama model discovery with graceful fallback
- Context pack compiler
- Public safety scanner
- Memory store with markdown export
- Verification runner (pytest + public-check)
- Typer CLI with all primary commands
- 58 passing tests
- Architecture, routing, memory, and safety docs

## Phase 2 -- Context and Extraction

- Improve context pack compiler: git log integration, session summary injection
- Extract and clean additional logic from private Cobalt Forge repo (after audit)
- Add `opencobalt context diff` to show what changed between context packs
- Add test coverage for context compiler

## Phase 3 -- Cost Control

- Provider and model registry with estimated token costs per model
- Monthly budget cap configured in `.env`
- Per-run max cost limit
- Cheap / standard / frontier routing modes
- Automatic local Ollama fallback when API budget is exhausted
- Batch mode flag for supported providers

## Phase 4 -- UI Foundation

Stack: Vite + React + TypeScript + CSS modules (no heavy component library)

Screens planned:
1. Command Center (status + recent events)
2. Context Pack Viewer
3. Session Ledger (event timeline)
4. Agent Router (interactive task routing)
5. Verification Receipts
6. DesignLab placeholder

Design must pass the anti-slop checklist in docs/DESIGN_SYSTEM.md before merging.

## Phase 5 -- DesignLab

- Design token generation from project brief
- Local style memory (what visual choices have been made)
- Anti-slop rule enforcement
- Playwright screenshot capture
- Vision model critique (optional, requires configured API)
- Visual regression baseline
- Logo and icon prompt generation

## Phase 6 -- Agent Execution Layer

- Wrapper scripts for launching Claude Code, Codex CLI, Gemini CLI in documented modes
- Session log capture from agent runs
- Automatic event logging from agent handoffs
- Basic eval / scoring of agent outputs

## Not in Scope

- Autonomous agent execution without human oversight
- Multi-user server mode
- Cloud hosting or deployment
- Real-time collaborative editing
- Training or fine-tuning models
- Any gray-market API access
