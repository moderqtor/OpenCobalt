"""Evidence-backed Research workflow owned by OpenCobalt."""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator, Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from opencobalt.core.mission_engine import Mission, MissionStep, MissionStore
from opencobalt.personal_ai.providers import (
    CancellationToken,
    ChatProvider,
    ProviderRegistry,
    ProviderRequest,
    ProviderResult,
)
from opencobalt.personal_ai.retrieval import (
    DocumentAcquisitionPipeline,
    HttpsGetAdapter,
    canonical_url,
    followup_urls_from_payload,
    is_public_https_url,
    looks_like_asset_url,
    looks_like_search_index,
    rank_and_dedupe_sources,
    search_seed_urls,
)
from opencobalt.personal_ai.router import ProviderSnapshot
from opencobalt.personal_ai.store import PersonalAIStore

_MAX_SOURCES = 8
_MAX_FOLLOWUPS = 6
_MAX_EVIDENCE = 16
_HttpsGetAdapter = HttpsGetAdapter

RESEARCH_PLAN_SCHEMA = {
    "type": "object",
    "required": ["research_question", "subquestions", "queries", "candidate_urls"],
    "properties": {
        "research_question": {"type": "string"},
        "subquestions": {"type": "array", "items": {"type": "string"}},
        "queries": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["query", "purpose"],
                "properties": {"query": {"type": "string"}, "purpose": {"type": "string"}},
            },
        },
        "candidate_urls": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["url", "why"],
                "properties": {
                    "url": {"type": "string"},
                    "why": {"type": "string"},
                    "source_type": {"type": "string"},
                },
            },
        },
        "limitations": {"type": "array", "items": {"type": "string"}},
    },
}

RESEARCH_EXTRACT_SCHEMA = {
    "type": "object",
    "required": ["evidence", "disagreements"],
    "properties": {
        "evidence": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["source_url", "claim"],
                "properties": {
                    "source_url": {"type": "string"},
                    "claim": {"type": "string"},
                    "passage": {"type": "string"},
                    "summary": {"type": "string"},
                    "evidence_strength": {"type": "string"},
                    "causal_class": {"type": "string"},
                    "relation": {"type": "string"},
                    "study_design": {"type": "string"},
                    "population": {"type": "string"},
                    "sample_size": {"type": "string"},
                    "endpoint": {"type": "string"},
                    "effect_direction": {"type": "string"},
                    "effect_magnitude": {"type": "string"},
                    "uncertainty": {"type": "string"},
                    "limitations": {"type": "string"},
                },
            },
        },
        "disagreements": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["topic", "positions"],
                "properties": {
                    "topic": {"type": "string"},
                    "positions": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
    },
}

RESEARCH_SYNTHESIS_SCHEMA = {
    "type": "object",
    "required": ["synthesis", "citations"],
    "properties": {
        "synthesis": {"type": "string"},
        "citations": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["claim_span", "evidence_id"],
                "properties": {
                    "claim_span": {"type": "string"},
                    "evidence_id": {"type": "string"},
                },
            },
        },
        "unresolved": {"type": "array", "items": {"type": "string"}},
        "causal_caution": {"type": "string"},
    },
}


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _uid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4()}"


def _iso(value: datetime | None = None) -> str:
    return (value or _now()).isoformat()


