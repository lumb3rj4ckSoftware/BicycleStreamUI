#!/usr/bin/env python3
"""
bridge.py

Schreibt zyklisch eine Datei `gc_live.json`, die von overlay_stein_cycling.html
gelesen werden kann.

Modi:
- test:  Simuliert Trainingsdaten (für Entwicklung / Overlay-Test)
- ant:   Liest echte Daten über `python -u -m openant scan --logging ERROR -a`
         und parst stdout in einem Thread
"""

import argparse
import dataclasses
import json
import os
import random
import re
import signal
import subprocess
import sys
import time
import threading
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# IDs – aktuell nicht zum Filtern benutzt, aber behalten falls du später willst
# ---------------------------------------------------------------------------

HR_DEVICE_ID = 8118       # HeartRate
PM_DEVICE_ID = 35165      # Powermeter (Pedale)
FE_DEVICE_ID = 34628      # KICKR Core 2 als FitnessEquipment (Speed)


@dataclass
class Metrics:
    distance: float   # km
    speed: float      # km/h (aktuell)
    avgspeed: float   # km/h (Durchschnitt)
    power: float      # W (aktuell)
    avgpower: float   # W (Durchschnitt)
    heartrate: float  # bpm
    cadence: float    # rpm
    timestamp: float  # Unix-Timestamp (Sekunden seit Epoch)


