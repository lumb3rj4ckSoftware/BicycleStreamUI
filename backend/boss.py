from __future__ import annotations

import time
import uuid
import random

from .monsters import MONSTERS
from dataclasses import dataclass, field
from typing import Any

from .persistence import SQLiteStore
from .utils import clamp, utc_now_iso


@dataclass
class ActiveFight:
    fight_id: str
    boss_type: str
    km_mark: float | None
    start_hp: int
    hp: int
    duration_s: float
    started_at_epoch: float
    end_at_epoch: float
    started_at: str
    monster_id: str = "ember-dragon"
    monster_name: str = "Emberfang"
    final_boss: bool = False
    scaling_chatters: int = 0
    rider_bonus_s: float = 0.0
    medipacks: int = 0
    rider_charge: float = 0.0
    participants: dict[str, dict[str, Any]] = field(default_factory=dict)
    medipack_users: set[str] = field(default_factory=set)
    simulation: bool = False

    def snapshot(self, now: float | None = None) -> dict[str, Any]:
        now = now if now is not None else time.time()
        top = sorted(self.participants.values(), key=lambda p: (-int(p.get("damage", 0)), -int(p.get("hits", 0)), p.get("user_id", "")))[:3]
        return {
            "fight_id": self.fight_id,
            "boss_type": self.boss_type,
            "monster_id": self.monster_id,
            "monster_name": self.monster_name,
            "scaling_chatters": self.scaling_chatters,
            "final_boss": self.final_boss,
            "km_mark": self.km_mark,
            "start_hp": self.start_hp,
            "hp": self.hp,
            "hp_percent": round(100.0 * self.hp / self.start_hp, 2) if self.start_hp else 0,
            "duration_s": self.duration_s,
            "remaining_s": max(0.0, self.end_at_epoch - now),
            "participant_count": len(self.participants),
            "top3": top,
            "rider_bonus_s": self.rider_bonus_s,
            "rider_charge": self.rider_charge,
            "medipacks": self.medipacks,
            "simulation": self.simulation,
        }


