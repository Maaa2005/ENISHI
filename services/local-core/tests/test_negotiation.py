from fastapi.testclient import TestClient

_DATE_RANGE = {"start": "2026-07-13", "end": "2026-07-13"}
_PREFERRED = [{"start": "13:00", "end": "18:00"}]


def _create_user(client: TestClient, headers: dict[str, str], name: str) -> str:
    response = client.post("/v1/users", json={"display_name": name}, headers=headers)
    assert response.status_code == 201
    return response.json()["id"]


def _add_busy(
    client: TestClient,
    headers: dict[str, str],
    user_id: str,
    busy: list[dict[str, str]],
) -> None:
    response = client.post(
        "/v1/memories",
        json={
            "user_id": user_id,
            "source_type": "manual",
            "memory_type": "schedule",
            "title": "予定",
            "content": {"busy": busy},
        },
        headers=headers,
    )
    assert response.status_code == 201


def _activate_clone(client: TestClient, headers: dict[str, str], user_id: str) -> str:
    clone = client.post(
        f"/v1/clones/{user_id}/ensure",
        json={"purpose": "日程調整", "provider_type": "mock"},
        headers=headers,
    ).json()
    activated = client.post(f"/v1/clones/{clone['id']}/activate", headers=headers)
    assert activated.status_code == 200
    return str(clone["id"])


def _negotiate(client: TestClient, headers: dict[str, str], a: str, b: str) -> dict[str, object]:
    response = client.post(
        "/v1/negotiations",
        json={
            "initiator_user_id": a,
            "responder_user_id": b,
            "topic": "AIエージェントの企画",
            "duration_minutes": 30,
            "date_range": _DATE_RANGE,
            "preferred_time_ranges": _PREFERRED,
        },
        headers=headers,
    )
    assert response.status_code == 201
    return dict(response.json())


