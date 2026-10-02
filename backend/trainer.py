from __future__ import annotations

import json
import os
import shlex
import subprocess
import time
from dataclasses import dataclass, asdict
from typing import Any, Protocol


class TrainerAdapter(Protocol):
    def capabilities(self) -> dict[str, Any]: ...
    def set_grade(self, percent: float) -> dict[str, Any]: ...
    def restore(self) -> dict[str, Any]: ...


class NullTrainerAdapter:
    def __init__(self, reason: str = "Kein FE-C Control-Adapter konfiguriert"):
        self.reason = reason

    def capabilities(self) -> dict[str, Any]:
        return {"found": False, "connected": False, "controllable": False, "grade": False, "reason": self.reason}

    def set_grade(self, percent: float) -> dict[str, Any]:
        raise RuntimeError(self.reason)

    def restore(self) -> dict[str, Any]:
        return {"ok": False, "reason": self.reason}


class FakeTrainerAdapter:
    def __init__(self, controllable: bool = True):
        self.grade = 0.0
        self.controllable = controllable
        self.commands: list[tuple[str, float | None]] = []

    def capabilities(self) -> dict[str, Any]:
        return {"found": True, "connected": True, "controllable": self.controllable, "grade": self.controllable, "device": "Fake KICKR CORE 2"}

    def set_grade(self, percent: float) -> dict[str, Any]:
        if not self.controllable:
            raise RuntimeError("Fake trainer marked uncontrollable")
        self.grade = float(percent)
        self.commands.append(("grade", self.grade))
        return {"ok": True, "grade_percent": self.grade}

    def restore(self) -> dict[str, Any]:
        self.grade = 0.0
        self.commands.append(("restore", None))
        return {"ok": True, "grade_percent": 0.0}


class ExternalFECAdapter:
    """
    Safe process boundary for a real ANT+ FE-C controller.

    The helper executable is intentionally capability-driven. It must implement:
      helper status
      helper grade <percent>
      helper restore
    and print one JSON object to stdout. This prevents this app from pretending that
    OpenANT's receiver scan is a reliable FE-C master-control implementation.
    """

    def __init__(self, command: str | list[str], timeout: float = 4.0):
        self.command = shlex.split(command) if isinstance(command, str) else list(command)
        self.timeout = float(timeout)
        if not self.command:
            raise ValueError("empty FE-C helper command")

    def _call(self, *args: str) -> dict[str, Any]:
        cp = subprocess.run(
            [*self.command, *args],
            capture_output=True,
            text=True,
            timeout=self.timeout,
            check=False,
        )
        text = (cp.stdout or "").strip()
        if cp.returncode != 0:
            raise RuntimeError((cp.stderr or text or f"FE-C helper exited {cp.returncode}").strip())
        try:
            obj = json.loads(text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"FE-C helper returned invalid JSON: {text[:300]}") from exc
        if not isinstance(obj, dict):
            raise RuntimeError("FE-C helper returned non-object JSON")
        return obj

    def capabilities(self) -> dict[str, Any]:
        return self._call("status")

    def set_grade(self, percent: float) -> dict[str, Any]:
        return self._call("grade", f"{float(percent):.2f}")

    def restore(self) -> dict[str, Any]:
        return self._call("restore")


@dataclass
class TrainerStatus:
    requested_enabled: bool = False
    control_active: bool = False
    found: bool = False
    connected: bool = False
    controllable: bool = False
    grade_capable: bool = False
    device: str = ""
    current_grade_percent: float = 0.0
    last_command: str = ""
    last_error: str = ""
    last_update: float = 0.0


class TrainerControlService:
    def __init__(self, config: dict[str, Any], adapter: TrainerAdapter | None = None):
        self.config = config
        tc = config.get("trainer", {})
        if adapter is None:
            helper = os.getenv("BICYCLE_FEC_HELPER") or tc.get("helper_command", "")
            adapter = ExternalFECAdapter(helper, tc.get("command_timeout_seconds", 4.0)) if helper else NullTrainerAdapter()
        self.adapter = adapter
        self.status = TrainerStatus()

    def enable(self) -> dict[str, Any]:
        self.status.requested_enabled = True
        try:
            caps = self.adapter.capabilities() or {}
            self.status.found = bool(caps.get("found"))
            self.status.connected = bool(caps.get("connected"))
            self.status.controllable = bool(caps.get("controllable"))
            self.status.grade_capable = bool(caps.get("grade", caps.get("track_resistance", False)))
            self.status.device = str(caps.get("device", caps.get("name", "")))
            self.status.control_active = self.status.connected and self.status.controllable and self.status.grade_capable
            self.status.last_error = "" if self.status.control_active else str(caps.get("reason", "FE-C Grade-Control capability not available"))
            self.status.last_command = "capability-test"
        except Exception as exc:
            self.status.control_active = False
            self.status.last_error = str(exc)
            self.status.last_command = "capability-test"
        self.status.last_update = time.time()
        return self.snapshot()

    def disable(self) -> dict[str, Any]:
        if self.status.control_active:
            self.restore()
        self.status.requested_enabled = False
        self.status.control_active = False
        self.status.last_command = "disabled"
        self.status.last_update = time.time()
        return self.snapshot()

    def set_grade(self, percent: float) -> dict[str, Any]:
        if not self.status.requested_enabled or not self.status.control_active:
            self.status.last_error = "Trainer Control ist nicht aktiv/capability-geprüft"
            self.status.last_update = time.time()
            return {"ok": False, "error": self.status.last_error}
        try:
            result = self.adapter.set_grade(float(percent))
            self.status.current_grade_percent = float(percent)
            self.status.last_command = f"grade {float(percent):.2f}%"
            self.status.last_error = ""
            self.status.last_update = time.time()
            return {"ok": True, "result": result}
        except Exception as exc:
            self.status.last_error = str(exc)
            self.status.control_active = False
            self.status.last_update = time.time()
            return {"ok": False, "error": self.status.last_error}

    def restore(self) -> dict[str, Any]:
        try:
            result = self.adapter.restore()
            self.status.current_grade_percent = float(self.config.get("trainer", {}).get("neutral_grade_percent", 0.0))
            self.status.last_command = "restore/neutral"
            self.status.last_error = "" if result.get("ok", True) else str(result.get("reason", "restore failed"))
            self.status.last_update = time.time()
            return {"ok": bool(result.get("ok", True)), "result": result}
        except Exception as exc:
            self.status.last_error = str(exc)
            self.status.last_update = time.time()
            return {"ok": False, "error": self.status.last_error}

    def emergency_restore(self) -> dict[str, Any]:
        out = self.restore()
        self.status.control_active = False
        self.status.requested_enabled = False
        self.status.last_command = "EMERGENCY RESTORE"
        return out

    def snapshot(self) -> dict[str, Any]:
        return asdict(self.status)
