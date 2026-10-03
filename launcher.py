from __future__ import annotations

import argparse
import logging
from logging.handlers import RotatingFileHandler
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def process_options(platform: str | None = None) -> dict:
    """Give each service its own group; never send console signals to the launcher."""
    if (platform or os.name) == "nt":
        return {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200)}
    return {"start_new_session": True}


def file_logger(name: str, filename: str, *, console: bool = False) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    (ROOT / "data").mkdir(parents=True, exist_ok=True)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    handler = RotatingFileHandler(ROOT / "data" / filename, maxBytes=2_097_152, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    if console:
        stream = logging.StreamHandler(sys.stdout)
        stream.setFormatter(logging.Formatter("\n[launcher] %(message)s"))
        logger.addHandler(stream)
    return logger


def relay_output(proc: subprocess.Popen, logger: logging.Logger) -> None:
    if proc.stdout is None:
        return
    try:
        for line in proc.stdout:
            if line.strip().startswith("Dist "):
                print("\r" + line.strip(), end="", flush=True)
            else:
                logger.info(line.rstrip())
                print(line, end="", flush=True)
    except (OSError, ValueError) as exc:
        logger.warning("Prozessausgabe konnte nicht gelesen werden: %s", exc)
    finally:
        proc.stdout.close()


class ManagedProcess:
    def __init__(self, name: str, command: list[str], env: dict[str, str], logger: logging.Logger):
        self.name, self.command, self.env, self.logger = name, command, env, logger
        self.proc: subprocess.Popen | None = None
        self.started_at = 0.0
        self.next_restart = 0.0
        self.failures = 0

    def _schedule(self, now: float) -> None:
        self.failures = min(self.failures + 1, 5)
        delay = min(30, 2 ** self.failures)
        self.next_restart = now + delay
        self.logger.warning("%s: neuer Start in %s s. Der andere Prozess bleibt aktiv.", self.name, delay)

    def start(self, now: float) -> None:
        try:
            output_log = file_logger("bicycle.launcher.output." + self.name, self.name + "-output.log")
            self.proc = subprocess.Popen(
                self.command, cwd=ROOT, env=self.env, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", bufsize=1, **process_options(),
            )
            self.started_at = now
            threading.Thread(target=relay_output, args=(self.proc, output_log), daemon=True).start()
            self.logger.info("%s gestartet (PID %s).", self.name, self.proc.pid)
        except OSError as exc:
            self.proc = None
            self.logger.error("%s konnte nicht gestartet werden: %s", self.name, exc)
            self._schedule(now)

    def tick(self, now: float) -> None:
        if self.proc is not None:
            code = self.proc.poll()
            if code is None:
                return
            if now - self.started_at >= 60:
                self.failures = 0
            self.logger.error("%s unerwartet beendet (Exit-Code %s). Details: data/%s-output.log", self.name, code, self.name)
            self.proc = None
            self._schedule(now)
        elif now >= self.next_restart:
            self.start(now)

    def request_stop(self) -> None:
        if self.proc is None or self.proc.poll() is not None:
            return
        try:
            # Windows CTRL_BREAK targets the separate process group created above.
            self.proc.send_signal(signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGTERM)
        except OSError:
            self.proc.terminate()

    def wait_stopped(self) -> None:
        if self.proc is None:
            return
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.logger.warning("%s reagiert nicht auf Stop; beende nur diesen Prozessbaum.", self.name)
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(self.proc.pid), "/T", "/F"], capture_output=True, timeout=5)
            else:
                try:
                    os.killpg(self.proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            self.proc.wait(timeout=5)


def backend_ready(port: int) -> bool:
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f"http://127.0.0.1:{port}/api/health", timeout=0.25) as r:
            return r.status == 200
    except (OSError, urllib.error.URLError):
        return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["ant", "test"], default="ant")
    parser.add_argument("--port", type=int, default=int(os.getenv("BICYCLE_STREAM_PORT", "5051")))
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    env = os.environ.copy()
    env["BICYCLE_STREAM_PORT"] = str(args.port)
    env["PYTHONIOENCODING"] = "utf-8"
    if args.mode == "test":
        env["BICYCLE_DISABLE_DISTANCE_PERSIST"] = "1"
    logger = file_logger("bicycle.launcher", "launcher.log", console=True)
    services = [
        ManagedProcess("bridge", [sys.executable, "-u", "bridge.py", "--mode", args.mode, "--output", "gc_live.json", "--interval", "0.5"], env, logger),
        ManagedProcess("backend", [sys.executable, "-u", "-m", "backend.app"], env, logger),
    ]
    browser_opened = args.no_browser
    stopping = threading.Event()
    # The launcher is the only recipient of the user's Ctrl+C. SIGBREAK/SIGTERM
    # also request an intentional shutdown, with no retries during cleanup.
    def stop_requested(_signum, _frame):
        stopping.set()
    previous = {}
    for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        sig = getattr(signal, name, None)
        if sig is not None:
            previous[sig] = signal.signal(sig, stop_requested)
    logger.info("Prozessüberwachung aktiv. Ctrl+C beendet beide Dienste bewusst.")
    try:
        while not stopping.is_set():
            now = time.monotonic()
            for service in services:
                service.tick(now)
            if not browser_opened and services[1].proc is not None and services[1].proc.poll() is None and backend_ready(args.port):
                webbrowser.open(f"http://127.0.0.1:{args.port}/admin")
                browser_opened = True
            stopping.wait(0.5)
    except KeyboardInterrupt:
        logger.info("Ctrl+C empfangen.")
    finally:
        logger.info("Bewusster Stop angefordert; beende Dienste ohne Neustart.")
        for service in services:
            try:
                service.request_stop()
            except OSError as exc:
                logger.warning("Stop-Signal für %s fehlgeschlagen: %s", service.name, exc)
        for service in services:
            try:
                service.wait_stopped()
            except (OSError, subprocess.TimeoutExpired) as exc:
                logger.error("Stop für %s fehlgeschlagen: %s", service.name, exc)
        for sig, handler in previous.items():
            signal.signal(sig, handler)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
