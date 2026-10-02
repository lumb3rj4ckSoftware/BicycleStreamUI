from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

from .utils import atomic_write_json, utc_now_iso


DEFAULT_CHALLENGE_STATE: dict[str, Any] = {
    "version": 1,
    "total_km": 0.0,
    "daily_km": {},
    "session_id": None,
    "last_live_distance": None,
    "last_live_timestamp": None,
    "triggered_events": [],
    "last_plan_status": "on_track",
    "manual_adjustments": [],
}


class ChallengeStateStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = threading.RLock()
        self.state = self._load()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            state = json.loads(json.dumps(DEFAULT_CHALLENGE_STATE))
            atomic_write_json(self.path, state)
            return state
        try:
            with self.path.open("r", encoding="utf-8") as fh:
                raw = json.load(fh)
            state = json.loads(json.dumps(DEFAULT_CHALLENGE_STATE))
            state.update(raw if isinstance(raw, dict) else {})
            return state
        except (OSError, json.JSONDecodeError):
            backup = self.path.with_suffix(self.path.suffix + ".broken")
            try:
                self.path.replace(backup)
            except OSError:
                pass
            state = json.loads(json.dumps(DEFAULT_CHALLENGE_STATE))
            atomic_write_json(self.path, state)
            return state

    def save(self) -> None:
        with self._lock:
            atomic_write_json(self.path, self.state)

    def reset(self) -> None:
        with self._lock:
            self.state = json.loads(json.dumps(DEFAULT_CHALLENGE_STATE))
            self.save()


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS fights (
  fight_id TEXT PRIMARY KEY,
  boss_type TEXT NOT NULL,
  km_mark REAL,
  started_at TEXT NOT NULL,
  ended_at TEXT,
  result TEXT,
  start_hp INTEGER NOT NULL,
  remaining_hp INTEGER NOT NULL,
  duration_s REAL NOT NULL,
  rider_bonus_s REAL NOT NULL DEFAULT 0,
  medipacks INTEGER NOT NULL DEFAULT 0,
  simulation INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS fight_participants (
  fight_id TEXT NOT NULL,
  user_id TEXT NOT NULL,
  login TEXT,
  display_name TEXT,
  hit_count INTEGER NOT NULL DEFAULT 0,
  damage INTEGER NOT NULL DEFAULT 0,
  subscriber_hits INTEGER NOT NULL DEFAULT 0,
  multiplier INTEGER NOT NULL DEFAULT 1,
  medipack_used INTEGER NOT NULL DEFAULT 0,
  first_participation_at TEXT NOT NULL,
  last_participation_at TEXT NOT NULL,
  PRIMARY KEY (fight_id, user_id),
  FOREIGN KEY (fight_id) REFERENCES fights(fight_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS damage_totals (
  user_id TEXT PRIMARY KEY,
  login TEXT,
  display_name TEXT,
  damage INTEGER NOT NULL DEFAULT 0,
  hits INTEGER NOT NULL DEFAULT 0,
  fights INTEGER NOT NULL DEFAULT 0,
  wins INTEGER NOT NULL DEFAULT 0,
  first_damage_at TEXT,
  last_damage_at TEXT
);

CREATE TABLE IF NOT EXISTS reward_eligibility (
  reward_key TEXT PRIMARY KEY,
  fight_id TEXT NOT NULL,
  user_id TEXT NOT NULL,
  multiplier INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  processed INTEGER NOT NULL DEFAULT 0,
  UNIQUE (fight_id, user_id)
);

CREATE TABLE IF NOT EXISTS event_log (
  event_id TEXT PRIMARY KEY,
  event_type TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS admin_adjustments (
  adjustment_id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,
  amount REAL,
  payload_json TEXT,
  created_at TEXT NOT NULL
);
"""


class SQLiteStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path, timeout=10)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        return con

    def _init_db(self) -> None:
        with self._lock, self._connect() as con:
            con.executescript(SCHEMA)

    def log_event(self, event_id: str, event_type: str, payload: dict[str, Any]) -> bool:
        with self._lock, self._connect() as con:
            cur = con.execute(
                "INSERT OR IGNORE INTO event_log(event_id,event_type,payload_json,created_at) VALUES(?,?,?,?)",
                (event_id, event_type, json.dumps(payload, ensure_ascii=False), utc_now_iso()),
            )
            return cur.rowcount == 1

    def log_adjustment(self, kind: str, amount: float | None = None, payload: dict[str, Any] | None = None) -> None:
        with self._lock, self._connect() as con:
            con.execute(
                "INSERT INTO admin_adjustments(kind,amount,payload_json,created_at) VALUES(?,?,?,?)",
                (kind, amount, json.dumps(payload or {}, ensure_ascii=False), utc_now_iso()),
            )

    def start_fight(self, fight: dict[str, Any]) -> None:
        with self._lock, self._connect() as con:
            con.execute(
                """INSERT OR REPLACE INTO fights
                (fight_id,boss_type,km_mark,started_at,start_hp,remaining_hp,duration_s,rider_bonus_s,medipacks,simulation)
                VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (
                    fight["fight_id"], fight["boss_type"], fight.get("km_mark"), fight["started_at"],
                    int(fight["start_hp"]), int(fight["remaining_hp"]), float(fight["duration_s"]),
                    float(fight.get("rider_bonus_s", 0)), int(fight.get("medipacks", 0)), int(bool(fight.get("simulation"))),
                ),
            )

    def _ensure_damage_user(self, con: sqlite3.Connection, user_id: str, login: str, display_name: str, now: str, *, fight_delta: int = 0) -> None:
        con.execute(
            """INSERT INTO damage_totals(user_id,login,display_name,fights,first_damage_at,last_damage_at)
               VALUES(?,?,?,?,?,?)
               ON CONFLICT(user_id) DO UPDATE SET
                 login=excluded.login,
                 display_name=excluded.display_name,
                 fights=damage_totals.fights + excluded.fights,
                 last_damage_at=excluded.last_damage_at""",
            (user_id, login, display_name, fight_delta, now, now),
        )

    def record_hit(self, fight_id: str, user: dict[str, str], damage: int, subscriber: bool) -> None:
        now = utc_now_iso()
        uid = user["user_id"]
        login = user.get("login", "")
        display = user.get("display_name", login)
        with self._lock, self._connect() as con:
            exists = con.execute(
                "SELECT 1 FROM fight_participants WHERE fight_id=? AND user_id=?", (fight_id, uid)
            ).fetchone() is not None
            con.execute(
                """INSERT INTO fight_participants
                   (fight_id,user_id,login,display_name,hit_count,damage,subscriber_hits,multiplier,medipack_used,first_participation_at,last_participation_at)
                   VALUES(?,?,?,?,?,?,?,?,0,?,?)
                   ON CONFLICT(fight_id,user_id) DO UPDATE SET
                     login=excluded.login,
                     display_name=excluded.display_name,
                     hit_count=fight_participants.hit_count+1,
                     damage=fight_participants.damage+excluded.damage,
                     subscriber_hits=fight_participants.subscriber_hits+excluded.subscriber_hits,
                     multiplier=MAX(fight_participants.multiplier,excluded.multiplier),
                     last_participation_at=excluded.last_participation_at""",
                (fight_id, uid, login, display, 1, int(damage), 1 if subscriber else 0, 2 if subscriber else 1, now, now),
            )
            self._ensure_damage_user(con, uid, login, display, now, fight_delta=0 if exists else 1)
            con.execute(
                """UPDATE damage_totals
                   SET damage=damage+?, hits=hits+1,
                       first_damage_at=COALESCE(first_damage_at,?), last_damage_at=?
                   WHERE user_id=?""",
                (int(damage), now, now, uid),
            )

    def record_medipack(self, fight_id: str, user: dict[str, str]) -> bool:
        now = utc_now_iso()
        uid = user["user_id"]
        login = user.get("login", "")
        display = user.get("display_name", login)
        with self._lock, self._connect() as con:
            row = con.execute(
                "SELECT medipack_used FROM fight_participants WHERE fight_id=? AND user_id=?", (fight_id, uid)
            ).fetchone()
            if row and int(row["medipack_used"]):
                return False
            if row:
                con.execute(
                    "UPDATE fight_participants SET medipack_used=1,login=?,display_name=?,last_participation_at=? WHERE fight_id=? AND user_id=?",
                    (login, display, now, fight_id, uid),
                )
                self._ensure_damage_user(con, uid, login, display, now, fight_delta=0)
            else:
                con.execute(
                    """INSERT INTO fight_participants
                    (fight_id,user_id,login,display_name,hit_count,damage,subscriber_hits,multiplier,medipack_used,first_participation_at,last_participation_at)
                    VALUES(?,?,?,?,0,0,0,1,1,?,?)""",
                    (fight_id, uid, login, display, now, now),
                )
                self._ensure_damage_user(con, uid, login, display, now, fight_delta=1)
            con.execute("UPDATE fights SET medipacks=medipacks+1 WHERE fight_id=?", (fight_id,))
            return True

    def finish_fight(self, fight_id: str, result: str, remaining_hp: int, rider_bonus_s: float, medipacks: int) -> list[dict[str, Any]]:
        now = utc_now_iso()
        rewards: list[dict[str, Any]] = []
        with self._lock, self._connect() as con:
            existing = con.execute("SELECT result FROM fights WHERE fight_id=?", (fight_id,)).fetchone()
            if not existing:
                return rewards
            first_finish = existing["result"] is None
            con.execute(
                "UPDATE fights SET ended_at=COALESCE(ended_at,?),result=COALESCE(result,?),remaining_hp=?,rider_bonus_s=?,medipacks=? WHERE fight_id=?",
                (now, result, int(remaining_hp), float(rider_bonus_s), int(medipacks), fight_id),
            )
            if not first_finish or result != "won":
                return rewards
            participants = con.execute(
                "SELECT user_id,multiplier FROM fight_participants WHERE fight_id=?", (fight_id,)
            ).fetchall()
            for row in participants:
                uid = row["user_id"]
                multiplier = int(row["multiplier"] or 1)
                con.execute("UPDATE damage_totals SET wins=wins+1 WHERE user_id=?", (uid,))
                key = f"boss-win:{fight_id}:{uid}"
                cur = con.execute(
                    "INSERT OR IGNORE INTO reward_eligibility(reward_key,fight_id,user_id,multiplier,created_at) VALUES(?,?,?,?,?)",
                    (key, fight_id, uid, multiplier, now),
                )
                if cur.rowcount == 1:
                    rewards.append({"reward_key": key, "fight_id": fight_id, "user_id": uid, "multiplier": multiplier})
        return rewards

    def top_damage(self, limit: int = 5) -> list[dict[str, Any]]:
        with self._lock, self._connect() as con:
            rows = con.execute(
                """SELECT user_id,login,display_name,damage,hits,fights,wins
                   FROM damage_totals
                   WHERE damage>0
                   ORDER BY damage DESC,hits DESC,fights DESC,COALESCE(first_damage_at,'') ASC,user_id ASC
                   LIMIT ?""",
                (int(limit),),
            ).fetchall()
            return [dict(r) for r in rows]

    def user_damage(self, user_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as con:
            row = con.execute(
                "SELECT user_id,login,display_name,damage,hits,fights,wins,COALESCE(first_damage_at,'') AS first_damage_at FROM damage_totals WHERE user_id=?",
                (user_id,),
            ).fetchone()
            if not row:
                return None
            # Match top_damage's complete deterministic ordering, including all tie-breakers.
            ranked = con.execute(
                """SELECT user_id FROM damage_totals
                   WHERE damage>0
                   ORDER BY damage DESC,hits DESC,fights DESC,COALESCE(first_damage_at,'') ASC,user_id ASC"""
            ).fetchall()
            rank = next((i for i, candidate in enumerate(ranked, start=1) if candidate["user_id"] == user_id), None)
            out = dict(row)
            out.pop("first_damage_at", None)
            out["rank"] = int(rank) if rank is not None else None
            return out

    def search_damage(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        q = f"%{query.lower()}%"
        with self._lock, self._connect() as con:
            rows = con.execute(
                """SELECT user_id,login,display_name,damage,hits,fights,wins FROM damage_totals
                   WHERE LOWER(login) LIKE ? OR LOWER(display_name) LIKE ?
                   ORDER BY damage DESC,hits DESC LIMIT ?""",
                (q, q, int(limit)),
            ).fetchall()
            return [dict(r) for r in rows]

    def fight_participants(self, fight_id: str) -> list[dict[str, Any]]:
        with self._lock, self._connect() as con:
            rows = con.execute(
                "SELECT * FROM fight_participants WHERE fight_id=? ORDER BY damage DESC,hit_count DESC,user_id ASC", (fight_id,)
            ).fetchall()
            return [dict(r) for r in rows]

    def count(self, table: str) -> int:
        if table not in {"fights", "fight_participants", "damage_totals", "reward_eligibility", "event_log", "admin_adjustments"}:
            raise ValueError("unsupported table")
        with self._lock, self._connect() as con:
            return int(con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
