"""HTTP contract tests for the local personal-AI control plane."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from opencobalt.api_server import app
from opencobalt.core.approval_bridge import ApprovalRequest, ApprovalStep
from opencobalt.personal_ai.api import _stream_ndjson
from opencobalt.personal_ai.models import ChatExecution, StreamEvent
from opencobalt.personal_ai.service import ChatLifecycleEvent, ChatRequest
from opencobalt.personal_ai.store import PersonalAIStore


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.chdir(tmp_path)
    with TestClient(app) as test_client:
        yield test_client


def _conversation(client: TestClient, title: str = "API conversation") -> dict:
    response = client.post(
        "/api/v1/conversations",
        json={"title": title, "project_path": None},
    )
    assert response.status_code == 201
    return response.json()


def _stream_mock_chat(
    client: TestClient,
    conversation_id: str,
    *,
    persona_id: str = "analytical",
) -> list[dict]:
    response = client.post(
        "/api/v1/chat/stream",
        json={
            "conversation_id": conversation_id,
            "message": "Explain the route in one sentence.",
            "persona_id": persona_id,
            "provider_override": "mock",
            "model_override": "mock-v1",
            "local_only": True,
        },
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    return [json.loads(line) for line in response.text.splitlines() if line]


def test_ndjson_disconnect_tracks_execution_before_execution_started() -> None:
    class FakeService:
        def __init__(self) -> None:
            self.abandoned = []

        def stream_request(self, _request):
            yield ChatLifecycleEvent(
                event_type="request_accepted",
                request_id="req-1",
                conversation_id="conv-1",
                route_id="route-1",
                execution_id="chatx-1",
                sequence=1,
            )

        def abandon(self, execution_id):
            self.abandoned.append(execution_id)
            return True

    service = FakeService()
    stream = _stream_ndjson(service, object())
    assert "request_accepted" in next(stream)

    stream.close()

    assert service.abandoned == ["chatx-1"]


def test_ndjson_disconnect_does_not_abandon_live_pending_approval() -> None:
    class FakeService:
        def __init__(self) -> None:
            self.abandoned = []

        def stream_request(self, _request):
            yield ChatLifecycleEvent(
                event_type="approval_required",
                request_id="req-1",
                conversation_id="conv-1",
                route_id="route-1",
                execution_id="chatx-1",
                sequence=1,
                payload={"approval": {"request_id": "areq-1", "state": "pending"}},
            )

        def has_live_pending_approval(self, execution_id):
            return execution_id == "chatx-1"

        def abandon(self, execution_id):
            self.abandoned.append(execution_id)
            return True

    service = FakeService()
    stream = _stream_ndjson(service, object())
    assert "approval_required" in next(stream)
    stream.close()
    assert service.abandoned == []


def test_context_is_keyed_by_resolved_ledger_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()

    with TestClient(app) as client:
        monkeypatch.chdir(first)
        created = _conversation(client, "First workspace")

        monkeypatch.chdir(second)
        assert client.get("/api/v1/conversations").json() == []

        monkeypatch.chdir(first)
        conversations = client.get("/api/v1/conversations").json()

    assert [item["conversation_id"] for item in conversations] == [created["conversation_id"]]


def test_api_context_does_not_reuse_deleted_or_recreated_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import shutil

    from opencobalt.personal_ai.api import _CONTEXTS, _api_context

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.chdir(workspace)
    original = _api_context()
    original.store.create_conversation(title="Original workspace")
    original_key = original.db_path
    assert original_key.parent.is_dir()

    monkeypatch.chdir(tmp_path)
    shutil.rmtree(workspace)
    assert original_key not in _CONTEXTS or not original_key.parent.is_dir()

    replacement = tmp_path / "workspace"
    replacement.mkdir()
    monkeypatch.chdir(replacement)
    refreshed = _api_context()

    assert refreshed is not original
    conversations = refreshed.store.list_conversations()
    assert conversations == []
    refreshed.store.create_conversation(title="Replacement workspace")
    assert [item.title for item in refreshed.store.list_conversations()] == [
        "Replacement workspace"
    ]


def test_conversation_project_path_is_canonical_and_rejects_traversal(
    client: TestClient,
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    inside = client.post(
        "/api/v1/conversations",
        json={"title": "Bounded", "project_path": "project"},
    )
    assert inside.status_code == 201
    assert inside.json()["project_path"] == str(project.resolve())

    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    attached = client.post(
        "/api/v1/conversations",
        json={"title": "Attached", "project_path": str(outside)},
    )
    assert attached.status_code == 201
    assert attached.json()["project_path"] == str(outside.resolve())

    escaped = client.post(
        "/api/v1/conversations",
        json={"title": "Escaped", "project_path": "../nope"},
    )
    assert escaped.status_code == 422


def test_attachment_upload_list_and_delete(client: TestClient) -> None:
    conversation = _conversation(client, "With docs")
    conversation_id = conversation["conversation_id"]
    uploaded = client.post(
        f"/api/v1/conversations/{conversation_id}/attachments",
        files={"file": ("notes.md", b"# Memo\nScreening evidence from the user.", "text/markdown")},
    )
    assert uploaded.status_code == 201
    body = uploaded.json()
    assert body["original_filename"] == "notes.md"
    assert body["ingestion_status"] == "extracted"
    listed = client.get(f"/api/v1/conversations/{conversation_id}/attachments")
    assert listed.status_code == 200
    assert listed.json()["attachments"][0]["attachment_id"] == body["attachment_id"]
    rejected = client.post(
        f"/api/v1/conversations/{conversation_id}/attachments",
        files={"file": ("payload.exe", b"MZ", "application/octet-stream")},
    )
    assert rejected.status_code == 422
    deleted = client.delete(
        f"/api/v1/conversations/{conversation_id}/attachments/{body['attachment_id']}"
    )
    assert deleted.status_code == 200
    empty = client.get(f"/api/v1/conversations/{conversation_id}/attachments")
    assert empty.json()["attachments"] == []


def test_research_source_exclude(client: TestClient, tmp_path: Path) -> None:
    store = PersonalAIStore(tmp_path / ".opencobalt" / "ledger.db")
    now = datetime.now(timezone.utc).isoformat()
    store.save_research_mission(
        {
            "research_id": "res-1",
            "mission_id": "mis-1",
            "conversation_id": None,
            "route_id": None,
            "question": "Medicare oral health screening evidence",
            "status": "complete",
            "synthesis": "placeholder",
            "limitations": [],
            "model_roles": {},
            "created_at": now,
            "updated_at": now,
            "metadata": {},
        }
    )
    store.save_research_source(
        {
            "source_id": "src-1",
            "research_id": "res-1",
            "url": "https://www.cms.gov/medicare",
            "title": "CMS Medicare",
            "source_type": "government_policy",
            "retrieval_status": "retrieved",
            "excerpt": "Medicare covers limited oral services.",
            "created_at": now,
            "canonical_url": "https://www.cms.gov/medicare",
            "quality_score": 0.8,
        }
    )
    excluded = client.post("/api/v1/research/res-1/sources/src-1/exclude")
    assert excluded.status_code == 200
    assert excluded.json()["excluded"] is True
    bundle = client.get("/api/v1/research/res-1")
    assert bundle.status_code == 200
    assert bundle.json()["sources"][0]["excluded"] is True


def test_mock_stream_persists_messages_route_execution_and_redacted_receipt(
    client: TestClient,
) -> None:
    conversation = _conversation(client)
    events = _stream_mock_chat(client, conversation["conversation_id"])

    event_types = [event["event_type"] for event in events]
    assert event_types[:3] == [
        "request_accepted",
        "route_selected",
        "execution_started",
    ]
    assert event_types[-1] == "completed"
    assert [event["sequence"] for event in events] == list(range(1, len(events) + 1))

    route_id = events[-1]["route_id"]
    route_detail = client.get(f"/api/v1/routes/{route_id}")
    assert route_detail.status_code == 200
    detail = route_detail.json()
    assert detail["route"]["selected_provider"] == "mock"
    assert detail["actual_provider"] == "mock"
    assert detail["selected_model"] == "mock-v1"
    assert detail["actual_model"] == "mock-v1"
    assert detail["route"]["requested_persona_id"] == "analytical"
    assert detail["route"]["actual_persona_id"] == "analytical"
    assert detail["candidates"]
    assert detail["executions"][0]["status"] == "complete"
    assert detail["verification"]["status"] == "passed"

    messages = client.get(
        f"/api/v1/conversations/{conversation['conversation_id']}/messages"
    ).json()
    assert [message["role"] for message in messages] == ["user", "assistant"]
    assert messages[-1]["content"] == "Mock response: Explain the route in one sentence."

    receipts = client.get("/api/v1/ledger/receipts").json()
    chat_receipt = next(item for item in receipts if item["selected_runtime"] == "noop")
    assert chat_receipt["verification_status"] == "verified"
    assert "task" not in chat_receipt
    assert "command_plan" not in chat_receipt

    # A fresh store instance sees the persisted history, as it would after restart.
    restarted_store = PersonalAIStore(Path(".opencobalt/ledger.db"))
    assert len(restarted_store.list_messages(conversation["conversation_id"])) == 2
    assert restarted_store.get_route(route_id) is not None


def test_route_detail_exposes_durable_associated_redacted_stream_history(
    client: TestClient,
) -> None:
    from opencobalt.personal_ai.api import _api_context

    conversation = _conversation(client, "Stream history")
    lifecycle = _stream_mock_chat(client, conversation["conversation_id"])
    route_id = lifecycle[-1]["route_id"]
    route = _api_context().store.get_route(route_id)
    assert route is not None

    earlier_execution = ChatExecution(
        request_id=route.request_id,
        route_id=route.route_id,
        conversation_id=route.conversation_id,
        provider_id="mock",
        model_id="mock-v1",
        status="failed",
        created_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
    )
    _api_context().store.save_execution(earlier_execution)
    secret_delta = f"private {Path.home()}/notes API_KEY=secret-stream-value"
    injected = [
        StreamEvent(
            execution_id=earlier_execution.execution_id,
            sequence=1,
            event_type="text_delta",
            payload={"text_delta": secret_delta},
            created_at=datetime(2020, 1, 1, 0, 0, 1, tzinfo=timezone.utc),
        ),
        StreamEvent(
            execution_id=earlier_execution.execution_id,
            sequence=2,
            event_type="completed",
            payload={
                "message": {"content": secret_delta, "message_id": "msg-sensitive"},
                "route": {"route_id": route.route_id},
                "receipt_id": "receipt-safe-id",
            },
            created_at=datetime(2020, 1, 1, 0, 0, 2, tzinfo=timezone.utc),
        ),
        StreamEvent(
            execution_id=earlier_execution.execution_id,
            sequence=3,
            event_type="tool_completed",
            payload={
                "tool_event": {
                    "tool_call_id": "tool-call-safe",
                    "tool_name": "file-reader",
                    "status": "complete",
                    "summary": "sensitive patient diagnosis",
                }
            },
            created_at=datetime(2020, 1, 1, 0, 0, 3, tzinfo=timezone.utc),
        ),
    ]
    for event in injected:
        _api_context().store.append_stream_event(event)

    other = _conversation(client, "Other route")
    other_lifecycle = _stream_mock_chat(client, other["conversation_id"])
    other_execution_ids = {
        item["execution_id"]
        for item in client.get(f"/api/v1/routes/{other_lifecycle[-1]['route_id']}").json()[
            "executions"
        ]
    }
    wrong_route_execution = ChatExecution(
        request_id=route.request_id,
        route_id=other_lifecycle[-1]["route_id"],
        conversation_id=other["conversation_id"],
        provider_id="mock",
        model_id="mock-v1",
        status="failed",
        created_at=datetime(2020, 1, 2, tzinfo=timezone.utc),
        updated_at=datetime(2020, 1, 2, tzinfo=timezone.utc),
    )
    _api_context().store.save_execution(wrong_route_execution)
    wrong_route_event = StreamEvent(
        execution_id=wrong_route_execution.execution_id,
        sequence=1,
        event_type="text_delta",
        payload={"text_delta": "wrong-route-sensitive-content"},
        created_at=datetime(2020, 1, 2, 0, 0, 1, tzinfo=timezone.utc),
    )
    _api_context().store.append_stream_event(wrong_route_event)
    other_execution_ids.add(wrong_route_execution.execution_id)

    detail = client.get(f"/api/v1/routes/{route_id}").json()
    assert detail["request_message"]["content"] == "Explain the route in one sentence."
    history = detail["stream_events"]
    route_execution_ids = {item["execution_id"] for item in detail["executions"]}

    assert [item["event_id"] for item in history[:2]] == [
        injected[0].event_id,
        injected[1].event_id,
    ]
    assert [item["created_at"] for item in history] == sorted(
        item["created_at"] for item in history
    )
    assert {item["execution_id"] for item in history} <= route_execution_ids
    assert wrong_route_execution.execution_id not in route_execution_ids
    assert not ({item["execution_id"] for item in history} & other_execution_ids)
    assert history[0]["payload"] == {
        "content_redacted": True,
        "text_characters": len(secret_delta),
    }
    assert history[1]["payload"] == {
        "message_id": "msg-sensitive",
        "receipt_id": "receipt-safe-id",
        "route_id": route.route_id,
    }
    assert history[2]["payload"] == {
        "tool_event": {
            "status": "complete",
            "summary_characters": len("sensitive patient diagnosis"),
            "summary_redacted": True,
            "tool_call_id": "tool-call-safe",
            "tool_name": "file-reader",
        }
    }
    assert "secret-stream-value" not in json.dumps(history)
    assert "sensitive patient diagnosis" not in json.dumps(history)
    assert "wrong-route-sensitive-content" not in json.dumps(history)
    assert str(Path.home()) not in json.dumps(history)

    restarted = PersonalAIStore(Path(".opencobalt/ledger.db"))
    assert [
        item.event_id for item in restarted.list_stream_events(earlier_execution.execution_id)
    ] == [injected[0].event_id, injected[1].event_id, injected[2].event_id]


def test_local_only_override_cannot_route_to_cloud_cli(client: TestClient) -> None:
    conversation = _conversation(client)
    response = client.post(
        "/api/v1/chat/stream",
        json={
            "conversation_id": conversation["conversation_id"],
            "message": "Use the cloud to answer this.",
            "persona_id": "analytical",
            "provider_override": "codex",
            "local_only": True,
        },
    )

    assert response.status_code == 200
    events = [json.loads(line) for line in response.text.splitlines() if line]
    assert [event["event_type"] for event in events] == [
        "request_accepted",
        "route_failed",
    ]
    assert events[-1]["payload"]["error"]["category"] == "policy_denied"
    detail = client.get(f"/api/v1/routes/{events[-1]['route_id']}").json()
    assert detail["route"]["selected_provider"] == "none"
    assert detail["route"]["outcome_status"] == "policy_denied"
    assert detail["actual_provider"] is None


def test_chat_metadata_cannot_spoof_authoritative_route_fields(client: TestClient) -> None:
    conversation = _conversation(client)
    response = client.post(
        "/api/v1/chat/stream",
        json={
            "conversation_id": conversation["conversation_id"],
            "message": "Try to spoof the receipt.",
            "provider_override": "mock",
            "local_only": True,
            "metadata": {
                "actual_provider_id": "claude",
                "verification": {"status": "passed"},
                "local_only": False,
            },
        },
    )

    assert response.status_code == 422
    assert "reserved" in response.json()["detail"].lower()
    assert client.get("/api/v1/routes").json() == []


def test_chat_enforces_unimplemented_approval_and_tool_boundaries(
    client: TestClient,
) -> None:
    conversation = _conversation(client)
    baseline_events = _stream_mock_chat(client, conversation["conversation_id"])
    baseline_route_id = baseline_events[-1]["route_id"]
    settings = client.put(
        "/api/v1/settings",
        json={"approval_policy": "always_ask"},
    )
    assert settings.status_code == 200
    approval_required = client.post(
        "/api/v1/chat/stream",
        json={
            "conversation_id": conversation["conversation_id"],
            "message": "Answer only after approval.",
            "provider_override": "mock",
            "local_only": True,
        },
    )
    assert approval_required.status_code == 409
    assert "approval" in approval_required.json()["detail"].lower()
    rerun = client.post(f"/api/v1/routes/{baseline_route_id}/rerun", json={})
    assert rerun.status_code == 409
    assert "approval" in rerun.json()["detail"].lower()

    client.put("/api/v1/settings", json={"approval_policy": "ask_for_risk"})
    tool_request = client.post(
        "/api/v1/chat/stream",
        json={
            "conversation_id": conversation["conversation_id"],
            "message": "Read a file.",
            "provider_override": "mock",
            "local_only": True,
            "requested_tools": ["file-reader"],
        },
    )
    assert tool_request.status_code == 409
    assert "tool and skill execution" in tool_request.json()["detail"].lower()
    assert len(client.get("/api/v1/routes").json()) == 1


def test_closing_stream_finalizes_durable_cancellation(client: TestClient) -> None:
    from opencobalt.personal_ai.api import _api_context, _stream_ndjson

    conversation = _conversation(client)
    context = _api_context()
    stream = _stream_ndjson(
        context.service,
        ChatRequest(
            conversation_id=conversation["conversation_id"],
            message="Stop before provider execution.",
            provider_override="mock",
            model_override="mock-v1",
            local_only=True,
        ),
    )

    first = json.loads(next(stream))
    second = json.loads(next(stream))
    started = json.loads(next(stream))
    assert [first["event_type"], second["event_type"], started["event_type"]] == [
        "request_accepted",
        "route_selected",
        "execution_started",
    ]
    stream.close()

    execution = context.store.get_execution(started["execution_id"])
    assert execution is not None
    assert execution.status == "cancelled"
    route = context.store.get_route(started["route_id"])
    assert route is not None and route.outcome_status == "cancelled"
    messages = context.store.list_messages(conversation["conversation_id"])
    assert messages[-1].status == "cancelled"
    confirmed = client.post(f"/api/v1/executions/{execution.execution_id}/cancel")
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "cancelled"


def test_cancel_request_then_stream_close_preserves_user_intent(client: TestClient) -> None:
    from opencobalt.personal_ai.api import _api_context, _stream_ndjson

    conversation = _conversation(client)
    context = _api_context()
    stream = _stream_ndjson(
        context.service,
        ChatRequest(
            conversation_id=conversation["conversation_id"],
            message="Stop this request explicitly.",
            provider_override="mock",
            model_override="mock-v1",
            local_only=True,
        ),
    )
    started = None
    for _ in range(3):
        event = json.loads(next(stream))
        started = event if event["event_type"] == "execution_started" else started
    assert started is not None

    requested = client.post(f"/api/v1/executions/{started['execution_id']}/cancel")
    assert requested.status_code == 200
    assert requested.json()["status"] == "cancel_requested"
    stream.close()

    execution = context.store.get_execution(started["execution_id"])
    assert execution is not None and execution.status == "cancelled"
    events = context.store.list_stream_events(execution.execution_id)
    assert events[-1].event_type == "cancelled"
    assert events[-1].payload["reason"] == "user_requested"
    confirmed = client.post(f"/api/v1/executions/{execution.execution_id}/cancel")
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "cancelled"


def test_route_rerun_returns_new_inspectable_route(client: TestClient) -> None:
    conversation = _conversation(client)
    original_events = _stream_mock_chat(client, conversation["conversation_id"])
    original_route_id = original_events[-1]["route_id"]

    response = client.post(
        f"/api/v1/routes/{original_route_id}/rerun",
        json={
            "persona_id": "reflective",
            "provider_id": "mock",
            "model_id": "mock-v1",
            "reasoning_effort": "high",
            "local_only": True,
        },
    )

    assert response.status_code == 200
    rerun = response.json()
    assert rerun["status"] == "complete"
    assert rerun["route_id"] != original_route_id
    detail = client.get(f"/api/v1/routes/{rerun['route_id']}").json()
    assert detail["route"]["requested_persona_id"] == "reflective"
    assert detail["route"]["selected_provider"] == "mock"
    assert detail["route"]["metadata"]["rerun_of_route_id"] == original_route_id


def test_rerun_with_another_provider_does_not_inherit_the_old_model(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opencobalt.personal_ai.api import _api_context

    conversation = _conversation(client)
    original_events = _stream_mock_chat(client, conversation["conversation_id"])
    original_route_id = original_events[-1]["route_id"]
    captured: list[ChatRequest] = []

    def capture(request: ChatRequest):
        captured.append(request)
        return iter(())

    context = _api_context()
    monkeypatch.setattr(context.service, "stream_request", capture)

    list(context.service.rerun(original_route_id, provider_id="codex"))

    assert captured[0].provider_override == "codex"
    assert captured[0].model_override is None


def test_completed_assistant_messages_can_be_compared_with_routes(
    client: TestClient,
) -> None:
    conversation = _conversation(client)
    _stream_mock_chat(client, conversation["conversation_id"], persona_id="analytical")
    _stream_mock_chat(client, conversation["conversation_id"], persona_id="reflective")
    assistant_messages = [
        message
        for message in client.get(
            f"/api/v1/conversations/{conversation['conversation_id']}/messages"
        ).json()
        if message["role"] == "assistant"
    ]

    response = client.post(
        "/api/v1/messages/compare",
        json={
            "first_message_id": assistant_messages[0]["message_id"],
            "second_message_id": assistant_messages[1]["message_id"],
        },
    )

    assert response.status_code == 200
    compared = response.json()["responses"]
    assert [item["message"]["message_id"] for item in compared] == [
        assistant_messages[0]["message_id"],
        assistant_messages[1]["message_id"],
    ]
    assert all(item["route"]["route_id"] == item["message"]["route_id"] for item in compared)


def test_route_can_be_promoted_to_a_planning_only_mission(client: TestClient) -> None:
    conversation = _conversation(client)
    events = _stream_mock_chat(client, conversation["conversation_id"])
    route_id = events[-1]["route_id"]

    response = client.post(f"/api/v1/routes/{route_id}/promote")

    assert response.status_code == 201
    promoted = response.json()
    assert promoted["mission"]["goal"] == "Explain the route in one sentence."
    assert promoted["mission"]["status"] == "plan_proposed"
    assert promoted["mission"]["last_receipt_id"]
    assert promoted["steps"][0]["approval_state"] == "pending"
    assert promoted["steps"][0]["execution_state"] == "not_started"
    assert promoted["steps"][0]["uses_execution_engine"] is False
    assert promoted["steps"][0]["requires_approval"] is False

    missions = client.get("/api/v1/missions").json()
    assert missions[0]["mission_id"] == promoted["mission"]["mission_id"]
    assert missions[0]["route_id"] == route_id
    assert missions[0]["conversation_id"] == conversation["conversation_id"]
    assert missions[0]["steps"][0]["step_id"] == promoted["steps"][0]["step_id"]


def test_persona_editor_versions_custom_profiles_and_resets_builtins(
    client: TestClient,
) -> None:
    personas = client.get("/api/v1/personas")
    assert personas.status_code == 200
    analytical = next(item for item in personas.json() if item["persona_id"] == "analytical")
    assert analytical["active_version"]["version"] == 1

    duplicated = client.post(
        "/api/v1/personas/analytical/duplicate",
        json={"name": "Analytical Custom"},
    )
    assert duplicated.status_code == 201
    custom_id = duplicated.json()["persona_id"]

    updated = client.patch(
        f"/api/v1/personas/{custom_id}",
        json={
            "name": "Analytical Concise",
            "controls": {"verbosity": "low", "warmth": "high"},
            "provider_affinities": {"mock": 3},
            "custom_instructions": "Lead with the decision.",
            "allowed_cognitive_policies": ["fast_answer", "decision_support"],
        },
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Analytical Concise"
    assert updated.json()["active_version"]["version"] == 2
    assert updated.json()["active_version"]["controls"]["verbosity"] == "low"
    assert updated.json()["active_version"]["controls"]["directness"] == "very_high"

    tested = client.post(
        f"/api/v1/personas/{custom_id}/test",
        json={"prompt": "Make a decision", "cognitive_policy": "decision_support"},
    )
    assert tested.status_code == 200
    assert tested.json()["executed"] is False
    assert "Lead with the decision." in tested.json()["rendered_policy"]

    reset = client.post("/api/v1/personas/analytical/reset")
    assert reset.status_code == 200
    assert reset.json()["active_version"]["version"] == 2
    assert reset.json()["active_version"]["controls"] == analytical["active_version"]["controls"]


def test_provider_memory_settings_and_missing_resource_contracts(
    client: TestClient,
) -> None:
    providers = client.get("/api/v1/providers")
    assert providers.status_code == 200
    mock = next(item for item in providers.json() if item["provider_id"] == "mock")
    assert mock["health"] == "ready"
    health = client.post("/api/v1/providers/mock/health")
    assert health.status_code == 200
    assert health.json()["successful_invocation_proven"] is False
    models = client.get("/api/v1/providers/mock/models")
    assert models.status_code == 200
    assert models.json()["models"][0]["model_id"] == "mock-v1"
    preference = client.get("/api/v1/providers/mock/preference")
    assert preference.status_code == 200
    assert preference.json() == {
        "provider_id": "mock",
        "enabled": True,
        "priority": 50,
        "cost_policy": "prefer_subscription",
    }
    updated_preference = client.patch(
        "/api/v1/providers/mock/preference",
        json={"enabled": False, "priority": 80, "cost_policy": "free_only"},
    )
    assert updated_preference.status_code == 200
    assert updated_preference.json()["enabled"] is False
    assert updated_preference.json()["priority"] == 80
    assert (
        PersonalAIStore(Path(".opencobalt/ledger.db")).list_provider_preferences()[0].cost_policy
        == "free_only"
    )

    created = client.post(
        "/api/v1/memory",
        json={
            "content": "Prefer terse validation receipts.",
            "source_type": "explicit_user_save",
            "reason": "The user explicitly asked to remember it.",
            "scope": "user",
            "status": "active",
            "pinned": True,
        },
    )
    assert created.status_code == 201
    memory_id = created.json()["memory_id"]
    updated = client.patch(
        f"/api/v1/memory/{memory_id}",
        json={"content": "Prefer concise validation receipts.", "pinned": False},
    )
    assert updated.status_code == 200
    assert updated.json()["content"] == "Prefer concise validation receipts."
    assert client.get("/api/v1/memory").json()[0]["pinned"] is False
    assert client.delete(f"/api/v1/memory/{memory_id}").status_code == 204
    assert client.get(f"/api/v1/memory/{memory_id}").status_code == 404

    settings = client.put(
        "/api/v1/settings",
        json={"default_persona_id": "builder", "theme": "dark"},
    )
    assert settings.status_code == 200
    assert settings.json()["default_persona_id"] == "builder"
    assert settings.json()["theme"] == "dark"
    assert settings.json()["approval_policy"] == "ask_for_risk"

    assert client.get("/api/v1/conversations/missing/messages").status_code == 404
    assert client.get("/api/v1/routes/missing").status_code == 404
    assert client.post("/api/v1/executions/missing/cancel").status_code == 404
    assert client.get("/api/v1/providers/missing/models").status_code == 404


def test_local_skill_import_is_inspected_pinned_disabled_and_receipted(
    client: TestClient,
    tmp_path: Path,
) -> None:
    source = tmp_path / "safe-skill"
    source.mkdir()
    (source / "skill.json").write_text(
        json.dumps(
            {
                "name": "safe-notes",
                "version": "1.0.0",
                "description": "Read-only procedural notes.",
                "permissions": [],
                "compatibility": {"opencobalt": ">=0.1"},
            }
        ),
        encoding="utf-8",
    )
    (source / "SKILL.md").write_text("# Safe notes\n", encoding="utf-8")

    preview = client.post(
        "/api/v1/skills/import/preview",
        json={"source_path": str(source)},
    )
    assert preview.status_code == 200
    assert preview.json()["requires_approval"] is False
    install = client.post(
        "/api/v1/skills/import/install",
        json={"preview_id": preview.json()["preview_id"]},
    )
    assert install.status_code == 201
    installed = install.json()
    assert installed["skill"]["enabled"] is False
    assert installed["version"]["content_hash"] == preview.json()["content_hash"]
    assert installed["receipt_id"]

    skills = client.get("/api/v1/skills").json()
    imported = next(item for item in skills if item.get("name") == "safe-notes")
    assert imported["source_kind"] == "imported"
    assert imported["versions"][0]["content_hash"] == preview.json()["content_hash"]
    detail = client.get(f"/api/v1/skills/{imported['skill_id']}")
    assert detail.status_code == 200
    assert detail.json()["versions"][0]["installed"] is True
    assert "install_path" not in detail.json()["versions"][0]
    activated = client.patch(
        f"/api/v1/skills/{imported['skill_id']}",
        json={"enabled": True},
    )
    assert activated.status_code == 200
    assert activated.json()["enabled"] is True
    assert client.get("/api/v1/skills/discovery").json()["available"] is False
    assert client.get("/api/v1/missions").json() == []


def test_skill_import_with_executable_content_requires_explicit_approval(
    client: TestClient,
    tmp_path: Path,
) -> None:
    source = tmp_path / "risky-skill"
    source.mkdir()
    (source / "skill.json").write_text(
        json.dumps(
            {
                "name": "bounded-runner",
                "version": "1.0.0",
                "description": "Contains executable content for inspection.",
                "permissions": ["shell"],
            }
        ),
        encoding="utf-8",
    )
    (source / "runner.py").write_text("print('never executed during import')\n", encoding="utf-8")

    preview = client.post(
        "/api/v1/skills/import/preview",
        json={"source_path": str(source)},
    ).json()
    assert preview["requires_approval"] is True
    assert preview["approval_request_id"]
    denied = client.post(
        "/api/v1/skills/import/install",
        json={"preview_id": preview["preview_id"]},
    )
    assert denied.status_code == 409

    approved = client.post(
        f"/api/v1/skills/approvals/{preview['approval_request_id']}/approve",
        json={"reason": "Inspected locally and approved for disabled installation."},
    )
    assert approved.status_code == 200
    install = client.post(
        "/api/v1/skills/import/install",
        json={
            "preview_id": preview["preview_id"],
            "approval_request_id": preview["approval_request_id"],
        },
    )
    assert install.status_code == 201
    assert install.json()["skill"]["enabled"] is False


def test_skill_approval_endpoint_rejects_unrelated_approval_requests(
    client: TestClient,
) -> None:
    from opencobalt.personal_ai.api import _api_context

    context = _api_context()
    request_id = "areq-unrelated"
    step_id = "astp-unrelated"
    context.skill_import.approval_bridge.store.save_request(
        ApprovalRequest(
            request_id=request_id,
            source_type="auto_route",
            source_id="mission-unrelated",
            run_id="mission-unrelated",
            goal_id="plan-unrelated",
            track_id="mission-unrelated",
            opportunity_plan_id="plan-unrelated",
            steps=[
                ApprovalStep(
                    step_id=step_id,
                    request_id=request_id,
                    source_type="auto_route",
                    source_id="mission-unrelated",
                    task="An unrelated action",
                    risk_level="yellow",
                    approval_required=True,
                    approval_state="pending",
                )
            ],
        )
    )

    response = client.post(
        f"/api/v1/skills/approvals/{request_id}/approve",
        json={"reason": "This route must not cross approval domains."},
    )

    assert response.status_code == 409
    stored = context.skill_import.approval_bridge.store.get_request(request_id)
    assert stored is not None
    assert stored.steps[0].approval_state == "pending"


def test_validation_errors_are_typed_and_do_not_create_records(client: TestClient) -> None:
    invalid = client.post(
        "/api/v1/conversations",
        json={"title": "   ", "project_path": None},
    )
    assert invalid.status_code == 422
    assert client.get("/api/v1/conversations").json() == []

    unknown_conversation = client.post(
        "/api/v1/chat/stream",
        json={"conversation_id": "missing", "message": "hello"},
    )
    assert unknown_conversation.status_code == 404


def test_explicit_data_export_is_in_memory_and_documents_retention_limits(
    client: TestClient,
) -> None:
    conversation = _conversation(client, "Exported conversation")
    _stream_mock_chat(client, conversation["conversation_id"])

    response = client.get("/api/v1/data/export")

    assert response.status_code == 200
    exported = response.json()
    assert exported["schema_version"] == 1
    assert exported["conversations"][0]["title"] == "Exported conversation"
    assert len(exported["messages"]) == 2
    assert exported["routes"][0]["selected_provider"] == "mock"
    assert exported["receipts"]
    assert all("task" not in receipt for receipt in exported["receipts"])
    assert all("command_plan" not in receipt for receipt in exported["receipts"])
    assert not (Path(".opencobalt") / "export.json").exists()

    retention = client.get("/api/v1/data/retention").json()
    assert retention["bulk_deletion_available"] is False
    assert retention["conversation_deletion_available"] is False
    assert retention["memory_deletion_endpoint"] == "/api/v1/memory/{memory_id}"
    assert "receipts" in retention["reason"].lower()


def test_route_and_export_redact_execution_error_paths_and_secrets(
    client: TestClient,
) -> None:
    from opencobalt.personal_ai.api import _api_context

    conversation = _conversation(client)
    events = _stream_mock_chat(client, conversation["conversation_id"])
    route_id = events[-1]["route_id"]
    route = _api_context().store.get_route(route_id)
    assert route is not None
    leaked = ChatExecution(
        request_id=route.request_id,
        route_id=route.route_id,
        conversation_id=route.conversation_id,
        provider_id="mock",
        status="failed",
        provider_error_type="provider_error",
        provider_error_message=(f"cwd {Path.home()}/private/repo API_KEY=secret-value-123"),
    )
    _api_context().store.save_execution(leaked)

    detail = client.get(f"/api/v1/routes/{route_id}").json()
    detail_error = detail["executions"][0]["provider_error_message"]
    assert str(Path.home()) not in detail_error
    assert "secret-value-123" not in detail_error
    assert "<home>" in detail_error
    assert "<redacted>" in detail_error

    exported = client.get("/api/v1/data/export").json()
    export_error = next(
        item["provider_error_message"]
        for item in exported["executions"]
        if item["execution_id"] == leaked.execution_id
    )
    assert export_error == detail_error