def atomic_write_json(path: str, obj) -> None:
    """
    Windows-freundlicher Schreibprozess:
    - erst in path.tmp schreiben und fsyncen (nur Writer benutzt diese Datei)
    - danach direkt in path schreiben
    - PermissionError beim Schreiben von path abfangen, damit die Bridge weiterläuft
    """
    tmp_path = f"{path}.tmp"

    # 1) In die TMP-Datei schreiben und sicher flushen
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(obj, f)
            f.flush()
            try:
                os.fsync(f.fileno())
            except (OSError, AttributeError):
                # fsync ist unter Windows nicht immer nötig/verfügbar, ignorieren
                pass
    except Exception as e:
        # Wenn schon das Schreiben der TMP-Datei schiefgeht, loggen und abbrechen
        print(f"\n[bridge.py] Fehler beim Schreiben von {tmp_path}: {e}", file=sys.stderr)
        return

    # 2) Hauptdatei schreiben (kann vom Browser kurzzeitig gelockt sein)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f)
    except PermissionError:
        # Overlay/Browsersource hält evtl. kurz einen Lock – einfach diesen Zyklus skippen
        print(
            f"\n[bridge.py] Warnung: PermissionError beim Schreiben von {path} – Zyklus übersprungen.",
            file=sys.stderr,
        )
    except Exception as e:
        print(f"\n[bridge.py] Fehler beim Schreiben von {path}: {e}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Konsolen-Ausgabe synchronisieren: Dist-Zeile immer unten halten
# ---------------------------------------------------------------------------

stdout_lock = threading.Lock()
_last_status_line = ""


def _build_status_line(metrics: Metrics) -> str:
    return (
        f"Dist: {metrics.distance:6.2f} km | "
        f"v: {metrics.speed:5.1f} km/h (Ø {metrics.avgspeed:5.1f}) | "
        f"P: {metrics.power:5.1f} W (Ø {metrics.avgpower:5.0f}) | "
        f"HR: {metrics.heartrate:5.1f} bpm | "
        f"CAD: {metrics.cadence:5.1f} rpm"
    )


def print_status_line(metrics: Metrics) -> None:
    """
    Zeichnet die Dist/Speed/Power/HR/CAD-Zeile als letzte Zeile im Terminal.
    Vor der Statuszeile wird bewusst eine Leerzeile erzeugt.
    """
    global _last_status_line
    line = _build_status_line(metrics)
    with stdout_lock:
        _last_status_line = line

        # Eine Zeile runter + aktuelle Zeile löschen + neue Statuszeile
        sys.stdout.write("\r\x1b[2K")          # aktuelle Zeile löschen
        sys.stdout.write("\n")                # Leerzeile erzeugen
        sys.stdout.write("\r\x1b[2K" + line)  # Statuszeile schreiben
        sys.stdout.flush()


def log_ant_line(line: str) -> None:
    """
    Schreibt einen ANT-Log *über* der Statuszeile.
    Die Statuszeile bleibt unten stehen und wird nach dem Log neu gezeichnet.
    """
    with stdout_lock:
        # aktuelle Statuszeile löschen
        sys.stdout.write("\r\x1b[2K")

        # Log ausgeben
        sys.stdout.write(f"[ANT] {line}\n")

        # Leerzeile + Statuszeile neu visualisieren
        if _last_status_line:
            sys.stdout.write("\n\r\x1b[2K" + _last_status_line)

        sys.stdout.flush()



# ---------------------------------------------------------------------------
# TEST-SIMULATOR (für Overlay-Entwicklung)
# ---------------------------------------------------------------------------

class TestSimulator:
    def __init__(self):
        self.start_time = time.time()
        self.last_time = self.start_time

        self.speed = 0.0
        self.power = 0.0
        self.hr = 80.0
        self.cad = 0.0

        self.target_speed = 25.0
        self.target_power = 180.0
        self.target_hr = 140.0
        self.target_cad = 85.0

        self.last_target_change = self.start_time

        self.distance_km = 0.0
        self.energy_j = 0.0

    def _smooth_step(self, current, target, factor, noise):
        base = current + (target - current) * factor
        return max(0.0, base + random.uniform(-noise, noise))

    def _maybe_change_targets(self, now):
        if now - self.last_target_change < random.uniform(10.0, 30.0):
            return
        self.last_target_change = now
        phase = random.random()
        if phase < 0.2:
            self.target_speed = random.uniform(20.0, 28.0)
            self.target_power = random.uniform(100.0, 180.0)
            self.target_hr = random.uniform(120.0, 145.0)
            self.target_cad = random.uniform(75.0, 90.0)
        elif phase < 0.8:
            self.target_speed = random.uniform(28.0, 38.0)
            self.target_power = random.uniform(180.0, 280.0)
            self.target_hr = random.uniform(140.0, 165.0)
            self.target_cad = random.uniform(80.0, 95.0)
        else:
            self.target_speed = random.uniform(35.0, 45.0)
            self.target_power = random.uniform(300.0, 800.0)
            self.target_hr = random.uniform(160.0, 185.0)
            self.target_cad = random.uniform(90.0, 105.0)

    def step(self) -> Metrics:
        now = time.time()
        dt = now - self.last_time
        self.last_time = now
        if dt <= 0:
            dt = 1e-3

        self._maybe_change_targets(now)

        self.speed = self._smooth_step(self.speed, self.target_speed, 0.15, 0.3)
        self.power = self._smooth_step(self.power, self.target_power, 0.20, 5.0)
        self.hr = self._smooth_step(self.hr, self.target_hr, 0.10, 1.0)
        self.cad = self._smooth_step(self.cad, self.target_cad, 0.25, 1.0)

        self.distance_km += self.speed * dt / 3600.0
        self.energy_j += self.power * dt

        elapsed = now - self.start_time
        if elapsed <= 0:
            avgspeed = 0.0
            avgpower = 0.0
        else:
            avgspeed = self.distance_km / (elapsed / 3600.0)
            avgpower = self.energy_j / elapsed

        return Metrics(
            distance=self.distance_km,
            speed=self.speed,
            avgspeed=avgspeed,
            power=self.power,
            avgpower=avgpower,
            heartrate=self.hr,
            cadence=self.cad,
            timestamp=now,
        )


def run_test_mode(args):
    simulator = TestSimulator()
    print(
        "[bridge.py] Test-Modus gestartet\n"
        f"  JSON-Datei: {args.output}\n"
        f"  Intervall : {args.interval:.3f} s\n"
        "Abbrechen mit STRG+C\n"
    )
    try:
        while True:
            metrics = simulator.step()
            atomic_write_json(args.output, dataclasses.asdict(metrics))
            print_status_line(metrics)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\n[bridge.py] Test-Modus beendet.")


# ---------------------------------------------------------------------------
# Helper: vorhandene Session aus JSON wieder aufgreifen (ANT)
# ---------------------------------------------------------------------------

def load_previous_session(json_path: str):
    """
    Versucht, eine bestehende gc_live.json einzulesen und –
    wenn der Timestamp nicht älter als 30 Minuten ist –
    Distanz + Energie + Startzeit für eine Fortsetzung zu rekonstruieren.

    Rückgabe:
      dict mit keys: distance_km, energy_j, start_time
      oder None, wenn keine Fortsetzung stattfinden soll.
    """
    if not os.path.exists(json_path):
        return None

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"[bridge.py] Hinweis: Konnte bestehende JSON nicht lesen ({e}) – starte neue Session.", file=sys.stderr)
        return None

    if not isinstance(data, dict):
        return None

    ts = data.get("timestamp")
    try:
        ts = float(ts)
    except (TypeError, ValueError):
        # Kein brauchbarer Timestamp -> neue Session
        return None

    now = time.time()
    age = now - ts
    if age > 1800:  # > 30 Minuten
        print("[bridge.py] Letzter Datensatz älter als 30 Minuten – starte neue Session.")
        return None

    # Distanz / Ø-Geschwindigkeit / Ø-Leistung aus der Datei holen
    try:
        distance = float(data.get("distance", 0.0))
        avgspeed = float(data.get("avgspeed", 0.0))
        avgpower = float(data.get("avgpower", 0.0))
    except (TypeError, ValueError):
        return None

    if distance <= 0.0 or avgspeed <= 0.0:
        # Keine sinnvollen Werte – neue Session
        return None

    # Fahrzeit aus Distanz + Durchschnittsgeschwindigkeit rekonstruieren
    elapsed_hours = distance / avgspeed
    elapsed_seconds = elapsed_hours * 3600.0
    if elapsed_seconds <= 0:
        return None

    # Energie aus Ø-Leistung rekonstruieren
    energy_j = max(0.0, avgpower) * elapsed_seconds

    start_time = now - elapsed_seconds

    print(
        f"[bridge.py] Fortsetzung bestehender Session: "
        f"Distanz={distance:.2f} km, "
        f"Øv={avgspeed:.1f} km/h, "
        f"ØP={avgpower:.0f} W, "
        f"Alter des Datensatzes={age/60:.1f} min"
    )

    return {
        "distance_km": distance,
        "energy_j": energy_j,
        "start_time": start_time,
    }


