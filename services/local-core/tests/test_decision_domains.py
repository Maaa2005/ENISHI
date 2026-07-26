"""意思決定ドメインレジストリ（Phase A: domains パッケージ）のテスト。"""

from fastapi.testclient import TestClient

_REGISTERED_INTENTS = {"cost.split", "meeting.schedule", "task.request"}


def test_registry_has_both_builtin_domains() -> None:
    from enishi_core.domains import registered_intents

    assert set(registered_intents()) == _REGISTERED_INTENTS


def test_get_domain_raises_enishi_error_for_unknown_intent() -> None:
    from enishi_core.domains import get_domain
    from enishi_core.errors import EnishiError

    try:
        get_domain("expense.approval")
    except EnishiError as exc:
        assert exc.code == "UNKNOWN_INTENT"
        assert exc.status_code == 422
        assert set(exc.details["registered_intents"]) == _REGISTERED_INTENTS
    else:
        raise AssertionError("expected EnishiError for unknown intent")


def test_get_domain_resolves_registered_intents() -> None:
    from enishi_core.domains import get_domain
    from enishi_core.domains.cost_split import CostSplitDomain
    from enishi_core.domains.meeting_schedule import MeetingScheduleDomain
    from enishi_core.domains.task_request import TaskRequestDomain

    assert isinstance(get_domain("meeting.schedule"), MeetingScheduleDomain)
    assert isinstance(get_domain("task.request"), TaskRequestDomain)
    assert isinstance(get_domain("cost.split"), CostSplitDomain)


def test_create_negotiation_with_unknown_intent_returns_422(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = client.post(
        "/v1/negotiations",
        json={
            "intent": "expense.approval",
            "initiator_user_id": "u1",
            "responder_user_id": "u2",
        },
        headers=auth_headers,
    )
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "UNKNOWN_INTENT"
    assert set(body["error"]["details"]["registered_intents"]) == _REGISTERED_INTENTS


def test_remote_negotiation_uses_domain_registry_not_direct_import() -> None:
    """新規7. E3-a: `remote_negotiation` は `evaluate_meeting_schedule` を直接 import せず、
    `get_domain("meeting.schedule").evaluate_decision` 経由で判断する。ローカル/リモートで
    判断コードが二重化しないための継ぎ目が保たれていることを確認する。
    """
    import inspect

    from enishi_core.domains import get_domain
    from enishi_core.domains.meeting_schedule import (
        MeetingScheduleDomain,
        evaluate_meeting_schedule,
    )
    from enishi_core.models import CloneAgent
    from enishi_core.services import remote_negotiation

    # remote_negotiation のモジュール名前空間に evaluate_meeting_schedule が
    # 直接 import されていない（get_domain 経由でしか到達できない）ことを確認する。
    assert not hasattr(remote_negotiation, "evaluate_meeting_schedule")
    source = inspect.getsource(remote_negotiation)
    assert "from enishi_core.services.decision_evaluator import evaluate_meeting_schedule" not in (
        source
    )
    assert "from enishi_core.domains.meeting_schedule import evaluate_meeting_schedule" not in (
        source
    )

    domain = get_domain("meeting.schedule")
    assert isinstance(domain, MeetingScheduleDomain)

    # レジストリ経由の評価が、ドメインの純粋関数 evaluate_meeting_schedule そのものに
    # 委譲されていること（判断ロジックが再実装されていないこと）を確認する。
    clone = CloneAgent(confidence_score=0.9, preference_profile={}, policy_profile={})
    kwargs: dict[str, object] = {
        "clone": clone,
        "delegation_enabled": True,
        "common_slot_count": 1,
        "selected_slot": None,
        "peer_personal_agent_id": "peer",
        "timezone": "UTC",
    }
    via_registry = domain.evaluate_decision(**kwargs)
    direct = evaluate_meeting_schedule(**kwargs)  # type: ignore[arg-type]
    assert via_registry == direct


def test_get_v1_intents_returns_all_registered_domains(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = client.get("/v1/intents", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 3
    assert {item["intent"] for item in body} == _REGISTERED_INTENTS
    for item in body:
        assert isinstance(item["payload_schema"], dict)
        assert "properties" in item["payload_schema"]
