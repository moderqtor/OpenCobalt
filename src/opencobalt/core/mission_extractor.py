"""Mission extraction schema and deterministic v0 extractor.

The extractor treats transcripts, tool output, diffs, and receipts as data.
It does not execute anything, does not call a network API, and does not store
the raw transcript. v0 is intentionally single-pass; a verifier can be added
later as a separate policy-gated stage.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from opencobalt.execution.runner import redact_text

MISSION_EXTRACTION_SCHEMA_VERSION = 2

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
- Separate source-mentioned prior mission/extraction/verification ids from
  current mission state and implementation artifacts when possible.
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
    source_references: MissionExtractionConfidenceLevel = "low"
    artifacts: MissionExtractionConfidenceLevel
    risks: MissionExtractionConfidenceLevel
    overall: MissionExtractionConfidenceLevel


class MissionExtraction(BaseModel):
    """Structured mission intelligence extracted from one session artifact."""

    model_config = ConfigDict(extra="forbid")

    goal: str
    status: MissionExtractionStatus
    findings: list[str]
    decisions: list[str]
    assumptions: list[str]
    open_questions: list[str]
    next_actions: list[str]
    files_touched: list[str]
    source_references: list[str] = Field(default_factory=list)
    artifacts: list[str]
    risks: list[str]
    confidence: MissionExtractionConfidence


class DeterministicMissionExtractor:
    """Small local extractor for tests and v0 offline operation.

    It recognizes explicit line-oriented labels such as ``Goal:``,
    ``Finding:``, and ``Next action:`` plus common agent final-report sections
    such as ``Final verification``, ``Files changed``, and
    ``Next recommendation``. Unlabeled uncertain statements become open
    questions. Other free-form text is ignored rather than elevated into facts,
    which keeps prompt-injection-like transcript text as data.
    """

    def extract(self, transcript: str) -> MissionExtraction:
        fields: dict[str, list[str]] = {
            "findings": [],
            "decisions": [],
            "assumptions": [],
            "open_questions": [],
            "next_actions": [],
            "files_touched": [],
            "source_references": [],
            "artifacts": [],
            "risks": [],
        }
        direct: set[str] = set()
        medium: set[str] = set()
        inferred: set[str] = set()
        goal = ""
        status: MissionExtractionStatus = "unknown"
        active_report_section: str | None = None
        verification_items: list[str] = []
        worktree_clean = False
        completion_state_seen = False

        def mark(field: str, level: MissionExtractionConfidenceLevel = "high") -> None:
            if level == "high":
                direct.add(field)
            elif level == "medium":
                medium.add(field)
            else:
                inferred.add(field)

        def add_list_value(
            field: str, value: str, *, level: MissionExtractionConfidenceLevel = "high"
        ) -> None:
            if _looks_instruction_injection(value):
                return
            redacted = _redact_value(value)
            if not redacted:
                return
            references = _extract_source_reference_ids(redacted)
            stored_value = (
                _replace_source_reference_ids(redacted)
                if field != "source_references"
                else redacted
            )
            fields[field].append(stored_value)
            mark(field, level)
            if field != "source_references":
                for reference in references:
                    fields["source_references"].append(reference)
                    mark("source_references", level)
            if field not in {"artifacts", "source_references"}:
                for artifact in _extract_artifact_ids(stored_value):
                    fields["artifacts"].append(artifact)
                    mark("artifacts", level)

        def add_files(value: str) -> None:
            for item in _split_values(value):
                add_list_value("files_touched", item)

        def add_limitation(value: str) -> None:
            if _looks_uncertain(value):
                add_list_value("open_questions", value)
            else:
                add_list_value("risks", value)

        def handle_core_label(normalized: str, value: str) -> None:
            nonlocal goal, status
            value = _redact_value(value)
            if not value:
                return
            if normalized == "goal":
                goal = value
                direct.add("goal")
                return
            if normalized == "status":
                parsed_status = _parse_status(value)
                status = parsed_status
                direct.add("status")
                if parsed_status == "unknown" and value.lower() != "unknown":
                    add_list_value("open_questions", f"Unrecognized status claim: {value}")
                return
            if normalized in {"files_touched", "artifacts"}:
                for item in _split_values(value):
                    add_list_value(normalized, item)
                return
            add_list_value(normalized, value)

        def handle_report_section(section: str, value: str) -> None:
            nonlocal goal, status, worktree_clean, completion_state_seen
            value = _redact_value(value)
            if not value:
                return
            if section == "branch":
                add_list_value("findings", f"Branch: {value}")
                add_list_value("artifacts", value)
            elif section == "base_branch_sha":
                add_list_value("findings", f"Base branch/SHA: {value}")
            elif section in {"test_baseline", "final_verification"}:
                verification_items.append(value)
                add_list_value("findings", f"{_report_section_title(section)}: {value}")
            elif section == "worktree":
                worktree_clean = "clean" in value.lower()
                add_list_value("findings", f"Worktree: {value}")
            elif section == "pushed_merged":
                lower = value.lower()
                completion_state_seen = any(
                    term in lower for term in ("merged: yes", "pushed: yes", "merged yes")
                )
                add_list_value("findings", f"Pushed or merged: {value}")
            elif section == "local_commit":
                completion_state_seen = True
                add_list_value("findings", f"Local commit: {value}")
                add_list_value("artifacts", value)
            elif section == "summary":
                if not goal:
                    goal = value
                    medium.add("goal")
                add_list_value("findings", f"Summary: {value}")
            elif section == "cli_added":
                add_list_value("artifacts", value)
            elif section in {
                "schema_added",
                "persistence_behavior",
                "cold_resume_behavior",
                "cli_behavior",
                "close_session_behavior",
                "verification_behavior",
                "handoff_behavior",
                "safety_behavior",
                "manual_smoke",
                "safety_findings",
                "tests_added",
            }:
                add_list_value("findings", f"{_report_section_title(section)}: {value}")
            elif section in {"known_limitations", "deferred"}:
                add_limitation(value)
            elif section == "files_changed":
                add_files(value)
            elif section == "next_recommendation":
                add_list_value("next_actions", value)
            elif section == "open_questions":
                add_list_value("open_questions", value)
            elif section == "risks":
                add_list_value("risks", value)
            if status == "unknown" and _explicit_status_from_report(section, value):
                status = _explicit_status_from_report(section, value) or "unknown"
                direct.add("status")

        for raw_line in transcript.splitlines():
            heading = _markdown_heading(raw_line)
            if heading is not None:
                active_report_section = _normalize_report_section(heading)
                continue
            line = _clean_line(raw_line)
            if not line:
                continue
            if _looks_instruction_injection(line):
                continue
            label, value = _split_label(line)
            if label is None:
                if active_report_section:
                    handle_report_section(active_report_section, line)
                elif _looks_uncertain(line):
                    fields["open_questions"].append(_redact_value(line))
                    inferred.add("open_questions")
                continue
            normalized = _normalize_label(label)
            report_section = _normalize_report_section(label)
            if normalized:
                active_report_section = None
                handle_core_label(normalized, value)
            elif report_section:
                if value:
                    active_report_section = None
                    handle_report_section(report_section, value)
                else:
                    active_report_section = report_section
            elif active_report_section and value:
                handle_report_section(active_report_section, line)
            elif _looks_uncertain(line):
                fields["open_questions"].append(_redact_value(line))
                inferred.add("open_questions")

        if not goal:
            goal = "unknown"
            inferred.add("goal")

        if status == "unknown" and _verification_supports_completion(
            verification_items, worktree_clean, completion_state_seen
        ):
            status = "completed"
            medium.add("status")
        elif status == "unknown" and fields["next_actions"]:
            status = "active"
            inferred.add("status")

        confidence = MissionExtractionConfidence(
            goal=_confidence_for(
                "goal", direct, medium, inferred, bool(goal and goal != "unknown")
            ),
            status=_confidence_for("status", direct, medium, inferred, status != "unknown"),
            findings=_confidence_for(
                "findings", direct, medium, inferred, bool(fields["findings"])
            ),
            decisions=_confidence_for(
                "decisions", direct, medium, inferred, bool(fields["decisions"])
            ),
            assumptions=_confidence_for(
                "assumptions", direct, medium, inferred, bool(fields["assumptions"])
            ),
            open_questions=_confidence_for(
                "open_questions", direct, medium, inferred, bool(fields["open_questions"])
            ),
            next_actions=_confidence_for(
                "next_actions", direct, medium, inferred, bool(fields["next_actions"])
            ),
            files_touched=_confidence_for(
                "files_touched", direct, medium, inferred, bool(fields["files_touched"])
            ),
            source_references=_confidence_for(
                "source_references",
                direct,
                medium,
                inferred,
                bool(fields["source_references"]),
            ),
            artifacts=_confidence_for(
                "artifacts", direct, medium, inferred, bool(fields["artifacts"])
            ),
            risks=_confidence_for("risks", direct, medium, inferred, bool(fields["risks"])),
            overall=_overall_confidence(direct, medium),
        )
        source_references = _dedupe(fields["source_references"])
        reference_fragments = {
            reference.split("-", 1)[1]
            for reference in source_references
            if "-" in reference
        }
        artifacts = [
            artifact
            for artifact in _dedupe(fields["artifacts"])
            if artifact not in source_references and artifact not in reference_fragments
        ]

        return MissionExtraction(
            goal=goal,
            status=status,
            findings=_dedupe(fields["findings"]),
            decisions=_dedupe(fields["decisions"]),
            assumptions=_dedupe(fields["assumptions"]),
            open_questions=_dedupe(fields["open_questions"]),
            next_actions=_dedupe(fields["next_actions"]),
            files_touched=_dedupe(fields["files_touched"]),
            source_references=source_references,
            artifacts=artifacts,
            risks=_dedupe(fields["risks"]),
            confidence=confidence,
        )


def load_extraction_json(path: Path) -> MissionExtraction:
    """Load externally generated extraction JSON and validate the v0 schema."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    return MissionExtraction.model_validate(payload)