class ResearchOrchestrator:
    def __init__(
        self,
        *,
        store: PersonalAIStore,
        providers: ProviderRegistry,
        missions: MissionStore,
        engine: Any,
    ) -> None:
        self.store = store
        self.providers = providers
        self.missions = missions
        self.engine = engine

    def run(
        self,
        *,
        question: str,
        conversation_id: str,
        route_id: str,
        snapshots: Sequence[ProviderSnapshot],
        local_only: bool,
        timeout_seconds: int,
        cancellation: CancellationToken | None = None,
        system_policy: str = "",
        attachment_ids: Sequence[str] | None = None,
    ) -> Iterator[dict[str, Any]]:
        started = _iso()
        mission = Mission(
            mission_id=_uid("mis"),
            goal=question,
            mission_type="research",
            status="created",
            max_risk="yellow",
            summary="Research mission created; evidence collection has not finished.",
        )
        self.missions.save_mission(mission)
        research_id = _uid("res")
        roles = assign_research_roles(snapshots)
        record = {
            "research_id": research_id,
            "mission_id": mission.mission_id,
            "conversation_id": conversation_id,
            "route_id": route_id,
            "question": question,
            "status": "planning",
            "synthesis": "",
            "limitations": [],
            "model_roles": {
                name: {
                    "provider_id": snapshot.provider_id,
                    "model_id": snapshot.model_id,
                    "display_name": snapshot.display_name,
                    "reason": role_reason(name, snapshot),
                }
                for name, snapshot in roles.items()
            },
            "created_at": started,
            "updated_at": started,
            "metadata": {"local_only": local_only},
        }
        self.store.save_research_mission(record)
        yield {"step": "mission_created", "research_id": research_id, "mission_id": mission.mission_id}

        if local_only:
            limitation = "Research retrieval requires network access; local-only blocked source fetch"
            self._fail(record, mission, limitation)
            yield {"step": "blocked", "error": limitation, "research_id": research_id}
            return
        if "planner" not in roles:
            limitation = "No eligible model was available for research planning"
            self._fail(record, mission, limitation)
            yield {"step": "failed", "error": limitation, "research_id": research_id}
            return

        yield {"step": "planning", "research_id": research_id, "model": roles["planner"].model_id}
        plan_result = self._complete(
            roles["planner"],
            _plan_prompt(question, system_policy),
            schema=RESEARCH_PLAN_SCHEMA,
            timeout_seconds=min(timeout_seconds, 180),
            cancellation=cancellation,
        )
        if plan_result.status != "complete":
            limitation = plan_result.error.message if plan_result.error else "planning failed"
            self._fail(record, mission, limitation, plan_result.receipt_id)
            yield {"step": "failed", "error": limitation, "research_id": research_id}
            return

        plan = _parse_structured(plan_result.content) or {}
        subquestions = _string_list(plan.get("subquestions"))[:12]
        queries = plan.get("queries") if isinstance(plan.get("queries"), list) else []
        for raw in queries[:12]:
            if not isinstance(raw, Mapping):
                continue
            query_text = str(raw.get("query") or "").strip()
            if not query_text:
                continue
            self.store.save_research_query(
                {
                    "query_id": _uid("rq"),
                    "research_id": research_id,
                    "query_text": query_text[:500],
                    "purpose": str(raw.get("purpose") or "")[:300],
                    "created_at": _iso(),
                }
            )
        self._save_step(mission, "Decompose research question", plan_result.receipt_id)
        yield {
            "step": "planned",
            "research_id": research_id,
            "subquestions": subquestions,
            "receipt_id": plan_result.receipt_id,
        }

        candidate_urls = _candidate_urls(plan, queries)
        yield {"step": "retrieving", "research_id": research_id, "candidate_count": len(candidate_urls)}
        sources = []
        seen_urls: set[str] = set()
        pipeline = DocumentAcquisitionPipeline(self.engine)
        for reused in self._reused_sources(research_id, conversation_id, question):
            key = canonical_url(str(reused.get("canonical_url") or reused.get("url") or ""))
            if key:
                seen_urls.add(key)
            sources.append(reused)
            self.store.save_research_source(reused)
        for attachment in self._attachment_sources(research_id, conversation_id, attachment_ids, pipeline):
            key = canonical_url(str(attachment.get("canonical_url") or attachment.get("url") or ""))
            if key:
                seen_urls.add(key)
            sources.append(attachment)
            self.store.save_research_source(attachment)
        queue = list(candidate_urls[:_MAX_SOURCES])
        while queue and len(sources) < _MAX_SOURCES + _MAX_FOLLOWUPS:
            if cancellation is not None and cancellation.cancelled:
                break
            url = queue.pop(0)
            key = canonical_url(url)
            if key in seen_urls:
                continue
            seen_urls.add(key)
            source, raw = self._retrieve_source(research_id, url, pipeline)
            sources.append(source)
            self.store.save_research_source(source)
            if source["retrieval_status"] != "retrieved":
                continue
            remaining = (_MAX_SOURCES + _MAX_FOLLOWUPS) - len(sources) - len(queue)
            for follow in followup_urls_from_payload(url, raw)[: max(0, remaining)]:
                follow_key = canonical_url(follow)
                if follow_key not in seen_urls:
                    queue.append(follow)
        retrieved = [item for item in sources if item["retrieval_status"] == "retrieved"]
        document_sources = rank_and_dedupe_sources(
            [
                item
                for item in retrieved
                if not looks_like_search_index(item["url"])
                and not looks_like_asset_url(item["url"])
                and not item.get("excluded")
            ],
            limit=_MAX_SOURCES,
        )
        self._save_step(
            mission,
            f"Retrieve sources ({len(retrieved)} retrieved / {len(sources)} attempted)",
            None,
        )
        yield {
            "step": "retrieved",
            "research_id": research_id,
            "source_count": len(sources),
            "retrieved_count": len(retrieved),
        }

        extractor = roles.get("extractor") or roles["planner"]
        yield {"step": "extracting", "research_id": research_id, "model": extractor.model_id}
        extract_result = self._complete(
            extractor,
            _extract_prompt(question, document_sources or retrieved or sources),
            schema=RESEARCH_EXTRACT_SCHEMA,
            timeout_seconds=min(timeout_seconds, 240),
            cancellation=cancellation,
        )
        extracted = _parse_structured(extract_result.content) or {}
        evidence_rows = []
        excerpt_fallback = False
        source_by_url = {item["url"]: item for item in sources}
        for raw in _as_list(extracted.get("evidence"))[:_MAX_EVIDENCE]:
            if not isinstance(raw, Mapping):
                continue
            url = str(raw.get("source_url") or "").strip()
            source = source_by_url.get(url)
            if source is None:
                source_id = str(raw.get("source_id") or "").strip()
                source = next(
                    (item for item in sources if item["source_id"] == source_id),
                    None,
                )
            claim = str(raw.get("claim") or "").strip()
            if not claim:
                continue
            linked = source is not None and source["retrieval_status"] == "retrieved"
            limitations = str(raw.get("limitations") or "")[:2000]
            uncertainty = str(raw.get("uncertainty") or "").strip()
            if uncertainty:
                limitations = f"{limitations} Uncertainty: {uncertainty}".strip()[:2000]
            row = {
                "evidence_id": _uid("ev"),
                "research_id": research_id,
                "source_id": source["source_id"] if source else None,
                "claim": claim[:2000],
                "passage": str(raw.get("passage") or "")[:4000],
                "summary": str(raw.get("summary") or "")[:2000],
                "evidence_strength": _bounded_token(raw.get("evidence_strength"), "unknown"),
                "causal_class": _causal_class(raw.get("causal_class")),
                "relation": _relation(raw.get("relation")),
                "study_design": str(raw.get("study_design") or "")[:200],
                "population": str(raw.get("population") or "")[:200],
                "sample_size": str(raw.get("sample_size") or "")[:80],
                "endpoint": str(raw.get("endpoint") or "")[:200],
                "effect_direction": str(raw.get("effect_direction") or "")[:80],
                "effect_magnitude": str(raw.get("effect_magnitude") or "")[:80],
                "limitations": limitations,
                "extraction_model": extractor.model_id,
                "reviewer_model": None,
                "verification_status": "linked" if linked else "unverified",
                "created_at": _iso(),
            }
            self.store.save_research_evidence(row)
            evidence_rows.append(row)
        if not evidence_rows and retrieved:
            fallback_sources = document_sources or retrieved
            for source in fallback_sources[:_MAX_EVIDENCE]:
                excerpt = str(source.get("excerpt") or "").strip()
                if not excerpt:
                    continue
                row = {
                    "evidence_id": _uid("ev"),
                    "research_id": research_id,
                    "source_id": source["source_id"],
                    "claim": f"Retrieved source: {source.get('title') or source['url']}",
                    "passage": excerpt[:4000],
                    "summary": excerpt[:500],
                    "evidence_strength": "retrieved_excerpt",
                    "causal_class": "unspecified",
                    "relation": "neutral",
                    "study_design": "",
                    "population": "",
                    "sample_size": "",
                    "endpoint": "",
                    "effect_direction": "",
                    "effect_magnitude": "",
                    "limitations": (
                        "OpenCobalt persisted this retrieved excerpt because the extractor "
                        "did not emit structured evidence for the source"
                    ),
                    "extraction_model": "opencobalt-retrieved-excerpt",
                    "reviewer_model": None,
                    "verification_status": "linked",
                    "created_at": _iso(),
                }
                self.store.save_research_evidence(row)
                evidence_rows.append(row)
            excerpt_fallback = True
        for raw in _as_list(extracted.get("disagreements"))[:12]:
            if not isinstance(raw, Mapping):
                continue
            topic = str(raw.get("topic") or "").strip()
            if not topic:
                continue
            self.store.save_research_disagreement(
                {
                    "disagreement_id": _uid("dg"),
                    "research_id": research_id,
                    "topic": topic[:500],
                    "positions": _string_list(raw.get("positions"))[:8],
                    "created_at": _iso(),
                }
            )
        self._save_step(mission, "Extract structured evidence", extract_result.receipt_id)
        yield {
            "step": "extracted",
            "research_id": research_id,
            "evidence_count": len(evidence_rows),
            "receipt_id": extract_result.receipt_id,
        }

        reviewer = roles.get("reviewer")
        if (
            reviewer is not None
            and evidence_rows
            and (reviewer.provider_id, reviewer.model_id)
            != (extractor.provider_id, extractor.model_id)
        ):
            yield {"step": "reviewing", "research_id": research_id, "model": reviewer.model_id}
            review_result = self._complete(
                reviewer,
                _review_prompt(question, evidence_rows),
                schema=RESEARCH_EXTRACT_SCHEMA,
                timeout_seconds=min(timeout_seconds, 180),
                cancellation=cancellation,
            )
            reviewed = _parse_structured(review_result.content) or {}
            for raw in _as_list(reviewed.get("evidence"))[:_MAX_EVIDENCE]:
                if not isinstance(raw, Mapping):
                    continue
                claim = str(raw.get("claim") or "").strip()
                match = next((item for item in evidence_rows if item["claim"] == claim), None)
                if match is None:
                    continue
                match["reviewer_model"] = reviewer.model_id
                if str(raw.get("causal_class") or ""):
                    match["causal_class"] = _causal_class(raw.get("causal_class"))
                if str(raw.get("limitations") or ""):
                    match["limitations"] = str(raw["limitations"])[:2000]
                self.store.save_research_evidence(match)
            self._save_step(mission, "Skeptical evidence review", review_result.receipt_id)
            yield {"step": "reviewed", "research_id": research_id, "receipt_id": review_result.receipt_id}

        synthesizer = roles.get("synthesizer") or extractor
        yield {"step": "synthesizing", "research_id": research_id, "model": synthesizer.model_id}
        excluded_source_ids = {
            item["source_id"] for item in sources if item.get("excluded")
        }
        synthesis_evidence = [
            item
            for item in evidence_rows
            if not item.get("source_id") or item.get("source_id") not in excluded_source_ids
        ]
        synthesis_sources = [
            item
            for item in (document_sources or retrieved)
            if not item.get("excluded")
        ]
        synthesis_result = self._complete(
            synthesizer,
            _synthesis_prompt(question, synthesis_evidence, synthesis_sources),
            schema=RESEARCH_SYNTHESIS_SCHEMA,
            timeout_seconds=min(timeout_seconds, 240),
            cancellation=cancellation,
        )
        synthesis_payload = _parse_structured(synthesis_result.content) or {}
        synthesis = str(synthesis_payload.get("synthesis") or synthesis_result.content or "").strip()
        evidence_ids = {item["evidence_id"] for item in evidence_rows}
        source_ids = {item["source_id"] for item in sources}
        citations = []
        for raw in _as_list(synthesis_payload.get("citations"))[:40]:
            if not isinstance(raw, Mapping):
                continue
            evidence_id = str(raw.get("evidence_id") or "").strip()
            linked_evidence = next(
                (item for item in evidence_rows if item["evidence_id"] == evidence_id),
                None,
            )
            if linked_evidence is None and evidence_id not in evidence_ids:
                status = "unverified"
                note = "citation evidence_id was not part of this research mission"
                source_id = None
            else:
                source_id = linked_evidence["source_id"] if linked_evidence else None
                source = next((item for item in sources if item["source_id"] == source_id), None)
                if source is not None and source["retrieval_status"] == "retrieved":
                    status = "verified_link"
                    note = "citation points at retrieved source evidence from this mission"
                else:
                    status = "unverified"
                    note = "cited evidence is not linked to a retrieved source"
            citation = {
                "citation_id": _uid("cit"),
                "research_id": research_id,
                "evidence_id": evidence_id or None,
                "source_id": source_id if source_id in source_ids else None,
                "claim_span": str(raw.get("claim_span") or "")[:1000],
                "verification_status": status,
                "verification_note": note,
                "created_at": _iso(),
            }
            self.store.save_research_citation(citation)
            citations.append(citation)

        limitations = _string_list(plan.get("limitations"))
        limitations.append(
            "Citation verification checks mission linkage and source retrieval, not factual truth"
        )
        if not retrieved:
            limitations.append(
                "No sources were independently retrieved; synthesis must not be treated as cited evidence"
            )
        if excerpt_fallback:
            limitations.append(
                "Extractor returned no structured evidence; retrieved excerpts were stored as linked evidence"
            )
        unverified = sum(1 for item in citations if item["verification_status"] != "verified_link")
        if unverified:
            limitations.append(f"{unverified} citation(s) remain unverified")
        record.update(
            {
                "status": "complete",
                "synthesis": synthesis,
                "limitations": limitations,
                "updated_at": _iso(),
                "metadata": {
                    **record.get("metadata", {}),
                    "subquestions": subquestions,
                    "causal_caution": str(synthesis_payload.get("causal_caution") or ""),
                    "unresolved": _string_list(synthesis_payload.get("unresolved")),
                    "planner_receipt_id": plan_result.receipt_id,
                    "extract_receipt_id": extract_result.receipt_id,
                    "synthesis_receipt_id": synthesis_result.receipt_id,
                },
            }
        )
        self.store.save_research_mission(record)
        self._save_step(mission, "Synthesize cited answer", synthesis_result.receipt_id)
        self._set_mission(mission, "completed", synthesis[:500], synthesis_result.receipt_id)
        yield {
            "step": "complete",
            "research_id": research_id,
            "mission_id": mission.mission_id,
            "synthesis": synthesis,
            "source_count": len(sources),
            "evidence_count": len(evidence_rows),
            "citation_count": len(citations),
            "limitations": limitations,
            "receipt_id": synthesis_result.receipt_id,
        }

    def _complete(
        self,
        snapshot: ProviderSnapshot,
        prompt: str,
        *,
        schema: dict[str, Any],
        timeout_seconds: int,
        cancellation: CancellationToken | None,
    ) -> ProviderResult:
        provider: ChatProvider = self.providers.get(snapshot.provider_id)
        request = ProviderRequest(
            message=prompt,
            model_id=snapshot.model_id,
            timeout_seconds=timeout_seconds,
            metadata={
                "research": True,
                "json_schema": schema,
                "reasoning_effort": "medium",
            },
        )
        return provider.execute(request, cancellation)

    def _retrieve_source(
        self,
        research_id: str,
        url: str,
        pipeline: DocumentAcquisitionPipeline | None = None,
    ) -> tuple[dict[str, Any], str]:
        created = _iso()
        source_id = _uid("src")
        pipeline = pipeline or DocumentAcquisitionPipeline(self.engine)
        document = pipeline.acquire_url(url)
        return document.to_source_record(
            source_id=source_id,
            research_id=research_id,
            created_at=created,
        ), document.raw

    def _attachment_sources(
        self,
        research_id: str,
        conversation_id: str,
        attachment_ids: Sequence[str] | None,
        pipeline: DocumentAcquisitionPipeline,
    ) -> list[dict[str, Any]]:
        ids = list(attachment_ids or [])
        if not ids:
            ids = [item["attachment_id"] for item in self.store.list_attachments(conversation_id)]
        sources: list[dict[str, Any]] = []
        seen: set[str] = set()
        for attachment_id in ids:
            if attachment_id in seen:
                continue
            seen.add(attachment_id)
            record = self.store.get_attachment(attachment_id)
            if record is None:
                continue
            if record.get("conversation_id") not in {None, conversation_id}:
                continue
            document = pipeline.acquire_upload(record)
            sources.append(
                document.to_source_record(
                    source_id=_uid("src"),
                    research_id=research_id,
                    created_at=_iso(),
                )
            )
        return sources

    def _reused_sources(
        self,
        research_id: str,
        conversation_id: str,
        question: str,
    ) -> list[dict[str, Any]]:
        tokens = {token.lower() for token in question.split() if len(token) > 4}
        reused: list[dict[str, Any]] = []
        for prior in self.store.list_research_missions(conversation_id=conversation_id, limit=8):
            if prior["research_id"] == research_id:
                continue
            if prior.get("status") not in {"complete", "completed"}:
                continue
            prior_tokens = {token.lower() for token in str(prior.get("question") or "").split() if len(token) > 4}
            if tokens and prior_tokens and len(tokens & prior_tokens) < 2:
                continue
            bundle = self.store.research_bundle(prior["research_id"])
            if not bundle:
                continue
            for source in bundle.get("sources") or []:
                if source.get("retrieval_status") != "retrieved":
                    continue
                if source.get("excluded"):
                    continue
                copied = dict(source)
                copied["source_id"] = _uid("src")
                copied["research_id"] = research_id
                copied["created_at"] = _iso()
                copied["quality_assessment"] = (
                    str(copied.get("quality_assessment") or "")
                    + "; reused from a prior mission in this conversation"
                ).strip("; ")
                reused.append(copied)
                if len(reused) >= 6:
                    return reused
        return reused

    def _fail(
        self,
        record: dict[str, Any],
        mission: Mission,
        limitation: str,
        receipt_id: str | None = None,
    ) -> None:
        record["status"] = "failed" if "blocked" not in limitation.lower() else "blocked"
        record["limitations"] = [limitation]
        record["updated_at"] = _iso()
        self.store.save_research_mission(record)
        self._set_mission(mission, record["status"], limitation, receipt_id)

    def _save_step(self, mission: Mission, title: str, receipt_id: str | None) -> None:
        step = MissionStep(
            step_id=_uid("mst"),
            mission_id=mission.mission_id,
            title=title,
            risk_level="yellow",
            approval_state="not_required",
            execution_state="executed" if receipt_id else "dry_run",
            receipt_id=receipt_id,
            uses_execution_engine=True,
            expected_receipt=receipt_id is not None,
        )
        self.missions.save_step(step)
        self.missions.append_mission_event(
            mission.mission_id,
            "mission.research_step",
            {"title": title, "receipt_id": receipt_id},
        )

    def _set_mission(
        self,
        mission: Mission,
        status: str,
        summary: str,
        receipt_id: str | None = None,
    ) -> None:
        mission.status = status
        mission.summary = summary[:1000]
        if receipt_id:
            mission.last_receipt_id = receipt_id
        self.missions.save_mission(mission)


