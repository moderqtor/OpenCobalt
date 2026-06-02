# Contributing

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
python3 -m pytest -q
ruff check src/ tests/
opencobalt public-check
```
