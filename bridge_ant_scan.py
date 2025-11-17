#!/usr/bin/env python3
import json
import os
import sys
import time
from dataclasses import dataclass, asdict

from openant.scripts.scan import Scan
from openant.devices.heart_rate import HeartRate
from openant.devices.power_meter import PowerMeter
from openant.devices.fitness_equipment import FitnessEquipment

# ==============================
# CONFIG
# ==============================
HR_DEVICE_ID = 8118
PM_DEVICE_ID = 35165
FE_DEVICE_ID = 34628

UPDATE_INTERVAL = 0.5
OUTPUT_JSON = "gc_live.json"


@dataclass
class Metrics:
    distance: float
    speed: float
    avgspeed: float
    power: float
    avgpower: float
    heartrate: float
    cadence: float


def write_json_atomic(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp, path)


def run():
    json_path = os.path.abspath(OUTPUT_JSON)

    print("\n[bridge_ant_scan] Starte (CLI-kompatibler) Scan Listener")
    print(f" ❤️ HR-ID:  {HR_DEVICE_ID}")
    print(f" ⚡ PM-ID:  {PM_DEVICE_ID}")
    print(f" 🚴 FE-ID:  {FE_DEVICE_ID}")
    print(f" 📄 JSON →   {json_path}")
    print(" ⛔ Stop: CTRL+C\n")

    state = {
        "hr": 0.0,
        "power": 0.0,
        "cadence": 0.0,
        "speed": 0.0,
    }

    hr_dev = None
    pm_dev = None
    fe_dev = None

    def on_found(device):
        nonlocal hr_dev, pm_dev, fe_dev
        print(f"🔍 Gerät: ID={device.device_number}, Type={device.device_type}")

        # HR
        if device.device_number == HR_DEVICE_ID and isinstance(device, HeartRate):
            hr_dev = device
            print(" ❤️ HR gekoppelt!")
            def on_hr(d):
                if d.computed_heart_rate is not None:
                    state["hr"] = float(d.computed_heart_rate)
            device.on_device_data = on_hr

        # Power
        if device.device_number == PM_DEVICE_ID and isinstance(device, PowerMeter):
            pm_dev = device
            print(" ⚡ Powermeter gekoppelt!")
            def on_pm(d):
                if d.instant_power is not None:
                    state["power"] = float(d.instant_power)
                if d.cadence is not None:
                    state["cadence"] = float(d.cadence)
            device.on_device_data = on_pm

        # FE-C
        if device.device_number == FE_DEVICE_ID and isinstance(device, FitnessEquipment):
            fe_dev = device
            print(" 🚴 FE-C gekoppelt!")
            def on_fec(d):
                if d.speed is not None:
                    state["speed"] = float(d.speed) * 3.6
            device.on_device_data = on_fec

    scanner = Scan(on_found=on_found)
    scanner.start()

    start = last = time.time()
    distance = 0.0
    energy = 0.0

    try:
        while True:
            now = time.time()
            dt = now - last
            last = now

            sp = state["speed"]
            pw = state["power"]
            hr = state["hr"]
            cad = state["cadence"]

            distance += sp * (dt / 3600.0)
            energy += pw * dt
            t = now - start

            avgspeed = distance/(t/3600.0) if t > 0 else 0
            avgpower = energy/t if t > 0 else 0

            write_json_atomic(json_path, asdict(Metrics(
                distance=distance,
                speed=sp,
                avgspeed=avgspeed,
                power=pw,
                avgpower=avgpower,
                heartrate=hr,
                cadence=cad,
            )))

            sys.stdout.write(
                f"\rSPD {sp:5.1f} km/h | PWR {pw:4.0f}W | HR {hr:3.0f} bpm | CAD {cad:3.0f} rpm | DIST {distance:6.2f} km"
            )
            sys.stdout.flush()

            time.sleep(UPDATE_INTERVAL)

    except KeyboardInterrupt:
        print("\n⛔ Stop…")
        scanner.stop()


if __name__ == "__main__":
    run()
