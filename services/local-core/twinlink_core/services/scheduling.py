"""日程計算（twinlink.md §27）。

空き時間の共通部分はLLMではなくPythonコードで決定的に計算する。
時刻はISO文字列（例 "2026-07-13T14:00"）で受け渡す。
"""

from datetime import date, datetime, time, timedelta
from typing import Any

_STEP_MINUTES = 30
_MAX_SLOTS = 20

Slot = dict[str, str]


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def _parse_time(value: str) -> time:
    return time.fromisoformat(value)


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value)


def overlaps(slot: Slot, busy_item: Slot) -> bool:
    """スロットとbusy区間が重なるかを判定する。"""
    slot_start = _parse_datetime(slot["start"])
    slot_end = _parse_datetime(slot["end"])
    busy_start = _parse_datetime(busy_item["start"])
    busy_end = _parse_datetime(busy_item["end"])
    return slot_start < busy_end and busy_start < slot_end


def candidate_slots(
    date_range: dict[str, str],
    preferred_time_ranges: list[dict[str, str]],
    duration_minutes: int,
    busy: list[Slot],
) -> list[Slot]:
    """期間内の優先時間帯を30分刻みで走査し、busyと重ならない候補を返す。"""
    start_date = _parse_date(date_range["start"])
    end_date = _parse_date(date_range["end"])
    duration = timedelta(minutes=duration_minutes)

    slots: list[Slot] = []
    current_date = start_date
    while current_date <= end_date and len(slots) < _MAX_SLOTS:
        for time_range in preferred_time_ranges:
            range_start = datetime.combine(current_date, _parse_time(time_range["start"]))
            range_end = datetime.combine(current_date, _parse_time(time_range["end"]))
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
    """両リストに共通する（start/endが一致する）スロットを返す。"""
    b_keys = {(slot["start"], slot["end"]) for slot in b}
    return [slot for slot in a if (slot["start"], slot["end"]) in b_keys]


def collect_busy(memories: list[Any]) -> list[Slot]:
    """schedule記憶のcontent["busy"]を集約する。"""
    busy: list[Slot] = []
    for memory in memories:
        if memory.memory_type != "schedule":
            continue
        for item in memory.content.get("busy", []):
            if isinstance(item, dict) and "start" in item and "end" in item:
                busy.append({"start": str(item["start"]), "end": str(item["end"])})
    return busy