def assign_research_roles(snapshots: Sequence[ProviderSnapshot]) -> dict[str, ProviderSnapshot]:
    eligible = [
        item
        for item in snapshots
        if item.available and item.provider_id in {"antigravity", "ollama", "mock"}
    ]
    if not eligible:
        return {}
    by_cost = sorted(
        eligible,
        key=lambda item: (
            {"free": 0, "low": 1, "standard": 2, "high": 3}[item.cost_category],
            {"weak": 0, "standard": 1, "strong": 2}[item.quality_tier],
        ),
    )
    by_strength = sorted(
        eligible,
        key=lambda item: (
            {"weak": 0, "standard": 1, "strong": 2}[item.quality_tier],
            {"high": 0, "standard": 1, "low": 2, "free": 3}[item.cost_category],
        ),
        reverse=True,
    )
    planner = next((item for item in by_cost if item.quality_tier != "weak"), by_cost[0])
    extractor = planner
    synthesizer = by_strength[0]
    reviewer = next(
        (
            item
            for item in by_strength
            if (item.provider_id, item.model_id) != (extractor.provider_id, extractor.model_id)
            and item.quality_tier == "strong"
        ),
        None,
    )
    roles = {"planner": planner, "extractor": extractor, "synthesizer": synthesizer}
    if (
        reviewer is not None
        and (reviewer.provider_id, reviewer.model_id)
        != (synthesizer.provider_id, synthesizer.model_id)
    ):
        roles["reviewer"] = reviewer
    return roles


