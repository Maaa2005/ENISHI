from fastapi.testclient import TestClient

from enishi_core.database import get_session
from enishi_core.services.audit import log_event


def test_audit_api_returns_only_safe_metadata(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    session = next(get_session())
    try:
        event = log_event(
            session,
            event_type="test_sensitive_event",
            payload={
                "session_id": "session_1",
                "status": "ok",
                "content": "private calendar body",
                "token": "secret-token",
                "public_key": "raw-key",
            },
        )
    finally:
        session.close()

    response = client.get("/v1/audit-events", headers=auth_headers)
    assert response.status_code == 200
    body = next(item for item in response.json() if item["id"] == event.id)
    assert body["payload"] == {"session_id": "session_1", "status": "ok"}
    assert "private calendar body" not in str(body)
    assert "secret-token" not in str(body)
    assert "raw-key" not in str(body)


def test_audit_api_enforces_limit(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    session = next(get_session())
    try:
        for index in range(3):
            log_event(session, event_type=f"event_{index}")
    finally:
        session.close()

    response = client.get("/v1/audit-events?limit=2", headers=auth_headers)
    assert response.status_code == 200
    assert len(response.json()) == 2

    invalid = client.get("/v1/audit-events?limit=201", headers=auth_headers)
    assert invalid.status_code == 422
