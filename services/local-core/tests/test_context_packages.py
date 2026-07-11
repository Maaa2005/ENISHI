from pathlib import Path

from fastapi.testclient import TestClient


def _create_active_clone(
    client: TestClient,
    headers: dict[str, str],
    *,
    tmp_path: Path | None = None,
) -> tuple[str, str, str | None]:
    user = client.post("/v1/users", json={"display_name": "中村"}, headers=headers).json()
    user_id = user["id"]
    client.post(
        "/v1/memories",
        json={
            "user_id": user_id,
            "source_type": "manual",
            "memory_type": "preference",
            "title": "簡潔",
            "content": {"detail": "短く答える"},
            "confidence": 0.9,
        },
        headers=headers,
    )
    client.post(
        "/v1/memories",
        json={
            "user_id": user_id,
            "source_type": "manual",
            "memory_type": "skill",
            "title": "Python",
            "content": {"level": "intermediate"},
            "confidence": 0.8,
        },
        headers=headers,
    )
    client.post(
        "/v1/memories",
        json={
            "user_id": user_id,
            "source_type": "manual",
            "memory_type": "decision",
            "title": "型必須",
            "content": {"rule": "完全な型ヒント"},
            "confidence": 0.8,
        },
        headers=headers,
    )
    project_id = None
    if tmp_path is not None:
        project_dir = tmp_path / "repo"
        project_dir.mkdir()
        (project_dir / "README.md").write_text("# Repo\n", encoding="utf-8")
        project = client.post(
            "/v1/projects",
            json={"user_id": user_id, "name": "repo", "root_path": str(project_dir)},
            headers=headers,
        ).json()
        project_id = project["id"]
    clone = client.post(
        f"/v1/clones/{user_id}/ensure",
        json={"purpose": "コーディング支援", "provider_type": "mock", "project_id": project_id},
        headers=headers,
    ).json()
    activated = client.post(f"/v1/clones/{clone['id']}/activate", headers=headers).json()
    return user_id, activated["id"], project_id


def test_create_context_package_fields_and_project(
    client: TestClient, auth_headers: dict[str, str], tmp_path: Path
) -> None:
    _user_id, clone_id, project_id = _create_active_clone(
        client, auth_headers, tmp_path=tmp_path
    )
    response = client.post(
        "/v1/context-packages",
        json={"clone_id": clone_id, "task_goal": "pytestを直す", "project_id": project_id},
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["clone_id"] == clone_id
    assert body["task_goal"] == "pytestを直す"
    assert body["relevant_preferences"]["簡潔"]["detail"] == "短く答える"
    assert body["relevant_skills"]["Python"]["level"] == "intermediate"
    assert body["relevant_decisions"] == [
        {"title": "型必須", "content": {"rule": "完全な型ヒント"}}
    ]
    assert "README.md" in body["file_references"]
    assert "git push" in body["prohibited_actions"]
    assert "依存パッケージ追加" in body["approval_requirements"]
    assert body["estimated_tokens"] > 0
    assert len(body["content_hash"]) == 64


def test_content_hash_stable_for_same_input(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    _user_id, clone_id, _project_id = _create_active_clone(client, auth_headers)
    first = client.post(
        "/v1/context-packages",
        json={"clone_id": clone_id, "task_goal": "同じ作業"},
        headers=auth_headers,
    ).json()
    second = client.post(
        "/v1/context-packages",
        json={"clone_id": clone_id, "task_goal": "同じ作業"},
        headers=auth_headers,
    ).json()
    assert first["content_hash"] == second["content_hash"]


def test_missing_clone_returns_404(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.post(
        "/v1/context-packages",
        json={"clone_id": "missing", "task_goal": "x"},
        headers=auth_headers,
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "CLONE_NOT_FOUND"


def test_secret_memory_not_leaked(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    user_id, clone_id, _project_id = _create_active_clone(client, auth_headers)
    client.post(
        "/v1/memories",
        json={
            "user_id": user_id,
            "source_type": "manual",
            "memory_type": "preference",
            "title": "秘密",
            "content": {"api_key": "SECRET_VALUE"},
            "sensitivity": "secret",
            "confidence": 1.0,
        },
        headers=auth_headers,
    )
    body = client.post(
        "/v1/context-packages",
        json={"clone_id": clone_id, "task_goal": "漏洩確認"},
        headers=auth_headers,
    ).json()
    assert "SECRET_VALUE" not in str(body)
