from __future__ import annotations

import json

from opencobalt.core.mission_engine import MissionStore
from opencobalt.execution.models import RuntimeCapabilitySnapshot
from opencobalt.integrations.antigravity_integration import (
    build_antigravity_command,
    build_antigravity_models_command,
)
from opencobalt.personal_ai.antigravity import (
    AntigravityChatProvider,
    _AntigravityPrintAdapter,
    infer_antigravity_model_profile,
    parse_antigravity_models_payload,
    parse_antigravity_payload,
    resolve_print_effort,
)
from opencobalt.personal_ai.models import AISettings
from opencobalt.personal_ai.providers import (
    CancellationToken,
    ProviderRegistry,
    ProviderRequest,
)
from opencobalt.personal_ai.research import (
    ResearchOrchestrator,
    assign_research_roles,
)
from opencobalt.personal_ai.retrieval import (
    classify_source_type,
    followup_urls_from_payload,
    html_to_text,
    is_public_https_url,
    looks_like_search_index,
    search_seed_urls,
)
from opencobalt.personal_ai.router import PersonalAIRouter, ProviderSnapshot, RoutingRequest
from opencobalt.personal_ai.service import ChatRequest, ChatService
from opencobalt.personal_ai.store import PersonalAIStore
from tests.test_personal_ai_providers import FakeAdapter, FakeEngine, _outcome


def _agy_caps(**supported: bool) -> dict:
    flags = {
        "non_interactive_print": True,
        "non_interactive_mode": True,
        "model_selection": True,
        "sandbox_mode": True,
        "json_output": True,
        "stream_json_output": True,
        "json_schema": True,
        "reasoning_effort": True,
        "execution_mode": True,
        "conversation_resume": True,
        "disable_slash_commands": True,
        "print_timeout": True,
        "models_subcommand": True,
    }
    flags.update(supported)
    return {
        key: {"supported": value, "source": "runtime_discovered", "evidence": key}
        for key, value in flags.items()
    }


def test_json_and_effort_flags_are_capability_gated():
    command = build_antigravity_command(
        "hello",
        model="gemini-3.6-flash-medium",
        sandbox=True,
        output_format="json",
        effort="low",
        disable_slash_commands=True,
        print_timeout="120s",
        capabilities=_agy_caps(),
    )
    assert command[:3] == ["agy", "--sandbox", "--output-format"]
    assert "--dangerously-skip-permissions" not in command
    assert command[-2:] == ["--print", "hello"]
    assert build_antigravity_models_command(capabilities=_agy_caps()) == [
        "agy",
        "--output-format",
        "json",
        "models",
    ]


def test_models_payload_parses_authenticated_catalog():
    payload = json.dumps(
        {
            "status": "SUCCESS",
            "command": {
                "name": "models",
                "data": {
                    "models": [
                        {"id": "gemini-3.1-pro-high", "label": "Gemini 3.1 Pro (High)"},
                        {"id": "gemini-3.6-flash-low", "label": "Gemini 3.6 Flash (Low)"},
                    ]
                },
            },
        }
    )
    models, limitations = parse_antigravity_models_payload(payload)
    assert [model.model_id for model in models] == [
        "gemini-3.1-pro-high",
        "gemini-3.6-flash-low",
    ]
    assert models[0].quality_tier == "strong"
    assert models[1].cost_category == "low"
    assert models[0].execution_location == "remote"
    assert any("heuristic" in item for item in limitations)


def test_stream_json_normalizes_tools_and_result():
    raw = "\n".join(
        [
            json.dumps(
                {
                    "event": "init",
                    "init": {"tools": ["read_url_content"], "permission_mode": "request-review"},
                }
            ),
            json.dumps(
                {
                    "event": "step_update",
                    "step_update": {
                        "step_index": 2,
                        "state": "DONE",
                        "step_type": "tool",
                        "tool_name": "read_url_content",
                        "tool_info": {"name": "read_url_content", "output": "ok"},
                    },
                }
            ),
            json.dumps(
                {
                    "event": "result",
                    "result": {
                        "conversation_id": "conv-agy",
                        "status": "SUCCESS",
                        "response": "done",
                        "usage": {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5},
                    },
                }
            ),
        ]
    )
    content, usage, tools, session, limitations = parse_antigravity_payload(raw)
    assert content == "done"
    assert session == "conv-agy"
    assert tools[0].tool_name == "read_url_content"
    assert usage["total_tokens"] == 5
    assert any("read_url_content" in item for item in limitations)


