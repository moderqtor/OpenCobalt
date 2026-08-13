# Contributing

Read [OPENCOBALT.md](../OPENCOBALT.md) and [AGENTS.md](../AGENTS.md) first.
The live implementation and tests are authoritative.

## Branch naming

All changes must come in via feature branches, not directly to `main`.

Use the following prefixes:

- `feature/*` -- new functionality
- `fix/*` -- bug fixes and corrections
- `docs/*` -- documentation-only changes

## Pull requests

- Open a PR from your branch to `main`
- CI must pass before merge (pytest + ruff)
- Keep PRs focused: one concern per PR

## Running checks locally

```bash
uv run ruff check .
uv run opencobalt public-check
uv run pytest
```

If UI files changed:

```bash
npm run build --prefix ui
```

Do not push or merge unless the maintainer explicitly asks for it.
