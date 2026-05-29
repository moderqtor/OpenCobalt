"""Discovers locally installed Ollama models.

Falls back gracefully when Ollama is not installed or not running.
Never assumes specific models are present -- always discovers dynamically.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass


@dataclass
class ModelInfo:
    name: str
    model_id: str
    size: str


def discover_models() -> list[ModelInfo]:
    """Return all locally installed Ollama models.

    Returns an empty list if Ollama is not installed or not reachable.
    """
    try:
        result = subprocess.run(
            ["ollama", "list"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return []
    if result.returncode != 0:
        return []
    return _parse_ollama_list(result.stdout)


def _parse_ollama_list(output: str) -> list[ModelInfo]:
    models = []
    lines = output.strip().splitlines()
    for line in lines[1:]:  # skip header row
        parts = line.split()
        if len(parts) >= 3:
            size = f"{parts[2]} {parts[3]}" if len(parts) >= 4 else parts[2]
            models.append(ModelInfo(name=parts[0], model_id=parts[1], size=size))
    return models


def is_ollama_available() -> bool:
    """Return True if the ollama binary is present and responsive."""
    try:
        result = subprocess.run(
            ["ollama", "--version"],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


def worker_tier_models(models: list[ModelInfo] | None = None) -> list[ModelInfo]:
    """Return models suitable for worker-tier tasks (local Ollama only).

    Worker-tier models handle low-stakes tasks: summarization, tagging,
    extraction, rough drafts. They are not used for architecture decisions,
    final code generation, security review, or public-facing content.
    """
    if models is None:
        models = discover_models()
    return models
