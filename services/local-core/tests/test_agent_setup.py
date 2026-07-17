from fastapi.testclient import TestClient

_PUBLIC_KEY = "AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQE="


def _create_user(client: TestClient, headers: dict[str, str], name: str = "中村") -> str:
    response = client.post("/v1/users", json={"display_name": name}, headers=headers)
    assert response.status_code == 201
    return str(response.json()["id"])


def _activate_clone(client: TestClient, headers: dict[str, str], user_id: str) -> str:
    clone = client.post(
        f"/v1/clones/{user_id}/ensure",
        json={"purpose": "コーディング支援", "provider_type": "mock"},
        headers=headers,
    ).json()
    activated = client.post(f"/v1/clones/{clone['id']}/activate", headers=headers)
    assert activated.status_code == 200
    return str(activated.json()["id"])


def _register_peer(client: TestClient, headers: dict[str, str], agent_id: str) -> None:
    created = client.post(
        "/v1/peers",
        json={"agent_id": agent_id, "display_name": "相手AI", "public_key": _PUBLIC_KEY},
        headers=headers,
    )
    assert created.status_code == 201
    trusted = client.post(f"/v1/peers/{agent_id}/trust", headers=headers)
    assert trusted.status_code == 200


def _add_memory(
    client: TestClient,
    headers: dict[str, str],
    user_id: str,
    *,
    memory_type: str,
    title: str,
    sensitivity: str,
) -> None:
    response = client.post(
        "/v1/memories",
        json={
            "user_id": user_id,
            "source_type": "manual",
            "memory_type": memory_type,
            "title": title,
            "content": {"value": title},
            "confidence": 1.0,
            "sensitivity": sensitivity,
        },
        headers=headers,
    )
    assert response.status_code == 201


