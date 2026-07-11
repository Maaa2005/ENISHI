from fastapi.testclient import TestClient


def _create_user(client: TestClient, headers: dict[str, str]) -> str:
    response = client.post("/v1/users", json={"display_name": "中村"}, headers=headers)
    assert response.status_code == 201
    return response.json()["id"]


def test_ensure_creates_review_required_clone(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    user_id = _create_user(client, auth_headers)
    response = client.post(
        f"/v1/clones/{user_id}/ensure",
        json={"purpose": "コーディング支援", "provider_type": "codex"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    clone = response.json()
    assert clone["status"] == "review_required"
    assert clone["user_id"] == user_id
    assert clone["activated_at"] is None
    assert clone["coding_profile"]["approval_rules"]["git_push"] is False


def test_ensure_reuses_existing_clone(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    user_id = _create_user(client, auth_headers)
    body = {"purpose": "コーディング支援", "provider_type": "codex"}
    first = client.post(f"/v1/clones/{user_id}/ensure", json=body, headers=auth_headers)
    second = client.post(f"/v1/clones/{user_id}/ensure", json=body, headers=auth_headers)
    assert first.json()["id"] == second.json()["id"]


def test_activate_clone(client: TestClient, auth_headers: dict[str, str]) -> None:
    user_id = _create_user(client, auth_headers)
    clone = client.post(
        f"/v1/clones/{user_id}/ensure",
        json={"purpose": "コーディング支援", "provider_type": "mock"},
        headers=auth_headers,
    ).json()

    activated = client.post(f"/v1/clones/{clone['id']}/activate", headers=auth_headers)
    assert activated.status_code == 200
    assert activated.json()["status"] == "active"
    assert activated.json()["activated_at"] is not None

    # active 状態からの再有効化は不正な状態遷移
    again = client.post(f"/v1/clones/{clone['id']}/activate", headers=auth_headers)
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "INVALID_STATE_TRANSITION"


def test_ensure_unknown_user_returns_404(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = client.post(
        "/v1/clones/nonexistent/ensure",
        json={"purpose": "x", "provider_type": "mock"},
        headers=auth_headers,
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "CLONE_NOT_FOUND"
