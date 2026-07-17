"""日程計算（enishi.md §27）。

空き時間の共通部分はLLMではなくPythonコードで決定的に計算する。
外部交渉ではUTC offset付きISO文字列を使い、異なるtimezoneの同一時刻を照合する。
"""

from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_STEP_MINUTES = 30
_MAX_SLOTS = 20

Slot = dict[str, str]


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def _parse_time(value: str) -> time:
    return time.fromisoformat(value)


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value)


def validate_timezone(value: str) -> ZoneInfo:
    try:
        return ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"unknown timezone: {value}") from exc


def overlaps(slot: Slot, busy_item: Slot) -> bool:
    """スロットとbusy区間が重なるかを判定する。"""
    slot_start = _parse_datetime(slot["start"])
    slot_end = _parse_datetime(slot["end"])
    busy_start = _parse_datetime(busy_item["start"])
    busy_end = _parse_datetime(busy_item["end"])
    slot_start, busy_start = _align_legacy_datetimes(slot_start, busy_start)
    slot_end, busy_end = _align_legacy_datetimes(slot_end, busy_end)
    return slot_start < busy_end and busy_start < slot_end


def candidate_slots(
    date_range: dict[str, str],
    preferred_time_ranges: list[dict[str, str]],
    duration_minutes: int,
    busy: list[Slot],
    timezone: str | None = None,
) -> list[Slot]:
    """期間内の優先時間帯を30分刻みで走査し、busyと重ならない候補を返す。"""
    start_date = _parse_date(date_range["start"])
    end_date = _parse_date(date_range["end"])
    duration = timedelta(minutes=duration_minutes)
    zone = validate_timezone(timezone) if timezone else None

    slots: list[Slot] = []
    current_date = start_date
    while current_date <= end_date and len(slots) < _MAX_SLOTS:
        for time_range in preferred_time_ranges:
            range_start = datetime.combine(
                current_date, _parse_time(time_range["start"]), tzinfo=zone
            )
            range_end = datetime.combine(
                current_date, _parse_time(time_range["end"]), tzinfo=zone
            )
            cursor = range_start
            while cursor + duration <= range_end and len(slots) < _MAX_SLOTS:
                slot: Slot = {
                    "start": cursor.isoformat(timespec="minutes"),
                    "end": (cursor + duration).isoformat(timespec="minutes"),
                }
                if not any(overlaps(slot, item) for item in busy):
                    slots.append(slot)
                cursor += timedelta(minutes=_STEP_MINUTES)
        current_date += timedelta(days=1)
    return slots


def intersect_slots(a: list[Slot], b: list[Slot]) -> list[Slot]:
    """offsetが異なっても、同じ瞬間のstart/endなら共通スロットとして返す。"""
    return [slot for slot in a if any(_same_slot(slot, other) for other in b)]


def _align_legacy_datetimes(left: datetime, right: datetime) -> tuple[datetime, datetime]:
    """v1のoffsetなし日時は、比較相手と同じローカルtimezoneとして扱う。"""
    if left.tzinfo is None and right.tzinfo is not None:
        left = left.replace(tzinfo=right.tzinfo)
    elif left.tzinfo is not None and right.tzinfo is None:
        right = right.replace(tzinfo=left.tzinfo)
    return left, right


def _same_slot(left: Slot, right: Slot) -> bool:
    left_start, right_start = _align_legacy_datetimes(
        _parse_datetime(left["start"]), _parse_datetime(right["start"])
    )
    left_end, right_end = _align_legacy_datetimes(
        _parse_datetime(left["end"]), _parse_datetime(right["end"])
    )
    if left_start.tzinfo is not None:
        left_start = left_start.astimezone(UTC)
        right_start = right_start.astimezone(UTC)
        left_end = left_end.astimezone(UTC)
        right_end = right_end.astimezone(UTC)
    return left_start == right_start and left_end == right_end


def _slot_key(slot: Slot) -> tuple[str, str]:
    values: list[str] = []
    for key in ("start", "end"):
        parsed = _parse_datetime(slot[key])
        values.append(
            parsed.astimezone(UTC).isoformat(timespec="minutes")
            if parsed.tzinfo is not None
            else parsed.isoformat(timespec="minutes")
        )
    return values[0], values[1]


def collect_busy(memories: list[Any], timezone: str | None = None) -> list[Slot]:
    """schedule記憶のcontent["busy"]を集約する。"""
    busy: list[Slot] = []
    for memory in memories:
        if memory.memory_type != "schedule":
            continue
        for item in memory.content.get("busy", []):
            if isinstance(item, dict) and "start" in item and "end" in item:
                slot = {"start": str(item["start"]), "end": str(item["end"])}
                if timezone:
                    zone = validate_timezone(timezone)
                    for key in ("start", "end"):
                        value = _parse_datetime(slot[key])
                        if value.tzinfo is None:
                            value = value.replace(tzinfo=zone)
                        slot[key] = value.isoformat(timespec="minutes")
                busy.append(slot)
    return busy
