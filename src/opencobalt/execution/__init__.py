"""Receipt-Backed Execution v0.

Local-first, policy-gated execution layer above agent runtimes. Every agent
action leaves a verifiable receipt: plan, command, output artifacts, hashes.
"""

from .adapters import (
    AntigravityAdapter,
    CommandOptions,
    NoopAdapter,
    OllamaAdapter,
    RuntimeAdapter,
    available_runtimes,
    get_adapter,
)
from .artifacts import attach_artifact, hash_file, verify_artifact
from .caffeinate import caffeinate_available, keep_awake
from .engine import ExecutionEngine, ExecutionOutcome
from .models import (
    ARTIFACT_TYPES,
    ExecutionArtifact,
    ExecutionPlan,
    ExecutionResult,
    ExecutionStep,
    WorkReceipt,
)
from .policy import PolicyDecision, check_execution, classify_risk, max_risk
from .runner import ProcessRunner
from .store import ExecutionStore

__all__ = [
    "ARTIFACT_TYPES",
    "AntigravityAdapter",
    "CommandOptions",
    "ExecutionArtifact",
    "ExecutionEngine",
    "ExecutionOutcome",
    "ExecutionPlan",
    "ExecutionResult",
    "ExecutionStep",
    "ExecutionStore",
    "NoopAdapter",
    "OllamaAdapter",
    "PolicyDecision",
    "ProcessRunner",
    "RuntimeAdapter",
    "WorkReceipt",
    "attach_artifact",
    "available_runtimes",
    "caffeinate_available",
    "check_execution",
    "classify_risk",
    "get_adapter",
    "hash_file",
    "keep_awake",
    "max_risk",
    "verify_artifact",
]