def test_invalid_model_envelope_is_an_error():
    raw = json.dumps(
        {
            "conversation_id": "",
            "status": "ERROR",
            "response": "",
            "error": "invalid model selection (--model \"nope\")",
        }
    )
    _content, _usage, _tools, _session, limitations = parse_antigravity_payload(raw)
    assert any("invalid model" in item.lower() or "error" in item.lower() for item in limitations)


def test_antigravity_local_only_is_blocked_before_engine():
    engine = FakeEngine()
    adapter = FakeAdapter("google-antigravity")
    adapter.executable = "agy"
    provider = AntigravityChatProvider(engine, adapter)
    result = provider.execute(ProviderRequest(message="hello", local_only=True))
    assert result.status == "blocked"
    assert result.error.category == "local_only_violation"
    assert engine.calls == []


def test_router_prefers_strong_model_for_research_without_fake_precision():
    router = PersonalAIRouter()
    flash = ProviderSnapshot(
        provider_id="antigravity",
        model_id="gemini-3.6-flash-low",
        runtime_id="google-antigravity",
        provider_family="google",
        available=True,
        local=False,
        requires_network=True,
        cost_category="low",
        quality_tier="standard",
        capabilities=frozenset({"chat", "research"}),
        display_name="Gemini 3.6 Flash (Low)",
    )
    pro = ProviderSnapshot(
        provider_id="antigravity",
        model_id="gemini-3.1-pro-high",
        runtime_id="google-antigravity",
        provider_family="google",
        available=True,
        local=False,
        requires_network=True,
        cost_category="standard",
        quality_tier="strong",
        capabilities=frozenset({"chat", "research"}),
        display_name="Gemini 3.1 Pro (High)",
        profile_evidence="antigravity_model_id_v1",
    )
    plan = router.route(
        RoutingRequest(
            request_id="req-1",
            conversation_id="conv-1",
            request_message_id="msg-1",
            prompt="Compare the strongest evidence for this policy question",
            requested_persona_id="analytical",
            cognitive_policy="research",
            settings=AISettings(),
        ),
        [flash, pro],
    )
    assert plan.task_class == "research"
    assert plan.record.selected_model == "gemini-3.1-pro-high"
    assert "was selected because" in plan.record.reasons[-1]
    assert "%" not in plan.record.reasons[-1]


def test_research_roles_do_not_duplicate_the_same_model_as_reviewer():
    flash = ProviderSnapshot(
        provider_id="antigravity",
        model_id="gemini-3.6-flash-medium",
        runtime_id="google-antigravity",
        provider_family="google",
        available=True,
        local=False,
        requires_network=True,
        cost_category="low",
        quality_tier="standard",
        capabilities=frozenset({"research", "chat"}),
    )
    opus = ProviderSnapshot(
        provider_id="antigravity",
        model_id="claude-opus-4-6-thinking",
        runtime_id="google-antigravity",
        provider_family="google",
        available=True,
        local=False,
        requires_network=True,
        cost_category="high",
        quality_tier="strong",
        capabilities=frozenset({"research", "chat"}),
    )
    roles = assign_research_roles([flash, opus])
    assert roles["planner"].model_id == "gemini-3.6-flash-medium"
    assert roles["synthesizer"].model_id == "claude-opus-4-6-thinking"
    assert "reviewer" not in roles


def test_private_urls_are_rejected():
    assert is_public_https_url("https://www.cms.gov/medicare") is True
    assert is_public_https_url("http://example.com") is False
    assert is_public_https_url("https://127.0.0.1/secret") is False
    assert is_public_https_url("https://localhost/x") is False


class RecyclingFakeEngine(FakeEngine):
    def run_task(self, task: str, **kwargs):
        self.calls.append((task, kwargs))
        if not self.outcomes:
            return _outcome(
                stdout="<html><title>Source</title><body>Retrieved public excerpt.</body></html>"
            )
        return self.outcomes.pop(0)


