#!/usr/bin/env python3
"""
bridge.py

Schreibt zyklisch eine Datei `gc_live.json`, die von overlay_stein_cycling.html
gelesen werden kann.

Unterstützte Modi:
- test:  Simuliert Trainingsdaten (für Entwicklung / Overlay-Test)
- ant:   Platzhalter für echte ANT+-Integration (siehe Hinweise unten)

Nutzung (Testmodus):
    python bridge.py --mode test --output gc_live.json --interval 0.5
"""

import argparse
import json
import math
import os
import random
import signal
import sys
import time
from dataclasses import dataclass, asdict


@dataclass
class Metrics:
    distance: float      # km
    speed: float         # km/h (aktuell)
    avgspeed: float      # km/h (Durchschnitt)
    power: float         # W (aktuell)
    avgpower: float      # W (Durchschnitt)
    heartrate: float     # bpm
    cadence: float       # rpm


class TestSimulator:
    """
    Einfacher Trainings-Simulator:
    - Baut langsam Leistung / Tempo auf
    - Variiert Werte leicht zufällig
    - Berechnet Distanz und Durchschnittswerte korrekt über die Zeit
    """

    def __init__(self):
        self.start_time = time.time()
        self.last_time = self.start_time

        # aktuelle Werte
        self.speed = 0.0      # km/h
        self.power = 0.0      # W
        self.hr = 80.0        # bpm
        self.cad = 0.0        # rpm

        # Zielwerte (ändern sich alle paar Sekunden)
        self.target_speed = 25.0
        self.target_power = 180.0
        self.target_hr = 140.0
        self.target_cad = 85.0

        self.last_target_change = self.start_time

        # aggregierte Größen
        self.distance_km = 0.0
        self.energy_j = 0.0   # für Durchschnittsleistung

    def _update_targets_if_needed(self, now: float):
        """Alle ~30–60 Sekunden neue Zielwerte setzen."""
        if now - self.last_target_change < random.uniform(25.0, 45.0):
            return

        self.last_target_change = now

        # Simuliere verschiedene Intensitäts-Phasen
        phase = random.random()

        if phase < 0.2:
            # lockeres Rollen / Erholung
            self.target_speed = random.uniform(20.0, 28.0)
            self.target_power = random.uniform(100.0, 180.0)
            self.target_hr = random.uniform(120.0, 145.0)
            self.target_cad = random.uniform(75.0, 90.0)
        elif phase < 0.8:
            # normale Sweetspot-/Tempo-Phase
            self.target_speed = random.uniform(28.0, 38.0)
            self.target_power = random.uniform(180.0, 280.0)
            self.target_hr = random.uniform(140.0, 165.0)
            self.target_cad = random.uniform(80.0, 95.0)
        else:
            # Intervalle / Sprints
            self.target_speed = random.uniform(35.0, 45.0)
            self.target_power = random.uniform(300.0, 800.0)
            self.target_hr = random.uniform(160.0, 185.0)
            self.target_cad = random.uniform(90.0, 105.0)

    def _smooth_step(self, current: float, target: float, factor: float, noise: float) -> float:
        """
        Einfache Exponential-Annäherung an target plus kleiner Rauschanteil.
        factor: 0..1 (wie "aggressiv" in Richtung target gezogen wird)
        noise: Maximalamplitude des Zufallsrauschens
        """
        base = current + (target - current) * factor
        jitter = random.uniform(-noise, noise)
        return base + jitter

    def step(self, now: float) -> Metrics:
        """Einen Simulationsschritt durchführen und neue Metriken berechnen."""
        dt = max(1e-3, now - self.last_time)
        self.last_time = now

        self._update_targets_if_needed(now)

        # aktuelle Werte sanft Richtung Ziel bewegen
        self.speed = max(0.0, self._smooth_step(self.speed, self.target_speed, factor=0.2, noise=0.5))
        self.power = max(0.0, self._smooth_step(self.power, self.target_power, factor=0.3, noise=10.0))
        self.hr = max(40.0, self._smooth_step(self.hr, self.target_hr, factor=0.15, noise=1.5))
        self.cad = max(0.0, self._smooth_step(self.cad, self.target_cad, factor=0.25, noise=1.0))

        # hart begrenzen auf halbwegs realistische Indoor-Werte
        self.speed = min(self.speed, 60.0)
        self.power = min(self.power, 1200.0)
        self.hr = min(self.hr, 210.0)
        self.cad = min(self.cad, 130.0)

        # Distanz: v [km/h] * dt[s] -> km
        self.distance_km += self.speed * (dt / 3600.0)

        # Energie: P[W] * dt[s] = J
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
        )


