# Research

Research is an evidence-backed Mission, not ordinary Chat. Selecting the
Research or Research synthesis cognitive policy in Chat launches
`ResearchOrchestrator` (`src/opencobalt/personal_ai/research.py`).

This is a local research workflow with bounded public HTTPS retrieval. It is
not equivalent to commercial deep-research products.

## Flow

```
question + cognitive policy
  -> Mission (type=research)
  -> plan (candidate URLs)
  -> retrieve public HTTPS sources
  -> extract structured evidence
  -> optional skeptical review on a distinct stronger model
  -> synthesize from the stored evidence set
  -> persist sources, evidence, citations, disagreements
```

Simple Chat questions do not become Missions. Local-only requests block
retrieval entirely.

## Source acquisition

OpenCobalt retrieves sources itself. Current behavior:

- The planner emits candidate URLs.
- PubMed eutils and CMS search are seeded as public lookup endpoints.
- Follow-up fetches are limited to a preferred-host list (PubMed, CMS, CDC,
  NIH, and similar public hosts).
- Fetch goes through `ExecutionEngine` over HTTPS.
- Caps: 8 primary sources plus 6 follow-ups; truncated excerpts.
- Localhost, private, and non-HTTPS URLs are rejected.

There is no general web-search engine, no authenticated paywall access, and
no dedicated PDF/binary parser beyond HTML, text, and JSON. Search-index and
asset URLs are excluded from document extraction.

## Evidence, synthesis, and citations

Extraction and synthesis use structured schemas. If the extractor returns
nothing, retrieved excerpts can still be stored as linked evidence.

A citation is marked `verified_link` only when it points at evidence whose
source was retrieved for this Mission. Otherwise it is `unverified`.

Citation linkage and receipt integrity do not prove factual truth. The
orchestrator always records that limitation.

## Model roles

Research LLM steps are assigned heuristically to eligible Chat providers:

- Eligible today: Antigravity, Ollama, Mock
- Planner and extractor prefer a non-weak cost-ordered candidate
- Synthesizer prefers the strongest eligible model
- Reviewer is optional and only used when a distinct strong model exists

Claude, Codex, and Cursor are not research-role eligible in this path.

## Persistence and inspection

Research tables live in the shared ledger. Mission detail in the UI and
`GET /api/v1/research/{research_id}` expose the bundle: question, sources,
evidence, citations, disagreements, model roles, synthesis, and limitations.

See [MISSIONS.md](MISSIONS.md) for the broader mission spine and
[PERSONAL_AI_ROUTER.md](PERSONAL_AI_ROUTER.md) for Chat entry.