def test_memory_sources_report_external_connectors_as_disconnected(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    listed = client.get("/v1/memory-sources", headers=auth_headers)
    assert listed.status_code == 200
    by_source = {row["source"]: row for row in listed.json()}
    assert by_source["memories"]["connected"] is True
    assert by_source["memories"]["enabled"] is True
    assert by_source["github"]["connected"] is False
    assert by_source["github"]["enabled"] is False

    updated = client.put(
        "/v1/memory-sources",
        json={"sources": [{"source": "github", "enabled": True, "scope": "all repos"}]},
        headers=auth_headers,
    )
    assert updated.status_code == 200
    github = {row["source"]: row for row in updated.json()}["github"]
    assert github["connected"] is False
    assert github["enabled"] is False
    assert github["scope"] == "all repos"


def test_default_disclosure_rejects_restricted_or_secret(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = client.put(
        "/v1/disclosure/default",
        json={
            "allowed_memory_types": ["preference"],
            "max_sensitivity": "restricted",
            "share_schedule": True,
            "share_skills": False,
            "extra": {},
        },
        headers=auth_headers,
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "DISCLOSURE_POLICY_INVALID"


def test_default_disclosure_applies_to_unconfigured_peer_context_payload(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    user_id = _create_user(client, auth_headers)
    clone_id = _activate_clone(client, auth_headers, user_id)
    _register_peer(client, auth_headers, "agt_default")
    _add_memory(
        client,
        auth_headers,
        user_id,
        memory_type="preference",
        title="公開できる好み",
        sensitivity="internal",
    )
    _add_memory(
        client,
        auth_headers,
        user_id,
        memory_type="skill",
        title="スキル",
        sensitivity="internal",
    )

    updated = client.put(
        "/v1/disclosure/default",
        json={
            "allowed_memory_types": ["preference"],
            "max_sensitivity": "internal",
            "share_schedule": True,
            "share_skills": False,
            "extra": {},
        },
        headers=auth_headers,
    )
    assert updated.status_code == 200

    package = client.post(
        "/v1/context-packages",
        json={
            "clone_id": clone_id,
            "task_goal": "相手へ渡す",
            "peer_agent_id": "agt_default",
        },
        headers=auth_headers,
    )
    assert package.status_code == 200
    body = package.json()
    assert "公開できる好み" in body["relevant_preferences"]
    assert body["relevant_skills"] == {}


def test_restricted_and_secret_never_leak_even_with_default_disclosure(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    user_id = _create_user(client, auth_headers)
    clone_id = _activate_clone(client, auth_headers, user_id)
    _register_peer(client, auth_headers, "agt_safe")
    for title, sensitivity in [("制限情報", "restricted"), ("秘密情報", "secret")]:
        _add_memory(
            client,
            auth_headers,
            user_id,
            memory_type="preference",
            title=title,
            sensitivity=sensitivity,
        )
    ok = client.put(
        "/v1/disclosure/default",
        json={
            "allowed_memory_types": ["preference"],
            "max_sensitivity": "private",
            "share_schedule": True,
            "share_skills": False,
            "extra": {},
        },
        headers=auth_headers,
    )
    assert ok.status_code == 200

    package = client.post(
        "/v1/context-packages",
        json={"clone_id": clone_id, "task_goal": "安全確認", "peer_agent_id": "agt_safe"},
        headers=auth_headers,
    )
    assert package.status_code == 200
    body = package.json()
    assert "制限情報" not in body["relevant_preferences"]
    assert "秘密情報" not in body["relevant_preferences"]


def test_policy_apis_save_and_return_rules(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    user_id = _create_user(client, auth_headers)

    delegation = client.put(
        "/v1/policies/delegation",
        json={"user_id": user_id, "rules": {"coding_task": False}},
        headers=auth_headers,
    )
    assert delegation.status_code == 200
    assert delegation.json()["rules"]["coding_task"] is False

    approval = client.put(
        "/v1/policies/approval-rules",
        json={"user_id": user_id, "rules": {"file_delete": False, "git_push": True}},
        headers=auth_headers,
    )
    assert approval.status_code == 200
    assert approval.json()["rules"]["file_delete"] is False

    loaded = client.get(
        f"/v1/policies/approval-rules?user_id={user_id}",
        headers=auth_headers,
    )
    assert loaded.status_code == 200
    assert loaded.json()["rules"]["file_delete"] is False


def test_meeting_preferences_can_edit_avoid_ranges(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    user_id = _create_user(client, auth_headers)
    clone_id = _activate_clone(client, auth_headers, user_id)
    before = client.get(
        f"/v1/users/{user_id}/meeting-preferences", headers=auth_headers
    )
    assert before.status_code == 200

    updated = client.put(
        f"/v1/users/{user_id}/meeting-preferences",
        json={
            "preferred_time_ranges": [{"start": "09:00", "end": "17:00"}],
            "avoid_time_ranges": [{"start": "12:00", "end": "13:00"}],
        },
        headers=auth_headers,
    )
    assert updated.status_code == 200
    assert updated.json()["clone_id"] == clone_id
    assert updated.json()["avoid_time_ranges"] == [{"start": "12:00", "end": "13:00"}]
    assert updated.json()["version"] > before.json()["version"]

    invalid = client.put(
        f"/v1/users/{user_id}/meeting-preferences",
        json={"avoid_time_ranges": [{"start": "25:00", "end": "26:00"}]},
        headers=auth_headers,
    )
    assert invalid.status_code == 422


def test_task_delegation_policy_blocks_coding_task(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    user_id = _create_user(client, auth_headers)
    clone_id = _activate_clone(client, auth_headers, user_id)
    client.put(
        "/v1/policies/delegation",
        json={"user_id": user_id, "rules": {"coding_task": False}},
        headers=auth_headers,
    )

    response = client.post(
        "/v1/tasks",
        json={
            "user_id": user_id,
            "clone_id": clone_id,
            "provider": "mock",
            "description": "実行",
        },
        headers=auth_headers,
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "TASK_PERMISSION_DENIED"