def _clean_line(line: str) -> str:
    return line.strip().removeprefix("-").removeprefix("*").strip()


def _markdown_heading(line: str) -> str | None:
    stripped = line.strip()
    if not stripped.startswith("#"):
        return None
    return stripped.lstrip("#").strip()


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


def _normalize_report_section(label: str) -> str | None:
    normalized = _normalize_key(label)
    return {
        "branch": "branch",
        "base": "base_branch_sha",
        "base branch": "base_branch_sha",
        "base sha": "base_branch_sha",
        "base branch sha": "base_branch_sha",
        "base branch and sha": "base_branch_sha",
        "test baseline": "test_baseline",
        "baseline": "test_baseline",
        "final verification": "final_verification",
        "verification": "final_verification",
        "final reported": "final_verification",
        "worktree": "worktree",
        "pushed or merged": "pushed_merged",
        "pushed merged": "pushed_merged",
        "pushed": "pushed_merged",
        "merged": "pushed_merged",
        "local commit": "local_commit",
        "local commit sha": "local_commit",
        "commit": "local_commit",
        "summary": "summary",
        "cli added": "cli_added",
        "commands added": "cli_added",
        "schema added": "schema_added",
        "persistence behavior": "persistence_behavior",
        "cold resume behavior": "cold_resume_behavior",
        "cold-resume behavior": "cold_resume_behavior",
        "cli behavior": "cli_behavior",
        "close session behavior": "close_session_behavior",
        "verification behavior": "verification_behavior",
        "handoff behavior": "handoff_behavior",
        "safety behavior": "safety_behavior",
        "manual smoke": "manual_smoke",
        "safety findings": "safety_findings",
        "known limitations": "known_limitations",
        "limitations": "known_limitations",
        "deferred": "deferred",
        "files changed": "files_changed",
        "files touched": "files_changed",
        "tests added": "tests_added",
        "next recommendation": "next_recommendation",
        "next branch recommendation": "next_recommendation",
        "recommended next branch": "next_recommendation",
        "open questions": "open_questions",
        "risks": "risks",
    }.get(normalized)


