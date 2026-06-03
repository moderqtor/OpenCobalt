# Integrations

OpenCobalt uses an integration system to register awareness of external tools without depending on them. Each integration is a slot -- it describes a tool, checks whether it is installed, and can return a description of what it would do with a given task. Integrations do not execute commands or make API calls on their own.

## What integrations are

An integration is a thin wrapper around an external tool (such as a CLI binary). It answers two questions:

1. Is this tool installed on the local machine?
2. What would this tool do if invoked with a given task description?

Integrations are not dependencies. If the external tool is not installed, the integration still loads and reports `installed: false`. Nothing crashes.

## Current integrations

| Name | Source | Tier | Capabilities | Install check | Status |
|------|--------|------|-------------|---------------|--------|
| aider | https://github.com/paul-gauthier/aider | worker | (code editing) | `shutil.which("aider")` | stub if not installed |
| ollama | https://github.com/ollama/ollama | worker | (local inference) | `subprocess.run(["ollama", "list"])` returns 0 | stub if not installed |
| claude-code | https://github.com/anthropics/claude-code | executive | architecture, code, review, debug, security | `shutil.which("claude")` | stub if not installed |
| gemini-cli | https://github.com/google-gemini/gemini-cli | executive | long-context, search, analyze, audit | `shutil.which("gemini")` | stub if not installed |
| cursor | https://www.cursor.com | manager | ui, editor, frontend, component, style | not checkable via PATH | always available |
| context7 | https://github.com/upstash/context7 | manager | docs, search, mcp, library-context | not checkable via PATH | always available |

## Adding a new integration

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
