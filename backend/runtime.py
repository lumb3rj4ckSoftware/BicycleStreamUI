from __future__ import annotations

import asyncio
import json
import logging
import logging.handlers
import os
import shutil
import time
from collections import deque
from copy import deepcopy
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .boss import BossEngine
from .challenge import ChallengeService
from .commands import ChatCommandService
from .config import PROJECT_ROOT, load_config, save_config, update_config
from .emotes import ThirdPartyEmoteResolver, emotes_from_fragments
from .events import EventManager
from .persistence import ChallengeStateStore, SQLiteStore
from .physical import PhysicalChallengeManager, gift_packages
from .trainer import FakeTrainerAdapter, TrainerControlService
from .twitch import TwitchGateway


class StreamRuntime:
    def __init__(self, *, root: Path | None = None, config_path: Path | None = None, trainer_adapter: Any = None):
        self.root = Path(root or PROJECT_ROOT)
        self.config_path = Path(config_path or (self.root / "config" / "challenge_config.json"))
        self.config = load_config(self.config_path)
        self.data_dir = self.root / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._configure_logging()
        self.log = logging.getLogger("bicyclestreamui")

        self.state_store = ChallengeStateStore(self.data_dir / "challenge_state.json")
        self.db = SQLiteStore(self.data_dir / "stream_state.sqlite")
        self.challenge = ChallengeService(self.config, self.state_store, self.db)
        self.events = EventManager()
        self.trainer = TrainerControlService(self.config, trainer_adapter)
        self.physical = PhysicalChallengeManager(self.config, self.trainer)
        self.boss = BossEngine(self.config, self.db, persist=True)
        self.sim_trainer = TrainerControlService(self.config, FakeTrainerAdapter())
        self.sim_physical = PhysicalChallengeManager(self.config, self.sim_trainer)
        self.sim_boss = BossEngine(self.config, None, persist=False)
        self.commands = ChatCommandService(self)

        self.telemetry: dict[str, Any] = {
            "distance": 0.0, "speed": 0.0, "avgspeed": 0.0, "power": 0.0,
            "avgpower": 0.0, "heartrate": 0.0, "cadence": 0.0,
            "timestamp": 0.0, "session_id": None, "source": "none",
        }
        self.telemetry_health = {"last_read": 0.0, "last_error": "", "bridge_file_exists": False}
        self.active_chatters: dict[str, float] = {}
        self.last_tick = time.time()
        self._tasks: list[asyncio.Task] = []
        self._twitch_task: asyncio.Task | None = None
        self._running = False
        self._last_bridge_mtime_ns = 0
        self._last_bridge_signature: tuple[Any, ...] | None = None

        self.simulation = {
            "active": False,
            "progress_percent": None,
            "plan_status": None,
            "telemetry": deepcopy(self.telemetry),
        }

        self.twitch = TwitchGateway(
            on_chat=self.on_twitch_chat,
            on_gift=self.on_twitch_gift,
            on_raid=self.on_twitch_raid,
            on_redemption=self.on_twitch_redemption,
            auth_path=self.data_dir / "twitch_auth.json",
            client_id=str(self.config.get("twitch", {}).get("client_id", "")),
        )
        self.emotes = ThirdPartyEmoteResolver(self.twitch.broadcaster_id)

    def _configure_logging(self) -> None:
        log_path = self.data_dir / "bicyclestreamui.log"
        cfg = self.config.get("server", {})
        root_logger = logging.getLogger("bicyclestreamui")
        if root_logger.handlers:
            return
        root_logger.setLevel(logging.INFO)
        handler = logging.handlers.RotatingFileHandler(
            log_path,
            maxBytes=int(cfg.get("log_max_bytes", 2_097_152)),
            backupCount=int(cfg.get("log_backup_count", 5)),
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        root_logger.addHandler(handler)
        stream = logging.StreamHandler()
        stream.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
        root_logger.addHandler(stream)

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._tasks = [
            asyncio.create_task(self._telemetry_loop(), name="telemetry-loop"),
            asyncio.create_task(self._tick_loop(), name="tick-loop"),
        ]
        if self.config.get("twitch", {}).get("third_party_emotes", True):
            self._tasks.append(asyncio.create_task(self._emote_refresh_loop(), name="emote-refresh"))
        self._tasks.append(asyncio.create_task(self.twitch.maintain_auth(), name="twitch-auth-maintenance"))
        await self._prepare_twitch_auth()
        await self._ensure_twitch_state()

    async def stop(self) -> None:
        self._running = False
        if self._twitch_task:
            await self.twitch.stop()
            self._twitch_task.cancel()
            self._twitch_task = None
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []
        try:
            self.trainer.restore()
        except Exception:
            pass

    async def _emote_refresh_loop(self) -> None:
        while self._running:
            await self._refresh_emotes_once()
            await asyncio.sleep(900)

    async def _refresh_emotes_once(self) -> None:
        try:
            await self.emotes.refresh()
            if self.emotes.last_errors:
                self.log.info("Third-party emote refresh partial errors: %s", self.emotes.last_errors)
        except Exception as exc:
            self.log.warning("Third-party emote refresh failed: %s", exc)

    def _medipack_config(self) -> dict[str, Any]:
        cfg = self.config.get("twitch", {})
        return {
            "title": str(cfg.get("medipack_reward_title", "Medipak")),
            "cost": int(cfg.get("medipack_reward_cost", 500)),
            "prompt": str(cfg.get("medipack_reward_prompt", "")),
        }

    async def _prepare_twitch_auth(self) -> None:
        if not self.twitch.token:
            return
        if not await self.twitch.validate_token():
            return
        self.emotes.broadcaster_id = self.twitch.broadcaster_id
        cfg = self.config.get("twitch", {})
        if self.config.get("features", {}).get("medipaks") and cfg.get("medipack_auto_create", True):
            try:
                await self.twitch.ensure_medipack_reward(**self._medipack_config())
            except Exception as exc:
                self.log.warning("Medipak reward could not be ensured on startup: %s", exc)

    async def _restart_twitch_task(self) -> None:
        if self._twitch_task:
            await self.twitch.stop()
            self._twitch_task.cancel()
            await asyncio.gather(self._twitch_task, return_exceptions=True)
            self._twitch_task = None
        self.twitch.running = False
        await self._ensure_twitch_state()

    async def _ensure_twitch_state(self) -> None:
        wanted = bool(self.config.get("features", {}).get("twitch_integration"))
        if wanted and not self._twitch_task and self.twitch.configured():
            self._twitch_task = asyncio.create_task(self.twitch.run(), name="twitch-eventsub")
        elif (not wanted or not self.twitch.configured()) and self._twitch_task:
            await self.twitch.stop()
            self._twitch_task.cancel()
            self._twitch_task = None

    def _bridge_path(self) -> Path:
        rel = self.config.get("server", {}).get("bridge_json", "gc_live.json")
        return self.root / rel

    async def _telemetry_loop(self) -> None:
        interval = float(self.config.get("server", {}).get("telemetry_interval_seconds", 0.5))
        while self._running:
            path = self._bridge_path()
            self.telemetry_health["bridge_file_exists"] = path.exists()
            try:
                if path.exists():
                    stat = path.stat()
                    if stat.st_mtime_ns != self._last_bridge_mtime_ns:
                        self._last_bridge_mtime_ns = stat.st_mtime_ns
                        raw = json.loads(path.read_text(encoding="utf-8"))
                        await self.process_telemetry(raw)
                        self.telemetry_health["last_read"] = time.time()
                        self.telemetry_health["last_error"] = ""
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.telemetry_health["last_error"] = str(exc)
                self.log.warning("Telemetry read failed: %s", exc)
            await asyncio.sleep(interval)

    async def process_telemetry(self, raw: dict[str, Any]) -> None:
        mapped = {
            "distance": float(raw.get("distance", 0.0) or 0.0),
            "speed": float(raw.get("speed", 0.0) or 0.0),
            "avgspeed": float(raw.get("avgspeed", 0.0) or 0.0),
            "power": float(raw.get("power", 0.0) or 0.0),
            "avgpower": float(raw.get("avgpower", 0.0) or 0.0),
            "heartrate": float(raw.get("heartrate", 0.0) or 0.0),
            "cadence": float(raw.get("cadence", 0.0) or 0.0),
            "timestamp": float(raw.get("timestamp", time.time()) or time.time()),
            "session_id": raw.get("session_id"),
            "source": raw.get("source", "bridge"),
        }
        self.telemetry = mapped
        if os.getenv("BICYCLE_DISABLE_DISTANCE_PERSIST", "0") == "1":
            return
        result = self.challenge.ingest_live_distance(
            mapped["distance"], session_id=mapped.get("session_id"), timestamp=mapped.get("timestamp")
        )
        if result.reason == "implausible_jump":
            self.log.warning("Ignored implausible live-distance jump to %.3f km", mapped["distance"])
        for trigger in result.triggers:
            await self._handle_distance_trigger(trigger)
        if result.back_on_track:
            self.events.emit("BACK_ON_TRACK", {"text": "BACK ON TRACK"})

    async def _handle_distance_trigger(self, trigger: dict[str, Any]) -> None:
        t = trigger["type"]
        if t == "MILESTONE_10" and self.config["features"].get("milestone_10"):
            self.events.emit(t, {"mark_km": trigger["mark_km"]}, dedupe_key=trigger.get("dedupe_key"))
        elif t == "MILESTONE_100" and self.config["features"].get("milestone_100"):
            self.events.emit(t, {"mark_km": trigger["mark_km"]}, dedupe_key=trigger.get("dedupe_key"))
        elif t == "GOAL_COMPLETE":
            self.events.emit(t, {"mark_km": trigger["mark_km"]}, dedupe_key=trigger.get("dedupe_key"))
        elif t == "BOSS_SPAWN" and self.config["features"].get("boss_battles"):
            if not self.boss.active:
                snap = self.boss.start(trigger["boss_type"], trigger["mark_km"], self.active_chatter_count())
                self.events.emit(
                    "BOSS_INCOMING",
                    {"boss_type": trigger["boss_type"], "mark_km": trigger["mark_km"], "hp": snap["start_hp"]},
                    dedupe_key=trigger.get("dedupe_key") + ":incoming" if trigger.get("dedupe_key") else None,
                )

    async def _tick_loop(self) -> None:
        while self._running:
            now = time.time()
            dt = max(0.0, min(1.5, now - self.last_tick))
            self.last_tick = now
            self.events.tick(now)
            if self.simulation["active"]:
                self.sim_physical.tick(now)
                ended = self.sim_boss.tick(now)
                if ended:
                    self._emit_boss_end(ended)
                if self.config["features"].get("rider_assist") and self.sim_boss.active:
                    added = self.sim_boss.rider_charge(self.simulation["telemetry"].get("speed", 0), dt)
                    if added:
                        self.events.emit("RIDER_BOOST", {"seconds": added, "simulation": True})
            else:
                self.physical.tick(now)
                ended = self.boss.tick(now)
                if ended:
                    self._emit_boss_end(ended)
                if self.config["features"].get("rider_assist") and self.boss.active:
                    added = self.boss.rider_charge(self.telemetry.get("speed", 0), dt)
                    if added:
                        self.events.emit("RIDER_BOOST", {"seconds": added})
            self._expire_chatters(now)
            await asyncio.sleep(0.2)

    def _expire_chatters(self, now: float | None = None) -> None:
        now = now or time.time()
        window = float(self.config["boss"].get("active_chatter_window_seconds", 300))
        stale = [uid for uid, ts in self.active_chatters.items() if now - ts > window]
        for uid in stale:
            self.active_chatters.pop(uid, None)

    def active_chatter_count(self) -> int:
        self._expire_chatters()
        return len(self.active_chatters)

    def _subscriber_from_chat(self, event: dict[str, Any]) -> bool:
        badges = event.get("badges") or []
        for badge in badges:
            set_id = str(badge.get("set_id", badge.get("id", ""))).lower()
            if set_id in {"subscriber", "founder"}:
                return True
        return bool(event.get("is_subscriber", False))

    def _user_from_event(self, event: dict[str, Any]) -> dict[str, str]:
        uid = str(event.get("chatter_user_id") or event.get("user_id") or "")
        login = str(event.get("chatter_user_login") or event.get("user_login") or uid)
        display = str(event.get("chatter_user_name") or event.get("user_name") or login)
        return {"user_id": uid, "login": login, "display_name": display}

    async def on_twitch_chat(self, event: dict[str, Any]) -> None:
        if not self.config["features"].get("twitch_integration"):
            return
        user = self._user_from_event(event)
        if not user["user_id"]:
            return
        self.active_chatters[user["user_id"]] = time.time()
        message = event.get("message") or {}
        text = str(message.get("text", ""))
        fragments = message.get("fragments") or []
        boss = self.sim_boss if self.simulation["active"] else self.boss
        if self.config["features"].get("boss_battles") and boss.active:
            emotes = emotes_from_fragments(fragments, self.emotes if self.config.get("twitch", {}).get("third_party_emotes", True) else None, text)
            if emotes:
                hit = boss.hit(user, subscriber=self._subscriber_from_chat(event), emote=emotes[0])
                if hit:
                    hit["emotes"] = emotes
                if hit:
                    self.events.emit("BOSS_HIT", hit, duration=0)
                    if hit.get("finished"):
                        self._emit_boss_end(hit["finished"])
        if self.config["features"].get("chat_commands"):
            reply = self.commands.handle(text, user["user_id"], user["display_name"])
            if reply:
                await self.twitch.send_chat(reply)

    async def on_twitch_gift(self, event: dict[str, Any]) -> None:
        if not self.config["features"].get("twitch_integration") or not self.config["features"].get("sub_challenges") or self.simulation["active"]:
            return
        count = int(event.get("total", 0) or 0)
        gifter = event.get("user_name") or "Anonymous"
        outcomes = self.physical.enqueue_gift(count)
        self._emit_gift_events(count, gifter, outcomes, simulation=False)

    def _emit_gift_events(self, count: int, gifter: str, outcomes: list[tuple[int, str]], *, simulation: bool) -> None:
        for package, outcome in outcomes:
            if package == 5:
                etype = "SUB_SPRINT"
                payload = {"gifter": gifter, "subs": count, "seconds": self.config["physical_challenges"]["sprint_5_seconds"], "mode": outcome}
            elif package == 10:
                etype = "SUB_CLIMB_1"
                payload = {"gifter": gifter, "subs": count, "grade": self.config["physical_challenges"]["climb_10_grade_percent"], "seconds": self.config["physical_challenges"]["climb_10_seconds"], "mode": outcome}
            else:
                etype = "SUB_CLIMB_2_STANDING"
                payload = {"gifter": gifter, "subs": count, "grade": self.config["physical_challenges"]["climb_15_grade_percent"], "seconds": self.config["physical_challenges"]["climb_15_seconds"], "mode": outcome}
            payload["simulation"] = simulation
            self.events.emit(etype, payload)

    async def on_twitch_raid(self, event: dict[str, Any]) -> None:
        if not self.config["features"].get("twitch_integration") or not self.config["features"].get("raid_challenges") or self.simulation["active"]:
            return
        viewers = int(event.get("viewers", 0) or 0)
        raider = str(event.get("from_broadcaster_user_name") or event.get("from_broadcaster_user_login") or "Raid")
        task, mode = self.physical.enqueue_raid(viewers)
        self.events.emit("RAID_STANDING", {"raider": raider, "viewers": viewers, "seconds": task.duration_s, "mode": mode})

    async def on_twitch_redemption(self, event: dict[str, Any]) -> None:
        if not self.config["features"].get("twitch_integration") or not self.config["features"].get("medipaks") or self.simulation["active"]:
            return
        reward = event.get("reward") or {}
        wanted_id = self.twitch.reward_id or os.getenv("TWITCH_MEDIPACK_REWARD_ID", "").strip()
        twitch_cfg = self.config.get("twitch", {})
        wanted_title = str(twitch_cfg.get("medipack_reward_title", "Medipak")).casefold()
        # Title fallback remains available only for explicit legacy/manual mode. In the default
        # auto-managed mode we accept only the reward created/tracked by this application.
        is_medipack = (wanted_id and str(reward.get("id", "")) == wanted_id) or (not wanted_id and not twitch_cfg.get("medipack_auto_create", True) and str(reward.get("title", "")).casefold() == wanted_title)
        if not is_medipack:
            return
        redemption_id = str(event.get("id", ""))
        if not self.boss.active:
            if redemption_id and self.twitch.reward_id:
                try:
                    await self.twitch.refund_redemption(redemption_id)
                    self.log.info("Refunded Medipak redemption outside bossfight: %s", redemption_id)
                except Exception as exc:
                    self.log.warning("Could not refund Medipak redemption outside bossfight: %s", exc)
            return
        result = self.boss.medipack(self._user_from_event(event))
        if result and result.get("applied"):
            result["redemption_id"] = redemption_id
            self.events.emit("BOSS_HEAL", result)
        elif redemption_id and self.twitch.reward_id:
            # Duplicate redemption by the same user/fight: do not keep the viewer's points.
            try:
                await self.twitch.refund_redemption(redemption_id)
                self.log.info("Refunded duplicate Medipak redemption: %s", redemption_id)
            except Exception as exc:
                self.log.warning("Could not refund duplicate Medipak redemption: %s", exc)

    def _emit_boss_end(self, summary: dict[str, Any]) -> None:
        if summary.get("result") == "won":
            self.events.emit("BOSS_DEFEATED", summary)
        else:
            self.events.emit("BOSS_ESCAPED", summary)

    def active_boss_snapshot(self) -> dict[str, Any] | None:
        return self.sim_boss.snapshot() if self.simulation["active"] else self.boss.snapshot()

    def _heat_level(self, speed: float) -> int:
        if not self.config["features"].get("speed_heat"):
            return 0
        h = self.config["heat"]
        if speed >= float(h["level3_kmh"]):
            return 3
        if speed >= float(h["level2_kmh"]):
            return 2
        if speed >= float(h["level1_kmh"]):
            return 1
        return 0

    def overlay_state(self) -> dict[str, Any]:
        sim = bool(self.simulation["active"])
        if sim:
            pct = self.simulation.get("progress_percent")
            target = float(self.config["challenge"]["target_km"])
            total_override = target * float(pct) / 100.0 if pct is not None else self.challenge.state["total_km"]
            challenge = self.challenge.snapshot(total_override=total_override, status_override=self.simulation.get("plan_status"))
            telemetry = deepcopy(self.simulation["telemetry"])
            physical = self.sim_physical.snapshot()
            boss = self.sim_boss.snapshot()
        else:
            challenge = self.challenge.snapshot()
            telemetry = deepcopy(self.telemetry)
            physical = self.physical.snapshot()
            boss = self.boss.snapshot()
        speed = float(telemetry.get("speed", 0) or 0)
        return {
            "server_time": time.time(),
            "simulation": sim,
            "challenge": challenge,
            "telemetry": telemetry,
            "heat_level": self._heat_level(speed),
            "physical": physical,
            "boss": boss,
            "event": self.events.active,
            "event_seq": self.events.last_seq,
            "features": deepcopy(self.config["features"]),
            "heat": deepcopy(self.config["heat"]),
            "trainer": self.trainer.snapshot(),
            "twitch": self.twitch.status(),
            "twitch_config": {
                "medipack_reward_title": str(self.config.get("twitch", {}).get("medipack_reward_title", "Medipak")),
                "medipack_reward_cost": int(self.config.get("twitch", {}).get("medipack_reward_cost", 500)),
                "medipack_reward_prompt": str(self.config.get("twitch", {}).get("medipack_reward_prompt", "")),
                "medipack_auto_create": bool(self.config.get("twitch", {}).get("medipack_auto_create", True)),
            },
            "health": deepcopy(self.telemetry_health),
            "active_chatters": self.active_chatter_count(),
        }

    def events_since(self, seq: int) -> list[dict[str, Any]]:
        return self.events.since(seq)

    def _refresh_service_configs(self) -> None:
        self.challenge.config = self.config
        self.trainer.config = self.config
        self.physical.config = self.config
        self.boss.config = self.config
        self.sim_trainer.config = self.config
        self.sim_physical.config = self.config
        self.sim_boss.config = self.config

    async def update_config_patch(self, patch: dict[str, Any]) -> dict[str, Any]:
        self.config = update_config(self.config, patch)
        save_config(self.config, self.config_path)
        self._refresh_service_configs()
        await self._ensure_twitch_state()
        return self.config

    def backup(self) -> list[str]:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = self.data_dir / "backups" / stamp
        backup_dir.mkdir(parents=True, exist_ok=True)
        outputs: list[str] = []
        for src in [self.data_dir / "challenge_state.json", self.data_dir / "stream_state.sqlite"]:
            if src.exists():
                dst = backup_dir / src.name
                shutil.copy2(src, dst)
                outputs.append(str(dst.relative_to(self.root)))
        return outputs

    def _simulation_start(self) -> dict[str, Any]:
        if self.boss.active or self.physical.active or self.physical.queue:
            raise ValueError("Simulation kann nicht starten, solange ein echter Boss/Physical Challenge aktiv ist")
        self.simulation["active"] = True
        self.simulation["progress_percent"] = self.challenge.snapshot()["percent"]
        self.simulation["plan_status"] = None
        self.simulation["telemetry"] = deepcopy(self.telemetry)
        self.sim_physical.queue.clear()
        self.sim_physical.active = None
        self.sim_boss.active = None
        self.sim_boss.last_result = None
        self.events.clear_transient()
        return self.overlay_state()

    def _simulation_stop(self) -> dict[str, Any]:
        self.simulation["active"] = False
        self.simulation["progress_percent"] = None
        self.simulation["plan_status"] = None
        self.sim_boss.active = None
        self.sim_physical.queue.clear()
        self.sim_physical.active = None
        self.events.clear_transient()
        return self.overlay_state()

    async def admin_action(self, action: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = payload or {}
        if action == "feature":
            name = str(payload["name"])
            if name in {"betting", "milestone_dedications"}:
                raise ValueError("Future hooks remain disabled by specification")
            if name not in self.config["features"]:
                raise ValueError("unknown feature")
            await self.update_config_patch({"features": {name: bool(payload["value"])}})
            if name == "trainer_control":
                self.trainer.enable() if payload["value"] else self.trainer.disable()
            return self.overlay_state()
        if action == "config_patch":
            await self.update_config_patch(payload)
            return self.overlay_state()
        if action == "twitch_auth_start":
            return await self.twitch.start_device_authorization()
        if action == "twitch_auth_poll":
            result = await self.twitch.poll_device_authorization()
            if result.get("status") == "authorized":
                self.emotes.broadcaster_id = self.twitch.broadcaster_id
                if self.config.get("twitch", {}).get("third_party_emotes", True):
                    asyncio.create_task(self._refresh_emotes_once(), name="emote-refresh-after-login")
                reward = None
                reward_error = ""
                if self.config["features"].get("medipaks") and self.config.get("twitch", {}).get("medipack_auto_create", True):
                    try:
                        reward = await self.twitch.ensure_medipack_reward(**self._medipack_config())
                    except Exception as exc:
                        reward_error = str(exc)
                        self.log.warning("Automatic Medipak creation failed: %s", exc)
                if not self.config["features"].get("twitch_integration"):
                    self.config = update_config(self.config, {"features": {"twitch_integration": True}})
                    save_config(self.config, self.config_path)
                    self._refresh_service_configs()
                await self._restart_twitch_task()
                result["reward"] = reward
                result["reward_error"] = reward_error
                result["state"] = self.overlay_state()
            return result
        if action == "twitch_logout":
            if self._twitch_task:
                await self.twitch.stop()
                self._twitch_task.cancel()
                await asyncio.gather(self._twitch_task, return_exceptions=True)
                self._twitch_task = None
            await self.twitch.logout(revoke=True)
            self.config = update_config(self.config, {"features": {"twitch_integration": False}})
            save_config(self.config, self.config_path)
            self._refresh_service_configs()
            return self.overlay_state()
        if action == "twitch_reward_ensure":
            self.config = update_config(self.config, {"twitch": {"medipack_auto_create": True}})
            save_config(self.config, self.config_path)
            self._refresh_service_configs()
            reward = await self.twitch.ensure_medipack_reward(**self._medipack_config())
            await self._restart_twitch_task()
            return {"ok": True, "reward": reward, "state": self.overlay_state()}
        if action == "twitch_reward_update":
            patch = {"twitch": {
                "medipack_reward_title": str(payload.get("title", self._medipack_config()["title"])),
                "medipack_reward_cost": max(1, int(payload.get("cost", self._medipack_config()["cost"]))),
                "medipack_reward_prompt": str(payload.get("prompt", self._medipack_config()["prompt"])),
                "medipack_auto_create": True,
            }}
            self.config = update_config(self.config, patch)
            save_config(self.config, self.config_path)
            self._refresh_service_configs()
            reward = await self.twitch.update_medipack_reward(**self._medipack_config())
            await self._restart_twitch_task()
            return {"ok": True, "reward": reward, "state": self.overlay_state()}
        if action == "twitch_reward_delete":
            result = await self.twitch.delete_medipack_reward(refund_unfulfilled=bool(payload.get("refund_unfulfilled", True)))
            self.config = update_config(self.config, {"twitch": {"medipack_auto_create": False}})
            save_config(self.config, self.config_path)
            self._refresh_service_configs()
            await self._restart_twitch_task()
            return {**result, "state": self.overlay_state()}
        if action == "twitch_redemptions":
            items = await self.twitch.list_medipack_redemptions(status=str(payload.get("status", "UNFULFILLED")), first=int(payload.get("first", 50)))
            return {"ok": True, "items": items}
        if action == "twitch_redemption_refund":
            item = await self.twitch.refund_redemption(str(payload["id"]))
            return {"ok": True, "item": item}
        if action == "twitch_redemption_fulfill":
            item = await self.twitch.update_redemption_status(str(payload["id"]), "FULFILLED")
            return {"ok": True, "item": item}
        if action == "challenge_set_total":
            self.challenge.set_total(float(payload["value"]))
        elif action == "challenge_adjust_total":
            self.challenge.adjust_total(float(payload["delta"]))
        elif action == "challenge_set_today":
            self.challenge.set_today(float(payload["value"]))
        elif action == "session_reset":
            self.challenge.reset_session()
        elif action == "challenge_reset":
            if str(payload.get("confirm", "")) != "RESET":
                raise ValueError("confirm must equal RESET")
            self.backup()
            self.challenge.full_reset()
        elif action == "backup":
            return {"ok": True, "files": self.backup()}
        elif action == "trainer_enable":
            return {"ok": True, "trainer": self.trainer.enable()}
        elif action == "trainer_disable":
            return {"ok": True, "trainer": self.trainer.disable()}
        elif action == "trainer_grade":
            return {"ok": True, "result": self.trainer.set_grade(float(payload["grade"]))}
        elif action == "trainer_restore":
            return {"ok": True, "result": self.trainer.restore()}
        elif action == "emergency_stop":
            self.physical.emergency_stop()
            self.sim_physical.emergency_stop()
            return {"ok": True, "trainer": self.trainer.snapshot()}
        elif action == "simulation_start":
            return self._simulation_start()
        elif action == "simulation_stop":
            return self._simulation_stop()
        elif action.startswith("sim_"):
            if not self.simulation["active"]:
                self._simulation_start()
            return self._admin_sim_action(action, payload)
        else:
            raise ValueError(f"unknown action: {action}")
        return self.overlay_state()

    def _admin_sim_action(self, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        if action == "sim_chat":
            text = str(payload.get("text", ""))[:500]
            user = {"user_id": str(payload.get("user_id", "sim-user")), "login": "simuser", "display_name": "SimUser"}
            emotes = emotes_from_fragments([], self.emotes, text)
            if self.sim_boss.active and emotes:
                hit = self.sim_boss.hit(user, subscriber=bool(payload.get("subscriber", False)), emote=emotes[0])
                if hit:
                    hit["emotes"] = emotes
                    self.events.emit("BOSS_HIT", hit, duration=0)
                    if hit.get("finished"):
                        self._emit_boss_end(hit["finished"])
            reply = self.commands.handle(text, user["user_id"], user["display_name"])
            return {"ok": True, "reply": reply or "Kein Befehl / Cooldown aktiv. Emotes werden bei aktivem Boss verarbeitet.", "simulation": True}
        elif action == "sim_progress":
            self.simulation["progress_percent"] = max(0.0, min(100.0, float(payload["percent"])))
        elif action == "sim_plan":
            status = str(payload["status"])
            if status == "back_on_track":
                self.events.emit("BACK_ON_TRACK", {"text": "BACK ON TRACK", "simulation": True})
                self.simulation["plan_status"] = "on_track"
            elif status in {"ahead", "on_track", "behind"}:
                self.simulation["plan_status"] = status
            else:
                raise ValueError("invalid plan status")
        elif action == "sim_heat":
            speed = float(payload["speed"])
            self.simulation["telemetry"].update({"speed": speed, "power": float(payload.get("power", 320)), "cadence": float(payload.get("cadence", 92))})
        elif action == "sim_event":
            etype = str(payload["type"])
            if etype == "MILESTONE_10":
                self.events.emit(etype, {"mark_km": int(payload.get("mark_km", 250)), "simulation": True})
            elif etype == "MILESTONE_100":
                self.events.emit(etype, {"mark_km": int(payload.get("mark_km", 500)), "simulation": True})
            elif etype == "GOAL_COMPLETE":
                self.events.emit(etype, {"mark_km": self.config["challenge"]["target_km"], "simulation": True})
            else:
                raise ValueError("unsupported simulated event")
        elif action == "sim_gift":
            count = int(payload["count"])
            outcomes = self.sim_physical.enqueue_gift(count)
            self._emit_gift_events(count, str(payload.get("gifter", "TestGifter")), outcomes, simulation=True)
        elif action == "sim_raid":
            viewers = int(payload["viewers"])
            task, mode = self.sim_physical.enqueue_raid(viewers)
            self.events.emit("RAID_STANDING", {"raider": payload.get("raider", "TestRaid"), "viewers": viewers, "seconds": task.duration_s, "mode": mode, "simulation": True})
        elif action == "sim_boss":
            boss_type = str(payload.get("boss_type", "small"))
            chatters = int(payload.get("chatters", 3))
            if self.sim_boss.active:
                self.sim_boss.finish("lost")
            snap = self.sim_boss.start(boss_type, float(payload.get("mark_km", 20 if boss_type == "small" else 100)), chatters, simulation=True)
            self.events.emit("BOSS_INCOMING", {"boss_type": boss_type, "mark_km": snap["km_mark"], "hp": snap["start_hp"], "simulation": True})
        elif action == "sim_hit":
            if not self.sim_boss.active:
                self.sim_boss.start("small", 20, int(payload.get("chatters", 3)), simulation=True)
            user = {"user_id": str(payload.get("user_id", "sim-user")), "login": str(payload.get("login", "simuser")), "display_name": str(payload.get("display_name", "SimUser"))}
            code = str(payload.get("emote", "Kappa"))
            emote = self.emotes.first_in_text(code)
            if not emote:
                known = {"Kappa": "25", "PogChamp": "305954156", "LUL": "425618", "HeyGuys": "30259"}
                eid = str(payload.get("emote_id") or known.get(code, ""))
                if not eid:
                    raise ValueError("Emote nicht im geladenen Katalog. Nutze Kappa, LUL, HeyGuys oder ein Kanal-/Global-Emote von 7TV/BTTV.")
                emote = {"id": eid, "code": code, "text": code, "provider": "Twitch", "url": f"https://static-cdn.jtvnw.net/emoticons/v2/{eid}/default/dark/3.0"}
            hit = self.sim_boss.hit(user, subscriber=bool(payload.get("subscriber", False)), emote=emote)
            if hit:
                self.events.emit("BOSS_HIT", hit, duration=0)
                if hit.get("finished"):
                    self._emit_boss_end(hit["finished"])
        elif action == "sim_medipack":
            if not self.sim_boss.active:
                self.sim_boss.start("small", 20, 3, simulation=True)
            user = {"user_id": str(payload.get("user_id", "sim-healer")), "login": str(payload.get("login", "simhealer")), "display_name": str(payload.get("display_name", "SimHealer"))}
            result = self.sim_boss.medipack(user)
            if result and result.get("applied"):
                self.events.emit("BOSS_HEAL", {**result, "simulation": True})
        elif action == "sim_rider_boost":
            if not self.sim_boss.active:
                self.sim_boss.start("small", 20, 3, simulation=True)
            seconds = self.sim_boss.add_rider_time(float(payload.get("seconds", self.config["boss"]["rider_bonus_seconds"])))
            self.events.emit("RIDER_BOOST", {"seconds": seconds, "simulation": True})
        elif action == "sim_boss_end":
            if self.sim_boss.active:
                summary = self.sim_boss.finish(str(payload.get("result", "won")))
                if summary:
                    self._emit_boss_end(summary)
        else:
            raise ValueError(f"unknown simulation action: {action}")
        return self.overlay_state()
