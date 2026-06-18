"""Deterministic verification for mission extraction records.

The verifier compares a structured extraction against source text supplied at
verification time. It treats source reports as data, never executes anything,
and returns compact metadata suitable for append-only persistence. Raw source
reports are not stored.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from opencobalt.execution.runner import redact_text

from .mission_extractor import (
    MissionExtraction,
    MissionExtractionConfidenceLevel,
    _clean_line,
    _dedupe,
    _extract_artifact_ids,
    _looks_instruction_injection,
    _markdown_heading,
    _normalize_report_section,
    _split_label,
)

MissionVerificationSupport = Literal["direct", "partial", "missing"]
MissionVerificationStatus = Literal["passed", "warnings", "failed"]

_FIELDS = (
    "goal",
    "status",
    "findings",
    "decisions",
    "assumptions",
    "open_questions",
    "next_actions",
    "files_touched",
    "artifacts",
    "risks",
    "confidence",
)


class MissionExtractionFieldVerification(BaseModel):
    """Source support and confidence after verifier adjustment for one field."""

    model_config = ConfigDict(extra="forbid")

    support: MissionVerificationSupport
    confidence_after: MissionExtractionConfidenceLevel


class MissionExtractionVerification(BaseModel):
    """Compact verifier output safe for durable storage."""

    model_config = ConfigDict(extra="forbid")

    status: MissionVerificationStatus
    overall_confidence_after_verification: MissionExtractionConfidenceLevel
    field_results: dict[str, MissionExtractionFieldVerification] = Field(
        default_factory=dict
    )
    warnings: list[str] = Field(default_factory=list)
    redactions_detected: list[str] = Field(default_factory=list)
    prompt_injection_lines_detected: int = 0


class DeterministicMissionExtractionVerifier:
    """Local v0 verifier for extraction/source consistency.

    This is a heuristic support checker, not a proof system. It downgrades
    confidence when source support is absent or only partial and emits warnings
    for common false-confidence hazards.
    """

    def verify(
        self, extraction: MissionExtraction, source_report: str
    ) -> MissionExtractionVerification:
        source = _PreparedSource.from_text(source_report)
        warnings: list[str] = []
        field_results: dict[str, MissionExtractionFieldVerification] = {}

        field_results["goal"] = self._verify_text_field(
            "goal", extraction.goal, extraction.confidence.goal, source, warnings
        )
        field_results["status"] = self._verify_status(extraction, source, warnings)
        for field in (
            "findings",
            "decisions",
            "assumptions",
            "open_questions",
            "next_actions",
            "files_touched",
            "artifacts",
            "risks",
        ):
            values = list(getattr(extraction, field))
            original_confidence = getattr(extraction.confidence, field)
            field_results[field] = self._verify_list_field(
                field, values, original_confidence, source, warnings
            )
        field_results["confidence"] = self._verify_confidence(
            extraction, field_results, warnings
        )

        warnings.extend(_missing_source_artifact_warnings(extraction, source))
        if source.prompt_injection_lines_detected:
            warnings.append(
                "suspicious prompt-injection lines detected in source report: "
                f"{source.prompt_injection_lines_detected}"
            )
        if source.redactions_detected:
            warnings.append(
                "token-shaped or secret-shaped source content was redacted before "
                "verification metadata was produced"
            )

        warnings = _dedupe(warnings)
        overall = _overall_after(field_results, bool(warnings))
        status: MissionVerificationStatus = "warnings" if warnings else "passed"
        return MissionExtractionVerification(
            status=status,
            overall_confidence_after_verification=overall,
            field_results=field_results,
            warnings=warnings,
            redactions_detected=source.redactions_detected,
            prompt_injection_lines_detected=source.prompt_injection_lines_detected,
        )

    def _verify_text_field(
        self,
        field: str,
        value: str,
        original_confidence: MissionExtractionConfidenceLevel,
        source: "_PreparedSource",
        warnings: list[str],
    ) -> MissionExtractionFieldVerification:
        if not value or value == "unknown":
            support: MissionVerificationSupport = "missing"
        else:
            support = source.support_for(value)
        confidence_after = _adjusted_confidence(original_confidence, support)
        _warn_high_without_direct(field, original_confidence, support, warnings)
        return MissionExtractionFieldVerification(
            support=support, confidence_after=confidence_after
        )

    def _verify_list_field(
        self,
        field: str,
        values: list[str],
        original_confidence: MissionExtractionConfidenceLevel,
        source: "_PreparedSource",
        warnings: list[str],
    ) -> MissionExtractionFieldVerification:
        if not values:
            support: MissionVerificationSupport = "missing"
        else:
            item_support = [source.support_for(value) for value in values]
            if all(item == "direct" for item in item_support):
                support = "direct"
            elif any(item != "missing" for item in item_support):
                support = "partial"
            else:
                support = "missing"
            for value, item in zip(values, item_support, strict=True):
                if item == "missing" and field in {
                    "findings",
                    "decisions",
                    "assumptions",
                    "next_actions",
                    "files_touched",
                    "artifacts",
                    "risks",
                }:
                    singular = field.removesuffix("s").replace("_", " ")
                    warnings.append(f"unsupported {singular}: {_preview(value)}")
        _warn_high_without_direct(field, original_confidence, support, warnings)
        return MissionExtractionFieldVerification(
            support=support,
            confidence_after=_adjusted_confidence(original_confidence, support),
        )

    def _verify_status(
        self,
        extraction: MissionExtraction,
        source: "_PreparedSource",
        warnings: list[str],
    ) -> MissionExtractionFieldVerification:
        original_confidence = extraction.confidence.status
        support = source.status_support(extraction.status)
        if extraction.status == "completed" and support != "direct":
            warnings.append("completed status lacks explicit source evidence")
        _warn_high_without_direct("status", original_confidence, support, warnings)
        return MissionExtractionFieldVerification(
            support=support,
            confidence_after=_adjusted_confidence(original_confidence, support),
        )

    def _verify_confidence(
        self,
        extraction: MissionExtraction,
        field_results: dict[str, MissionExtractionFieldVerification],
        warnings: list[str],
    ) -> MissionExtractionFieldVerification:
        missing_or_partial = [
            field
            for field, result in field_results.items()
            if field != "confidence" and result.support != "direct"
        ]
        if not missing_or_partial:
            support: MissionVerificationSupport = "direct"
        elif len(missing_or_partial) < len(field_results) - 1:
            support = "partial"
        else:
            support = "missing"
        if extraction.confidence.overall == "high" and support != "direct":
            warnings.append(
                "high confidence without direct source support: overall confidence"
            )
        return MissionExtractionFieldVerification(
            support=support,
            confidence_after=_adjusted_confidence(
                extraction.confidence.overall, support
            ),
        )


class _PreparedSource:
    def __init__(
        self,
        *,
        redacted_text: str,
        support_text: str,
        sections: dict[str, list[str]],
        redactions_detected: list[str],
        prompt_injection_lines_detected: int,
    ) -> None:
        self.redacted_text = redacted_text
        self.support_text = support_text
        self.normalized_support_text = _normalize_text(support_text)
        self.sections = sections
        self.redactions_detected = redactions_detected
        self.prompt_injection_lines_detected = prompt_injection_lines_detected
        self.artifacts = _extract_artifact_ids(redacted_text)
        self.commit_shas = _commit_shas(redacted_text)
        self.test_counts = _test_counts(redacted_text)
        self.files_changed = _section_values(sections, "files_changed")
        self.known_limitations = _section_values(sections, "known_limitations")

    @classmethod
    def from_text(cls, text: str) -> "_PreparedSource":
        redacted = redact_text(text)
        redactions = (
            ["token-shaped content redacted"] if redacted != text else []
        )
        sections: dict[str, list[str]] = {}
        support_lines: list[str] = []
        prompt_injection_count = 0
        active_section: str | None = None
        for raw_line in redacted.splitlines():
            heading = _markdown_heading(raw_line)
            if heading is not None:
                active_section = _normalize_report_section(heading)
                if active_section:
                    sections.setdefault(active_section, [])
                    support_lines.append(heading)
                continue
            line = _clean_line(raw_line)
            if not line:
                continue
            if _looks_instruction_injection(line):
                prompt_injection_count += 1
                continue
            label, value = _split_label(line)
            report_section = _normalize_report_section(label or "") if label else None
            if report_section:
                active_section = report_section
                sections.setdefault(report_section, [])
                if value:
                    sections[report_section].append(value)
                    support_lines.append(f"{label}: {value}")
                else:
                    support_lines.append(label or "")
                continue
            if active_section:
                sections.setdefault(active_section, []).append(line)
            support_lines.append(line)
        return cls(
            redacted_text=redacted,
            support_text="\n".join(support_lines),
            sections=sections,
            redactions_detected=redactions,
            prompt_injection_lines_detected=prompt_injection_count,
        )

    def support_for(self, value: str) -> MissionVerificationSupport:
        normalized = _normalize_text(value)
        if not normalized:
            return "missing"
        if normalized in self.normalized_support_text:
            return "direct"
        artifacts = _extract_artifact_ids(value)
        if artifacts and any(artifact in self.redacted_text for artifact in artifacts):
            return "direct"
        tokens = [token for token in normalized.split() if len(token) >= 4]
        if len(tokens) >= 4:
            hits = sum(1 for token in tokens if token in self.normalized_support_text)
            if hits >= max(3, len(tokens) // 2):
                return "partial"
        return "missing"

    def status_support(self, status: str) -> MissionVerificationSupport:
        lowered = self.support_text.lower()
        if status == "unknown":
            return "direct" if "status: unknown" in lowered else "partial"
        if f"status: {status}" in lowered:
            return "direct"
        if status == "completed":
            if any(
                term in lowered
                for term in (
                    "merged: yes",
                    "merged yes",
                    "status: completed",
                    "merged: true",
                    "local commit:",
                )
            ):
                return "partial"
            if any(term in lowered for term in ("passed", "all checks passed", "clean")):
                return "partial"
        if status == "active" and any(
            term in lowered for term in ("next action:", "next recommendation:")
        ):
            return "partial"
        if status == "blocked" and any(term in lowered for term in ("blocked", "failed")):
            return "direct"
        if status == "abandoned" and "abandoned" in lowered:
            return "direct"
        return "missing"


def _missing_source_artifact_warnings(
    extraction: MissionExtraction, source: _PreparedSource
) -> list[str]:
    warnings: list[str] = []
    extracted_text = extraction.model_dump_json()
    for limitation in source.known_limitations:
        if not _any_extraction_value_contains(
            limitation, extraction.risks + extraction.open_questions
        ):
            warnings.append(f"known limitation missing from risks/open questions: {limitation}")
    for file_path in source.files_changed:
        if file_path not in extraction.files_touched:
            warnings.append(f"files changed present in source but missing: {file_path}")
    for sha in source.commit_shas:
        if sha not in extracted_text:
            warnings.append(
                f"commit SHA present in source but missing from artifacts/findings: {sha}"
            )
    for test_count in source.test_counts:
        if test_count not in extracted_text:
            warnings.append(
                "test count present in source but missing from artifacts/findings: "
                f"{test_count}"
            )
    return warnings


def _section_values(sections: dict[str, list[str]], section: str) -> list[str]:
    values: list[str] = []
    for item in sections.get(section, []):
        values.extend(_split_section_items(item))
    return _dedupe([value for value in values if value])


def _split_section_items(value: str) -> list[str]:
    if "," in value:
        return [item.strip() for item in value.split(",") if item.strip()]
    return [value.strip()] if value.strip() else []


def _any_extraction_value_contains(needle: str, values: list[str]) -> bool:
    normalized_needle = _normalize_text(needle)
    return any(normalized_needle in _normalize_text(value) for value in values)


def _commit_shas(text: str) -> list[str]:
    return _dedupe(re.findall(r"\b[0-9a-f]{7,40}\b", text))


def _test_counts(text: str) -> list[str]:
    return _dedupe(re.findall(r"\b\d+\s+passed,\s+\d+\s+warnings?\b", text))


def _normalize_text(value: str) -> str:
    normalized = value.lower()
    normalized = re.sub(r"[^a-z0-9_./-]+", " ", normalized)
    return " ".join(normalized.split())


def _adjusted_confidence(
    original: MissionExtractionConfidenceLevel,
    support: MissionVerificationSupport,
) -> MissionExtractionConfidenceLevel:
    if support == "direct":
        return original
    if support == "partial":
        return "medium" if original == "high" else original
    return "low"


def _warn_high_without_direct(
    field: str,
    original_confidence: MissionExtractionConfidenceLevel,
    support: MissionVerificationSupport,
    warnings: list[str],
) -> None:
    if original_confidence == "high" and support != "direct":
        warnings.append(f"high confidence without direct source support: {field}")


def _overall_after(
    field_results: dict[str, MissionExtractionFieldVerification],
    has_warnings: bool,
) -> MissionExtractionConfidenceLevel:
    core_fields = [field for field in _FIELDS if field in field_results]
    if any(field_results[field].confidence_after == "low" for field in core_fields):
        return "low"
    if has_warnings:
        return "medium"
    if all(field_results[field].confidence_after == "high" for field in core_fields):
        return "high"
    return "medium"


def _preview(value: str, limit: int = 120) -> str:
    return value if len(value) <= limit else f"{value[:limit - 3]}..."