def _normalize_key(value: str) -> str:
    normalized = value.strip().lower().replace("-", " ").replace("_", " ")
    normalized = normalized.replace("/", " ")
    normalized = re.sub(r"[^a-z0-9\s]+", " ", normalized)
    return " ".join(normalized.split())


def _report_section_title(section: str) -> str:
    return {
        "test_baseline": "Test baseline",
        "final_verification": "Final verification",
        "schema_added": "Schema added",
        "persistence_behavior": "Persistence behavior",
        "cold_resume_behavior": "Cold-resume behavior",
        "cli_behavior": "CLI behavior",
        "close_session_behavior": "Close-session behavior",
        "verification_behavior": "Verification behavior",
        "handoff_behavior": "Handoff behavior",
        "safety_behavior": "Safety behavior",
        "manual_smoke": "Manual smoke",
        "safety_findings": "Safety findings",
        "tests_added": "Tests added",
    }.get(section, section.replace("_", " ").title())


def _explicit_status_from_report(
    section: str, value: str
) -> MissionExtractionStatus | None:
    if section not in {"pushed_merged", "worktree", "final_verification"}:
        return None
    lower = value.lower()
    if any(term in lower for term in ("failed", "failure", "blocked")):
        return "blocked"
    if any(term in lower for term in ("abandoned", "not merged", "not pushed")):
        return None
    if section == "pushed_merged" and any(term in lower for term in ("merged: yes", "merged yes")):
        return "completed"
    return None


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


