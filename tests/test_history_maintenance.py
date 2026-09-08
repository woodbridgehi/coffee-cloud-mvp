from app.history_maintenance import HistoryMaintenance


def test_expired_backlog_gets_multiple_bounded_passes_instead_of_hourly_cap():
    schedule = HistoryMaintenance(3600, 500)
    remaining = 6500
    now = 100
    passes = 0
    while remaining:
        assert schedule.due(now)
        deleted = min(remaining, 500)
        remaining -= deleted
        schedule.completed(now, {"events": deleted})
        assert not schedule.due(now + 1)
        now += 5
        passes += 1
    assert passes == 13
    assert schedule.due(now)
    schedule.completed(now, {"events": 0})
    assert not schedule.due(now + 5)
    assert schedule.due(now + 3600)
