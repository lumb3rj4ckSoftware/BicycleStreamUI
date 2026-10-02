from __future__ import annotations

import heapq
import itertools
import time
import uuid
from collections import deque
from dataclasses import asdict, dataclass
from typing import Any


EVENT_PRIORITIES = {
    "GOAL_COMPLETE": 100,
    "BOSS_DEFEATED": 95,
    "BOSS_ESCAPED": 92,
    "MILESTONE_100": 88,
    "BOSS_INCOMING": 82,
    "BACK_ON_TRACK": 78,
    "SUB_CLIMB_2_STANDING": 72,
    "SUB_CLIMB_1": 68,
    "SUB_SPRINT": 64,
    "RAID_STANDING": 62,
    "MILESTONE_10": 55,
    "BOSS_HEAL": 45,
    "RIDER_BOOST": 44,
    "BOSS_HIT": 10,
}

EVENT_DURATIONS = {
    "GOAL_COMPLETE": 8.0,
    "MILESTONE_100": 5.0,
    "MILESTONE_10": 2.6,
    "BACK_ON_TRACK": 3.0,
    "BOSS_INCOMING": 3.0,
    "BOSS_DEFEATED": 6.0,
    "BOSS_ESCAPED": 5.0,
    "SUB_SPRINT": 3.0,
    "SUB_CLIMB_1": 3.5,
    "SUB_CLIMB_2_STANDING": 4.0,
    "RAID_STANDING": 4.0,
    "BOSS_HEAL": 2.2,
    "RIDER_BOOST": 2.2,
    "BOSS_HIT": 0.0,
}


@dataclass(slots=True)
class OverlayEvent:
    seq: int
    event_id: str
    type: str
    payload: dict[str, Any]
    priority: int
    created_at: float
    duration: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class EventManager:
    """Central event stream + priority scheduler for fullscreen callouts."""

    def __init__(self, history_size: int = 1200):
        self._counter = itertools.count(1)
        self._history: deque[OverlayEvent] = deque(maxlen=history_size)
        self._queue: list[tuple[int, int, OverlayEvent]] = []
        self._active: OverlayEvent | None = None
        self._active_until = 0.0
        self._dedupe: set[str] = set()

    def emit(
        self,
        event_type: str,
        payload: dict[str, Any] | None = None,
        *,
        priority: int | None = None,
        duration: float | None = None,
        dedupe_key: str | None = None,
    ) -> OverlayEvent | None:
        if dedupe_key and dedupe_key in self._dedupe:
            return None
        if dedupe_key:
            self._dedupe.add(dedupe_key)
        seq = next(self._counter)
        ev = OverlayEvent(
            seq=seq,
            event_id=str(uuid.uuid4()),
            type=event_type,
            payload=payload or {},
            priority=priority if priority is not None else EVENT_PRIORITIES.get(event_type, 30),
            created_at=time.time(),
            duration=duration if duration is not None else EVENT_DURATIONS.get(event_type, 3.0),
        )
        self._history.append(ev)
        # BOSS_HIT is a high-volume projectile event and is intentionally not a central text callout.
        if ev.duration > 0:
            heapq.heappush(self._queue, (-ev.priority, ev.seq, ev))
            if self._active and ev.priority >= self._active.priority + 20:
                self._active = None
                self._active_until = 0.0
        return ev

    def tick(self, now: float | None = None) -> None:
        now = now if now is not None else time.time()
        if self._active and now >= self._active_until:
            self._active = None
        if self._active is None and self._queue:
            _, _, ev = heapq.heappop(self._queue)
            self._active = ev
            self._active_until = now + ev.duration

    @property
    def active(self) -> dict[str, Any] | None:
        return self._active.to_dict() if self._active else None

    @property
    def last_seq(self) -> int:
        return self._history[-1].seq if self._history else 0

    def since(self, seq: int) -> list[dict[str, Any]]:
        return [ev.to_dict() for ev in self._history if ev.seq > seq]

    def clear_transient(self) -> None:
        self._queue.clear()
        self._active = None
        self._active_until = 0.0
