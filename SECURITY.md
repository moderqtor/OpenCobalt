# Security

## Scope

OpenCobalt is a local-first tool intended for single-user, local development environments. It does not operate servers, handle multi-user access, or process untrusted external input in production.

## What OpenCobalt Does Not Do

- Does not make outbound network calls by default
- Does not store credentials (API keys are read from environment variables only)
- Does not write to the Obsidian vault unless explicitly configured
- Does not push, deploy, or publish anything automatically
- Does not execute agent commands autonomously

## Credential Handling

- API keys (Anthropic, OpenAI, Google) are read from environment variables only
- No default values for API keys are hardcoded in source
- The `.env` file is gitignored and must never be committed
- The `.env.example` file contains only placeholder comments

## Public Repo Safety

The `public-check` command scans for common hygiene issues before any push:

```bash
opencobalt public-check
```

Detects:
- `.env` files present in the repo tree
- Hardcoded secret patterns (passwords, API keys, tokens)
- References to private vault paths
- Oversized files (over 10 MB)
- `node_modules/` or `.venv/` accidentally included

## Autonomy Lanes

**Green lane** (safe to proceed):
- Read repo files
- Create local artifacts
- Run tests
- Write docs
- Create local SQLite records
- Build context packs
- Inspect public docs

**Yellow lane** (proceed with care):
- Copy code from other repos after auditing
- Install dependencies
- Launch local CLIs
- Write to configured export paths

**Red lane** (requires explicit user instruction):
- Push to GitHub
- Publish packages
- Deploy
- Delete folders
- Read `.env` contents
- Submit forms or send messages
- Automate logged-in web accounts
- Access billing or account settings

## Reporting Issues

Open an issue at the project repository. Do not include credentials or private paths in issue reports.
