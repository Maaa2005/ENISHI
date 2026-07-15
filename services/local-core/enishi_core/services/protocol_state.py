"""プロトコル状態機械（enishi.md §25 プロトコル状態機械 v2）。

署名が正しくても、状態として受け付けられないメッセージは拒否する。
REQUEST → PROPOSE → {ACCEPT | COUNTER}、COUNTER → {ACCEPT | COUNTER}（ラウンド上限）。
REJECT / ERROR は任意時点で受理し終端。終端後の受信・sequence非単調は拒否する。
"""

from enishi_core.errors import EnishiError

MAX_COUNTER_ROUNDS = 3

# セッション状態 × 受理可能message_type。
# "open" のセッションでは直前のメッセージ種別で次を決めるため、
# ここでは「進行中に受理しうる型」を持ち、直前型との遷移は _ALLOWED_AFTER で検証する。
_ALLOWED_AFTER: dict[str, set[str]] = {
    "": {"REQUEST"},  # セッション未開始
    "REQUEST": {"PROPOSE", "REJECT", "ERROR"},
    "PROPOSE": {"ACCEPT", "COUNTER", "REJECT", "ERROR"},
    "COUNTER": {"ACCEPT", "COUNTER", "REJECT", "ERROR"},
    "REQUEST_APPROVAL": {"REJECT", "ERROR"},
}

_TERMINAL_STATUSES = {"agreed", "failed"}
_WAITING_APPROVAL_STATUS = "waiting_approval"


def _reject(message: str, details: dict[str, object]) -> EnishiError:
    return EnishiError(
        code="INVALID_STATE_TRANSITION",
        message=message,
        status_code=409,
        details=details,
    )


def validate_incoming(
    current_status: str,
    last_sequence: int,
    message_type: str,
    sequence: int,
    *,
    last_message_type: str = "",
    counter_rounds: int = 0,
) -> None:
    """受信メッセージが状態機械上受理可能かを検証する。違反は409を送出する。"""
    if current_status in _TERMINAL_STATUSES:
        raise _reject(
            "終端したセッションへのメッセージは受理できません。",
            {"status": current_status, "message_type": message_type},
        )

    if current_status == _WAITING_APPROVAL_STATUS and message_type not in {"REJECT", "ERROR"}:
        raise _reject(
            "承認待ちのセッションでは新しい交渉メッセージを受理できません。",
            {"status": current_status, "message_type": message_type},
        )

    if sequence != last_sequence + 1:
        raise _reject(
            "sequenceが単調増加していません。",
            {"expected": last_sequence + 1, "received": sequence},
        )

    allowed = _ALLOWED_AFTER.get(last_message_type, set())
    if message_type not in allowed:
        raise _reject(
            f"{last_message_type or '開始前'} の後に {message_type} は受理できません。",
            {"last_message_type": last_message_type, "message_type": message_type},
        )

    if message_type == "COUNTER" and counter_rounds >= MAX_COUNTER_ROUNDS:
        raise _reject(
            "COUNTERのラウンド上限を超えています。",
            {"counter_rounds": counter_rounds, "max": MAX_COUNTER_ROUNDS},
        )
