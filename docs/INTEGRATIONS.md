# Integrations

OpenCobalt uses an integration system to register awareness of external tools
without depending on them. Each integration is a slot: it describes a tool or
runtime and checks whether it is installed. Integrations do not execute commands
or make API calls on their own.

## What integrations are

An integration answers two questions:

1. Is this tool installed on the local machine?
2. What static profile should OpenCobalt show for this tool?

Integrations are not dependencies. If the external tool is not installed, the integration still loads and reports `installed: false`. Nothing crashes.

Execution adapters are stricter. They live in `src/opencobalt/execution/` and
must produce capability snapshots, normalized invocations, hashed artifacts,
normalized receipts, provenance references, and tests. An integration registry
entry is not runtime adapter support.

## Current integrations

| Name | Source | Tier | Capabilities | Install check | Status |
|------|--------|------|-------------|---------------|--------|
| aider | https://github.com/paul-gauthier/aider | worker | code editing | `shutil.which("aider")` | stub if not installed |
| ollama | https://github.com/ollama/ollama | worker | local inference | `subprocess.run(["ollama", "list"])` returns 0 | stub if not installed |
| claude-code | https://github.com/anthropics/claude-code | executive | architecture, code, review, debug, security | `shutil.which("claude")` | stub if not installed |
| google-antigravity | https://antigravity.google/product/antigravity-cli | executive | agent-runtime, interactive-cli, runtime-discovered workflows | `shutil.which("agy")` plus `agy --version` and `agy --help` diagnostics | primary Google agent runtime |
| cursor | https://www.cursor.com | manager | ui, editor, frontend, component, style | not checkable via PATH | integration stub only |
| context7 | https://github.com/upstash/context7 | manager | docs, search, mcp, library-context | not checkable via PATH | always available |
| github-cli | https://github.com/cli/cli | manager | pr-create, issue-link, branch, review | `shutil.which("gh")` | stub if not installed |
| obsidian | https://obsidian.md | manager | notes, knowledge-base, export, search | `/Applications/Obsidian.app` exists | available if installed |

Legacy aliases `gemini-cli`, `gemini_cli`, `google-gemini-cli`, and
`antigravity-cli` resolve to `google-antigravity` with a deprecation warning.
Gemini remains valid as a model-family name, for example `gemini-pro`, but
Gemini CLI is no longer the canonical Google runtime.

Use `opencobalt doctor antigravity` to inspect local `agy` behavior. OpenCobalt checks PATH, version, help output, and runtime-discovered evidence for non-interactive mode, model selection, plugins, sandboxing, and other capabilities. Unknown Antigravity features are reported as `unknown`, not guessed.

## Adding a new integration

Do not use this checklist to add an execution adapter. Runtime adapters must
follow `docs/ADAPTER_RECEIPT_NORMALIZATION.md`.

1. Create a file in `src/opencobalt/integrations/` that subclasses `BaseIntegration`:

```python
# src/opencobalt/integrations/mytool_integration.py
from __future__ import annotations
import shutil
from .base_integration import BaseIntegration

class MyToolIntegration(BaseIntegration):
    name = "mytool"
    description = "Brief description of what mytool does"
    source_url = "https://github.com/example/mytool"
    tier = "worker"
    capabilities = ["task-type-a", "task-type-b"]

    def install_check(self) -> bool:
        return shutil.which("mytool") is not None

    def invoke(self, task: str) -> str:
        return f"mytool run '{task}' (stub -- run manually if mytool is installed)"
```

2. Add it to the registry in `src/opencobalt/integrations/registry.py`:

```python
from .mytool_integration import MyToolIntegration

REGISTRY: dict[str, BaseIntegration] = {
    ...
    "mytool": MyToolIntegration(),  # add here
}
```

3. Add tests in `tests/test_integrations.py` covering at minimum:
   - `name` attribute is correct
   - `install_check()` returns a `bool`
   - `invoke()` returns a string containing "stub"

## Rules for install_check()

- Use `shutil.which()` for simple binary presence checks (no subprocess needed).
- Use `subprocess.run()` with `capture_output=True` and a short `timeout` when the tool needs to be responsive, not just present.
- Always wrap `subprocess.run()` in a `try/except (FileNotFoundError, subprocess.TimeoutExpired, OSError)` and return `False` in the except block.
- Never make network or API calls inside `install_check()`.

## CLI usage

```
opencobalt integrations list
opencobalt integrations check
```

`integrations list` lists all registered integrations with their name, tier, capabilities, and status.
`integrations check` runs `install_check()` on all integrations and reports which are active or inactive.