def role_reason(role: str, snapshot: ProviderSnapshot) -> str:
    label = snapshot.display_name or snapshot.model_id or snapshot.provider_id
    if role == "planner":
        return (
            f"{label} was assigned to query generation because it is available and in a "
            f"{snapshot.cost_category} cost category sufficient for scouting"
        )
    if role == "extractor":
        return f"{label} was assigned to evidence extraction from retrieved sources"
    if role == "reviewer":
        return (
            f"{label} was assigned as skeptical reviewer because it is a distinct stronger model"
        )
    return f"{label} was assigned to synthesis of the inspectable evidence set"


def _plan_prompt(question: str, system_policy: str) -> str:
    policy = f"{system_policy.rstrip()}\n\n" if system_policy.strip() else ""
    return (
        f"{policy}You are planning an evidence-backed research mission for OpenCobalt.\n"
        "Do not write the final answer yet.\n"
        "Prefer systematic reviews, major guidelines, government sources, and primary "
        "research over commentary.\n"
        "For policy questions, prefer CMS, Medicare, CDC, NIH, statutes/regulations, "
        "and official guidelines.\n"
        "Propose specific canonical HTTPS document URLs, not search-result pages.\n"
        "Prefer agency document roots, PubMed article identifiers, statutes, "
        "regulations, and guideline pages that are likely to exist.\n"
        f"Research question:\n{question}\n"
    )