# ---------------------------------------------------------------------------
# ANT-MODUS mit separatem Reader-Thread
# ---------------------------------------------------------------------------

def run_ant_mode(args):
    json_path = args.output
    interval = args.interval

    print(
        "[bridge.py] ANT-Modus gestartet\n"
        f"  JSON-Datei: {json_path}\n"
        f"  Intervall : {interval:.3f} s\n"
        "  Quelle: python -u -m openant scan --logging ERROR -a\n"
        "  Beenden mit STRG+C\n"
    )

    # Gemeinsamer Zustand, der vom Reader-Thread beschrieben und
    # von der Hauptschleife gelesen wird
    state_lock = threading.Lock()
    state = {
        "speed_kmh": 0.0,
        "power_w": 0.0,
        "hr_bpm": 0.0,
        "cad_rpm": 0.0,
    }
    stop_flag = {"stop": False}

    re_hr = re.compile(r"heart_rate=(\d+)")
    re_power = re.compile(r"instantaneous_power=(\d+)")
    re_cad = re.compile(r"cadence=(\d+)")
    re_speed = re.compile(r"speed=([0-9.]+)")

    # Unbuffered (-u), damit Zeilen nicht gesammelt werden
    cmd = [sys.executable, "-u", "-m", "openant", "scan", "--logging", "ERROR", "-a"]
    print(f"[bridge.py] Starte Subprozess: {' '.join(cmd)}")

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except FileNotFoundError:
        print(
            "[bridge.py] Fehler: python -m openant konnte nicht gestartet werden.\n"
            "Bist du in der .venv und ist openant installiert?\n",
            file=sys.stderr,
        )
        sys.exit(1)

    def reader_thread():
        try:
            for raw_line in proc.stdout:
                if stop_flag["stop"]:
                    break
                line = raw_line.rstrip("\n")
                if not line:
                    continue

                # Debug-Ausgabe sauber über der Statuszeile
                log_ant_line(line)

                if line.startswith("<class 'usb.core.USBError'>"):
                    # nur Info, Zustand bleibt
                    continue

                with state_lock:
                    # HR
                    if "heart_rate_" in line and "HeartRateData(" in line:
                        m = re_hr.search(line)
                        if m:
                            state["hr_bpm"] = float(m.group(1))

                    # POWER + CADENCE
                    if "power_meter_" in line and "PowerData(" in line:
                        m_p = re_power.search(line)
                        if m_p:
                            state["power_w"] = float(m_p.group(1))
                        m_c = re_cad.search(line)
                        if m_c:
                            state["cad_rpm"] = float(m_c.group(1))

                    # SPEED (FitnessEquipment)
                    if "fitness_equipment_" in line and "FitnessEquipmentData(" in line:
                        m_s = re_speed.search(line)
                        if m_s:
                            try:
                                speed_ms = float(m_s.group(1))
                                # 65535.0 = ungültig, 0.0 = stehen ist okay
                                if 0.0 <= speed_ms < 50.0:
                                    state["speed_kmh"] = speed_ms * 3.6
                            except ValueError:
                                pass
        finally:
            try:
                proc.terminate()
            except Exception:
                pass

    t = threading.Thread(target=reader_thread, daemon=True)
    t.start()

    # Hauptschleife: nur Integrationslogik + JSON-Schreiben mit fixem Intervall

    # Versuche, bestehende Session zu laden (falls < 30 min alt)
    previous = load_previous_session(json_path)

    now = time.time()
    if previous is not None:
        start_time = previous["start_time"]
        distance_km = previous["distance_km"]
        energy_j = previous["energy_j"]
        # last_time jetzt setzen; dt startet ab aktuellem Zeitpunkt
        last_time = now
    else:
        start_time = now
        last_time = now
        distance_km = 0.0
        energy_j = 0.0

    try:
        while True:
            time.sleep(interval)

            now = time.time()
            dt = now - last_time
            if dt < 0:
                dt = 0.0
            last_time = now

            with state_lock:
                speed_kmh = state["speed_kmh"]
                power_w = state["power_w"]
                hr_bpm = state["hr_bpm"]
                cad_rpm = state["cad_rpm"]

            # Integration (einfach, aber stabil)
            distance_km += speed_kmh * dt / 3600.0
            energy_j += power_w * dt

            elapsed = now - start_time
            if elapsed > 0:
                avgspeed = distance_km / (elapsed / 3600.0)
                avgpower = energy_j / elapsed
            else:
                avgspeed = 0.0
                avgpower = 0.0

            metrics = Metrics(
                distance=distance_km,
                speed=speed_kmh,
                avgspeed=avgspeed,
                power=power_w,
                avgpower=avgpower,
                heartrate=hr_bpm,
                cadence=cad_rpm,
                timestamp=now,
            )

            atomic_write_json(json_path, dataclasses.asdict(metrics))
            print_status_line(metrics)

    except KeyboardInterrupt:
        print("\n[bridge.py] ANT-Modus beendet (CTRL+C).")
    finally:
        stop_flag["stop"] = True
        try:
            proc.terminate()
        except Exception:
            pass
        try:
            t.join(timeout=1.0)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="GC-Live-Bridge für Cycling-Overlay")
    parser.add_argument(
        "--mode",
        choices=["test", "ant"],
        default="test",
        help="test (Simulationsdaten) oder ant (echte ANT+-Daten via openant scan)",
    )
    parser.add_argument(
        "--output",
        default="gc_live.json",
        help="Pfad zur JSON-Datei für das Overlay",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=0.5,
        help="Update-Intervall in Sekunden",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    signal.signal(signal.SIGINT, signal.default_int_handler)

    if args.mode == "test":
        run_test_mode(args)
    elif args.mode == "ant":
        run_ant_mode(args)
    else:
        print(f"Unbekannter Modus: {args.mode}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
