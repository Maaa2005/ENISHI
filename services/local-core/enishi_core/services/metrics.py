"""トークン削減比較サービス（enishi.md §28）。

固定値を返さず、記録済みのTokenMetricから実測値を集計する。
"""

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from enishi_core.errors import EnishiError
from enishi_core.models import TokenMetric
from enishi_core.models.base import new_id, utc_now
from enishi_core.schemas import (
    MethodMetricSummary,
    MetricsExperimentRead,
    MetricsSummary,
    NegotiationMetrics,
)
from enishi_core.services.token_counter import estimate_json_tokens, estimate_tokens

DEFAULT_TEMPLATE = (
    "田中様\n\n"
    "お世話になっております。\n"
    "来週、AIエージェントの企画について30分ほどお話しする時間をいただきたいです。\n"
    "可能であれば午後を希望しております。\n"
    "ご都合のよい時間をお知らせください。\n\n"
    "よろしくお願いいたします。"
)


def summarize_metrics(session: Session) -> MetricsSummary:
    rows = list(session.scalars(select(TokenMetric)))

    totals: dict[str, dict[str, int]] = {}
    for row in rows:
        bucket = totals.setdefault(
            row.method,
            {
                "input_tokens": 0,
                "output_tokens": 0,
                "llm_calls": 0,
                "message_count": 0,
                "duration_ms": 0,
            },
        )
        bucket["input_tokens"] += row.input_tokens
        bucket["output_tokens"] += row.output_tokens
        bucket["llm_calls"] += row.llm_calls
        bucket["message_count"] += row.message_count
        bucket["duration_ms"] += row.duration_ms

    methods = [
        MethodMetricSummary(
            method=method,
            input_tokens=values["input_tokens"],
            output_tokens=values["output_tokens"],
            total_tokens=values["input_tokens"] + values["output_tokens"],
            llm_calls=values["llm_calls"],
            message_count=values["message_count"],
            duration_ms=values["duration_ms"],
        )
        for method, values in sorted(totals.items())
    ]

    email_total = totals.get("email", {}).get("input_tokens", 0) + totals.get("email", {}).get(
        "output_tokens", 0
    )
    structured_total = totals.get("structured", {}).get("input_tokens", 0) + totals.get(
        "structured", {}
    ).get("output_tokens", 0)

    reduction_rate: float | None = None
    if email_total > 0:
        reduction_rate = (email_total - structured_total) / email_total * 100

    return MetricsSummary(methods=methods, reduction_rate=reduction_rate)


def _to_summary(row: TokenMetric) -> MethodMetricSummary:
    return MethodMetricSummary(
        method=row.method,
        input_tokens=row.input_tokens,
        output_tokens=row.output_tokens,
        total_tokens=row.input_tokens + row.output_tokens,
        llm_calls=row.llm_calls,
        message_count=row.message_count,
        duration_ms=row.duration_ms,
    )


def negotiation_metrics(session: Session, session_id: str) -> NegotiationMetrics:
    """指定した交渉セッションの実測トークンを比較する（§28）。"""
    rows = list(session.scalars(select(TokenMetric).where(TokenMetric.session_id == session_id)))
    by_method = {row.method: row for row in rows}
    structured = by_method.get("structured")
    email = by_method.get("email")
    if structured is None or email is None:
        raise EnishiError(
            code="NEGOTIATION_NOT_FOUND",
            message="交渉セッションのメトリクスが見つかりません。",
            status_code=404,
            details={"session_id": session_id},
        )

    email_total = email.input_tokens + email.output_tokens
    structured_total = structured.input_tokens + structured.output_tokens
    reduction_rate: float | None = None
    if email_total > 0:
        reduction_rate = (email_total - structured_total) / email_total * 100

    return NegotiationMetrics(
        structured=_to_summary(structured),
        email=_to_summary(email),
        reduction_rate=reduction_rate,
    )


def run_experiment(
    session: Session,
    *,
    template: str,
    round_trips: int,
    uses_delta: bool,
) -> MetricsExperimentRead:
    """メール方式との比較実験を実行してTokenMetricへ記録する。"""
    experiment_id = f"experiment_{new_id()}"
    created_at: datetime = utc_now()
    structured_json: dict[str, Any] = {
        "intent": "meeting.schedule",
        "duration_minutes": 30,
        "preferred_time": "afternoon",
        "topic": "AIエージェントの企画",
    }
    if uses_delta:
        structured_messages = [
            structured_json,
            {"delta": {"candidate_slots": ["2026-07-13T13:00:00+09:00"]}},
            {"delta": {"selected_slot": "2026-07-13T13:00:00+09:00"}},
        ]
    else:
        structured_messages = [structured_json for _ in range(round_trips * 2 + 1)]

    email_messages = [template]
    for index in range(round_trips):
        email_messages.append(
            f"候補をご連絡します。\n\n"
            f"{index + 1}往復目の候補: 2026-07-13 13:00-13:30\n"
            f"ご都合はいかがでしょうか。"
        )
        email_messages.append(
            f"確認しました。\n\n"
            f"{index + 1}往復目の候補で調整可能です。よろしくお願いいたします。"
        )

    structured_total = sum(estimate_json_tokens(message) for message in structured_messages)
    email_total = sum(estimate_tokens(message) for message in email_messages)
    rows = [
        TokenMetric(
            task_id=experiment_id,
            method="structured",
            input_tokens=structured_total // 2,
            output_tokens=structured_total - structured_total // 2,
            llm_calls=0,
            message_count=len(structured_messages),
        ),
        TokenMetric(
            task_id=experiment_id,
            method="email",
            input_tokens=email_total // 2,
            output_tokens=email_total - email_total // 2,
            llm_calls=len(email_messages),
            message_count=len(email_messages),
        ),
    ]
    session.add_all(rows)
    session.commit()

    summaries = [_to_summary(row) for row in rows]
    reduction_rate: float | None = None
    if email_total > 0:
        reduction_rate = (email_total - structured_total) / email_total * 100
    return MetricsExperimentRead(
        id=experiment_id,
        template=template,
        round_trips=round_trips,
        uses_delta=uses_delta,
        structured_json=structured_json,
        methods=summaries,
        reduction_rate=reduction_rate,
        created_at=created_at,
    )
