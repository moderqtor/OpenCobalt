"""Normalized public-HTTPS document acquisition for Research."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import shutil
import socket
import subprocess
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urljoin, urlsplit

from opencobalt.execution.models import RuntimeCapabilitySnapshot
from opencobalt.personal_ai.documents import (
    extract_csv_text,
    extract_html_text,
    extract_pdf_text,
    sniff_kind,
)

_FETCH_BYTES = 150_000
_EXCERPT_CHARS = 8_000
_MAX_FOLLOWUPS = 6
_MAX_REDIRECTS = 3
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}
_ASSET_SUFFIXES = {
    ".css",
    ".js",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".ico",
    ".webp",
    ".woff",
    ".woff2",
    ".map",
}
_JUNK_PATH_TOKENS = (
    "/email-updates",
    "/login",
    "/signup",
    "/themes/",
    "/sites/default/files/css",
    "/sites/default/files/js",
    "/favicon",
    "/user/",
    "/cart",
)
PREFERRED_SOURCE_HOSTS = {
    "pubmed.ncbi.nlm.nih.gov",
    "eutils.ncbi.nlm.nih.gov",
    "ncbi.nlm.nih.gov",
    "cms.gov",
    "medicare.gov",
    "cdc.gov",
    "nih.gov",
    "nidcr.nih.gov",
    "fda.gov",
    "ssa.gov",
    "govinfo.gov",
    "federalregister.gov",
    "uspreventiveservicestaskforce.org",
    "cochranelibrary.com",
    "api.crossref.org",
    "doi.org",
}
_LITERATURE_ROOTS = {
    "doi.org",
    "crossref.org",
    "pubmed.ncbi.nlm.nih.gov",
    "ncbi.nlm.nih.gov",
    "nih.gov",
}
_GOVERNMENT_ROOTS = {
    "cms.gov",
    "medicare.gov",
    "cdc.gov",
    "fda.gov",
    "ssa.gov",
    "govinfo.gov",
    "federalregister.gov",
}
_REVIEW_ROOTS = {"cochranelibrary.com", "uspreventiveservicestaskforce.org"}
_JOURNALISM_ROOTS = {"nytimes.com", "washingtonpost.com", "reuters.com", "bbc.com"}
_DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+\b", re.IGNORECASE)
Resolver = Callable[[str, int], Sequence[str]]
_MINIMUM_HARD_LIMIT_CURL = (8, 4, 0)


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _normalized_hostname(host: str) -> str:
    value = host.rstrip(".").casefold()
    try:
        return value.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ValueError("invalid URL hostname") from exc


def _validated_https_target_parts(url: str) -> tuple[str, int]:
    try:
        parsed = urlsplit(url)
        port = parsed.port or 443
    except ValueError as exc:
        raise ValueError("malformed HTTPS URL") from exc
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("URL must use HTTPS and include a hostname")
    if parsed.username or parsed.password or parsed.fragment:
        raise ValueError("URL credentials and fragments are not allowed")
    if len(url) > 2000:
        raise ValueError("URL exceeds the maximum length")
    host = _normalized_hostname(parsed.hostname)
    if host in {"localhost"} or host.endswith(".local"):
        raise ValueError("local hostnames are not public HTTPS destinations")
    if not 1 <= port <= 65535:
        raise ValueError("invalid HTTPS destination port")
    if "." not in host:
        try:
            ipaddress.ip_address(host)
        except ValueError as exc:
            raise ValueError("hostname must be fully qualified") from exc
    return host, port


def _is_global_address(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    return bool(
        address.is_global
        and not address.is_private
        and not address.is_loopback
        and not address.is_link_local
        and not address.is_multicast
        and not address.is_reserved
        and not address.is_unspecified
    )


def is_public_https_url(url: str) -> bool:
    """Syntactic preflight; acquisition separately resolves and pins DNS."""
    try:
        host, _port = _validated_https_target_parts(url)
    except ValueError:
        return False
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return True
    return _is_global_address(host)


def normalized_host(host: str) -> str:
    try:
        value = _normalized_hostname(host)
    except ValueError:
        return ""
    return value[4:] if value.startswith("www.") else value


def host_matches_trusted_root(host: str, trusted_root: str) -> bool:
    """Return whether a hostname belongs to a configured trusted root."""
    try:
        candidate = _normalized_hostname(host)
        root = _normalized_hostname(trusted_root)
    except ValueError:
        return False
    return candidate == root or candidate.endswith(f".{root}")


@dataclass(frozen=True)
class ResolvedHttpsTarget:
    url: str
    host: str
    port: int
    addresses: tuple[str, ...]


def _resolve_host_addresses(host: str, port: int) -> list[str]:
    try:
        records = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError(f"HTTPS hostname resolution failed: {exc}") from exc
    return [str(record[4][0]) for record in records]


def resolve_public_https_target(
    url: str,
    *,
    resolver: Resolver = _resolve_host_addresses,
) -> ResolvedHttpsTarget:
    host, port = _validated_https_target_parts(url)
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        raw_addresses = resolver(host, port)
    else:
        raw_addresses = [str(literal)]
    addresses: list[str] = []
    for raw in raw_addresses:
        try:
            address = ipaddress.ip_address(str(raw).split("%", 1)[0])
        except ValueError as exc:
            raise ValueError("hostname resolution returned an invalid address") from exc
        if not _is_global_address(str(address)):
            raise ValueError(f"hostname resolved to non-public address {address}")
        rendered = str(address)
        if rendered not in addresses:
            addresses.append(rendered)
    if not addresses:
        raise ValueError("HTTPS hostname resolution returned no addresses")
    return ResolvedHttpsTarget(
        url=url,
        host=host,
        port=port,
        addresses=tuple(addresses),
    )


def canonical_url(url: str) -> str:
    parsed = urlsplit(url.strip())
    if not parsed.scheme:
        return url
    host = normalized_host(parsed.hostname or "")
    path = parsed.path.rstrip("/") or "/"
    return f"{parsed.scheme}://{host}{path}" + (f"?{parsed.query}" if parsed.query else "")


def redirect_network_identity(url: str) -> tuple[str, int, str, str]:
    """Identify a redirect hop without applying source-deduplication rules."""
    host, port = _validated_https_target_parts(url)
    parsed = urlsplit(url)
    return host, port, parsed.path or "/", parsed.query


def _curl_version(executable: str) -> str:
    try:
        result = subprocess.run(
            [executable, "--version"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.splitlines()[0] if result.returncode == 0 and result.stdout else ""


def _curl_enforces_hard_max_filesize(version: str) -> bool:
    match = re.match(r"^curl\s+(\d+)\.(\d+)\.(\d+)(?:\s|$)", version.strip())
    return bool(match and tuple(int(item) for item in match.groups()) >= _MINIMUM_HARD_LIMIT_CURL)


def classify_source_type(url: str) -> str:
    host = urlsplit(url).hostname or ""
    if any(host_matches_trusted_root(host, root) for root in _LITERATURE_ROOTS):
        return "primary_literature"
    if any(host_matches_trusted_root(host, root) for root in _GOVERNMENT_ROOTS):
        return "government_policy"
    if any(host_matches_trusted_root(host, root) for root in _REVIEW_ROOTS):
        return "review"
    if any(host_matches_trusted_root(host, root) for root in _JOURNALISM_ROOTS):
        return "journalism"
    return "unknown"


def source_quality_hint(url: str, *, source_type: str | None = None) -> str:
    kind = source_type or classify_source_type(url)
    return {
        "primary_literature": "scientific literature host; still requires study-design review",
        "government_policy": "authoritative government/policy host; not causal proof",
        "review": "review or guideline host; prefer primary evidence when making causal claims",
        "journalism": "secondary reporting; use only for context unless primary evidence is absent",
        "user_document": "user-provided document; data, not authority",
        "unknown": "host class not identified; treat as unverified until retrieved",
    }.get(kind, "host class not identified; treat as unverified until retrieved")


def source_quality_score(url: str, *, source_type: str = "", retrieval_status: str = "") -> float:
    kind = source_type or classify_source_type(url)
    base = {
        "primary_literature": 0.86,
        "government_policy": 0.82,
        "review": 0.8,
        "user_document": 0.78,
        "journalism": 0.42,
        "unknown": 0.35,
    }.get(kind, 0.35)
    if retrieval_status != "retrieved":
        base -= 0.25
    if looks_like_search_index(url):
        base -= 0.3
    return max(0.0, min(1.0, base))


class HttpsGetAdapter:
    runtime_id = "opencobalt-https-get"
    display_name = "OpenCobalt public HTTPS fetch"
    isolates_answer_only_inference = True

    def __init__(
        self,
        target: ResolvedHttpsTarget,
        *,
        timeout_seconds: int = 20,
        output_path: Path,
        headers_path: Path,
        curl_version: str | None = None,
    ) -> None:
        self.target = target
        self.url = target.url
        self.timeout_seconds = timeout_seconds
        self.output_path = output_path
        self.headers_path = headers_path
        self.executable = shutil.which("curl") or "curl"
        self._executable_available = shutil.which("curl") is not None
        self.curl_version = (
            _curl_version(self.executable) if curl_version is None else curl_version
        )
        self.hard_size_limit_supported = bool(
            self._executable_available
            and _curl_enforces_hard_max_filesize(self.curl_version)
        )
        self._available = self.hard_size_limit_supported

    def discover_capabilities(self) -> RuntimeCapabilitySnapshot:
        return RuntimeCapabilitySnapshot(
            adapter_id=self.runtime_id,
            adapter_name=self.display_name,
            executable_path=self.executable if self._available else None,
            available=self._available,
            capabilities=["https_get"] if self._available else [],
            supported_artifact_types=["stdout", "stderr"],
            supports_dry_run=True,
            supports_noninteractive=self._available,
            supports_json_output=False,
            requires_network=True,
            requires_credentials=False,
            max_safe_risk="yellow",
            limitations=(
                []
                if self._available
                else [
                    "curl 8.4.0 or newer is required to enforce the hard response-size limit"
                    if self._executable_available
                    else "curl is required for source retrieval"
                ]
            ),
            verifiability_level="partial" if self._available else "unavailable",
            capability_details={
                "url_scheme": "https",
                "curl_version": self.curl_version,
                "hard_response_size_limit": self.hard_size_limit_supported,
            },
        ).with_hash()

    def build_command(self, task: str, options: Any = None) -> list[str]:
        _ = task, options
        if not self._available:
            raise ValueError("HTTPS fetch adapter is unavailable")
        command = [
            self.executable,
            "--disable",
            "--silent",
            "--show-error",
            "--fail-with-body",
            "--noproxy",
            "*",
            "--proto",
            "=https",
            "--max-filesize",
            str(_FETCH_BYTES),
            "--connect-timeout",
            "8",
            "--max-time",
            str(self.timeout_seconds),
            "--header",
            "User-Agent: OpenCobaltResearch/1.0 (https://github.com/moderqtor/OpenCobalt)",
            "--header",
            "Accept-Encoding: identity",
            "--dump-header",
            str(self.headers_path),
            "--output",
            str(self.output_path),
            "--write-out",
            "%{http_code}",
        ]
        rendered_addresses = ",".join(
            f"[{address}]" if ":" in address else address
            for address in self.target.addresses
        )
        command.extend(
            [
                "--resolve",
                f"{self.target.host}:{self.target.port}:{rendered_addresses}",
            ]
        )
        command.extend(["--url", self.url])
        return command

    def supports_non_interactive(self) -> bool:
        return self._available

    def default_timeout_seconds(self) -> int:
        return self.timeout_seconds

    def risk_for_task(self, task: str) -> str:
        _ = task
        return "green"


@dataclass
class RetrievedDocument:
    url: str
    canonical_url: str
    source_type: str
    title: str = ""
    authors: list[str] = field(default_factory=list)
    publication_date: str | None = None
    retrieved_at: str | None = None
    retrieval_status: str = "unverified"
    content: str = ""
    excerpt: str = ""
    pages: list[dict[str, Any]] = field(default_factory=list)
    content_hash: str | None = None
    retrieval_adapter: str = "https_html"
    mime_type: str = ""
    limitations: list[str] = field(default_factory=list)
    quality_assessment: str = ""
    quality_score: float = 0.0
    raw: str = ""
    attachment_id: str | None = None

    def to_source_record(self, *, source_id: str, research_id: str, created_at: str) -> dict[str, Any]:
        return {
            "source_id": source_id,
            "research_id": research_id,
            "url": self.url,
            "canonical_url": self.canonical_url,
            "title": self.title[:300],
            "source_type": self.source_type,
            "publication_date": self.publication_date,
            "authors": self.authors,
            "retrieved_at": self.retrieved_at,
            "retrieval_status": self.retrieval_status,
            "content_hash": self.content_hash,
            "excerpt": self.excerpt[:_EXCERPT_CHARS],
            "quality_assessment": self.quality_assessment,
            "quality_score": self.quality_score,
            "retrieval_adapter": self.retrieval_adapter,
            "mime_type": self.mime_type,
            "attachment_id": self.attachment_id,
            "limitations": self.limitations,
            "page_map": self.pages,
            "created_at": created_at,
        }


class DocumentAcquisitionPipeline:
    """Fetch a URL or uploaded document into one RetrievedDocument."""

    def __init__(
        self,
        engine: Any,
        *,
        resolver: Resolver = _resolve_host_addresses,
        max_redirects: int = _MAX_REDIRECTS,
        curl_version: str | None = None,
    ) -> None:
        self.engine = engine
        self.resolver = resolver
        self.max_redirects = max(0, min(int(max_redirects), _MAX_REDIRECTS))
        self.curl_version = (
            _curl_version(shutil.which("curl") or "curl")
            if curl_version is None
            else curl_version
        )

    def acquire_url(self, url: str) -> RetrievedDocument:
        created = _now()
        if not is_public_https_url(url):
            return RetrievedDocument(
                url=url,
                canonical_url=canonical_url(url),
                source_type=classify_source_type(url),
                retrieval_status="rejected",
                excerpt="URL rejected: not a public HTTPS source",
                limitations=["not a public HTTPS source"],
                quality_assessment=source_quality_hint(url),
                retrieved_at=None,
            )
        doi = extract_doi(url)
        if doi:
            document = self._acquire_doi(doi, url)
            if document.retrieval_status == "retrieved":
                return document
        return self._fetch_and_normalize(url, created)

    def acquire_upload(self, record: Mapping[str, Any]) -> RetrievedDocument:
        filename = str(record.get("original_filename") or record.get("stored_filename") or "document")
        text = str(record.get("extracted_text") or record.get("excerpt") or "")
        status = str(record.get("ingestion_status") or "extracted")
        retrieval = "retrieved" if text.strip() and status != "rejected" else "empty"
        digest = str(record.get("sha256") or "") or (
            hashlib.sha256(text.encode("utf-8")).hexdigest() if text else None
        )
        return RetrievedDocument(
            url=f"attachment://{record.get('attachment_id')}/{filename}",
            canonical_url=f"attachment://{record.get('attachment_id')}",
            source_type="user_document",
            title=filename,
            retrieved_at=str(record.get("created_at") or _now()),
            retrieval_status=retrieval,
            content=text,
            excerpt=text[:_EXCERPT_CHARS],
            pages=list(record.get("sections") or []),
            content_hash=digest,
            retrieval_adapter="upload",
            mime_type=str(record.get("mime_type") or ""),
            limitations=list(record.get("limitations") or ["user-provided document is data, not authority"]),
            quality_assessment=source_quality_hint("", source_type="user_document"),
            quality_score=source_quality_score("", source_type="user_document", retrieval_status=retrieval),
            attachment_id=str(record.get("attachment_id") or "") or None,
        )

    def _acquire_doi(self, doi: str, original_url: str) -> RetrievedDocument:
        api_url = f"https://api.crossref.org/works/{quote(doi)}"
        meta = self._fetch_and_normalize(api_url, _now(), adapter="doi_crossref")
        payload = _parse_structured(meta.raw or meta.content)
        message = payload.get("message") if isinstance(payload, Mapping) else None
        if not isinstance(message, Mapping):
            return self._fetch_and_normalize(original_url, _now())
        title = " ".join(_string_list(message.get("title"))) or meta.title
        authors = []
        for author in _as_list(message.get("author")):
            if not isinstance(author, Mapping):
                continue
            name = " ".join(
                part for part in (author.get("given"), author.get("family")) if part
            ).strip()
            if name:
                authors.append(name)
        date_parts = message.get("issued") if isinstance(message.get("issued"), Mapping) else {}
        parts = date_parts.get("date-parts") if isinstance(date_parts, Mapping) else None
        publication_date = None
        if isinstance(parts, list) and parts and isinstance(parts[0], list):
            publication_date = "-".join(str(item) for item in parts[0][:3])
        resource = message.get("resource") if isinstance(message.get("resource"), Mapping) else {}
        primary = resource.get("primary") if isinstance(resource, Mapping) else {}
        target = str(primary.get("URL") or "") if isinstance(primary, Mapping) else ""
        if not target:
            links = message.get("link") if isinstance(message.get("link"), list) else []
            for link in links:
                if isinstance(link, Mapping) and str(link.get("URL") or "").startswith("https://"):
                    target = str(link.get("URL"))
                    break
        document = meta
        document.title = title[:300]
        document.authors = authors[:12]
        document.publication_date = publication_date
        document.source_type = "primary_literature"
        document.retrieval_adapter = "doi_crossref"
        document.quality_assessment = source_quality_hint(target or original_url, source_type="primary_literature")
        if target and is_public_https_url(target) and canonical_url(target) != canonical_url(api_url):
            body = self._fetch_and_normalize(target, _now(), adapter="doi_crossref")
            if body.retrieval_status == "retrieved":
                body.title = body.title or title
                body.authors = body.authors or authors
                body.publication_date = body.publication_date or publication_date
                body.source_type = "primary_literature"
                body.retrieval_adapter = "doi_crossref"
                return body
            document.limitations.append("Crossref metadata retrieved; canonical publisher document was not")
        document.quality_score = source_quality_score(
            target or original_url,
            source_type="primary_literature",
            retrieval_status=document.retrieval_status,
        )
        return document

    def _fetch_and_normalize(
        self,
        url: str,
        created: str,
        *,
        adapter: str | None = None,
    ) -> RetrievedDocument:
        document = RetrievedDocument(
            url=url,
            canonical_url=canonical_url(url),
            source_type=classify_source_type(url),
            quality_assessment=source_quality_hint(url),
            retrieval_adapter=adapter or guess_adapter(url),
        )
        current_url = url
        seen: set[tuple[str, int, str, str]] = set()
        with tempfile.TemporaryDirectory(prefix="oc-fetch-") as directory:
            tmpdir = Path(directory)
            for redirect_count in range(self.max_redirects + 1):
                try:
                    target = resolve_public_https_target(
                        current_url,
                        resolver=self.resolver,
                    )
                except ValueError as exc:
                    document.retrieval_status = "rejected"
                    document.excerpt = str(exc)[:300]
                    document.limitations.append(str(exc)[:300])
                    return document
                key = redirect_network_identity(current_url)
                if key in seen:
                    document.retrieval_status = "failed"
                    document.excerpt = "fetch failed: redirect loop detected"
                    document.limitations.append("redirect loop detected")
                    return document
                seen.add(key)

                output_path = tmpdir / f"body-{redirect_count}"
                headers_path = tmpdir / f"headers-{redirect_count}"
                fetch = HttpsGetAdapter(
                    target,
                    output_path=output_path,
                    headers_path=headers_path,
                    curl_version=self.curl_version,
                )
                if not fetch.hard_size_limit_supported:
                    document.retrieval_status = "failed"
                    document.excerpt = (
                        "fetch failed: curl cannot enforce the hard response-size limit"
                    )
                    document.limitations.append(
                        "curl 8.4.0 or newer is required to enforce the hard response-size limit"
                    )
                    return document
                output_path.write_bytes(b"")
                headers_path.write_bytes(b"")
                try:
                    outcome = self.engine.run_task(
                        f"retrieve research source {current_url}",
                        runtime=fetch.runtime_id,
                        execute=True,
                        approved=False,
                        timeout_seconds=fetch.timeout_seconds,
                        unsafe_skip_permissions=False,
                        execution_context="answer_only_inference",
                        adapter=fetch,
                    )
                except (KeyError, ValueError) as exc:
                    document.retrieval_status = "failed"
                    document.excerpt = str(exc)[:300]
                    document.limitations.append(str(exc)[:300])
                    return document
                result = getattr(outcome, "result", None)
                if result is None or str(getattr(result, "status", "")) != "succeeded":
                    document.retrieval_status = "failed"
                    document.excerpt = str(getattr(result, "error", None) or "fetch failed")[:300]
                    return document

                status, location = _response_metadata(result, headers_path)
                if status in _REDIRECT_STATUSES:
                    if redirect_count >= self.max_redirects:
                        document.retrieval_status = "failed"
                        document.excerpt = "fetch failed: redirect limit exceeded"
                        document.limitations.append("redirect limit exceeded")
                        return document
                    if not location:
                        document.retrieval_status = "failed"
                        document.excerpt = "fetch failed: redirect omitted Location"
                        document.limitations.append("redirect omitted Location")
                        return document
                    current_url = urljoin(current_url, location)
                    continue
                if status is None or not 200 <= status < 300:
                    document.retrieval_status = "failed"
                    document.excerpt = f"fetch failed: HTTP status {status or 'unknown'}"
                    document.limitations.append(document.excerpt)
                    return document

                try:
                    oversized = output_path.stat().st_size > _FETCH_BYTES
                except OSError:
                    oversized = False
                if oversized:
                    document.retrieval_status = "failed"
                    document.excerpt = "fetch failed: response exceeded hard size limit"
                    document.limitations.append("response exceeded hard size limit")
                    return document

                payload = _read_payload(result, output_path)
                normalized = normalize_payload(
                    current_url,
                    payload,
                    adapter=document.retrieval_adapter,
                )
                if canonical_url(current_url) != canonical_url(url):
                    normalized.limitations.append(
                        f"retrieved after {redirect_count} validated HTTPS redirect(s)"
                    )
                return normalized

        document.retrieval_status = "failed"
        document.excerpt = "fetch failed: redirect processing ended unexpectedly"
        document.limitations.append(document.excerpt)
        return document


def _response_metadata(result: Any, headers_path: Path) -> tuple[int | None, str | None]:
    raw_headers = ""
    try:
        raw_headers = headers_path.read_text(encoding="iso-8859-1")[:65_536]
    except OSError:
        pass
    statuses = re.findall(r"(?im)^HTTP/\S+\s+(\d{3})\b", raw_headers)
    status = int(statuses[-1]) if statuses else None
    preview = str(getattr(result, "stdout_preview", "") or "").strip()
    if status is None and re.fullmatch(r"\d{3}", preview):
        status = int(preview)
    blocks = re.split(r"\r?\n\r?\n", raw_headers.strip()) if raw_headers else []
    location = None
    if blocks:
        match = re.search(r"(?im)^Location:\s*([^\r\n]+)", blocks[-1])
        if match:
            location = match.group(1).strip()
    return status, location


def guess_adapter(url: str) -> str:
    host = normalized_host(urlsplit(url).hostname or "")
    path = urlsplit(url).path.lower()
    if any(
        host_matches_trusted_root(host, root)
        for root in {"eutils.ncbi.nlm.nih.gov", "pubmed.ncbi.nlm.nih.gov"}
    ):
        return "pubmed"
    if any(
        host_matches_trusted_root(host, root)
        for root in {"api.crossref.org", "doi.org"}
    ):
        return "doi_crossref"
    if path.endswith(".pdf"):
        return "pdf"
    if any(host_matches_trusted_root(host, root) for root in _GOVERNMENT_ROOTS):
        return "government_https"
    return "https_html"


def extract_doi(url: str) -> str | None:
    parsed = urlsplit(url)
    host = normalized_host(parsed.hostname or "")
    if host == "doi.org":
        doi = unquote(parsed.path.lstrip("/"))
        return doi if doi.lower().startswith("10.") else None
    match = _DOI_RE.search(unquote(url))
    return match.group(0) if match else None


def normalize_payload(url: str, payload: bytes, *, adapter: str) -> RetrievedDocument:
    kind = sniff_kind(urlsplit(url).path, payload=payload)
    raw_text = ""
    title = url
    authors: list[str] = []
    publication_date = None
    pages: list[dict[str, Any]] = []
    limitations: list[str] = []
    mime = ""
    if kind == "pdf" or payload.startswith(b"%PDF"):
        text, pages, limitations = extract_pdf_text(payload)
        adapter = "pdf"
        mime = "application/pdf"
        title = Path(urlsplit(url).path).name or url
    else:
        raw_text = payload.decode("utf-8", errors="replace")
        parsed_json = _parse_structured(raw_text)
        if parsed_json is not None:
            text = json.dumps(parsed_json)[:_EXCERPT_CHARS]
            title = url
            mime = "application/json"
            if adapter == "https_html":
                adapter = "json"
        elif kind == "csv":
            text = extract_csv_text(raw_text)
            mime = "text/csv"
        else:
            parsed_title, text = extract_html_text(raw_text)
            html_heading = html_title(raw_text)
            title = parsed_title or html_heading or url
            mime = "text/html"
            if adapter == "https_html" and classify_source_type(url) == "government_policy":
                adapter = "government_https"
            authors, publication_date = html_publication_meta(raw_text)
    excerpt = (text or "")[:_EXCERPT_CHARS]
    status = "retrieved" if excerpt.strip() else "empty"
    digest = hashlib.sha256(excerpt.encode("utf-8")).hexdigest() if excerpt else None
    source_type = classify_source_type(url)
    return RetrievedDocument(
        url=url,
        canonical_url=canonical_url(url),
        source_type=source_type,
        title=title[:300],
        authors=authors,
        publication_date=publication_date,
        retrieved_at=_now(),
        retrieval_status=status,
        content=excerpt,
        excerpt=excerpt,
        pages=pages,
        content_hash=digest,
        retrieval_adapter=adapter,
        mime_type=mime,
        limitations=limitations,
        quality_assessment=source_quality_hint(url, source_type=source_type),
        quality_score=source_quality_score(url, source_type=source_type, retrieval_status=status),
        raw=raw_text,
    )


def _read_payload(result: Any, output_path: Path | None) -> bytes:
    if output_path is not None and output_path.exists() and output_path.stat().st_size:
        return output_path.read_bytes()[:_FETCH_BYTES]
    path = getattr(result, "stdout_path", None)
    if path:
        data = Path(path).read_bytes()[:_FETCH_BYTES]
        if data:
            return data
    preview = str(getattr(result, "stdout_preview", "") or getattr(result, "content", "") or "")
    return preview.encode("utf-8", errors="replace")[:_FETCH_BYTES]


def html_title(raw: str) -> str:
    match = re.search(r"(?is)<title[^>]*>(.*?)</title>", raw)
    if not match:
        return ""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", match.group(1))).strip()


def html_publication_meta(raw: str) -> tuple[list[str], str | None]:
    authors: list[str] = []
    for match in re.finditer(
        r'(?is)<meta[^>]+(?:name|property)=["\'](?:author|citation_author|dc.creator)["\'][^>]+content=["\']([^"\']+)["\']',
        raw,
    ):
        name = match.group(1).strip()
        if name and name not in authors:
            authors.append(name)
    date = None
    for match in re.finditer(
        r'(?is)<meta[^>]+(?:name|property)=["\'](?:citation_date|citation_publication_date|dc.date|date)["\'][^>]+content=["\']([^"\']+)["\']',
        raw,
    ):
        date = match.group(1).strip()[:40]
        break
    return authors[:12], date


def html_to_text(raw: str) -> str:
    _, text = extract_html_text(raw)
    if text:
        return text
    parser = _LegacyExtractor()
    try:
        parser.feed(raw)
        parser.close()
    except Exception:
        return re.sub(r"<[^>]+>", " ", raw)
    return re.sub(r"\s+", " ", parser.text).strip()


class _LegacyExtractor(HTMLParser):
    _skip_tags = {
        "script", "style", "noscript", "svg", "nav", "header", "footer",
        "aside", "form", "iframe", "button",
    }
    _main_tags = {"main", "article"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._main_depth = 0
        self._body: list[str] = []
        self._main: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._skip_tags:
            self._skip_depth += 1
            return
        names = {key.lower(): (value or "") for key, value in attrs}
        if tag in self._main_tags or names.get("role") == "main":
            self._main_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in self._skip_tags and self._skip_depth:
            self._skip_depth -= 1
            return
        if tag in self._main_tags and self._main_depth:
            self._main_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = data.strip()
        if not text:
            return
        if self._main_depth:
            self._main.append(text)
        else:
            self._body.append(text)

    @property
    def text(self) -> str:
        main = " ".join(self._main).strip()
        body = " ".join(self._body).strip()
        if len(main) >= 200:
            return main
        return body or main


def search_seed_urls(query: str) -> list[str]:
    encoded = re.sub(r"\s+", "+", query.strip())[:180]
    if not encoded:
        return []
    bibliographic = quote(re.sub(r"\s+", " ", query.strip())[:180])
    return [
        (
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
            f"?db=pubmed&retmode=json&retmax=5&term={encoded}"
        ),
        f"https://www.cms.gov/search/cms?keys={encoded}",
        f"https://api.crossref.org/works?query.bibliographic={bibliographic}&rows=3",
        f"https://www.govinfo.gov/app/search/{encoded}",
    ]


def looks_like_search_index(url: str) -> bool:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    path = parsed.path.lower()
    query = parsed.query.lower()
    if "esearch.fcgi" in path or "search" in path.split("/"):
        return True
    if (
        host_matches_trusted_root(host, "api.crossref.org")
        and "query.bibliographic" in query
    ):
        return True
    if "term=" in query or "keys=" in query:
        return True
    if host_matches_trusted_root(
        host, "pubmed.ncbi.nlm.nih.gov"
    ) and not re.fullmatch(r"/\d+/?", parsed.path):
        return bool(query)
    return False


def looks_like_asset_url(url: str) -> bool:
    path = urlsplit(url).path.lower()
    if Path(path).suffix in _ASSET_SUFFIXES:
        return True
    return any(token in path for token in _JUNK_PATH_TOKENS)


def followup_urls_from_payload(url: str, raw: str) -> list[str]:
    found: list[str] = []
    payload = _parse_structured(raw)
    if isinstance(payload, Mapping):
        result = payload.get("esearchresult")
        ids = result.get("idlist") if isinstance(result, Mapping) else None
        if isinstance(ids, list):
            for pmid in ids[:5]:
                pmid_text = re.sub(r"[^0-9]", "", str(pmid))
                if pmid_text:
                    found.append(
                        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
                        f"?db=pubmed&id={pmid_text}&rettype=abstract&retmode=text"
                    )
                    found.append(f"https://pubmed.ncbi.nlm.nih.gov/{pmid_text}/")
        items = payload.get("message")
        if isinstance(items, Mapping):
            works = items.get("items")
            if isinstance(works, list):
                for work in works[:3]:
                    if not isinstance(work, Mapping):
                        continue
                    doi = str(work.get("DOI") or "").strip()
                    if doi:
                        found.append(f"https://doi.org/{doi}")
    for match in re.finditer(r"""href=["']([^"'#]+)["']""", raw, flags=re.IGNORECASE):
        candidate = urljoin(url, match.group(1).strip())
        if _is_preferred_document_url(candidate):
            found.append(candidate)
    for doi in _DOI_RE.findall(raw)[:3]:
        found.append(f"https://doi.org/{doi}")
    deduped: list[str] = []
    seen: set[str] = set()
    for item in found:
        key = canonical_url(item)
        if key in seen or item == url:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped[:_MAX_FOLLOWUPS]


def _is_preferred_document_url(url: str) -> bool:
    if not is_public_https_url(url):
        return False
    if looks_like_search_index(url):
        return False
    parsed = urlsplit(url)
    path = parsed.path.lower()
    if looks_like_asset_url(url) or path in {"", "/"}:
        return False
    host = normalized_host(parsed.hostname or "")
    if not any(host_matches_trusted_root(host, root) for root in PREFERRED_SOURCE_HOSTS):
        return False
    if host == "pubmed.ncbi.nlm.nih.gov":
        return bool(re.fullmatch(r"/\d+/?", parsed.path))
    if host == "eutils.ncbi.nlm.nih.gov":
        return "efetch.fcgi" in path
    if host == "ncbi.nlm.nih.gov":
        return bool(
            re.search(r"/pmc/articles/", path)
            or re.search(r"/books/nbk\d+", path)
        )
    if host == "api.crossref.org":
        return "/works/" in path and "query" not in parsed.query.lower()
    return True


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


def rank_and_dedupe_sources(sources: Sequence[Mapping[str, Any]], *, limit: int = 8) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    seen_hash: set[str] = set()
    seen_url: set[str] = set()
    for item in sorted(
        sources,
        key=lambda row: float(row.get("quality_score") or source_quality_score(
            str(row.get("url") or ""),
            source_type=str(row.get("source_type") or ""),
            retrieval_status=str(row.get("retrieval_status") or ""),
        )),
        reverse=True,
    ):
        url = canonical_url(str(item.get("canonical_url") or item.get("url") or ""))
        digest = str(item.get("content_hash") or "")
        if url and url in seen_url:
            continue
        if digest and digest in seen_hash:
            continue
        if looks_like_search_index(str(item.get("url") or "")):
            continue
        if looks_like_asset_url(str(item.get("url") or "")):
            continue
        if url:
            seen_url.add(url)
        if digest:
            seen_hash.add(digest)
        ranked.append(dict(item))
        if len(ranked) >= limit:
            break
    return ranked
