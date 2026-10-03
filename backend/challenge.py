from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from .persistence import ChallengeStateStore, SQLiteStore


@dataclass(slots=True)
class IngestResult:
    delta_km: float
    triggers: list[dict[str, Any]]
    back_on_track: bool
    reason: str = "ok"


class ChallengeService:
    def __init__(self, config: dict[str, Any], state_store: ChallengeStateStore, db: SQLiteStore | None = None):
        self.config = config
        self.store = state_store
        self.db = db

    @property
    def state(self) -> dict[str, Any]:
        return self.store.state

    def _cfg(self) -> dict[str, Any]:
        return self.config["challenge"]

    def _date(self, value: str) -> date:
        return date.fromisoformat(value)

    def plan(self, today: date | None = None, *, total_override: float | None = None, status_override: str | None = None) -> dict[str, Any]:
        today = today or date.today()
        c = self._cfg()
        start = self._date(c["start_date"])
        end = self._date(c["end_date"])
        target = float(c["target_km"])
        total = float(self.state["total_km"] if total_override is None else total_override)
        total_days = max(1, (end - start).days + 1)
        daily_target = target / total_days
        if today < start:
            passed_days = 0
            remaining_days = total_days
            today_target = 0.0
        elif today > end:
            passed_days = total_days
            remaining_days = 0
            today_target = 0.0
        else:
            # Current day is intentionally not counted as fully missed.
            passed_days = max(0, (today - start).days)
            remaining_days = (end - today).days + 1
            today_target = daily_target
        planned_completed = daily_target * passed_days
        diff = total - planned_completed
        tolerance = float(c.get("plan_tolerance_km", 1.0))
        if status_override:
            status = status_override
        elif diff < -tolerance:
            status = "behind"
        elif diff > tolerance:
            status = "ahead"
        else:
            status = "on_track"
        remaining_km = max(0.0, target - total)
        needed = remaining_km / remaining_days if remaining_days > 0 else (0.0 if remaining_km <= 0 else math.inf)
        return {
            "status": status,
            "planned_completed_km": round(planned_completed, 3),
            "ahead_behind_km": round(diff, 3),
            "daily_target_km": round(today_target, 3),
            "remaining_days": remaining_days,
            "remaining_km": round(remaining_km, 3),
            "needed_daily_avg_km": round(needed, 3) if math.isfinite(needed) else None,
            "total_days": total_days,
        }

    def _next_multiple(self, value: float, interval: int) -> int:
        return int((math.floor(value / interval) + 1) * interval)

    def snapshot(self, today: date | None = None, *, total_override: float | None = None, status_override: str | None = None) -> dict[str, Any]:
        today = today or date.today()
        c = self._cfg()
        total = float(self.state["total_km"] if total_override is None else total_override)
        target = float(c["target_km"])
        interval = int(c["milestone_interval_km"])
        major_interval = int(c["major_milestone_interval_km"])
        plan = self.plan(today, total_override=total, status_override=status_override)
        return {
            "title": c["title"],
            "target_km": target,
            "total_km": round(total, 3),
            "percent": round(min(100.0, max(0.0, total / target * 100.0)), 3),
            "remaining_km": plan["remaining_km"],
            "today_km": round(float(self.state.get("daily_km", {}).get(today.isoformat(), 0.0)), 3),
            "plan": plan,
            "next_10_km": min(int(target), self._next_multiple(total, interval)) if total < target else self._next_multiple(total, interval),
            "next_100_km": min(int(target), self._next_multiple(total, major_interval)) if total < target else self._next_multiple(total, major_interval),
            "major_markers": [x for x in range(major_interval, int(target) + 1, major_interval)],
            "start_date": c["start_date"],
            "end_date": c["end_date"],
        }

    def _trigger_key(self, kind: str, mark: int | float) -> str:
        return f"{kind}:{mark:g}"

    def _crossed_marks(self, before: float, after: float, interval: int, target: float) -> list[int]:
        if after <= before:
            return []
        first = (math.floor(before / interval) + 1) * interval
        marks: list[int] = []
        m = first
        while m <= after + 1e-9 and m <= target + 1e-9:
            marks.append(int(m))
            m += interval
        return marks

    def ingest_live_distance(self, distance_km: float, *, session_id: str | None, timestamp: float | None = None, today: date | None = None) -> IngestResult:
        today = today or date.today()
        state = self.state
        cfg = self._cfg()
        distance_km = max(0.0, float(distance_km))
        previous_status = self.plan(today)["status"]
        stored_session = state.get("session_id")
        baseline = state.get("last_live_distance")

        if baseline is None or (session_id and stored_session and session_id != stored_session):
            state["session_id"] = session_id or stored_session
            state["last_live_distance"] = distance_km
            state["last_live_timestamp"] = timestamp
            self.store.save()
            return IngestResult(0.0, [], False, "baseline")
        if session_id and not stored_session:
            state["session_id"] = session_id

        baseline = float(baseline)
        reset_threshold = float(cfg.get("reset_threshold_km", 0.05))
        if distance_km < baseline - reset_threshold:
            state["last_live_distance"] = distance_km
            state["last_live_timestamp"] = timestamp
            if session_id:
                state["session_id"] = session_id
            self.store.save()
            return IngestResult(0.0, [], False, "counter_reset")

        delta = distance_km - baseline
        state["last_live_distance"] = distance_km
        state["last_live_timestamp"] = timestamp
        if session_id:
            state["session_id"] = session_id
        if delta <= 0:
            self.store.save()
            return IngestResult(0.0, [], False, "no_positive_delta")
        max_delta = float(cfg.get("max_live_delta_km", 2.0))
        if delta > max_delta:
            self.store.save()
            return IngestResult(0.0, [], False, "implausible_jump")

        before = float(state["total_km"])
        after = before + delta
        state["total_km"] = after
        day_key = today.isoformat()
        state.setdefault("daily_km", {})[day_key] = float(state.get("daily_km", {}).get(day_key, 0.0)) + delta
        target = float(cfg["target_km"])
        minor = int(cfg["milestone_interval_km"])
        major = int(cfg["major_milestone_interval_km"])
        triggered = set(state.setdefault("triggered_events", []))
        out: list[dict[str, Any]] = []

        for mark in self._crossed_marks(before, after, minor, target):
            if mark % major == 0:
                continue
            key = self._trigger_key("milestone10", mark)
            if key not in triggered:
                triggered.add(key)
                out.append({"type": "MILESTONE_10", "mark_km": mark, "dedupe_key": key})
        for mark in self._crossed_marks(before, after, major, target):
            key = self._trigger_key("milestone100", mark)
            if key not in triggered and mark < target:
                triggered.add(key)
                out.append({"type": "MILESTONE_100", "mark_km": mark, "dedupe_key": key})
        if before < target <= after:
            key = self._trigger_key("goal", target)
            if key not in triggered:
                triggered.add(key)
                out.append({"type": "GOAL_COMPLETE", "mark_km": target, "dedupe_key": key})

        # Boss marks are independent from visual milestones.
        boss_cfg = self.config.get("boss", {})
        boss_interval = int(boss_cfg.get("interval_km", 20))
        boss_major = int(boss_cfg.get("major_interval_km", 100))
        for mark in self._crossed_marks(before, after, boss_interval, after):
            key = self._trigger_key("boss", mark)
            if key not in triggered:
                triggered.add(key)
                out.append({
                    "type": "BOSS_SPAWN",
                    "mark_km": mark,
                    "boss_type": "major" if mark % boss_major == 0 or abs(mark - target) < 1e-6 else "small",
                    "dedupe_key": key,
                })

        # The target always has a final boss, even if intervals do not divide it.
        if before < target <= after:
            key = self._trigger_key("boss", target)
            if key not in triggered:
                triggered.add(key)
                out.append({"type": "BOSS_SPAWN", "mark_km": target, "boss_type": "major", "dedupe_key": key})

        state["triggered_events"] = sorted(triggered)
        current_status = self.plan(today)["status"]
        back_on_track = previous_status == "behind" and current_status in {"on_track", "ahead"}
        state["last_plan_status"] = current_status
        self.store.save()
        return IngestResult(delta, out, back_on_track)

    def reset_session(self) -> None:
        self.state["session_id"] = None
        self.state["last_live_distance"] = None
        self.state["last_live_timestamp"] = None
        self.store.save()
        if self.db:
            self.db.log_adjustment("session_reset")

    def set_total(self, value: float) -> None:
        old = float(self.state["total_km"])
        self.state["total_km"] = max(0.0, float(value))
        self.store.save()
        if self.db:
            self.db.log_adjustment("set_total", self.state["total_km"] - old, {"old": old, "new": self.state["total_km"]})

    def adjust_total(self, delta: float) -> None:
        old = float(self.state["total_km"])
        self.state["total_km"] = max(0.0, old + float(delta))
        self.store.save()
        if self.db:
            self.db.log_adjustment("adjust_total", float(delta), {"old": old, "new": self.state["total_km"]})

    def set_today(self, value: float, today: date | None = None) -> None:
        today = today or date.today()
        key = today.isoformat()
        old = float(self.state.setdefault("daily_km", {}).get(key, 0.0))
        self.state["daily_km"][key] = max(0.0, float(value))
        self.store.save()
        if self.db:
            self.db.log_adjustment("set_today", float(value) - old, {"date": key, "old": old, "new": value})

    def full_reset(self) -> None:
        if self.db:
            self.db.log_adjustment("challenge_full_reset")
        self.store.reset()