def _extract_prompt(question: str, sources: Sequence[Mapping[str, Any]]) -> str:
    blocks = []
    for source in sources[:_MAX_SOURCES]:
        blocks.append(
            f"SOURCE {source.get('source_id')}\nURL: {source.get('url')}\n"
            f"TITLE: {source.get('title')}\nTYPE: {source.get('source_type')}\n"
            f"RETRIEVAL: {source.get('retrieval_status')}\n"
            f"EXCERPT:\n{source.get('excerpt', '')[:4000]}\n"
        )
    joined = "\n\n".join(blocks) or "No retrieved source excerpts are available."
    return (
        "Extract structured evidence ONLY from the retrieved excerpts below.\n"
        "If an excerpt does not support a claim, do not emit that claim.\n"
        "Distinguish association from causation. Record study design, population, "
        "endpoint, effect direction, uncertainty, confounding, and limitations when "
        "the source provides them.\n"
        "Copy each source_url exactly from the URL line. Prefer one evidence record "
        "per retrieved source that actually contains relevant text.\n"
        f"Research question:\n{question}\n\n{joined}\n"
    )


def _review_prompt(question: str, evidence: Sequence[Mapping[str, Any]]) -> str:
    payload = json.dumps(
        [
            {
                "evidence_id": item["evidence_id"],
                "claim": item["claim"],
                "causal_class": item["causal_class"],
                "limitations": item["limitations"],
                "verification_status": item["verification_status"],
            }
            for item in evidence
        ],
        indent=2,
    )
    return (
        "You are a skeptical reviewer. Check whether cited retrieved evidence actually "
        "supports each claim, whether causal language is overstated, and whether "
        "important limitations were omitted. Do not invent new sources.\n"
        f"Research question:\n{question}\n\nEvidence JSON:\n{payload}\n"
    )


