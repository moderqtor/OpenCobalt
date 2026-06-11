"""Legacy compatibility shim for deprecated Gemini CLI integration naming."""

from __future__ import annotations

import warnings

from .antigravity_integration import AntigravityIntegration


class GeminiCLIIntegration(AntigravityIntegration):
    """Deprecated alias for Google Antigravity CLI."""

    def __init__(self) -> None:
        warnings.warn(
            "Gemini CLI integration is legacy; use google-antigravity with the agy command.",
            DeprecationWarning,
            stacklevel=2,
        )