class IsolatedAgyAdapter(FakeAdapter):
    def __init__(self) -> None:
        super().__init__("google-antigravity", isolates_answer_only_inference=True)
        self.executable = "agy"

    def discover_capabilities(self) -> RuntimeCapabilitySnapshot:
        return RuntimeCapabilitySnapshot(
            adapter_id=self.runtime_id,
            adapter_name=self.display_name,
            executable_path="/private/bin/agy",
            available=True,
            capabilities=["completion"],
            supported_artifact_types=["stdout", "stderr"],
            supports_dry_run=True,
            supports_noninteractive=True,
            supports_json_output=True,
            requires_network=True,
            requires_credentials=True,
            max_safe_risk="yellow",
            limitations=[],
            verifiability_level="partial",
            capability_details=_agy_caps(),
        ).with_hash()


def _catalog_stdout(*model_ids: str) -> str:
    return _catalog_stdout_records(*[{"id": model_id, "label": model_id} for model_id in model_ids])


def _catalog_stdout_records(*models: dict) -> str:
    return json.dumps(
        {
            "status": "SUCCESS",
            "command": {
                "name": "models",
                "data": {"models": list(models)},
            },
        }
    )


def _print_argv(engine: FakeEngine) -> list[str]:
    return engine.calls[-1][1]["adapter"].build_command("hello")


def _print_stdout(response: str) -> str:
    return json.dumps(
        {
            "conversation_id": "agy-session-1",
            "status": "SUCCESS",
            "response": response,
            "usage": {"input_tokens": 4, "output_tokens": 6, "total_tokens": 10},
        }
    )


def test_research_policy_creates_persisted_mission(tmp_path):
    engine = RecyclingFakeEngine(_outcome(stdout="ok"))
    store = PersonalAIStore(tmp_path / "ledger.db")
    service = ChatService(
        store=store,
        providers=ProviderRegistry(
            engine,
            adapters={
                "codex-cli": FakeAdapter("codex-cli"),
                "google-antigravity": FakeAdapter("google-antigravity"),
                "claude-code": FakeAdapter("claude-code"),
                "ollama": FakeAdapter(
                    "ollama",
                    requires_network=False,
                    requires_credentials=False,
                    isolates_answer_only_inference=True,
                ),
            },
            executable_finder=lambda _name: None,
        ),
        enable_mock=True,
        missions=MissionStore(tmp_path / "ledger.db"),
        engine=engine,
    )
    conversation = service.create_conversation(title="Research")
    events = list(
        service.stream_request(
            ChatRequest(
                conversation_id=conversation.conversation_id,
                message="What is the strongest evidence for Medicare oral-health screening?",
                persona_id="analytical",
                cognitive_policy="research",
            )
        )
    )
    assert any(event.event_type.startswith("research_") for event in events)
    assert events[-1].event_type == "completed"
    missions = store.list_research_missions()
    assert missions
    bundle = store.research_bundle(missions[0]["research_id"])
    assert bundle["question"].startswith("What is the strongest evidence")
    assert bundle["mission_id"]
    assert bundle["sources"]
    assert bundle["evidence"]
    assert any(item["verification_status"] == "unverified" for item in bundle["citations"])
    reopened = PersonalAIStore(tmp_path / "ledger.db")
    persisted = reopened.research_bundle(missions[0]["research_id"])
    assert persisted["research_id"] == bundle["research_id"]
    assert persisted["synthesis"] == bundle["synthesis"]


def test_persona_is_not_the_provider():
    profile = infer_antigravity_model_profile("gemini-3.1-pro-high", "Gemini 3.1 Pro (High)")
    assert profile["family"] == "gemini"
    assert profile["heuristic"] == "antigravity_model_id_v1"