def test_negotiation_agrees_with_valid_slot(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    a = _create_user(client, auth_headers, "中村")
    b = _create_user(client, auth_headers, "田中")
    a_busy = [{"start": "2026-07-13T13:00", "end": "2026-07-13T14:00"}]
    b_busy = [{"start": "2026-07-13T17:00", "end": "2026-07-13T18:00"}]
    _add_busy(client, auth_headers, a, a_busy)
    _add_busy(client, auth_headers, b, b_busy)
    _activate_clone(client, auth_headers, a)
    _activate_clone(client, auth_headers, b)

    result = _negotiate(client, auth_headers, a, b)
    assert result["status"] == "agreed"
    selected = result["result"]["selected_slot"]

    from twinlink_core.services.scheduling import overlaps

    for busy_item in a_busy + b_busy:
        assert not overlaps(selected, busy_item)

    messages = client.get(
        f"/v1/negotiations/{result['id']}/messages", headers=auth_headers
    ).json()
    assert [m["message_type"] for m in messages] == ["REQUEST", "PROPOSE", "ACCEPT"]
    # 2通目以降は差分のみ（payloadは空でdeltaに情報を入れる）
    for message in messages[1:]:
        assert message["payload"] == {}
        assert message["delta"] != {}


def test_negotiation_agrees_via_counter(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    a = _create_user(client, auth_headers, "中村")
    b = _create_user(client, auth_headers, "田中")
    # initiator候補の上位5件(13:00-15:00開始)がresponderのbusyと全て衝突する
    _add_busy(
        client, auth_headers, b, [{"start": "2026-07-13T13:00", "end": "2026-07-13T15:30"}]
    )
    _activate_clone(client, auth_headers, a)
    _activate_clone(client, auth_headers, b)

    result = _negotiate(client, auth_headers, a, b)
    assert result["status"] == "agreed"

    messages = client.get(
        f"/v1/negotiations/{result['id']}/messages", headers=auth_headers
    ).json()
    types = [m["message_type"] for m in messages]
    assert types == ["REQUEST", "PROPOSE", "COUNTER", "ACCEPT"]
    assert result["result"]["selected_slot"]["start"] >= "2026-07-13T15:30"


def test_negotiation_fails_when_no_common_slot(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    a = _create_user(client, auth_headers, "中村")
    b = _create_user(client, auth_headers, "田中")
    full_day = [{"start": "2026-07-13T13:00", "end": "2026-07-13T18:00"}]
    _add_busy(client, auth_headers, b, full_day)
    _activate_clone(client, auth_headers, a)
    _activate_clone(client, auth_headers, b)

    result = _negotiate(client, auth_headers, a, b)
    assert result["status"] == "failed"
    assert result["result"]["code"] == "NO_AVAILABLE_SLOT"

    messages = client.get(
        f"/v1/negotiations/{result['id']}/messages", headers=auth_headers
    ).json()
    assert messages[-1]["message_type"] == "ERROR"
    assert messages[-1]["delta"]["code"] == "NO_AVAILABLE_SLOT"


def test_negotiation_requires_active_clones(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    a = _create_user(client, auth_headers, "中村")
    b = _create_user(client, auth_headers, "田中")
    # ensureのみでactivateしない
    client.post(
        f"/v1/clones/{a}/ensure",
        json={"purpose": "日程調整", "provider_type": "mock"},
        headers=auth_headers,
    )

    response = client.post(
        "/v1/negotiations",
        json={
            "initiator_user_id": a,
            "responder_user_id": b,
            "topic": "打ち合わせ",
            "duration_minutes": 30,
            "date_range": _DATE_RANGE,
            "preferred_time_ranges": _PREFERRED,
        },
        headers=auth_headers,
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CLONE_REVIEW_REQUIRED"


def test_negotiation_metrics_computed_from_transcripts(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    a = _create_user(client, auth_headers, "中村")
    b = _create_user(client, auth_headers, "田中")
    _activate_clone(client, auth_headers, a)
    _activate_clone(client, auth_headers, b)

    result = _negotiate(client, auth_headers, a, b)
    response = client.get(
        f"/v1/metrics/negotiations/{result['id']}", headers=auth_headers
    )
    assert response.status_code == 200
    body = response.json()

    structured_total = body["structured"]["total_tokens"]
    email_total = body["email"]["total_tokens"]
    assert email_total > structured_total
    assert body["structured"]["llm_calls"] == 0
    assert body["email"]["llm_calls"] == body["email"]["message_count"]
    assert body["reduction_rate"] is not None
    assert 0 < body["reduction_rate"] < 100
    expected = (email_total - structured_total) / email_total * 100
    assert abs(body["reduction_rate"] - expected) < 1e-9


def test_messages_use_protocol_format(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    a = _create_user(client, auth_headers, "中村")
    b = _create_user(client, auth_headers, "田中")
    clone_a = _activate_clone(client, auth_headers, a)
    clone_b = _activate_clone(client, auth_headers, b)

    result = _negotiate(client, auth_headers, a, b)
    messages = client.get(
        f"/v1/negotiations/{result['id']}/messages", headers=auth_headers
    ).json()
    assert messages
    for message in messages:
        assert message["protocol"] == "twinlink/0.1"
        assert message["session_id"] == result["id"]
        assert message["intent"] == "meeting.schedule"
        assert message["requires_human_approval"] is False
        assert {message["sender_agent_id"], message["receiver_agent_id"]} == {clone_a, clone_b}


def test_list_negotiations_newest_first(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    a = _create_user(client, auth_headers, "中村")
    b = _create_user(client, auth_headers, "田中")
    _activate_clone(client, auth_headers, a)
    _activate_clone(client, auth_headers, b)

    first = _negotiate(client, auth_headers, a, b)
    second = _negotiate(client, auth_headers, a, b)

    response = client.get("/v1/negotiations", headers=auth_headers)
    assert response.status_code == 200
    ids = [n["id"] for n in response.json()]
    assert set(ids) == {first["id"], second["id"]}
    assert ids.index(second["id"]) <= ids.index(first["id"])

    limited = client.get("/v1/negotiations", params={"limit": 1}, headers=auth_headers)
    assert len(limited.json()) == 1


def test_get_unknown_negotiation_returns_404(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = client.get("/v1/negotiations/nonexistent", headers=auth_headers)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NEGOTIATION_NOT_FOUND"
