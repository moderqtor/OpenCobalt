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

Research retrieval is a normalized `DocumentAcquisitionPipeline`
(`src/opencobalt/personal_ai/retrieval.py`). Downstream evidence extraction
does not depend on whether a document came from PubMed, a PDF, Crossref, a
government host, or a user upload.

Current resolver behavior:

- Generic public HTTPS HTML: redirects, canonical URL, title, and primary
  content extraction. Navigation and search chrome are stripped when possible.
- PDF: bounded download, `%PDF` verification, and text extraction with page
  provenance when `pypdf` is installed.
- PubMed / NCBI: structured eutils/efetch plus follow-up article URLs.
- DOI / Crossref: bibliographic seed search and DOI target resolution.
- Government / policy hosts: generic HTTPS retrieval for CMS, CDC, NIH,
  govinfo, and similar public hosts. No paper-specific URLs are hardcoded.
- User uploads: conversation attachments become `user_document` sources.

Fetch goes through `ExecutionEngine` over HTTPS with SSRF rejection for
localhost, private IPs, credentials, file URLs, and non-HTTPS schemes.
Caps: 8 primary sources plus 6 follow-ups; truncated excerpts; 150 KB fetch
bound. Search-index and asset URLs are excluded from document extraction.

A later Research Mission in the same conversation can reuse previously
retrieved sources when the question overlaps. Excluded sources are skipped.

There is no general web-search engine, no authenticated paywall access, and
no browser fallback in the standard path.

## Evidence, synthesis, and citations

Extraction and synthesis use structured schemas. Evidence records can store
study design, population, endpoint, effect direction, magnitude, and
limitations when the source provides them. Uncertainty is folded into
limitations. If the extractor returns nothing, retrieved excerpts can still
be stored as linked evidence.

Excluded sources are omitted from later reuse and from synthesis input.

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
