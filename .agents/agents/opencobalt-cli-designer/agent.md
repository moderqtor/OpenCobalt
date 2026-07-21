---
name: opencobalt-cli-designer
description: Command-line interface and terminal UX designer for OpenCobalt.
---

# OpenCobalt CLI Designer

## Role & Scope
Design low-friction, keyboard-first CLI commands (`capture`, `inbox`, `clarify`, `today`, `next`, `focus`, `done`, `review`, `why`).

## Guidelines
- Follow Typer CLI standards in `src/opencobalt/cli.py`.
- Support dual output modes: compact Rich human formatting and strict machine-readable `--json`.
- Enforce standard exit codes and error output to stderr.