def _looks_instruction_injection(line: str) -> bool:
    lower = line.strip().lower()
    return lower.startswith(
        (
            "ignore previous instructions",
            "ignore all previous instructions",
            "disregard previous instructions",
            "forget previous instructions",
            "system instruction:",
            "developer instruction:",
        )
    )


def _redact_value(value: str) -> str:
    return redact_text(value.strip())


def _extract_artifact_ids(value: str) -> list[str]:
    artifact_text = _without_source_reference_ids(value)
    patterns = (
        r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/pull/\d+",
        r"\b[0-9a-f]{7,40}\b",
        r"\b(?:mev|mstp|apr|aplan|oplan|orun|run|trk|cand|rcpt)-[A-Za-z0-9_-]{6,}\b",
        r"\b\d+\s+passed,\s+\d+\s+warnings?\b",
    )
    artifacts: list[str] = []
    for pattern in patterns:
        artifacts.extend(match.group(0) for match in re.finditer(pattern, artifact_text))
    return _dedupe(artifacts)


def _extract_source_reference_ids(value: str) -> list[str]:
    return _dedupe(
        match.group(0)
        for match in re.finditer(
            r"\b(?:mis|mex|mver)-[A-Za-z0-9_-]{6,}\b",
            value,
        )
    )


def _without_source_reference_ids(value: str) -> str:
    return re.sub(
        r"\b(?:mis|mex|mver)-[A-Za-z0-9_-]{6,}\b",
        " ",
        value,
    )


def _replace_source_reference_ids(value: str) -> str:
    return re.sub(
        r"\b(?:mis|mex|mver)-[A-Za-z0-9_-]{6,}\b",
        "<source-reference>",
        value,
    )


def _verification_supports_completion(
    verification_items: list[str], worktree_clean: bool, completion_state_seen: bool
) -> bool:
    if not verification_items:
        return False
    joined = " ".join(item.lower() for item in verification_items)
    if any(term in joined for term in ("failed", "failure", "error", "dirty")):
        return False
    has_success = any(
        term in joined
        for term in (
            "passed",
            "clean",
            "all checks passed",
            "public safety: clean",
            "public-check: clean",
        )
    )
    if not has_success:
        return False
    if "pytest" in joined or "passed" in joined:
        return True
    return worktree_clean or completion_state_seen


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
    field: str,
    direct: set[str],
    medium: set[str],
    inferred: set[str],
    has_value: bool,
) -> MissionExtractionConfidenceLevel:
    if field in direct:
        return "high"
    if field in medium:
        return "medium"
    if field in inferred or has_value:
        return "low"
    return "low"


def _overall_confidence(
    direct: set[str], medium: set[str]
) -> MissionExtractionConfidenceLevel:
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
    direct_count = len(direct & strong_fields)
    supported_count = len((direct | medium) & strong_fields)
    if direct_count >= 8 and "status" in direct:
        return "high"
    if supported_count >= 4:
        return "medium"
    return "low"