def test_isolated_print_uses_scratch_cwd_and_never_skips_permissions():
    adapter = _AntigravityPrintAdapter(
        capabilities=_agy_caps(),
        model_id="gemini-3.6-flash-medium",
        timeout_seconds=90,
    )
    command = adapter.build_command("hello")
    assert command[0] == "agy"
    assert "--sandbox" in command
    assert "--output-format" in command
    assert "--disable-slash-commands" in command
    assert "--dangerously-skip-permissions" not in command
    assert command[-2:] == ["--print", "hello"]

    engine = FakeEngine(
        _outcome(stdout=_catalog_stdout("gemini-3.6-flash-medium")),
        _outcome(stdout=_print_stdout("isolated answer")),
    )
    provider = AntigravityChatProvider(engine, IsolatedAgyAdapter())
    result = provider.execute(
        ProviderRequest(message="hello", model_id="gemini-3.6-flash-medium")
    )
    assert result.status == "complete"
    assert result.content == "isolated answer"
    assert result.session_id == "agy-session-1"
    assert "scratch" in str(engine.calls[-1][1]["cwd"])
    assert engine.calls[-1][1]["unsafe_skip_permissions"] is False


def test_invalid_antigravity_model_is_blocked():
    engine = FakeEngine(_outcome(stdout=_catalog_stdout("gemini-3.6-flash-medium")))
    provider = AntigravityChatProvider(engine, IsolatedAgyAdapter())
    result = provider.execute(ProviderRequest(message="hello", model_id="not-a-real-model"))
    assert result.status == "blocked"
    assert result.error.category == "unavailable"
    assert len(engine.calls) == 1


def test_antigravity_cancellation_and_timeout():
    engine = FakeEngine(
        _outcome(stdout=_catalog_stdout("gemini-3.6-flash-medium")),
        _outcome(status="timeout", error="print timed out"),
    )
    provider = AntigravityChatProvider(engine, IsolatedAgyAdapter())
    cancelled = CancellationToken()
    cancelled.cancel()
    result = provider.execute(
        ProviderRequest(message="hello", model_id="gemini-3.6-flash-medium"),
        cancelled,
    )
    assert result.status == "cancelled"
    timed_out = provider.execute(
        ProviderRequest(message="hello", model_id="gemini-3.6-flash-medium")
    )
    assert timed_out.status == "failed"
    assert timed_out.error.category == "timeout"


def test_antigravity_provider_error_envelope():
    engine = FakeEngine(
        _outcome(stdout=_catalog_stdout("gemini-3.6-flash-medium")),
        _outcome(
            stdout=json.dumps(
                {
                    "status": "ERROR",
                    "response": "",
                    "error": "authentication required",
                }
            )
        ),
    )
    provider = AntigravityChatProvider(engine, IsolatedAgyAdapter())
    result = provider.execute(
        ProviderRequest(message="hello", model_id="gemini-3.6-flash-medium")
    )
    assert result.status == "failed"
    assert result.error.category == "authentication"


def test_local_only_research_is_blocked_without_fetch(tmp_path):
    engine = FakeEngine()
    store = PersonalAIStore(tmp_path / "ledger.db")
    orchestrator = ResearchOrchestrator(
        store=store,
        providers=ProviderRegistry(
            engine,
            adapters={
                "codex-cli": FakeAdapter("codex-cli"),
                "google-antigravity": FakeAdapter("google-antigravity"),
                "claude-code": FakeAdapter("claude-code"),
                "ollama": FakeAdapter("ollama"),
            },
            executable_finder=lambda _name: None,
        ),
        missions=MissionStore(tmp_path / "ledger.db"),
        engine=engine,
    )
    events = list(
        orchestrator.run(
            question="Should Medicare add an oral-health checkpoint?",
            conversation_id="conv-1",
            route_id="route-1",
            snapshots=[],
            local_only=True,
            timeout_seconds=30,
        )
    )
    assert events[-1]["step"] == "blocked"
    assert engine.calls == []
    assert store.list_research_missions()[0]["status"] == "blocked"


