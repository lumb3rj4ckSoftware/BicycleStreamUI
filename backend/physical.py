from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, asdict
from typing import Any

from .trainer import TrainerControlService


@dataclass
class PhysicalTask:
    task_id: str
    kind: str
    label: str
    duration_s: float
    grade_percent: float | None = None
    standing: bool = False
    source: str = ""
    created_at: float = 0.0
    started_at: float | None = None
    end_at: float | None = None

    def snapshot(self, now: float | None = None) -> dict[str, Any]:
        now = now if now is not None else time.time()
        out = asdict(self)
        out["remaining_s"] = max(0.0, (self.end_at or now) - now) if self.started_at is not None else self.duration_s
        return out


def gift_packages(count: int, strategy: str = "highest_once_then_fives") -> list[int]:
    count = int(count)
    if count in {5, 10, 15}:
        return [count]
    if count < 5 or count % 5:
        return []
    if strategy == "exact_only":
        return []
    if strategy == "fives_only":
        return [5] * (count // 5)
    if strategy == "repeat_highest_then_fives":
        out: list[int] = []
        remaining = count
        while remaining >= 15:
            out.append(15)
            remaining -= 15
        if remaining == 10:
            out.append(10)
        elif remaining == 5:
            out.append(5)
        return out
    # Final specification default: one highest matching package, remainder as fives.
    if count > 15:
        return [15] + [5] * ((count - 15) // 5)
    return []


class PhysicalChallengeManager:
    def __init__(self, config: dict[str, Any], trainer: TrainerControlService):
        self.config = config
        self.trainer = trainer
        self.queue: list[PhysicalTask] = []
        self.active: PhysicalTask | None = None

    def _task(self, kind: str, label: str, duration: float, *, grade: float | None = None, standing: bool = False, source: str = "") -> PhysicalTask:
        return PhysicalTask(str(uuid.uuid4()), kind, label, float(duration), grade, standing, source, time.time())

    def task_for_package(self, package: int, source: str = "gift") -> PhysicalTask:
        pc = self.config["physical_challenges"]
        if package == 5:
            return self._task("sprint", "SPRINT", pc["sprint_5_seconds"], source=source)
        if package == 10:
            return self._task("climb", "CLIMB 1%", pc["climb_10_seconds"], grade=pc["climb_10_grade_percent"], source=source)
        if package == 15:
            return self._task("standing_climb", "STANDING + CLIMB 2%", pc["climb_15_seconds"], grade=pc["climb_15_grade_percent"], standing=True, source=source)
        raise ValueError(f"unsupported gift package: {package}")

    def enqueue(self, task: PhysicalTask, now: float | None = None) -> str:
        now = now if now is not None else time.time()
        # Only a normal 5-sub sprint explicitly stacks by extending remaining time.
        if self.active and self.active.kind == "sprint" and task.kind == "sprint" and self.active.end_at is not None:
            self.active.end_at += task.duration_s
            return "extended"
        self.queue.append(task)
        self.tick(now)
        return "queued" if self.active is not task else "started"

    def enqueue_gift(self, count: int, now: float | None = None) -> list[tuple[int, str]]:
        strategy = self.config["physical_challenges"].get("higher_multiple_strategy", "highest_once_then_fives")
        packages = gift_packages(count, strategy)
        out: list[tuple[int, str]] = []
        for package in packages:
            out.append((package, self.enqueue(self.task_for_package(package), now=now)))
        return out

    def enqueue_raid(self, viewers: int, now: float | None = None) -> tuple[PhysicalTask, str]:
        pc = self.config["physical_challenges"]
        seconds = max(0, int(viewers))
        if pc.get("raid_cap_enabled"):
            seconds = min(seconds, int(pc.get("raid_cap_seconds", seconds)))
        task = self._task("raid_standing", f"RAID // STANDING", seconds, standing=True, source="raid")
        return task, self.enqueue(task, now=now)

    def _start(self, task: PhysicalTask, now: float) -> None:
        task.started_at = now
        task.end_at = now + task.duration_s
        self.active = task
        if task.grade_percent is not None:
            self.trainer.set_grade(task.grade_percent)

    def tick(self, now: float | None = None) -> None:
        now = now if now is not None else time.time()
        if self.active and self.active.end_at is not None and now >= self.active.end_at:
            if self.active.grade_percent is not None:
                self.trainer.restore()
            self.active = None
        if self.active is None and self.queue:
            task = self.queue.pop(0)
            self._start(task, now)

    def emergency_stop(self) -> None:
        self.queue.clear()
        self.active = None
        self.trainer.emergency_restore()

    def snapshot(self, now: float | None = None) -> dict[str, Any]:
        now = now if now is not None else time.time()
        return {
            "active": self.active.snapshot(now) if self.active else None,
            "queue_length": len(self.queue),
            "queued": [t.snapshot(now) for t in self.queue[:4]],
        }
