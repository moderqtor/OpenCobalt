"""First-turn draft controls, repository attach, and attachment promotion.

Mimics ChatPage.ensureConversation then send: POST a new conversation from
Settings defaults, PATCH the visible draft routing onto that row, then stream
with those same controls. Previous conversations are not copied into the draft.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from opencobalt.api_server import app
from opencobalt.personal_ai.models import ProviderPreference
from opencobalt.personal_ai.store import PersonalAIStore


def _client(tmp_path: Path, monkeypatch) -> TestClient:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENCOBALT_ENABLE_DEVELOPMENT_MOCK", "1")
    store = PersonalAIStore(tmp_path / ".opencobalt" / "ledger.db")
    for provider_id in ("antigravity", "claude", "codex", "cursor", "gemini", "ollama"):
        store.save_provider_preference(
            ProviderPreference(provider_id=provider_id, enabled=False)
        )
    return TestClient(app)


def _routing_patch(controls: dict) -> dict:
    return {
        "mode": "automatic" if controls.get("automatic", True) else "manual",
        "provider_id": controls.get("provider_id"),
        "model_id": controls.get("model_id"),
        "reasoning_effort": controls.get("reasoning_effort", "medium"),
        "allow_fallback": bool(controls.get("allow_fallback")),
        "privacy_mode": controls.get("privacy_mode", "standard"),
        "local_only": bool(controls.get("local_only")),
        "write_seq": 1,
    }


def _stream_payload(conversation_id: str, message: str, controls: dict) -> dict:
    payload = {
        "conversation_id": conversation_id,
        "message": message,
        "persona_id": controls.get("persona_id", "analytical"),
        "cognitive_policy": controls.get("cognitive_policy", "deep_analysis"),
        "reasoning_effort": controls.get("reasoning_effort", "medium"),
        "privacy_mode": controls.get("privacy_mode", "standard"),
        "local_only": bool(controls.get("local_only")),
        "allow_fallback": bool(controls.get("allow_fallback")),
    }
    if not controls.get("automatic", True):
        payload["provider_override"] = controls.get("provider_id")
        if controls.get("model_id"):
            payload["model_override"] = controls["model_id"]
    return payload


def _promote_draft(
    client: TestClient,
    *,
    controls: dict,
    message: str = "Explain DNS caching in one sentence.",
    project_path: str | None = None,
    attach: tuple[str, bytes, str] | None = None,
):
    payload: dict = {"title": "New conversation"}
    if project_path is not None:
        payload["project_path"] = project_path
    created = client.post("/api/v1/conversations", json=payload)
    if created.status_code != 201:
        return created, None, None
    conversation_id = created.json()["conversation_id"]
    patched = client.patch(
        f"/api/v1/conversations/{conversation_id}/routing",
        json=_routing_patch(controls),
    )
    assert patched.status_code == 200, patched.text
    if attach is not None:
        uploaded = client.post(
            f"/api/v1/conversations/{conversation_id}/attachments",
            files={"file": attach},
        )
        assert uploaded.status_code == 201, uploaded.text
    streamed = client.post(
        "/api/v1/chat/stream",
        json=_stream_payload(conversation_id, message, controls),
    )
    return created, patched, streamed


def _events(response) -> list[dict]:
    return [json.loads(line) for line in response.text.splitlines() if line]


def _route_detail(client: TestClient, streamed) -> dict:
    events = _events(streamed)
    route_id = next(
        (event.get("route_id") for event in reversed(events) if event.get("route_id")),
        None,
    )
    assert route_id, events[-1] if events else streamed.text
    detail = client.get(f"/api/v1/routes/{route_id}")
    assert detail.status_code == 200, detail.text
    return detail.json()


def _stored_routing(client: TestClient, conversation_id: str) -> dict:
    routing = client.get(f"/api/v1/conversations/{conversation_id}/routing")
    stored = client.get(f"/api/v1/conversations/{conversation_id}")
    assert routing.status_code == 200
    assert stored.status_code == 200
    return routing.json(), stored.json()["metadata"]["routing"]


def test_draft_manual_provider_model_first_send_persists_and_executes(tmp_path, monkeypatch):
    controls = {
        "automatic": False,
        "provider_id": "mock",
        "model_id": "mock-v1",
        "allow_fallback": True,
    }
    with _client(tmp_path, monkeypatch) as client:
        created, patched, streamed = _promote_draft(client, controls=controls)
        assert created.status_code == 201
        assert streamed.status_code == 200
        conversation_id = created.json()["conversation_id"]
        view, sqlite_routing = _stored_routing(client, conversation_id)
        assert patched.json()["mode"] == "manual"
        assert view["mode"] == "manual"
        assert view["provider_id"] == "mock"
        assert view["model_id"] == "mock-v1"
        assert view["allow_fallback"] is True
        assert sqlite_routing["mode"] == "manual"
        assert sqlite_routing["manual_preset"]["provider_id"] == "mock"
        assert sqlite_routing["manual_preset"]["model_id"] == "mock-v1"
        route = _route_detail(client, streamed)
        assert route["actual_provider"] == "mock"
        assert route["actual_model"] == "mock-v1"
        assert route["selected_provider"] == "mock"


def test_draft_high_reasoning_first_send_persists_and_executes(tmp_path, monkeypatch):
    controls = {"automatic": True, "reasoning_effort": "high"}
    with _client(tmp_path, monkeypatch) as client:
        created, _, streamed = _promote_draft(client, controls=controls)
        conversation_id = created.json()["conversation_id"]
        view, sqlite_routing = _stored_routing(client, conversation_id)
        assert view["mode"] == "automatic"
        assert view["reasoning_effort"] == "high"
        assert sqlite_routing["reasoning_effort"] == "high"
        route = _route_detail(client, streamed)
        assert route["route"]["metadata"]["reasoning_effort"] == "high"
        assert streamed.status_code == 200
        assert _events(streamed)[-1]["event_type"] == "completed"


def test_draft_private_local_only_first_send_persists_and_executes(tmp_path, monkeypatch):
    controls = {
        "automatic": True,
        "privacy_mode": "private",
        "local_only": True,
        "provider_id": None,
        "model_id": None,
    }
    with _client(tmp_path, monkeypatch) as client:
        disabled = client.patch(
            "/api/v1/providers/ollama/preference",
            json={"enabled": False},
        )
        assert disabled.status_code == 200, disabled.text
        created, _, streamed = _promote_draft(
            client,
            controls=controls,
            message="Summarize why local-only chat matters.",
        )
        conversation_id = created.json()["conversation_id"]
        view, sqlite_routing = _stored_routing(client, conversation_id)
        assert view["privacy_mode"] == "private"
        assert view["local_only"] is True
        assert sqlite_routing["privacy_mode"] == "private"
        assert sqlite_routing["local_only"] is True
        route = _route_detail(client, streamed)
        assert route["route"]["metadata"]["privacy_mode"] == "private"
        assert route["route"]["metadata"]["local_only"] is True
        assert route["actual_provider"] == "mock"


def test_draft_automatic_untouched_first_send_uses_settings_defaults(tmp_path, monkeypatch):
    controls = {"automatic": True}
    with _client(tmp_path, monkeypatch) as client:
        created, _, streamed = _promote_draft(client, controls=controls)
        conversation_id = created.json()["conversation_id"]
        view, sqlite_routing = _stored_routing(client, conversation_id)
        assert view["mode"] == "automatic"
        assert view["provider_id"] is None
        assert view["model_id"] is None
        assert view["reasoning_effort"] == "medium"
        assert view["privacy_mode"] == "standard"
        assert view["local_only"] is False
        assert sqlite_routing["mode"] == "automatic"
        assert sqlite_routing["manual_preset"]["provider_id"] is None
        route = _route_detail(client, streamed)
        assert route["actual_provider"] == "mock"
        assert streamed.status_code == 200


def test_existing_conversation_send_keeps_its_own_routing(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        existing = client.post("/api/v1/conversations", json={"title": "Existing"}).json()
        conversation_id = existing["conversation_id"]
        patched = client.patch(
            f"/api/v1/conversations/{conversation_id}/routing",
            json={
                "mode": "manual",
                "provider_id": "mock",
                "model_id": "mock-v1",
                "write_seq": 1,
            },
        )
        assert patched.status_code == 200
        streamed = client.post(
            "/api/v1/chat/stream",
            json=_stream_payload(
                conversation_id,
                "Explain caching.",
                {
                    "automatic": False,
                    "provider_id": "mock",
                    "model_id": "mock-v1",
                },
            ),
        )
        assert streamed.status_code == 200
        view, sqlite_routing = _stored_routing(client, conversation_id)
        assert view["mode"] == "manual"
        assert view["provider_id"] == "mock"
        assert sqlite_routing["manual_preset"]["model_id"] == "mock-v1"
        assert _route_detail(client, streamed)["actual_provider"] == "mock"


def test_new_draft_does_not_inherit_previous_chat_settings(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        previous = client.post("/api/v1/conversations", json={"title": "A"}).json()
        assert (
            client.patch(
                f"/api/v1/conversations/{previous['conversation_id']}/routing",
                json={
                    "mode": "manual",
                    "provider_id": "mock",
                    "model_id": "mock-v1",
                    "reasoning_effort": "high",
                    "privacy_mode": "private",
                    "local_only": True,
                    "allow_fallback": True,
                },
            ).status_code
            == 200
        )
        created, _, streamed = _promote_draft(
            client,
            controls={"automatic": True},
            message="What is a hash table?",
        )
        new_id = created.json()["conversation_id"]
        view, sqlite_routing = _stored_routing(client, new_id)
        previous_view, _ = _stored_routing(client, previous["conversation_id"])
        assert previous_view["mode"] == "manual"
        assert previous_view["provider_id"] == "mock"
        assert view["mode"] == "automatic"
        assert view["provider_id"] is None
        assert view["reasoning_effort"] == "medium"
        assert view["privacy_mode"] == "standard"
        assert view["local_only"] is False
        assert sqlite_routing["manual_preset"]["provider_id"] is None
        assert _route_detail(client, streamed)["actual_provider"] == "mock"


def test_manual_then_attach_then_send_keeps_draft_routing(tmp_path, monkeypatch):
    controls = {
        "automatic": False,
        "provider_id": "mock",
        "model_id": "mock-v1",
        "privacy_mode": "private",
    }
    with _client(tmp_path, monkeypatch) as client:
        created, _, streamed = _promote_draft(
            client,
            controls=controls,
            attach=("notes.md", b"# Memo\nDraft attachment.", "text/markdown"),
        )
        conversation_id = created.json()["conversation_id"]
        view, sqlite_routing = _stored_routing(client, conversation_id)
        assert view["mode"] == "manual"
        assert view["provider_id"] == "mock"
        assert view["privacy_mode"] == "private"
        assert sqlite_routing["mode"] == "manual"
        assert _route_detail(client, streamed)["actual_provider"] == "mock"


def test_attach_then_manual_then_send_matches_visible_controls(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        created = client.post("/api/v1/conversations", json={"title": "New conversation"})
        conversation_id = created.json()["conversation_id"]
        assert (
            client.patch(
                f"/api/v1/conversations/{conversation_id}/routing",
                json=_routing_patch({"automatic": True}),
            ).status_code
            == 200
        )
        uploaded = client.post(
            f"/api/v1/conversations/{conversation_id}/attachments",
            files={"file": ("notes.md", b"# Memo\nLater manual.", "text/markdown")},
        )
        assert uploaded.status_code == 201
        later = {
            "automatic": False,
            "provider_id": "mock",
            "model_id": "mock-v1",
            "reasoning_effort": "high",
        }
        patched = client.patch(
            f"/api/v1/conversations/{conversation_id}/routing",
            json={**_routing_patch(later), "write_seq": 2},
        )
        assert patched.status_code == 200
        streamed = client.post(
            "/api/v1/chat/stream",
            json=_stream_payload(conversation_id, "Explain the memo.", later),
        )
        view, sqlite_routing = _stored_routing(client, conversation_id)
        assert view["mode"] == "manual"
        assert view["provider_id"] == "mock"
        assert view["model_id"] == "mock-v1"
        assert view["reasoning_effort"] == "high"
        assert sqlite_routing["mode"] == "manual"
        assert sqlite_routing["write_seq"] == 2
        assert _route_detail(client, streamed)["actual_model"] == "mock-v1"


def test_draft_repository_is_available_on_first_coding_like_send(tmp_path, monkeypatch):
    repo = tmp_path / "workspace-repo"
    repo.mkdir()
    (repo / "auth.py").write_text("def login():\n    return True\n", encoding="utf-8")
    with _client(tmp_path, monkeypatch) as client:
        created, _, streamed = _promote_draft(
            client,
            controls={"automatic": True},
            project_path=str(repo),
            message="Refactor the authentication helper in this repository and add tests.",
        )
        assert created.status_code == 201
        conversation = client.get(
            f"/api/v1/conversations/{created.json()['conversation_id']}"
        ).json()
        assert conversation["project_path"] == str(repo.resolve())
        assert streamed.status_code == 200
        route = _route_detail(client, streamed)
        assert conversation["project_path"] == str(repo.resolve())
        assert streamed.status_code == 200
        assert route["route"]["metadata"]["capability_role"] == "coding_agent"
        messages = client.get(
            f"/api/v1/conversations/{conversation['conversation_id']}/messages"
        ).json()
        assert messages, "first coding-like send must record a request after repo attach"


def test_repository_canonicalization_expands_home_without_creating_conversation(
    tmp_path, monkeypatch
):
    home = tmp_path / "home"
    repo = home / "dev" / "OpenCobalt"
    repo.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    with _client(tmp_path, monkeypatch) as client:
        canonicalized = client.post(
            "/api/v1/repositories/canonicalize",
            json={"project_path": "  ~/dev/OpenCobalt  "},
        )

        assert canonicalized.status_code == 200, canonicalized.text
        assert canonicalized.json() == {"project_path": str(repo.resolve())}
        assert client.get("/api/v1/conversations").json() == []


def test_invalid_draft_repository_does_not_create_or_send(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        created = client.post(
            "/api/v1/conversations",
            json={"title": "New conversation", "project_path": "../nope"},
        )
        assert created.status_code == 422
        detail = created.json()["detail"]
        assert "repository path" in str(detail).lower() or "traversal" in str(detail).lower()
        listed = client.get("/api/v1/conversations").json()
        assert listed == []
        missing = tmp_path / "does-not-exist"
        missing_create = client.post(
            "/api/v1/conversations",
            json={"title": "New conversation", "project_path": str(missing)},
        )
        assert missing_create.status_code == 422
        assert client.get("/api/v1/conversations").json() == []


def test_manual_automatic_manual_survives_draft_promotion(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        created = client.post("/api/v1/conversations", json={"title": "New conversation"}).json()
        conversation_id = created["conversation_id"]
        assert (
            client.patch(
                f"/api/v1/conversations/{conversation_id}/routing",
                json=_routing_patch(
                    {
                        "automatic": False,
                        "provider_id": "mock",
                        "model_id": "mock-v1",
                    }
                ),
            ).status_code
            == 200
        )
        automatic = client.patch(
            f"/api/v1/conversations/{conversation_id}/routing",
            json={"mode": "automatic", "write_seq": 2},
        ).json()
        restored = client.patch(
            f"/api/v1/conversations/{conversation_id}/routing",
            json={"mode": "manual", "write_seq": 3},
        ).json()
        assert automatic["mode"] == "automatic"
        assert automatic["provider_id"] == "mock"
        assert restored["mode"] == "manual"
        assert restored["provider_id"] == "mock"
        assert restored["model_id"] == "mock-v1"
        store = PersonalAIStore(tmp_path / ".opencobalt" / "ledger.db")
        loaded = store.get_conversation(conversation_id)
        assert loaded is not None
        assert loaded.metadata["routing"]["manual_preset"]["model_id"] == "mock-v1"