def _synthesis_prompt(
    question: str,
    evidence: Sequence[Mapping[str, Any]],
    sources: Sequence[Mapping[str, Any]],
) -> str:
    payload = json.dumps(
        {
            "sources": [
                {
                    "source_id": item["source_id"],
                    "url": item["url"],
                    "title": item["title"],
                    "source_type": item["source_type"],
                    "retrieval_status": item["retrieval_status"],
                }
                for item in sources
            ],
            "evidence": [
                {
                    "evidence_id": item["evidence_id"],
                    "source_id": item["source_id"],
                    "claim": item["claim"],
                    "summary": item["summary"],
                    "causal_class": item["causal_class"],
                    "relation": item["relation"],
                    "limitations": item["limitations"],
                    "verification_status": item["verification_status"],
                }
                for item in evidence
            ],
        },
        indent=2,
    )
    return (
        "Write the final research synthesis using ONLY the evidence set below.\n"
        "Cite claims with evidence_id values that exist in this set.\n"
        "Do not convert association into causation. If evidence is missing or "
        "unverified, say so.\n"
        f"Research question:\n{question}\n\n{payload}\n"
    )


def _candidate_urls(plan: Mapping[str, Any], queries: Sequence[Any]) -> list[str]:
    planner: list[str] = []
    for raw in _as_list(plan.get("candidate_urls")):
        url = str(raw.get("url") if isinstance(raw, Mapping) else raw).strip()
        if is_public_https_url(url):
            planner.append(url)
    seeds: list[str] = []
    for raw in queries:
        if not isinstance(raw, Mapping):
            continue
        query = str(raw.get("query") or "").strip()
        if query:
            seeds.extend(search_seed_urls(query))
    reserved = seeds[:2]
    merged = planner[:6] + reserved + planner[6:] + seeds[2:]
    deduped: list[str] = []
    seen: set[str] = set()
    for url in merged:
        if url in seen:
            continue
        seen.add(url)
        deduped.append(url)
    return deduped[:_MAX_SOURCES]


def _parse_structured(raw: str) -> dict[str, Any] | None:
    text = raw.strip()
    if not text:
        return None
    try:
        payload = json.loads(text)
        return payload if isinstance(payload, dict) else None
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            payload = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _string_list(value: Any) -> list[str]:
    return [str(item).strip() for item in _as_list(value) if str(item).strip()]


def _bounded_token(value: Any, default: str) -> str:
    text = str(value or default).strip().lower().replace(" ", "_")
    return text[:40] or default


def _causal_class(value: Any) -> str:
    text = _bounded_token(value, "unspecified")
    if "caus" in text:
        return "causal_claim"
    if "assoc" in text:
        return "association"
    if text in {"unspecified", "neutral", "not_causal"}:
        return text
    return "unspecified"


def _relation(value: Any) -> str:
    text = _bounded_token(value, "neutral")
    if text in {"supportive", "contradictory", "neutral"}:
        return text
    if "contradict" in text or "against" in text:
        return "contradictory"
    if "support" in text or "for" in text:
        return "supportive"
    return "neutral"
