"""Mission extraction schema and deterministic v0 extractor.

The extractor treats transcripts, tool output, diffs, and receipts as data.
It does not execute anything, does not call a network API, and does not store
the raw transcript. v0 is intentionally single-pass; a verifier can be added
later as a separate policy-gated stage.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from opencobalt.execution.runner import redact_text

MISSION_EXTRACTION_SCHEMA_VERSION = 1

MissionExtractionStatus = Literal["active", "blocked", "completed", "abandoned", "unknown"]
MissionExtractionConfidenceLevel = Literal["high", "medium", "low"]

EXTRACTION_PROMPT_TEMPLATE = """You are a mission state extractor for OpenCobalt.

Given the following session transcript, tool outputs, diffs, receipts, or agent report, produce ONLY valid JSON matching the schema exactly.

Do not summarize loosely. Extract durable mission state with precision.

Rules:
- If a claim is uncertain, put it in open_questions rather than guessing.
- Do not mark work completed unless the input provides explicit evidence.
- Do not infer success from optimistic wording alone.
- Preserve concrete file paths exactly when available.
- Preserve concrete artifact identifiers exactly when available.
- Decisions are choices that were actually made, not recommendations.
- Findings are discovered facts supported by the session.
- Assumptions are beliefs used by the agent that may not be proven.
- Risks are possible failure modes, regressions, safety issues, or unresolved hazards.
- Next actions should be executable continuation steps for a future agent.
- Use low confidence when evidence is partial, ambiguous, or missing.
- Use medium confidence when the input supports the field but not conclusively.
- Use high confidence only when the input directly supports the field.
- Return JSON only. No markdown. No commentary.
"""


class MissionExtractionConfidence(BaseModel):
    """Confidence values for each top-level extraction field."""

    model_config = ConfigDict(extra="forbid")

    goal: MissionExtractionConfidenceLevel
    status: MissionExtractionConfidenceLevel
    findings: MissionExtractionConfidenceLevel
    decisions: MissionExtractionConfidenceLevel
    assumptions: MissionExtractionConfidenceLevel
    open_questions: MissionExtractionConfidenceLevel
    next_actions: MissionExtractionConfidenceLevel
    files_touched: MissionExtractionConfidenceLevel
    artifacts: MissionExtractionConfidenceLevel
    risks: MissionExtractionConfidenceLevel
    overall: MissionExtractionConfidenceLevel


class MissionExtraction(BaseModel):
    """Structured mission intelligence extracted from one session artifact."""

    model_config = ConfigDict(extra="forbid")

    goal: str
    status: MissionExtractionStatus
    findings: list[str] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    files_touched: list[str] = Field(default_factory=list)
    artifacts: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    confidence: MissionExtractionConfidence


class DeterministicMissionExtractor:
    """Small local extractor for tests and v0 offline operation.

    It recognizes explicit line-oriented labels such as ``Goal:``,
    ``Finding:``, and ``Next action:``. Unlabeled uncertain statements become
    open questions. Other free-form text is ignored rather than elevated into
    facts, which keeps prompt-injection-like transcript text as data.
    """

    def extract(self, transcript: str) -> MissionExtraction:
        fields: dict[str, list[str]] = {
            "findings": [],
            "decisions": [],
            "assumptions": [],
            "open_questions": [],
            "next_actions": [],
            "files_touched": [],
            "artifacts": [],
            "risks": [],
        }
        direct: set[str] = set()
        inferred: set[str] = set()
        goal = ""
        status: MissionExtractionStatus = "unknown"

        for raw_line in transcript.splitlines():
            line = _clean_line(raw_line)
            if not line:
                continue
            label, value = _split_label(line)
            if label is None:
                if _looks_uncertain(line):
                    fields["open_questions"].append(_redact_value(line))
                    inferred.add("open_questions")
                continue
            value = _redact_value(value)
            if not value:
                continue
            normalized = _normalize_label(label)
            if normalized == "goal":
                goal = value
                direct.add("goal")
            elif normalized == "status":
                parsed_status = _parse_status(value)
                status = parsed_status
                direct.add("status")
                if parsed_status == "unknown" and value.lower() != "unknown":
                    fields["open_questions"].append(f"Unrecognized status claim: {value}")
                    inferred.add("open_questions")
            elif normalized in {"files_touched", "artifacts"}:
                fields[normalized].extend(_split_values(value))
                direct.add(normalized)
            elif normalized:
                fields[normalized].append(value)
                direct.add(normalized)

        if not goal:
            goal = "unknown"
            inferred.add("goal")

        if status == "unknown" and fields["next_actions"]:
            status = "active"
            inferred.add("status")

        confidence = MissionExtractionConfidence(
            goal=_confidence_for("goal", direct, inferred, bool(goal and goal != "unknown")),
            status=_confidence_for("status", direct, inferred, status != "unknown"),
            findings=_confidence_for("findings", direct, inferred, bool(fields["findings"])),
            decisions=_confidence_for("decisions", direct, inferred, bool(fields["decisions"])),
            assumptions=_confidence_for(
                "assumptions", direct, inferred, bool(fields["assumptions"])
            ),
            open_questions=_confidence_for(
                "open_questions", direct, inferred, bool(fields["open_questions"])
            ),
            next_actions=_confidence_for(
                "next_actions", direct, inferred, bool(fields["next_actions"])
            ),
            files_touched=_confidence_for(
                "files_touched", direct, inferred, bool(fields["files_touched"])
            ),
            artifacts=_confidence_for("artifacts", direct, inferred, bool(fields["artifacts"])),
            risks=_confidence_for("risks", direct, inferred, bool(fields["risks"])),
            overall=_overall_confidence(direct),
        )
        return MissionExtraction(
            goal=goal,
            status=status,
            findings=_dedupe(fields["findings"]),
            decisions=_dedupe(fields["decisions"]),
            assumptions=_dedupe(fields["assumptions"]),
            open_questions=_dedupe(fields["open_questions"]),
            next_actions=_dedupe(fields["next_actions"]),
            files_touched=_dedupe(fields["files_touched"]),
            artifacts=_dedupe(fields["artifacts"]),
            risks=_dedupe(fields["risks"]),
            confidence=confidence,
        )


def load_extraction_json(path: Path) -> MissionExtraction:
    """Load externally generated extraction JSON and validate the v0 schema."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    return MissionExtraction.model_validate(payload)


