"""Central execution policy gate.

Classifies task risk deterministically (keyword-based, no LLM) and decides
whether a plan may execute. Dry-run is always allowed. Black-risk execution
is not supported in v0.

Risk ladder:
  green  -- read-only planning, summarization, static analysis
  yellow -- local file edits, test runs, generated artifacts
  red    -- shell execution, credential/environment access, deployment
  black  -- destructive filesystem operations, credential export
"""

from __future__ import annotations

from pydantic import BaseModel

from .models import RiskLevel

_RISK_ORDER: dict[str, int] = {"green": 0, "yellow": 1, "red": 2, "black": 3}

_BLACK_KEYWORDS = (
    "credential export",
    "export credentials",
    "delete everything",
    "rm -rf",
    "wipe",
    "format disk",
    "drop database",
)

_RED_KEYWORDS = (
    ".env",
    "api key",
    "api keys",
    "browser login",
    "browser profile",
    "browser profiles",
    "cookie",
    "cookies",
    "credential",
    "deploy",
    "deployment",
    "environment configuration",
    "external network automation",
    "package publishing",
    "private key",
    "private keys",
    "production config",
    "publish package",
    "secret",
    "secrets",
    "shell execution",
    "ssh key",
    "ssh keys",
    "token",
    "tokens",
)

_YELLOW_KEYWORDS = (
    "edit",
    "write file",
    "modify",
    "refactor",
    "fix",
    "patch",
    "test",
    "tests",
    "generate",
    "create file",
    "artifact",
    "screenshot",
    "browser",
    "install",
    "file",
)


def classify_risk(task: str) -> RiskLevel:
    """Return the risk level for a task description. Deterministic."""
    task_lower = task.lower()
    if any(kw in task_lower for kw in _BLACK_KEYWORDS):
        return "black"
    if any(kw in task_lower for kw in _RED_KEYWORDS):
        return "red"
    if any(kw in task_lower for kw in _YELLOW_KEYWORDS):
        return "yellow"
    return "green"


def max_risk(*levels: str) -> RiskLevel:
    """Return the most severe of the given risk levels."""
    worst = max(levels, key=lambda lv: _RISK_ORDER.get(lv, 0), default="green")
    return worst if worst in _RISK_ORDER else "green"  # type: ignore[return-value]


def approval_required(risk_level: str) -> bool:
    return _RISK_ORDER.get(risk_level, 0) >= _RISK_ORDER["red"]


class PolicyDecision(BaseModel):
    allowed: bool
    risk_level: RiskLevel
    reason: str
    requires_approval: bool = False


def check_execution(
    risk_level: str,
    *,
    dry_run: bool,
    execute: bool,
    approved: bool,
) -> PolicyDecision:
    """Gate a plan before any subprocess is started.

    Rules:
      dry-run            always allowed
      green / yellow     require explicit --execute
      red                require explicit --execute plus --yes approval
      black              blocked in v0, no override
    """
    level: RiskLevel = risk_level if risk_level in _RISK_ORDER else "green"  # type: ignore[assignment]
    needs_approval = approval_required(level)

    if dry_run:
        return PolicyDecision(
            allowed=True,
            risk_level=level,
            reason="dry-run is always allowed; no subprocess will start",
            requires_approval=needs_approval,
        )
    if level == "black":
        return PolicyDecision(
            allowed=False,
            risk_level=level,
            reason="black-risk tasks are blocked; v0 has no unsafe override",
            requires_approval=True,
        )
    if not execute:
        return PolicyDecision(
            allowed=False,
            risk_level=level,
            reason="execution requires explicit --execute",
            requires_approval=needs_approval,
        )
    if level == "red" and not approved:
        return PolicyDecision(
            allowed=False,
            risk_level=level,
            reason="red-risk execution requires explicit approval (--yes)",
            requires_approval=True,
        )
    return PolicyDecision(
        allowed=True,
        risk_level=level,
        reason=f"{level} task approved for execution",
        requires_approval=needs_approval,
    )
