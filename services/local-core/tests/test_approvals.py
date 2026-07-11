from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient


def _create_user(client: TestClient, headers: dict[str, str]) -> str:
    response = client.post("/v1/users", json={"display_name": "中村"}, headers=headers)
    assert response.status_code == 201
    return response.json()["id"]


def _create_approval(
    client: TestClient, headers: dict[str, str], user_id: str
) -> dict[str, object]:
    """POST /v1/approvals はAPI仕様に存在しないため、サービス層を通じて直接作成する。"""
    from twinlink_core.database import get_session
    from twinlink_core.services.approvals import create_approval

    session = next(get_session())
    try:
        approval = create_approval(
            session,
            user_id=user_id,
            action_type="git_commit",
            description="変更をコミットする",
            level=2,
        )
        return {
            "id": approval.id,
            "user_id": approval.user_id,
            "status": approval.status,
        }
    finally:
        session.close()


def test_approve_approval(client: TestClient, auth_headers: dict[str, str]) -> None:
    user_id = _create_user(client, auth_headers)
    approval = _create_approval(client, auth_headers, user_id)

    response = client.post(
        f"/v1/approvals/{approval['id']}/approve", headers=auth_headers
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "approved"
    assert body["resolved_at"] is not None


def test_reject_approval(client: TestClient, auth_headers: dict[str, str]) -> None:
    user_id = _create_user(client, auth_headers)
    approval = _create_approval(client, auth_headers, user_id)

    response = client.post(f"/v1/approvals/{approval['id']}/reject", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["status"] == "rejected"


def test_double_resolve_returns_409(client: TestClient, auth_headers: dict[str, str]) -> None:
    user_id = _create_user(client, auth_headers)
    approval = _create_approval(client, auth_headers, user_id)

    first = client.post(f"/v1/approvals/{approval['id']}/approve", headers=auth_headers)
    assert first.status_code == 200

    second = client.post(f"/v1/approvals/{approval['id']}/approve", headers=auth_headers)
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "INVALID_STATE_TRANSITION"


def test_list_approvals(client: TestClient, auth_headers: dict[str, str]) -> None:
    user_id = _create_user(client, auth_headers)
    _create_approval(client, auth_headers, user_id)

    response = client.get("/v1/approvals", params={"user_id": user_id}, headers=auth_headers)
    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["status"] == "pending"
    assert response.json()[0]["expires_at"] is not None


def test_list_marks_expired_approval(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    from twinlink_core.database import get_session
    from twinlink_core.services.approvals import create_approval

    user_id = _create_user(client, auth_headers)
    session = next(get_session())
    try:
        approval = create_approval(
            session,
            user_id=user_id,
            action_type="git_commit",
            description="期限切れ",
            level=2,
            expires_at=datetime.now(UTC) - timedelta(seconds=1),
        )
        approval_id = approval.id
    finally:
        session.close()

    response = client.get("/v1/approvals", params={"user_id": user_id}, headers=auth_headers)
    assert response.status_code == 200
    assert response.json()[0]["id"] == approval_id
    assert response.json()[0]["status"] == "expired"


def test_approve_records_audit_log(client: TestClient, auth_headers: dict[str, str]) -> None:
    from sqlalchemy import select
    from twinlink_core.database import get_session
    from twinlink_core.models import AuditLog

    user_id = _create_user(client, auth_headers)
    approval = _create_approval(client, auth_headers, user_id)

    client.post(f"/v1/approvals/{approval['id']}/approve", headers=auth_headers)

    session = next(get_session())
    try:
        query = select(AuditLog).where(AuditLog.event_type == "approval_approved")
        events = list(session.scalars(query))
    finally:
        session.close()
    assert len(events) == 1
    assert events[0].payload["approval_id"] == approval["id"]
