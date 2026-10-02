#!/usr/bin/env python3
from __future__ import annotations

"""Bicycle telemetry bridge.

Keeps the original project contract (`gc_live.json`) while adding a stable session_id.
Modes:
  test - plausible synthetic data
  ant  - parses `python -u -m openant scan --logging ERROR -a`
"""

import argparse
import dataclasses
import json
import os
import random
import re
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

HR_DEVICE_ID = 8118
PM_DEVICE_ID = 35165
FE_DEVICE_ID = 34628


@dataclass
class Metrics:
    distance: float
    speed: float
    avgspeed: float
    power: float
    avgpower: float
    heartrate: float
    cadence: float
    timestamp: float
    session_id: str
    source: str


def atomic_write_json(path: str | Path, obj: dict) -> None:
    """Write a stable JSON file without `os.replace` locking failures on Windows OBS reads."""
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(obj, fh)
            fh.flush()
            try:
                os.fsync(fh.fileno())
            except OSError:
                pass
    except Exception as exc:
        print(f"\n[bridge.py] TMP write failed: {exc}", file=sys.stderr)
        return
    # First try atomic replacement. If Windows/browser locking prevents it, use a direct overwrite.
    try:
        os.replace(tmp, path)
        return
    except PermissionError:
        pass
    except OSError:
        pass
    try:
        with path.open("w", encoding="utf-8") as fh:
            json.dump(obj, fh)
    except PermissionError:
        print(f"\n[bridge.py] Warning: {path} is locked; cycle skipped.", file=sys.stderr)
    except OSError as exc:
        print(f"\n[bridge.py] Write failed: {exc}", file=sys.stderr)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


class TestSimulator:
    def __init__(self):
        self.started = self.last = time.time()
        self.session_id = f"test-{uuid.uuid4()}"
        self.speed = 0.0
        self.power = 0.0
        self.hr = 80.0
        self.cad = 0.0
        self.distance = 0.0
        self.energy = 0.0
        self.targets = [25.0, 180.0, 140.0, 85.0]
        self.last_target = self.started

    def _smooth(self, value: float, target: float, factor: float, noise: float) -> float:
        return max(0.0, value + (target - value) * factor + random.uniform(-noise, noise))

    def step(self) -> Metrics:
        now = time.time()
        dt = max(0.001, now - self.last)
        self.last = now
        if now - self.last_target > random.uniform(10, 25):
            self.last_target = now
            phase = random.random()
            if phase < 0.25:
                self.targets = [random.uniform(20, 28), random.uniform(100, 180), random.uniform(120, 145), random.uniform(75, 90)]
            elif phase < 0.8:
                self.targets = [random.uniform(28, 38), random.uniform(180, 300), random.uniform(140, 165), random.uniform(80, 98)]
            else:
                self.targets = [random.uniform(38, 46), random.uniform(350, 800), random.uniform(160, 185), random.uniform(90, 110)]
        self.speed = self._smooth(self.speed, self.targets[0], .15, .3)
        self.power = self._smooth(self.power, self.targets[1], .2, 5)
        self.hr = self._smooth(self.hr, self.targets[2], .1, 1)
        self.cad = self._smooth(self.cad, self.targets[3], .25, 1)
        self.distance += self.speed * dt / 3600.0
        self.energy += self.power * dt
        elapsed = max(.001, now - self.started)
        return Metrics(
            self.distance, self.speed, self.distance / (elapsed / 3600.0), self.power,
            self.energy / elapsed, self.hr, self.cad, now, self.session_id, "test"
        )


def _load_previous_session(path: Path) -> tuple[float, float, float, str] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        age = time.time() - float(data.get("timestamp", 0))
        if age > 1800 or data.get("source") not in {None, "ant"}:
            return None
        distance = float(data.get("distance", 0.0))
        avgpower = float(data.get("avgpower", 0.0))
        # Exact previous elapsed duration is unavailable in legacy JSON. Use a conservative
        # reconstructed 1-second energy baseline; distance continuity is what matters here.
        energy = max(0.0, avgpower)
        started = time.time() - 1.0
        sid = str(data.get("session_id") or f"ant-{uuid.uuid4()}")
        return distance, energy, started, sid
    except Exception:
        return None


