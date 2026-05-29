# Integrations

OpenCobalt uses an integration system to register awareness of external tools without depending on them. Each integration is a slot -- it describes a tool, checks whether it is installed, and can return a description of what it would do with a given task. Integrations do not execute commands or make API calls on their own.

## What integrations are

An integration is a thin wrapper around an external tool (such as a CLI binary). It answers two questions:

1. Is this tool installed on the local machine?
2. What would this tool do if invoked with a given task description?

Integrations are not dependencies. If the external tool is not installed, the integration still loads and reports `installed: false`. Nothing crashes.

## Current integrations

| Name   | Source URL                              | What it does                                   | Install check |
|--------|-----------------------------------------|------------------------------------------------|---------------|
| aider  | https://github.com/paul-gauthier/aider  | Code editing via aider (AI pair programmer)    | `shutil.which("aider") is not None` |
| ollama | https://github.com/ollama/ollama        | Local model inference via Ollama               | `subprocess.run(["ollama", "list"], timeout=3)` returns 0 |

Note: both integrations are stubs. Their `invoke()` methods return a string describing what the tool would do -- they do not actually run the tool.

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

    def install_check(self) -> bool:
        return shutil.which("mytool") is not None

    def invoke(self, task: str) -> str:
        return f"mytool run '{task}' (stub -- run manually if mytool is installed)"
```

2. Add it to the registry in `src/opencobalt/integrations/registry.py`:

```python
from .mytool_integration import MyToolIntegration

REGISTRY: dict[str, BaseIntegration] = {
    "aider": AiderIntegration(),
    "ollama": OllamaIntegration(),
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
```

Lists all registered integrations with their name, description, and installed status.