def atomic_write_json(path: str, obj) -> None:
    """Robustes Schreiben unter Windows, ohne atomaren Replace."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f)


def run_test_mode(args):
    simulator = TestSimulator()
    json_path = os.path.abspath(args.output)
    interval = args.interval

    print(f"[bridge.py] Testmodus gestartet")
    print(f"  JSON-Datei: {json_path}")
    print(f"  Intervall : {interval:.3f} s")
    print("  Beenden mit STRG+C")

    try:
        while True:
            now = time.time()
            metrics = simulator.step(now)
            atomic_write_json(json_path, asdict(metrics))

            # kleine, aber informative Console-Ausgabe
            sys.stdout.write(
                f"\rDist: {metrics.distance:6.2f} km | "
                f"v: {metrics.speed:5.1f} km/h (Ø {metrics.avgspeed:4.1f}) | "
                f"P: {metrics.power:6.1f} W (Ø {metrics.avgpower:4.0f}) | "
                f"HR: {metrics.heartrate:5.1f} bpm | "
                f"CAD: {metrics.cadence:5.1f} rpm"
            )
            sys.stdout.flush()

            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n[bridge.py] Beendet (KeyboardInterrupt).")


def run_ant_mode(args):
    """
    Platzhalter für echten ANT+-Modus.

    Warum hier kein „fertiger“ Code steht:
    -------------------------------------
    - ANT+ unter Windows mit libusb / openant ans Laufen zu bekommen,
      hängt stark von deinem Stick, den Treibern und den konkreten Geräten ab.
    - Ohne Zugriff auf deine Hardware kann ich dir keinen Code liefern,
      der garantiert „einfach so“ funktioniert – das wäre dieselbe Art
      von Bullshit wie beim GoldenCheetah-Thema, nur in Python.

    Was du tun kannst:
    ------------------
    1. Installiere das openant-Paket:
           pip install openant

    2. Nutze dessen CLI, um erstmal sicher zu stellen, dass dein Dongle und
       deine Geräte überhaupt erkannt werden, z.B.:
           openant scan
           openant influx --verbose FitnessDevice
           openant influx --verbose PowerMeter
           openant influx --verbose HeartRate

    3. Wenn das stabil läuft, kann man im nächsten Schritt entweder:
       - direkt über die openant-Python-API die Daten ziehen und hier in
         gc_live.json schreiben, oder
       - openant per MQTT laufen lassen und dieses Skript nur noch als
         MQTT->JSON-Bridge verwenden.

    Damit du nicht komplett im Regen stehst, hier ein grobes Gerüst,
    wie so ein ANT-Loop aussehen *könnte* (Pseudocode):

        from openant.easy.node import Node
        from openant.devices import HeartRate, PowerMeter, FitnessDevice

        node = Node()
        hr = HeartRate(node)
        pm = PowerMeter(node)
        ft = FitnessDevice(node)

        # callbacks, die bei neuen Daten die aktuellen Werte updaten
        # und dann periodisch Metrics(...) -> gc_live.json schreiben.

    Aber: Das hängt an deiner konkreten Konfiguration und muss an der
    echten Hardware debuggt werden.

    Damit das Skript sich halbwegs sauber verhält, breche ich den ANT-Modus
    hier bewusst mit einer klaren Fehlermeldung ab.
    """
    print(
        "[bridge.py] ANT-Modus ist aktuell nur ein Platzhalter.\n"
        "Ich kann dir ohne Zugriff auf deinen ANT+-Stick und die Geräte "
        "keinen ehrlichen 'läuft-out-of-the-box'-Code liefern.\n\n"
        "Der Testmodus funktioniert voll und simuliert realistische Werte.\n"
        "Für den echten ANT-Stream ist der nächste Schritt:\n"
        "  - openant + dein Dongle lauffähig machen\n"
        "  - Beispiele aus https://github.com/Tigge/openant/examples ansehen\n"
        "  - dann die Daten in dieses JSON-Schema gießen."
    )
    sys.exit(1)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Brücke zwischen Sensor-Daten und gc_live.json für dein OBS-Overlay."
    )
    parser.add_argument(
        "--mode",
        choices=["test", "ant"],
        default="test",
        help="test = simulierte Daten, ant = (Platzhalter) echte ANT+-Integration",
    )
    parser.add_argument(
        "--output",
        default="gc_live.json",
        help="Pfad zur Ausgabedatei (Standard: gc_live.json im aktuellen Ordner)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=0.5,
        help="Update-Intervall in Sekunden (Standard: 0.5)",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)

    # Sauberes Beenden bei Ctrl+C auch unter Windows
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
