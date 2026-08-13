"""Normalized research acquisition: SSRF, DOI, ranking, and uploads."""

from __future__ import annotations

from opencobalt.personal_ai.research import ResearchOrchestrator
from opencobalt.personal_ai.retrieval import (
    DocumentAcquisitionPipeline,
    HttpsGetAdapter,
    canonical_url,
    extract_doi,
    followup_urls_from_payload,
    is_public_https_url,
    looks_like_search_index,
    normalize_payload,
    rank_and_dedupe_sources,
    search_seed_urls,
)
from opencobalt.personal_ai.store import PersonalAIStore
from tests.test_personal_ai_providers import FakeEngine, _outcome


def test_ssrf_rejects_private_and_credential_urls() -> None:
    assert not is_public_https_url("http://example.com")
    assert not is_public_https_url("https://localhost/secret")
    assert not is_public_https_url("https://127.0.0.1/x")
    assert not is_public_https_url("https://192.168.1.4/x")
    assert not is_public_https_url("https://user:pass@example.com/x")
    assert not is_public_https_url("file:///etc/passwd")
    assert is_public_https_url("https://www.cms.gov/medicare")


def test_doi_extraction_and_crossref_seed() -> None:
    assert extract_doi("https://doi.org/10.1234/abc.def") == "10.1234/abc.def"
    seeds = search_seed_urls("oral health screening older adults")
    assert any("eutils.ncbi.nlm.nih.gov" in item for item in seeds)
    assert any("cms.gov" in item for item in seeds)
    assert any("api.crossref.org" in item for item in seeds)
    assert any("govinfo.gov" in item for item in seeds)
    assert "periodontal" not in "".join(seeds)


def test_crossref_followups_become_doi_urls() -> None:
    follow = followup_urls_from_payload(
        "https://api.crossref.org/works?query.bibliographic=medicare",
        '{"message":{"items":[{"DOI":"10.1111/example"}]}}',
    )
    assert "https://doi.org/10.1111/example" in follow
    assert looks_like_search_index(
        "https://api.crossref.org/works?query.bibliographic=medicare"
    )


def test_html_normalization_drops_chrome() -> None:
    html = (
        b"<html><head><title>Coverage</title>"
        b'<meta name="author" content="CMS">'
        b"</head><body><nav>Menu</nav><article>"
        b"Medicare covers a limited oral-health benefit.</article></body></html>"
    )
    document = normalize_payload("https://www.cms.gov/medicare/coverage", html, adapter="https_html")
    assert document.title == "Coverage"
    assert document.source_type == "government_policy"
    assert "limited oral-health benefit" in document.excerpt
    assert "Menu" not in document.excerpt
    assert document.authors == ["CMS"]
    assert document.retrieval_adapter == "government_https"


def test_rank_and_dedupe_prefers_stronger_sources() -> None:
    ranked = rank_and_dedupe_sources(
        [
            {
                "url": "https://news.example/story",
                "canonical_url": "https://news.example/story",
                "source_type": "journalism",
                "retrieval_status": "retrieved",
                "content_hash": "aaa",
                "quality_score": 0.4,
            },
            {
                "url": "https://pubmed.ncbi.nlm.nih.gov/123/",
                "canonical_url": "https://pubmed.ncbi.nlm.nih.gov/123",
                "source_type": "primary_literature",
                "retrieval_status": "retrieved",
                "content_hash": "bbb",
                "quality_score": 0.86,
            },
            {
                "url": "https://pubmed.ncbi.nlm.nih.gov/123/?from=related",
                "canonical_url": "https://pubmed.ncbi.nlm.nih.gov/123",
                "source_type": "primary_literature",
                "retrieval_status": "retrieved",
                "content_hash": "bbb",
                "quality_score": 0.86,
            },
        ],
        limit=2,
    )
    assert ranked[0]["source_type"] == "primary_literature"
    assert len(ranked) == 2


def test_upload_becomes_retrieved_document(tmp_path) -> None:
    store = PersonalAIStore(tmp_path / "ledger.db")
    conversation = store.create_conversation(title="Research")
    store.save_attachment(
        {
            "attachment_id": "att-1",
            "conversation_id": conversation.conversation_id,
            "original_filename": "memo.md",
            "stored_filename": "memo.md",
            "stored_path": str(tmp_path / "memo.md"),
            "mime_type": "text/markdown",
            "size_bytes": 12,
            "sha256": "abc",
            "ingestion_status": "extracted",
            "extracted_text": "User-supplied evidence about screening.",
            "excerpt": "User-supplied evidence about screening.",
            "page_count": None,
            "sections": [],
            "limitations": [],
            "kind": "markdown",
            "created_at": "2026-01-01T00:00:00+00:00",
        }
    )
    pipeline = DocumentAcquisitionPipeline(FakeEngine(_outcome(stdout="unused")))
    document = pipeline.acquire_upload(store.get_attachment("att-1"))
    assert document.source_type == "user_document"
    assert document.retrieval_status == "retrieved"
    assert "User-supplied" in document.excerpt
    assert document.attachment_id == "att-1"


def test_research_reuses_prior_retrieved_sources_and_skips_excluded(tmp_path) -> None:
    store = PersonalAIStore(tmp_path / "ledger.db")
    now = "2026-01-01T00:00:00+00:00"
    store.save_research_mission(
        {
            "research_id": "res-old",
            "mission_id": "mis-old",
            "conversation_id": "conv-1",
            "route_id": "rte-1",
            "question": "Medicare oral health screening evidence",
            "status": "complete",
            "created_at": now,
            "updated_at": now,
        }
    )
    store.save_research_source(
        {
            "source_id": "src-keep",
            "research_id": "res-old",
            "url": "https://www.cms.gov/medicare",
            "canonical_url": "https://www.cms.gov/medicare",
            "title": "CMS",
            "retrieval_status": "retrieved",
            "excerpt": "coverage text",
            "created_at": now,
            "excluded": False,
        }
    )
    store.save_research_source(
        {
            "source_id": "src-skip",
            "research_id": "res-old",
            "url": "https://example.com/weak",
            "canonical_url": "https://example.com/weak",
            "title": "Weak",
            "retrieval_status": "retrieved",
            "excerpt": "commentary",
            "created_at": now,
            "excluded": True,
        }
    )
    orchestrator = ResearchOrchestrator(
        store=store,
        providers=None,
        missions=None,
        engine=None,
    )
    reused = orchestrator._reused_sources(
        "res-new",
        "conv-1",
        "Medicare oral health screening checkpoint",
    )
    assert len(reused) == 1
    assert reused[0]["url"] == "https://www.cms.gov/medicare"
    assert reused[0]["research_id"] == "res-new"
    assert "reused from a prior mission" in reused[0]["quality_assessment"]


def test_fetch_adapter_bounds_https_and_size() -> None:
    command = HttpsGetAdapter("https://www.cdc.gov/").build_command("retrieve")
    assert "--proto" in command and command[command.index("--proto") + 1] == "=https"
    assert "--max-filesize" in command
    assert "--dangerously-skip-permissions" not in command
    assert canonical_url("https://www.CDC.gov/path/") == "https://cdc.gov/path"
