# Roadmap

Near-term sequence, not an aspirational backlog. Older phase history lives in
git and [history/](history/README.md).

## Now

1. Use the product. Dogfood Chat, Research Missions, and Cursor coding
   Missions on real work.
2. Improve research source quality and citation usefulness on real questions.
   Retrieval now covers HTML, PDF, PubMed, DOI/Crossref, government hosts,
   and user uploads; remaining work is evidence ranking and live-provider
   synthesis quality.
3. Keep coding staging and promotion honest: repository containment is
   implemented; host sandboxing is not.

## Next

- Knowledge and reference integration only where OpenCobalt adds routing,
  evidence, or provenance value.
- Voice Profiles learned from user-provided writing. Not implemented today.
- UI and desktop polish. The web UI is canonical; Tauri is a development
  wrapper.
- Outcome-weighted routing using recorded execution history more strongly
  than the current bounded heuristic. Success, latency, and cancellation
  signals are now recorded; they are not a learned router.

## Later, if justified

These are directional possibilities, not commitments:

- Richer research retrieval and optional Zotero or linked-note sources
- Specialist UI/design systems
- Cursor, Codex, and Antigravity specialization where the adapter contract
  is complete
- Optional specialist APIs
- Evaluation and verifier systems
- Secure skill/plugin discovery
- Browser or computer-use capabilities
- Standalone desktop packaging that does not require a development toolchain

An integration ships only when it participates in capability discovery,
policy, receipts, and provenance. Adding a launcher is not enough.

## Not the current strategy

- Cold resume as the primary product wedge
- Daily Operator as the product identity
- Hosted multi-user routing
- Enterprise governance theater
- Collecting every adjacent tool because it can be detected on PATH
