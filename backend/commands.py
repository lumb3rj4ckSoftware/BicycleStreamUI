from __future__ import annotations

import time
from typing import Any


class ChatCommandService:
    def __init__(self, runtime: Any):
        self.runtime = runtime
        self.last_used: dict[tuple[str, str], float] = {}

    def _cooldown_ok(self, command: str, user_id: str, now: float) -> bool:
        cooldown = float(self.runtime.config.get("twitch", {}).get("command_cooldown_seconds", 8))
        key = (command, user_id)
        last = self.last_used.get(key, 0)
        if now - last < cooldown:
            return False
        self.last_used[key] = now
        return True

    def handle(self, text: str, user_id: str, display_name: str = "") -> str | None:
        reply = self._handle(text, user_id, display_name)
        if reply and self.runtime.simulation["active"] and not reply.startswith("[SIM]"):
            return "[SIM] " + reply
        return reply

    def _handle(self, text: str, user_id: str, display_name: str = "") -> str | None:
        tokens = (text or "").strip().split(maxsplit=1)
        if not tokens:
            return None
        cmd = tokens[0].lower()
        if cmd not in {"!km", "!heute", "!plan", "!next", "!topdamage", "!damage", "!boss", "!october1000"}:
            return None
        now = time.time()
        if not self._cooldown_ok(cmd, user_id, now):
            return None
        simulation = self.runtime.simulation["active"]
        snap = self.runtime.overlay_state()["challenge"]
        if cmd == "!october1000":
            return "1000 km im Oktober: !km – Gesamtstand | !heute – Tageskilometer | !plan – Zeitplan | !next – nächste Kilometer-Marken | !boss – laufender Boss | !damage – dein Schaden und Rang | !topdamage – Damage-Rangliste | !october1000 – diese Befehlsübersicht. Greift Monster mit euren Emotes an!"
        if cmd == "!km":
            return f"{snap['total_km']:.1f}/{snap['target_km']:.0f} km ({snap['percent']:.1f} %) – noch {snap['remaining_km']:.1f} km."
        if cmd == "!heute":
            return f"Heute: {snap['today_km']:.1f} km | Tagesrichtwert: {snap['plan']['daily_target_km']:.1f} km."
        if cmd == "!plan":
            diff = snap["plan"]["ahead_behind_km"]
            word = "Vorsprung" if diff >= 0 else "Rückstand"
            needed = snap["plan"]["needed_daily_avg_km"]
            needed_text = f"{needed:.1f} km/Tag" if needed is not None else "Zielzeitraum vorbei"
            return f"{word}: {abs(diff):.1f} km | ab jetzt nötig: {needed_text}."
        if cmd == "!next":
            return f"Nächste Marken: {snap['next_10_km']} km / {snap['next_100_km']} km."
        if simulation and cmd in {"!damage", "!topdamage"}:
            fight = self.runtime.sim_boss.active
            participants = list(fight.participants.values()) if fight else (self.runtime.sim_boss.last_result or {}).get("participants", [])
            if cmd == "!damage":
                row = next((p for p in participants if p["user_id"] == user_id), None)
                return f"[SIM] {display_name or 'Du'}: {row['damage'] if row else 0} Damage im Testkampf (nicht gespeichert)."
            top = sorted(participants, key=lambda p: -p["damage"])[:5]
            return "[SIM] Top Damage: " + (" | ".join(f"{p['display_name']}: {p['damage']}" for p in top) or "noch keine Treffer")
        if cmd == "!topdamage":
            top = self.runtime.db.top_damage(5)
            if not top:
                return "Noch kein Boss-Damage gespeichert."
            return "Top Damage: " + " | ".join(f"{i+1}. {r['display_name'] or r['login']} {r['damage']}" for i, r in enumerate(top))
        if cmd == "!damage":
            row = self.runtime.db.user_damage(user_id)
            if not row:
                return f"{display_name or 'Du'}: noch kein Lifetime-Damage."
            return f"{display_name or row['display_name']}: Rang #{row['rank']} – {row['damage']} Damage, {row['fights']} Kämpfe, {row['wins']} Siege."
        if cmd == "!boss":
            boss = self.runtime.active_boss_snapshot()
            if not boss:
                return "Aktuell ist kein Boss aktiv."
            return f"Boss: {boss['hp']}/{boss['start_hp']} HP, noch {boss['remaining_s']:.0f}s, {boss['participant_count']} Teilnehmer."
        return None
