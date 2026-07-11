from twinlink_core.services.scheduling import candidate_slots, intersect_slots, overlaps

_DATE_RANGE = {"start": "2026-07-13", "end": "2026-07-13"}
_AFTERNOON = [{"start": "13:00", "end": "15:00"}]


def test_candidate_slots_within_preferred_ranges() -> None:
    slots = candidate_slots(_DATE_RANGE, _AFTERNOON, 30, busy=[])
    assert slots[0] == {"start": "2026-07-13T13:00", "end": "2026-07-13T13:30"}
    assert all(s["start"] >= "2026-07-13T13:00" for s in slots)
    assert all(s["end"] <= "2026-07-13T15:00" for s in slots)
    assert len(slots) == 4  # 13:00, 13:30, 14:00, 14:30


def test_candidate_slots_excludes_busy() -> None:
    busy = [{"start": "2026-07-13T13:00", "end": "2026-07-13T14:00"}]
    slots = candidate_slots(_DATE_RANGE, _AFTERNOON, 30, busy=busy)
    starts = [s["start"] for s in slots]
    assert "2026-07-13T13:00" not in starts
    assert "2026-07-13T13:30" not in starts
    assert "2026-07-13T14:00" in starts


def test_overlaps() -> None:
    slot = {"start": "2026-07-13T13:00", "end": "2026-07-13T13:30"}
    assert overlaps(slot, {"start": "2026-07-13T13:15", "end": "2026-07-13T14:00"})
    assert not overlaps(slot, {"start": "2026-07-13T13:30", "end": "2026-07-13T14:00"})


def test_intersect_slots() -> None:
    a = candidate_slots(_DATE_RANGE, _AFTERNOON, 30, busy=[])
    b = candidate_slots(
        _DATE_RANGE,
        _AFTERNOON,
        30,
        busy=[{"start": "2026-07-13T13:00", "end": "2026-07-13T14:00"}],
    )
    common = intersect_slots(a, b)
    assert common
    assert all(slot in a and slot in b for slot in common)


def test_intersect_slots_empty_when_no_common() -> None:
    a = candidate_slots(_DATE_RANGE, [{"start": "09:00", "end": "10:00"}], 30, busy=[])
    b = candidate_slots(_DATE_RANGE, [{"start": "13:00", "end": "14:00"}], 30, busy=[])
    assert intersect_slots(a, b) == []
