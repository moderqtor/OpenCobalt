# Quickstart

## Requirements

- Python 3.11 or later
- Ollama (optional, for local model commands)

## Install

```bash
git clone https://github.com/cmheenan/OpenCobalt
cd OpenCobalt
pip install -e ".[dev]"
```

## Verify the install

```bash
opencobalt status
```

Expected output: repo path, Python version, Ollama availability, ledger status, docs check, public safety status.

## Check available models

```bash
opencobalt models
```

If Ollama is installed and running, this lists installed models. Worker-tier models are used for summarization and lightweight drafting only.

## Route a task

```bash
opencobalt route "write unit tests for the ledger module"
opencobalt route "summarize the recent session logs"
opencobalt route "design the router architecture"
```

Each command returns a tool recommendation, tier, score, and reasoning.

## Write to the ledger

```bash
opencobalt log --summary "reviewed authentication design"
opencobalt memory status
```

## Run verification

```bash
opencobalt verify
```

Runs pytest and public-check. Records results in the ledger.

## Pre-push safety scan

```bash
opencobalt public-check
```

Scans for .env files, hardcoded secrets, private vault paths, oversized artifacts, node_modules.

## Build a context pack

```bash
opencobalt context
```

Compiles README, docs, and src files into a single context pack at `.opencobalt/context/latest.md`. Token estimate included.

## Configuration (optional)

Copy `.env.example` to `.env` and add API keys only if you want optional API routing. OpenCobalt works fully without any API keys.

```bash
cp .env.example .env
# Edit .env as needed
```

The `.env` file is gitignored. Never commit it.

## Run tests

```bash
pytest
```