def test_models_payload_does_not_infer_explicit_effort_from_reasoning_capable_ids():
    payload = json.dumps(
        {
            "status": "SUCCESS",
            "command": {
                "name": "models",
                "data": {
                    "models": [
                        {"id": "claude-sonnet-4-6", "label": "Claude Sonnet 4.6"},
                        {"id": "gemini-3.6-flash-medium", "label": "Gemini 3.6 Flash (Medium)"},
                        {
                            "id": "gemini-3-pro",
                            "label": "Gemini 3 Pro",
                            "supportsEffort": True,
                            "effortLevels": ["low", "medium", "high"],
                        },
                    ]
                },
            },
        }
    )
    models, _limitations = parse_antigravity_models_payload(payload)
    by_id = {model.model_id: model for model in models}
    assert list(by_id) == [
        "claude-sonnet-4-6",
        "gemini-3.6-flash-medium",
        "gemini-3-pro",
    ]
    assert by_id["claude-sonnet-4-6"].reasoning_support is True
    assert by_id["claude-sonnet-4-6"].explicit_effort_supported is False
    assert by_id["gemini-3.6-flash-medium"].effort_levels == ["medium"]
    assert by_id["gemini-3.6-flash-medium"].explicit_effort_supported is False
    assert by_id["gemini-3-pro"].explicit_effort_supported is True
    assert by_id["gemini-3-pro"].effort_levels == ["low", "medium", "high"]


def test_resolve_print_effort_requires_model_evidence_not_global_help():
    assert (
        resolve_print_effort(
            "medium",
            model_id="claude-sonnet-4-6",
            explicit_effort_supported=False,
        )
        is None
    )
    assert (
        resolve_print_effort(
            "medium",
            model_id="gemini-3.6-flash-medium",
            explicit_effort_supported=True,
            effort_levels=["medium"],
        )
        is None
    )
    assert (
        resolve_print_effort(
            "medium",
            model_id="gemini-3-pro",
            explicit_effort_supported=True,
            effort_levels=["low", "medium", "high"],
        )
        == "medium"
    )
    assert (
        resolve_print_effort(
            "high",
            model_id="gemini-3-pro",
            explicit_effort_supported=True,
            effort_levels=["low", "medium"],
        )
        is None
    )


def test_print_adapter_omits_effort_unless_the_selected_model_accepts_it():
    unsupported = _AntigravityPrintAdapter(
        capabilities=_agy_caps(),
        model_id="claude-sonnet-4-6",
        effort="medium",
    ).build_command("hello")
    encoded = _AntigravityPrintAdapter(
        capabilities=_agy_caps(),
        model_id="gemini-3.6-flash-medium",
        effort="low",
        explicit_effort_supported=True,
        effort_levels=["low", "medium", "high"],
    ).build_command("hello")
    proven = _AntigravityPrintAdapter(
        capabilities=_agy_caps(),
        model_id="gemini-3-pro",
        effort="medium",
        explicit_effort_supported=True,
        effort_levels=["low", "medium", "high"],
    ).build_command("hello")
    research = _AntigravityPrintAdapter(
        capabilities=_agy_caps(),
        model_id="claude-sonnet-4-6",
        effort="medium",
        output_format="stream-json",
        research=True,
    ).build_command("hello")

    assert "--model" in unsupported
    assert unsupported[unsupported.index("--model") + 1] == "claude-sonnet-4-6"
    assert "--effort" not in unsupported
    assert encoded[encoded.index("--model") + 1] == "gemini-3.6-flash-medium"
    assert "--effort" not in encoded
    assert proven[proven.index("--model") + 1] == "gemini-3-pro"
    assert proven[proven.index("--effort") + 1] == "medium"
    assert research[research.index("--model") + 1] == "claude-sonnet-4-6"
    assert "--effort" not in research


