from fastapi.testclient import TestClient


def _create_user(client: TestClient, headers: dict[str, str]) -> str:
    response = client.post("/v1/users", json={"display_name": "中村"}, headers=headers)
    assert response.status_code == 201
    return response.json()["id"]


def _memory_payload(user_id: str, **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "user_id": user_id,
        "source_type": "conversation",
        "memory_type": "preference",
        "title": "コーヒーが好き",
        "content": {"detail": "ブラックコーヒーを好む"},
        "sensitivity": "internal",
    }
    payload.update(overrides)
    return payload


def test_create_and_list_memories(client: TestClient, auth_headers: dict[str, str]) -> None:
    user_id = _create_user(client, auth_headers)
    created = client.post(
        "/v1/memories", json=_memory_payload(user_id), headers=auth_headers
    )
    assert created.status_code == 201
    body = created.json()
    assert body["status"] == "active"
    assert body["sensitivity"] == "internal"

    listed = client.get("/v1/memories", params={"user_id": user_id}, headers=auth_headers)
    assert listed.status_code == 200
    assert [m["id"] for m in listed.json()] == [body["id"]]


def test_delete_memory_marks_deleted_and_hides_from_list(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    user_id = _create_user(client, auth_headers)
    created = client.post(
        "/v1/memories", json=_memory_payload(user_id), headers=auth_headers
    ).json()

    deleted = client.delete(f"/v1/memories/{created['id']}", headers=auth_headers)
    assert deleted.status_code == 200
    assert deleted.json()["status"] == "deleted"

    listed = client.get("/v1/memories", params={"user_id": user_id}, headers=auth_headers)
    assert listed.json() == []


def test_delete_memory_outdates_clone_and_context_excludes_deleted_content(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    from sqlalchemy import select
    from twinlink_core.database import get_session
    from twinlink_core.models import AuditLog, CloneAgent

    user_id = _create_user(client, auth_headers)
    created = client.post(
        "/v1/memories",
        json=_memory_payload(
            user_id,
            title="削除される好み",
            content={"detail": "コンテキストに戻さない"},
        ),
        headers=auth_headers,
    ).json()
    clone = client.post(
        f"/v1/clones/{user_id}/ensure",
        json={"purpose": "コーディング支援", "provider_type": "mock"},
        headers=auth_headers,
    ).json()
    activated = client.post(f"/v1/clones/{clone['id']}/activate", headers=auth_headers).json()

    deleted = client.delete(f"/v1/memories/{created['id']}", headers=auth_headers)
    assert deleted.status_code == 200

    context = client.post(
        "/v1/context-packages",
        json={"clone_id": activated["id"], "task_goal": "削除確認"},
        headers=auth_headers,
    ).json()
    assert "コンテキストに戻さない" not in str(context)

    session = next(get_session())
    try:
        stored_clone = session.get(CloneAgent, activated["id"])
        assert stored_clone is not None
        assert stored_clone.status == "outdated"
        event = session.scalars(
            select(AuditLog).where(AuditLog.event_type == "memory_deleted")
        ).one()
    finally:
        session.close()
    assert event.payload["memory_id"] == created["id"]
    assert "コンテキストに戻さない" not in str(event.payload)


def test_invalid_sensitivity_returns_422(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    user_id = _create_user(client, auth_headers)
    response = client.post(
        "/v1/memories",
        json=_memory_payload(user_id, sensitivity="top_secret"),
        headers=auth_headers,
    )
    assert response.status_code == 422


def test_invalid_memory_type_returns_422(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    user_id = _create_user(client, auth_headers)
    response = client.post(
        "/v1/memories",
        json=_memory_payload(user_id, memory_type="unknown_type"),
        headers=auth_headers,
    )
    assert response.status_code == 422


def test_exportable_memories_excludes_secret(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    from twinlink_core.database import get_session
    from twinlink_core.services.memories import exportable_memories

    user_id = _create_user(client, auth_headers)
    client.post(
        "/v1/memories",
        json=_memory_payload(user_id, title="公開情報", sensitivity="internal"),
        headers=auth_headers,
    )
    client.post(
        "/v1/memories",
        json=_memory_payload(user_id, title="秘密情報", sensitivity="secret"),
        headers=auth_headers,
    )

    session = next(get_session())
    try:
        exportable = exportable_memories(session, user_id)
    finally:
        session.close()

    titles = {m.title for m in exportable}
    assert "公開情報" in titles
    assert "秘密情報" not in titles
