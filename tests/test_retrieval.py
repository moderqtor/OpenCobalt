"""Normalized research acquisition: SSRF, DOI, ranking, and uploads."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from opencobalt.personal_ai.research import ResearchOrchestrator
from opencobalt.personal_ai.retrieval import (
    DocumentAcquisitionPipeline,
    HttpsGetAdapter,
    canonical_url,
    classify_source_type,
    extract_doi,
    followup_urls_from_payload,
    host_matches_trusted_root,
    is_public_https_url,
    looks_like_search_index,
    normalize_payload,
    rank_and_dedupe_sources,
    resolve_public_https_target,
    search_seed_urls,
)
from opencobalt.personal_ai.store import PersonalAIStore
from tests.test_personal_ai_providers import FakeEngine, _outcome


def test_ssrf_rejects_private_and_credential_urls() -> None:
    assert not is_public_https_url("http://example.com")
    assert not is_public_https_url("https://localhost/secret")
    assert not is_public_https_url("https://127.0.0.1/x")
    assert not is_public_https_url("https://192.168.1.4/x")
    assert not is_public_https_url("https://[::1]/x")
    assert not is_public_https_url("https://10.0.0.1/x")
    assert not is_public_https_url("https://172.16.0.1/x")
    assert not is_public_https_url("https://169.254.1.2/x")
    assert not is_public_https_url("https://[fe80::1]/x")
    assert not is_public_https_url("https://224.0.0.1/x")
    assert not is_public_https_url("https://0.0.0.0/x")
    assert not is_public_https_url("https://192.0.2.1/x")
    assert not is_public_https_url("https://user:pass@example.com/x")
    assert not is_public_https_url("file:///etc/passwd")
    assert not is_public_https_url("https://[broken")
    assert is_public_https_url("https://www.cms.gov/medicare")


def test_resolved_public_target_rejects_any_non_global_dns_answer() -> None:
    for address in (
        "127.0.0.1",
        "::1",
        "10.0.0.1",
        "172.16.0.1",
        "192.168.0.1",
        "169.254.1.1",
        "fe80::1",
        "fc00::1",
        "224.0.0.1",
        "0.0.0.0",
        "192.0.2.1",
    ):
        with pytest.raises(ValueError, match="non-public"):
            resolve_public_https_target(
                "https://public-looking.example/source",
                resolver=lambda _host, _port, address=address: [address],
            )

    with pytest.raises(ValueError, match="non-public"):
        resolve_public_https_target(
            "https://mixed.example/source",
            resolver=lambda _host, _port: ["93.184.216.34", "127.0.0.1"],
        )


class ScriptedFetchEngine:
    def __init__(self, responses: dict[str, tuple[int, str | None, bytes]]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, dict]] = []

    def run_task(self, task: str, **kwargs):
        self.calls.append((task, kwargs))
        adapter = kwargs["adapter"]
        status, location, payload = self.responses[adapter.url]
        adapter.output_path.write_bytes(payload)
        headers = [f"HTTP/1.1 {status} scripted"]
        if location is not None:
            headers.append(f"Location: {location}")
        adapter.headers_path.write_text("\r\n".join(headers) + "\r\n\r\n")
        return SimpleNamespace(
            result=SimpleNamespace(
                status="succeeded",
                error=None,
                stdout_path=None,
                stdout_preview=str(status),
            )
        )


def _controlled_resolver(mapping: dict[str, list[str]]):
    def resolve(host: str, _port: int) -> list[str]:
        return mapping[host]

    return resolve


def test_fetch_rejects_private_dns_and_redirect_destinations() -> None:
    private_engine = ScriptedFetchEngine({})
    private = DocumentAcquisitionPipeline(
        private_engine,
        resolver=_controlled_resolver({"public-looking.example": ["127.0.0.1"]}),
    ).acquire_url("https://public-looking.example/source")
    assert private.retrieval_status == "rejected"
    assert private_engine.calls == []

    redirect_engine = ScriptedFetchEngine(
        {
            "https://public.example/start": (
                302,
                "https://internal.example/secret",
                b"",
            )
        }
    )
    redirected = DocumentAcquisitionPipeline(
        redirect_engine,
        resolver=_controlled_resolver(
            {
                "public.example": ["93.184.216.34"],
                "internal.example": ["10.0.0.8"],
            }
        ),
    ).acquire_url("https://public.example/start")
    assert redirected.retrieval_status == "rejected"
    assert "non-public" in " ".join(redirected.limitations)
    assert len(redirect_engine.calls) == 1


def test_fetch_rejects_redirect_loops_and_excessive_redirects() -> None:
    resolver = _controlled_resolver(
        {
            "a.example": ["8.8.8.8"],
            "b.example": ["8.8.4.4"],
            **{f"hop-{index}.example": [f"1.1.1.{index + 1}"] for index in range(5)},
        }
    )
    loop_engine = ScriptedFetchEngine(
        {
            "https://a.example/start": (302, "https://b.example/next", b""),
            "https://b.example/next": (302, "https://a.example/start", b""),
        }
    )
    looped = DocumentAcquisitionPipeline(loop_engine, resolver=resolver).acquire_url(
        "https://a.example/start"
    )
    assert looped.retrieval_status == "failed"
    assert "redirect loop" in " ".join(looped.limitations).lower()

    chain = {
        f"https://hop-{index}.example/path": (
            302,
            f"https://hop-{index + 1}.example/path",
            b"",
        )
        for index in range(4)
    }
    chain["https://hop-4.example/path"] = (200, None, b"should not be reached")
    excessive_engine = ScriptedFetchEngine(chain)
    excessive = DocumentAcquisitionPipeline(
        excessive_engine,
        resolver=resolver,
        max_redirects=3,
    ).acquire_url("https://hop-0.example/path")
    assert excessive.retrieval_status == "failed"
    assert "redirect limit" in " ".join(excessive.limitations).lower()
    assert len(excessive_engine.calls) == 4


def test_legitimate_public_fetch_pins_approved_address_without_curl_redirects() -> None:
    url = "https://evidence.example/article"
    engine = ScriptedFetchEngine(
        {url: (200, None, b"<html><article>Public evidence text.</article></html>")}
    )
    document = DocumentAcquisitionPipeline(
        engine,
        resolver=_controlled_resolver({"evidence.example": ["93.184.216.34"]}),
    ).acquire_url(url)

    assert document.retrieval_status == "retrieved"
    assert "Public evidence text" in document.excerpt
    command = engine.calls[0][1]["adapter"].build_command("retrieve")
    assert command[command.index("--resolve") + 1] == (
        "evidence.example:443:93.184.216.34"
    )
    assert command[command.index("--noproxy") + 1] == "*"
    assert "--location" not in command
    assert "--proto-redir" not in command


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


def test_fetch_adapter_bounds_https_and_size(tmp_path) -> None:
    target = resolve_public_https_target(
        "https://www.cdc.gov/",
        resolver=lambda _host, _port: ["23.48.203.67"],
    )
    command = HttpsGetAdapter(
        target,
        output_path=tmp_path / "body",
        headers_path=tmp_path / "headers",
    ).build_command("retrieve")
    assert "--proto" in command and command[command.index("--proto") + 1] == "=https"
    assert "--max-filesize" in command
    assert "--dangerously-skip-permissions" not in command
    assert canonical_url("https://www.CDC.gov/path/") == "https://cdc.gov/path"


@pytest.mark.parametrize(
    ("url", "trusted_root"),
    [
        ("https://evilcms.gov.example/x", "cms.gov"),
        ("https://cdc.gov.attacker.example/x", "cdc.gov"),
        ("https://notnih.gov.example/x", "nih.gov"),
        ("https://medicare.gov.evil.example/x", "medicare.gov"),
        ("https://pubmed.ncbi.nlm.nih.gov.evil.example/x", "pubmed.ncbi.nlm.nih.gov"),
        ("https://doi.org.attacker.example/x", "doi.org"),
        ("https://api.crossref.org.attacker.example/x", "api.crossref.org"),
    ],
)
def test_trusted_source_lookalikes_receive_no_quality_boost(url, trusted_root) -> None:
    host = url.split("/")[2]
    assert host_matches_trusted_root(host, trusted_root) is False
    assert classify_source_type(url) == "unknown"


def test_trusted_source_classification_accepts_exact_roots_and_subdomains() -> None:
    assert host_matches_trusted_root("www.cms.gov", "cms.gov")
    assert host_matches_trusted_root("sub.cdc.gov", "cdc.gov")
    assert classify_source_type("https://sub.cms.gov/policy") == "government_policy"
    assert classify_source_type("https://pubmed.ncbi.nlm.nih.gov/123") == (
        "primary_literature"
    )