class BossEngine:
    def __init__(self, config: dict[str, Any], store: SQLiteStore | None, *, persist: bool = True):
        self.config = config
        self.store = store
        self.persist = persist
        self.active: ActiveFight | None = None
        self.last_result: dict[str, Any] | None = None
        self._monster_deck = []

    def hp_for(self, boss_type: str, active_chatters: int) -> int:
        b = self.config["boss"]
        active_chatters = max(0, int(active_chatters))
        if boss_type == "major":
            hp = float(b["major_hp_base"]) + active_chatters * float(b["major_hp_per_chatter"])
            return int(round(clamp(hp, float(b["major_hp_min"]), float(b["major_hp_max"]))))
        hp = float(b["small_hp_base"]) + active_chatters * float(b["small_hp_per_chatter"])
        return int(round(clamp(hp, float(b["small_hp_min"]), float(b["small_hp_max"]))))

    def start(self, boss_type: str, km_mark: float | None, active_chatters: int, *, now: float | None = None, simulation: bool = False) -> dict[str, Any]:
        if self.active:
            return self.active.snapshot(now)
        now = now if now is not None else time.time()
        final_boss = km_mark is not None and abs(float(km_mark) - float(self.config["challenge"]["target_km"])) < 1e-6
        if final_boss:
            boss_type = "major"
        b = self.config["boss"]
        duration = float(b["major_duration_seconds"] if boss_type == "major" else b["small_duration_seconds"])
        hp = self.hp_for(boss_type, active_chatters)
        if not self._monster_deck:
            self._monster_deck = random.sample(MONSTERS, len(MONSTERS))
        monster = self._monster_deck.pop()
        fight = ActiveFight(
            fight_id=str(uuid.uuid4()), boss_type=boss_type, km_mark=km_mark, start_hp=hp, hp=hp,
            duration_s=duration, started_at_epoch=now, end_at_epoch=now + duration,
            started_at=utc_now_iso(), simulation=simulation,
            final_boss=final_boss, monster_id=monster["id"], monster_name=monster["name"], scaling_chatters=max(0, int(active_chatters)),
        )
        self.active = fight
        if self.persist and self.store and not simulation:
            self.store.start_fight({
                "fight_id": fight.fight_id, "boss_type": boss_type, "km_mark": km_mark,
                "started_at": fight.started_at, "start_hp": hp, "remaining_hp": hp,
                "duration_s": duration, "rider_bonus_s": 0, "medipacks": 0, "simulation": False,
            })
        return fight.snapshot(now)

    def _local_participant(self, user: dict[str, str]) -> dict[str, Any]:
        assert self.active
        uid = user["user_id"]
        if uid not in self.active.participants:
            self.active.participants[uid] = {
                "user_id": uid,
                "login": user.get("login", ""),
                "display_name": user.get("display_name", user.get("login", "")),
                "hits": 0,
                "damage": 0,
                "multiplier": 1,
                "medipack_used": False,
            }
        else:
            self.active.participants[uid]["login"] = user.get("login", self.active.participants[uid].get("login", ""))
            self.active.participants[uid]["display_name"] = user.get("display_name", self.active.participants[uid].get("display_name", ""))
        return self.active.participants[uid]

    def hit(self, user: dict[str, str], *, subscriber: bool, emote: dict[str, Any], now: float | None = None) -> dict[str, Any] | None:
        if not self.active:
            return None
        now = now if now is not None else time.time()
        damage = 2 if subscriber else 1
        fight = self.active
        p = self._local_participant(user)
        p["hits"] += 1
        p["damage"] += damage
        p["multiplier"] = max(int(p.get("multiplier", 1)), 2 if subscriber else 1)
        fight.hp = max(0, fight.hp - damage)
        if self.persist and self.store and not fight.simulation:
            self.store.record_hit(fight.fight_id, user, damage, subscriber)
        result = {
            "fight_id": fight.fight_id,
            "user": user,
            "damage": damage,
            "subscriber": subscriber,
            "emote": emote,
            "hp": fight.hp,
            "start_hp": fight.start_hp,
        }
        if fight.hp <= 0:
            result["finished"] = self.finish("won", now=now)
        return result

    def medipack(self, user: dict[str, str], *, now: float | None = None) -> dict[str, Any] | None:
        if not self.active:
            return None
        uid = user["user_id"]
        fight = self.active
        if uid in fight.medipack_users:
            return {"applied": False, "reason": "already_used", "user": user}
        if self.persist and self.store and not fight.simulation:
            if not self.store.record_medipack(fight.fight_id, user):
                fight.medipack_users.add(uid)
                return {"applied": False, "reason": "already_used", "user": user}
        fight.medipack_users.add(uid)
        p = self._local_participant(user)
        p["medipack_used"] = True
        bonus = float(self.config["boss"].get("medipack_seconds", 10))
        fight.end_at_epoch += bonus
        fight.medipacks += 1
        return {"applied": True, "seconds": bonus, "user": user, "fight_id": fight.fight_id}

    def add_rider_time(self, seconds: float) -> float:
        if not self.active:
            return 0.0
        b = self.config["boss"]
        cap = float(b["rider_major_cap_seconds"] if self.active.boss_type == "major" else b["rider_small_cap_seconds"])
        remaining_cap = max(0.0, cap - self.active.rider_bonus_s)
        added = min(float(seconds), remaining_cap)
        if added > 0:
            self.active.end_at_epoch += added
            self.active.rider_bonus_s += added
        return added

    def rider_charge(self, speed_kmh: float, dt: float) -> float:
        if not self.active or dt <= 0:
            return 0.0
        b = self.config["boss"]
        speed = float(speed_kmh)
        if speed >= 40:
            rate = float(b["rider_charge_40"])
        elif speed >= 35:
            rate = float(b["rider_charge_35"])
        elif speed >= 30:
            rate = float(b["rider_charge_30"])
        else:
            rate = 0.0
        self.active.rider_charge += rate * dt
        required = float(b.get("rider_charge_required", 100.0))
        added_total = 0.0
        while self.active.rider_charge >= required:
            added = self.add_rider_time(float(b.get("rider_bonus_seconds", 10)))
            if added <= 0:
                self.active.rider_charge = min(self.active.rider_charge, required)
                break
            added_total += added
            self.active.rider_charge -= required
        return added_total

    def tick(self, now: float | None = None) -> dict[str, Any] | None:
        if not self.active:
            return None
        now = now if now is not None else time.time()
        if now >= self.active.end_at_epoch:
            return self.finish("lost", now=now)
        return None

    def finish(self, result: str, *, now: float | None = None) -> dict[str, Any] | None:
        if not self.active:
            return None
        now = now if now is not None else time.time()
        fight = self.active
        summary = fight.snapshot(now)
        summary["result"] = result
        summary["ended_at"] = utc_now_iso()
        rewards: list[dict[str, Any]] = []
        if self.persist and self.store and not fight.simulation:
            rewards = self.store.finish_fight(fight.fight_id, result, fight.hp, fight.rider_bonus_s, fight.medipacks)
            summary["participants"] = self.store.fight_participants(fight.fight_id)
        else:
            summary["participants"] = sorted(fight.participants.values(), key=lambda x: (-x.get("damage", 0), x.get("user_id", "")))
        summary["reward_eligibility"] = rewards
        self.last_result = summary
        self.active = None
        return summary

    def snapshot(self, now: float | None = None) -> dict[str, Any] | None:
        return self.active.snapshot(now) if self.active else None
