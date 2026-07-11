from pathlib import Path

from fastapi.testclient import TestClient


def _create_user(client: TestClient, headers: dict[str, str]) -> str:
    response = client.post("/v1/users", json={"display_name": "中村"}, headers=headers)
    assert response.status_code == 201
    return response.json()["id"]


def test_register_project_in_existing_directory(
    client: TestClient, auth_headers: dict[str, str], tmp_path: Path
) -> None:
    user_id = _create_user(client, auth_headers)
    project_dir = tmp_path / "myproject"
    project_dir.mkdir()
    (project_dir / ".git").mkdir()

    response = client.post(
        "/v1/projects",
        json={"user_id": user_id, "name": "myproject", "root_path": str(project_dir)},
        headers=auth_headers,
    )
    assert response.status_code == 201
    body = response.json()
    assert body["repository_type"] == "git"
    assert body["trusted"] is False
    assert body["permissions"]["delete"] is False
    assert body["permissions"]["git_push"] is False
    assert body["permissions"]["use_network"] is False


def test_register_nonexistent_path_returns_400(
    client: TestClient, auth_headers: dict[str, str], tmp_path: Path
) -> None:
    user_id = _create_user(client, auth_headers)
    response = client.post(
        "/v1/projects",
        json={
            "user_id": user_id,
            "name": "missing",
            "root_path": str(tmp_path / "does-not-exist"),
        },
        headers=auth_headers,
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "PROJECT_PATH_NOT_ALLOWED"


def test_register_root_returns_400(client: TestClient, auth_headers: dict[str, str]) -> None:
    user_id = _create_user(client, auth_headers)
    response = client.post(
        "/v1/projects",
        json={"user_id": user_id, "name": "root", "root_path": "/"},
        headers=auth_headers,
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "PROJECT_PATH_NOT_ALLOWED"


def test_register_home_directory_returns_400(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    user_id = _create_user(client, auth_headers)
    response = client.post(
        "/v1/projects",
        json={"user_id": user_id, "name": "home", "root_path": "~"},
        headers=auth_headers,
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "PROJECT_PATH_NOT_ALLOWED"


def test_get_unknown_project_returns_404(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = client.get("/v1/projects/nonexistent", headers=auth_headers)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PROJECT_NOT_FOUND"


def test_patch_project_permissions(
    client: TestClient, auth_headers: dict[str, str], tmp_path: Path
) -> None:
    user_id = _create_user(client, auth_headers)
    project_dir = tmp_path / "myproject"
    project_dir.mkdir()

    created = client.post(
        "/v1/projects",
        json={"user_id": user_id, "name": "myproject", "root_path": str(project_dir)},
        headers=auth_headers,
    ).json()
    assert created["repository_type"] is None

    patched = client.patch(
        f"/v1/projects/{created['id']}",
        json={"trusted": True, "permissions": {**created["permissions"], "git_commit": True}},
        headers=auth_headers,
    )
    assert patched.status_code == 200
    body = patched.json()
    assert body["trusted"] is True
    assert body["permissions"]["git_commit"] is True
