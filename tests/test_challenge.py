from datetime import date


def test_first_day_not_behind(services):
    challenge, _ = services
    p = challenge.plan(date(2026, 10, 1))
    assert p["planned_completed_km"] == 0
    assert p["status"] == "on_track"


def test_plan_day_transition_and_month_end(services):
    challenge, _ = services
    # At start of Oct 2 one full day is expected.
    p = challenge.plan(date(2026, 10, 2))
    assert 32.2 < p["planned_completed_km"] < 32.3
    assert p["status"] == "behind"
    challenge.set_total(1000)
    p = challenge.plan(date(2026, 11, 1))
    assert p["remaining_days"] == 0
    assert p["remaining_km"] == 0


def test_delta_reset_session_and_implausible_jump(services):
    challenge, _ = services
    assert challenge.ingest_live_distance(10, session_id="A", today=date(2026,10,1)).delta_km == 0
    assert round(challenge.ingest_live_distance(10.5, session_id="A", today=date(2026,10,1)).delta_km, 3) == .5
    # Counter reset: no negative / duplicate km.
    r = challenge.ingest_live_distance(.1, session_id="A", today=date(2026,10,1))
    assert r.delta_km == 0 and r.reason == "counter_reset"
    assert challenge.state["total_km"] == .5
    # New session becomes baseline.
    r = challenge.ingest_live_distance(3, session_id="B", today=date(2026,10,1))
    assert r.delta_km == 0 and r.reason == "baseline"
    r = challenge.ingest_live_distance(9, session_id="B", today=date(2026,10,1))
    assert r.delta_km == 0 and r.reason == "implausible_jump"
    assert challenge.state["total_km"] == .5


def test_milestone_dedup_and_boss_replacement(services):
    challenge, _ = services
    challenge.set_total(98.9)
    challenge.state["last_live_distance"] = 0.0
    challenge.state["session_id"] = "A"
    challenge.store.save()
    r = challenge.ingest_live_distance(1.2, session_id="A", today=date(2026,10,5))
    types = [(x["type"], x.get("mark_km"), x.get("boss_type")) for x in r.triggers]
    assert ("MILESTONE_100", 100, None) in types
    assert ("BOSS_SPAWN", 100, "major") in types
    assert ("MILESTONE_10", 100, None) not in types
    # Restart-style baseline/data replay can't retrigger persisted mark.
    challenge.state["last_live_distance"] = 0.0
    challenge.store.save()
    r2 = challenge.ingest_live_distance(1.2, session_id="A", today=date(2026,10,5))
    assert not any(x.get("mark_km") == 100 for x in r2.triggers)


def test_back_on_track_transition(services):
    challenge, _ = services
    challenge.set_total(0)
    challenge.state["last_live_distance"] = 0
    challenge.state["session_id"] = "A"
    challenge.store.save()
    # Oct 2 expected is ~32.26; add plausible chunks.
    back = False
    distance = 0
    for _ in range(17):
        distance += 2
        r = challenge.ingest_live_distance(distance, session_id="A", today=date(2026,10,2))
        back = back or r.back_on_track
    assert back is True
