import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient


def _setup_active_clone(
    client: TestClient,
    headers: dict[str, str],
    tmp_path: Path | None = None,
) -> tuple[str, str, str | None]:
    user = client.post("/v1/users", json={"display_name": "中村"}, headers=headers).json()
    user_id = user["id"]
    project_id = None
    if tmp_path is not None:
        project_dir = tmp_path / "repo"
        project_dir.mkdir()
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


def _wait_for_task(
    client: TestClient,
    headers: dict[str, str],
    task_id: str,
    *,
    timeout: float = 2.0,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        task = client.get(f"/v1/tasks/{task_id}", headers=headers).json()
        if task["status"] in {"completed", "failed", "cancelled", "expired"}:
            return task
        time.sleep(0.02)
    return client.get(f"/v1/tasks/{task_id}", headers=headers).json()


def test_mock_task_completes(client: TestClient, auth_headers: dict[str, str]) -> None:
    user_id, clone_id, _project_id = _setup_active_clone(client, auth_headers)
    response = client.post(
        "/v1/tasks",
        json={
            "user_id": user_id,
            "clone_id": clone_id,
            "provider": "mock",
            "description": "テストを実行",
        },
        headers=auth_headers,
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] in {"queued", "running"}
    body = _wait_for_task(client, auth_headers, body["id"])
    assert body["status"] == "completed"
    assert body["output_lines"]
    assert body["started_at"] is not None
    assert body["finished_at"] is not None


def test_list_tasks_filters_by_user_and_orders_newest_first(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    user_id, clone_id, _project_id = _setup_active_clone(client, auth_headers)
    other_user_id, other_clone_id, _ = _setup_active_clone(client, auth_headers)
    first = client.post(
        "/v1/tasks",
        json={
            "user_id": user_id,
            "clone_id": clone_id,
            "provider": "mock",
            "description": "first",
        },
        headers=auth_headers,
    ).json()
    second = client.post(
        "/v1/tasks",
        json={
            "user_id": user_id,
            "clone_id": clone_id,
            "provider": "mock",
            "description": "second",
        },
        headers=auth_headers,
    ).json()
    client.post(
        "/v1/tasks",
        json={
            "user_id": other_user_id,
            "clone_id": other_clone_id,
            "provider": "mock",
            "description": "other",
        },
        headers=auth_headers,
    )

    response = client.get(f"/v1/tasks?user_id={user_id}&limit=2", headers=auth_headers)
    assert response.status_code == 200
    assert [task["id"] for task in response.json()] == [second["id"], first["id"]]


def test_level3_operation_forbidden(client: TestClient, auth_headers: dict[str, str]) -> None:
    user_id, clone_id, _project_id = _setup_active_clone(client, auth_headers)
    response = client.post(
        "/v1/tasks",
        json={
            "user_id": user_id,
            "clone_id": clone_id,
            "provider": "mock",
            "description": "pushする",
            "requested_operations": ["git_push"],
        },
        headers=auth_headers,
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "TASK_PERMISSION_DENIED"


def test_level2_approval_then_completed(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    user_id, clone_id, _project_id = _setup_active_clone(client, auth_headers)
    created = client.post(
        "/v1/tasks",
        json={
            "user_id": user_id,
            "clone_id": clone_id,
            "provider": "mock",
            "description": "依存追加",
            "requested_operations": ["install_dependencies"],
        },
        headers=auth_headers,
    ).json()
    assert created["status"] == "waiting_approval"
    approval_id = created["approval_id"]
    approved = client.post(f"/v1/approvals/{approval_id}/approve", headers=auth_headers)
    assert approved.status_code == 200
    task = _wait_for_task(client, auth_headers, created["id"])
    assert task["status"] == "completed"


def test_level2_task_is_never_claimable_before_approval(
    client: TestClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from enishi_core.database import get_session
    from enishi_core.services import tasks as task_service

    user_id, clone_id, _project_id = _setup_active_clone(client, auth_headers)
    claim_results: list[str | None] = []
    original_create_approval = task_service.create_approval

    def create_approval_with_claim_attempt(*args: Any, **kwargs: Any) -> Any:
        claim_session = next(get_session())
        try:
            claimed = task_service.claim_next_task(claim_session, "approval-race-test")
            claim_results.append(None if claimed is None else claimed.id)
        finally:
            claim_session.close()
        return original_create_approval(*args, **kwargs)

    monkeypatch.setattr(task_service, "create_approval", create_approval_with_claim_attempt)

    session = next(get_session())
    try:
        task = task_service.create_task(
            session,
            user_id=user_id,
            clone_id=clone_id,
            provider="mock",
            description="依存追加",
            requested_operations=["install_dependencies"],
        )
        assert task.status == "waiting_approval"
    finally:
        session.close()

    assert claim_results == [None]

    claim_session = next(get_session())
    try:
        assert task_service.claim_next_task(claim_session, "approval-race-test") is None
    finally:
        claim_session.close()


def test_level2_reject_cancels(client: TestClient, auth_headers: dict[str, str]) -> None:
    user_id, clone_id, _project_id = _setup_active_clone(client, auth_headers)
    created = client.post(
        "/v1/tasks",
        json={
            "user_id": user_id,
            "clone_id": clone_id,
            "provider": "mock",
            "description": "依存追加",
            "requested_operations": ["install_dependencies"],
        },
        headers=auth_headers,
    ).json()
    rejected = client.post(
        f"/v1/approvals/{created['approval_id']}/reject",
        headers=auth_headers,
    )
    assert rejected.status_code == 200
    task = client.get(f"/v1/tasks/{created['id']}", headers=auth_headers).json()
    assert task["status"] == "cancelled"


def test_expired_approval_cannot_queue_old_task(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    user_id, clone_id, _project_id = _setup_active_clone(client, auth_headers)
    expires_at = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    created = client.post(
        "/v1/tasks",
        json={
            "user_id": user_id,
            "clone_id": clone_id,
            "provider": "mock",
            "description": "古い承認では実行しない",
            "requested_operations": ["install_dependencies"],
            "approval_expires_at": expires_at,
        },
        headers=auth_headers,
    ).json()

    approved = client.post(
        f"/v1/approvals/{created['approval_id']}/approve",
        headers=auth_headers,
    )
    assert approved.status_code == 409
    assert approved.json()["error"]["code"] == "APPROVAL_EXPIRED"

    task = client.get(f"/v1/tasks/{created['id']}", headers=auth_headers).json()
    assert task["status"] == "expired"
    assert task["started_at"] is None
    assert task["failure_code"] == "APPROVAL_EXPIRED"


def test_inactive_clone_returns_409(client: TestClient, auth_headers: dict[str, str]) -> None:
    user = client.post("/v1/users", json={"display_name": "中村"}, headers=auth_headers).json()
    clone = client.post(
        f"/v1/clones/{user['id']}/ensure",
        json={"purpose": "コーディング支援", "provider_type": "mock"},
        headers=auth_headers,
    ).json()
    response = client.post(
        "/v1/tasks",
        json={
            "user_id": user["id"],
            "clone_id": clone["id"],
            "provider": "mock",
            "description": "実行",
        },
        headers=auth_headers,
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CLONE_REVIEW_REQUIRED"


def test_cancel_after_cancel_returns_409(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    user_id, clone_id, _project_id = _setup_active_clone(client, auth_headers)
    created = client.post(
        "/v1/tasks",
        json={
            "user_id": user_id,
            "clone_id": clone_id,
            "provider": "mock",
            "description": "依存追加",
            "requested_operations": ["install_dependencies"],
        },
        headers=auth_headers,
    ).json()
    first = client.post(f"/v1/tasks/{created['id']}/cancel", headers=auth_headers)
    assert first.status_code == 200
    second = client.post(f"/v1/tasks/{created['id']}/cancel", headers=auth_headers)
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "INVALID_STATE_TRANSITION"


def test_get_missing_task_returns_404(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.get("/v1/tasks/missing", headers=auth_headers)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "TASK_NOT_FOUND"


def test_websocket_streams_output_and_end(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    user_id, clone_id, _project_id = _setup_active_clone(client, auth_headers)
    task = client.post(
        "/v1/tasks",
        json={
            "user_id": user_id,
            "clone_id": clone_id,
            "provider": "mock",
            "description": "配信確認",
        },
        headers=auth_headers,
    ).json()
    task = _wait_for_task(client, auth_headers, task["id"])
    with client.websocket_connect(
        f"/v1/tasks/{task['id']}/stream",
        headers=auth_headers,
    ) as websocket:
        first = websocket.receive_text()
        end = None
        while end is None:
            message = websocket.receive_text()
            if '"event": "end"' in message:
                end = message
    assert first.startswith("task: 配信確認")
    assert '"status": "completed"' in end
