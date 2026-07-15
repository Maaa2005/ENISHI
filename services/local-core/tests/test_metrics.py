from fastapi.testclient import TestClient


def _insert_metric(method: str, input_tokens: int, output_tokens: int) -> None:
    from enishi_core.database import get_session
    from enishi_core.models import TokenMetric

    session = next(get_session())
    try:
        session.add(
            TokenMetric(
                method=method,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                llm_calls=1,
                message_count=1,
                duration_ms=100,
            )
        )
        session.commit()
    finally:
        session.close()


def test_metrics_summary_with_no_data_returns_null_reduction_rate(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = client.get("/v1/metrics/summary", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["methods"] == []
    assert body["reduction_rate"] is None


def test_metrics_summary_computes_reduction_rate(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    _insert_metric("email", input_tokens=800, output_tokens=200)
    _insert_metric("structured", input_tokens=150, output_tokens=50)

    response = client.get("/v1/metrics/summary", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()

    methods = {m["method"]: m for m in body["methods"]}
    assert methods["email"]["total_tokens"] == 1000
    assert methods["structured"]["total_tokens"] == 200
    assert body["reduction_rate"] == 80.0


def test_metrics_experiment_records_conditions_and_results(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = client.post(
        "/v1/metrics/experiments",
        json={"template": "候補日を教えてください。", "round_trips": 2, "uses_delta": True},
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["template"] == "候補日を教えてください。"
    assert body["round_trips"] == 2
    assert body["uses_delta"] is True
    assert body["structured_json"]["intent"] == "meeting.schedule"
    methods = {m["method"]: m for m in body["methods"]}
    assert methods["email"]["message_count"] == 5
    assert methods["structured"]["message_count"] == 3
    assert body["reduction_rate"] is not None

    summary = client.get("/v1/metrics/summary", headers=auth_headers)
    assert summary.status_code == 200
    assert {m["method"] for m in summary.json()["methods"]} == {"email", "structured"}
