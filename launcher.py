from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=["ant", "test"], default="ant")
    p.add_argument("--port", type=int, default=int(os.getenv("BICYCLE_STREAM_PORT", "5051")))
    p.add_argument("--no-browser", action="store_true")
    args = p.parse_args()
    env = os.environ.copy()
    env["BICYCLE_STREAM_PORT"] = str(args.port)
    # Test bridge telemetry must never increment the production challenge.
    if args.mode == "test":
        env["BICYCLE_DISABLE_DISTANCE_PERSIST"] = "1"
    procs = [
        subprocess.Popen([sys.executable, "-u", "bridge.py", "--mode", args.mode, "--output", "gc_live.json", "--interval", "0.5"], cwd=ROOT, env=env),
        subprocess.Popen([sys.executable, "-u", "-m", "backend.app"], cwd=ROOT, env=env),
    ]
    if not args.no_browser:
        time.sleep(1.5)
        webbrowser.open(f"http://127.0.0.1:{args.port}/admin")
    try:
        while all(proc.poll() is None for proc in procs):
            time.sleep(.5)
    except KeyboardInterrupt:
        pass
    finally:
        for proc in procs:
            if proc.poll() is None:
                try:
                    proc.send_signal(signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGTERM)
                except Exception:
                    proc.terminate()
        for proc in procs:
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