def run_test(args: argparse.Namespace) -> None:
    sim = TestSimulator()
    print(f"[bridge.py] test mode -> {args.output}; Ctrl+C to stop")
    try:
        while True:
            m = sim.step()
            atomic_write_json(args.output, dataclasses.asdict(m))
            print(f"\rDist {m.distance:7.2f} km | {m.speed:5.1f} km/h | {m.power:4.0f} W | HR {m.heartrate:3.0f} | CAD {m.cadence:3.0f}", end="", flush=True)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\n[bridge.py] stopped")


def run_ant(args: argparse.Namespace) -> None:
    output = Path(args.output)
    previous = _load_previous_session(output)
    if previous:
        distance, energy, started, session_id = previous
        print(f"[bridge.py] continuing recent ANT session at {distance:.2f} km")
    else:
        distance, energy, started, session_id = 0.0, 0.0, time.time(), f"ant-{uuid.uuid4()}"
    state = {"speed": 0.0, "power": 0.0, "heartrate": 0.0, "cadence": 0.0}
    lock = threading.Lock()
    stop = threading.Event()
    re_hr = re.compile(r"heart_rate=(\d+)")
    re_power = re.compile(r"instantaneous_power=(-?\d+)")
    re_cad = re.compile(r"cadence=(-?[0-9.]+)")
    re_speed = re.compile(r"speed=([0-9.]+)")

    cmd = [sys.executable, "-u", "-m", "openant", "scan", "--logging", "ERROR", "-a"]
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    except Exception as exc:
        raise SystemExit(f"Could not start OpenANT scanner: {exc}")

    def reader() -> None:
        assert proc.stdout
        try:
            for line in proc.stdout:
                if stop.is_set():
                    break
                line = line.strip()
                with lock:
                    if "heart_rate_" in line and "HeartRateData(" in line:
                        m = re_hr.search(line)
                        if m:
                            state["heartrate"] = float(m.group(1))
                    if "power_meter_" in line and "PowerData(" in line:
                        m = re_power.search(line)
                        if m:
                            state["power"] = max(0.0, float(m.group(1)))
                        m = re_cad.search(line)
                        if m:
                            state["cadence"] = max(0.0, float(m.group(1)))
                    if "fitness_equipment_" in line and "FitnessEquipmentData(" in line:
                        m = re_speed.search(line)
                        if m:
                            speed_ms = float(m.group(1))
                            if 0 <= speed_ms < 50:
                                state["speed"] = speed_ms * 3.6
        finally:
            stop.set()

    threading.Thread(target=reader, daemon=True).start()
    last = time.time()
    try:
        while not stop.is_set():
            now = time.time()
            dt = max(.001, now - last)
            last = now
            with lock:
                speed, power, hr, cad = state["speed"], state["power"], state["heartrate"], state["cadence"]
            distance += speed * dt / 3600.0
            energy += power * dt
            elapsed = max(.001, now - started)
            m = Metrics(distance, speed, distance / (elapsed / 3600.0), power, energy / elapsed, hr, cad, now, session_id, "ant")
            atomic_write_json(output, dataclasses.asdict(m))
            print(f"\rDist {m.distance:7.2f} km | {m.speed:5.1f} km/h | {m.power:4.0f} W | HR {m.heartrate:3.0f} | CAD {m.cadence:3.0f}", end="", flush=True)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        try:
            proc.terminate()
        except Exception:
            pass
        print("\n[bridge.py] stopped")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["test", "ant"], default="ant")
    parser.add_argument("--output", default="gc_live.json")
    parser.add_argument("--interval", type=float, default=.5)
    args = parser.parse_args()
    if args.mode == "test":
        run_test(args)
    else:
        run_ant(args)


if __name__ == "__main__":
    main()