def test_execute_and_research_print_omit_unsupported_effort_flags():
    engine = FakeEngine(
        _outcome(stdout=_catalog_stdout("claude-sonnet-4-6")),
        _outcome(stdout=_print_stdout("391")),
        _outcome(stdout=_print_stdout("research answer")),
        _outcome(
            stdout=_catalog_stdout_records(
                {
                    "id": "gemini-3-pro",
                    "label": "Gemini 3 Pro",
                    "supportsEffort": True,
                    "effortLevels": ["low", "medium", "high"],
                }
            )
        ),
        _outcome(stdout=_print_stdout("ok")),
        _outcome(stdout=_catalog_stdout("gemini-3.6-flash-medium")),
        _outcome(stdout=_print_stdout("ok")),
    )
    provider = AntigravityChatProvider(engine, IsolatedAgyAdapter())
    first = provider.execute(
        ProviderRequest(
            message="hello",
            model_id="claude-sonnet-4-6",
            metadata={"reasoning_effort": "medium"},
        )
    )
    assert first.status == "complete"
    assert "--effort" not in _print_argv(engine)

    research = provider.execute(
        ProviderRequest(
            message="hello",
            model_id="claude-sonnet-4-6",
            metadata={"research": True, "reasoning_effort": "medium"},
        )
    )
    assert research.status == "complete"
    research_argv = _print_argv(engine)
    assert "--effort" not in research_argv
    assert research_argv[research_argv.index("--model") + 1] == "claude-sonnet-4-6"

    proven = provider.execute(
        ProviderRequest(
            message="hello",
            model_id="gemini-3-pro",
            metadata={"reasoning_effort": "medium"},
        )
    )
    assert proven.status == "complete"
    proven_argv = _print_argv(engine)
    assert proven_argv[proven_argv.index("--effort") + 1] == "medium"
    assert proven_argv[proven_argv.index("--model") + 1] == "gemini-3-pro"

    encoded = provider.execute(
        ProviderRequest(
            message="hello",
            model_id="gemini-3.6-flash-medium",
            metadata={"reasoning_effort": "low"},
        )
    )
    assert encoded.status == "complete"
    encoded_argv = _print_argv(engine)
    assert encoded_argv[encoded_argv.index("--model") + 1] == "gemini-3.6-flash-medium"
    assert "--effort" not in encoded_argv


def test_https_fetch_command_is_bounded_and_https_only():
    from opencobalt.personal_ai.research import _HttpsGetAdapter

    command = _HttpsGetAdapter("https://www.cms.gov/").build_command("retrieve")
    assert command[0].endswith("curl") or command[0] == "curl"
    assert "--proto" in command and command[command.index("--proto") + 1] == "=https"
    assert "--compressed" in command
    assert "--max-filesize" in command
    assert command[command.index("--max-filesize") + 1] == "150000"
    assert "--dangerously-skip-permissions" not in command
    assert command[-1] == "https://www.cms.gov/"
    assert classify_source_type("https://pubmed.ncbi.nlm.nih.gov/?term=x") == "primary_literature"
    assert classify_source_type("https://www.cms.gov/medicare") == "government_policy"
    seeds = search_seed_urls("oral health screening older adults")
    assert "eutils.ncbi.nlm.nih.gov" in seeds[0]
    assert "esearch.fcgi" in seeds[0]
    assert "cms.gov" in seeds[1]
    assert "periodontal" not in "".join(seeds)
    assert looks_like_search_index(seeds[0])
    assert looks_like_search_index(seeds[1])
    assert not looks_like_search_index("https://pubmed.ncbi.nlm.nih.gov/12345678/")
    follow = followup_urls_from_payload(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&term=x",
        json.dumps({"esearchresult": {"idlist": ["12345678"]}}),
    )
    assert "https://pubmed.ncbi.nlm.nih.gov/12345678/" in follow
    assert any("efetch.fcgi" in item and "12345678" in item for item in follow)
    html_follow = followup_urls_from_payload(
        "https://www.cms.gov/search/cms?keys=medicare",
        '<html><a href="/medicare/coverage/dental">Dental</a>'
        '<a href="/themes/custom/print.css">css</a>'
        '<a href="https://evil.example/ads">ad</a></html>',
    )
    assert html_follow == ["https://www.cms.gov/medicare/coverage/dental"]
    pubmed_html = followup_urls_from_payload(
        "https://pubmed.ncbi.nlm.nih.gov/37934473/",
        '<a href="/account/settings/">account</a>'
        '<a href="https://www.ncbi.nlm.nih.gov/mesh/">mesh</a>'
        '<a href="https://www.ncbi.nlm.nih.gov/pmc/articles/PMC123/">pmc</a>',
    )
    assert pubmed_html == ["https://www.ncbi.nlm.nih.gov/pmc/articles/PMC123/"]
    excerpt = html_to_text(
        "<html><nav>Skip menu</nav><main><h1>Medicare Dental Coverage</h1>"
        "<p>Medicare Part B generally does not cover routine dental care.</p></main>"
        "<footer>email updates</footer></html>"
    )
    assert "Medicare Part B generally does not cover routine dental care." in excerpt
    assert "Skip menu" not in excerpt
    assert "email updates" not in excerpt