def _clean_line(line: str) -> str:
    return line.strip().removeprefix("-").removeprefix("*").strip()


def _split_label(line: str) -> tuple[str | None, str]:
    if ":" not in line:
        return None, line
    label, value = line.split(":", 1)
    return label.strip(), value.strip()


def _normalize_label(label: str) -> str | None:
    normalized = label.strip().lower().replace("-", " ").replace("_", " ")
    normalized = " ".join(normalized.split())
    return {
        "goal": "goal",
        "status": "status",
        "finding": "findings",
        "findings": "findings",
        "decision": "decisions",
        "decisions": "decisions",
        "assumption": "assumptions",
        "assumptions": "assumptions",
        "open question": "open_questions",
        "open questions": "open_questions",
        "question": "open_questions",
        "next action": "next_actions",
        "next actions": "next_actions",
        "files touched": "files_touched",
        "file touched": "files_touched",
        "artifact": "artifacts",
        "artifacts": "artifacts",
        "risk": "risks",
        "risks": "risks",
    }.get(normalized)


def _parse_status(value: str) -> MissionExtractionStatus:
    normalized = value.strip().lower()
    if normalized in {"active", "blocked", "completed", "abandoned", "unknown"}:
        return normalized  # type: ignore[return-value]
    return "unknown"


def _split_values(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _looks_uncertain(line: str) -> bool:
    lower = line.lower()
    return (
        "?" in line
        or lower.startswith(("maybe ", "whether ", "unclear ", "unknown "))
        or " not sure " in f" {lower} "
        or " uncertain " in f" {lower} "
    )


def _redact_value(value: str) -> str:
    return redact_text(value.strip())


def _dedupe(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _confidence_for(
    field: str, direct: set[str], inferred: set[str], has_value: bool
) -> MissionExtractionConfidenceLevel:
    if field in direct:
        return "high"
    if field in inferred or has_value:
        return "low"
    return "low"


def _overall_confidence(direct: set[str]) -> MissionExtractionConfidenceLevel:
    strong_fields = {
        "goal",
        "status",
        "findings",
        "decisions",
        "open_questions",
        "next_actions",
        "files_touched",
        "artifacts",
        "risks",
    }
    count = len(direct & strong_fields)
    if count >= 8 and "status" in direct:
        return "high"
    if count >= 4:
        return "medium"
    return "low"
