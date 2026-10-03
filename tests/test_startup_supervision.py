from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
from unittest.mock import Mock

import httpx
import pytest

import bridge
import launcher
from backend.app import create_app
from test_twitch_auth_rewards import make_runtime


def test_windows_services_have_separate_process_groups():
    assert launcher.process_options("nt")["creationflags"] & 0x200
    assert launcher.process_options("posix") == {"start_new_session": True}


@pytest.mark.parametrize("exit_code", [0, 1, 130])
def test_child_exit_restarts_only_that_service(exit_code, monkeypatch):
    failed, healthy = Mock(), Mock()
    failed.poll.return_value = exit_code
    healthy.poll.return_value = None
    logger = Mock()
    services = [launcher.ManagedProcess("bridge", [], {}, logger), launcher.ManagedProcess("backend", [], {}, logger)]
    services[0].proc, services[1].proc = failed, healthy
    restart = Mock()
    monkeypatch.setattr(services[0], "start", restart)
    services[0].tick(1)
    services[1].tick(1)
    assert services[0].next_restart == 3
    services[0].tick(2)
    restart.assert_not_called()
    services[0].tick(3)
    restart.assert_called_once_with(3)
    healthy.send_signal.assert_not_called()
    healthy.terminate.assert_not_called()
    assert services[1].proc is healthy
    assert any(str(exit_code) in str(c) for c in logger.error.call_args_list)


def test_spawn_failure_is_logged_and_retried(monkeypatch):
    service = launcher.ManagedProcess("backend", ["python"], {}, Mock())
    monkeypatch.setattr(launcher.subprocess, "Popen", Mock(side_effect=OSError("Start failed")))
    service.start(0)
    assert service.proc is None and service.next_restart == 2
    service.tick(2)
    assert service.next_restart == 6
    service.logger.error.assert_called()


def test_ant_scanner_error_is_visible_and_returns_failure(tmp_path, monkeypatch, capsys):
    proc = Mock()
    proc.stdout = ["USB error: No ANT+ dongle found\n"]
    proc.poll.return_value = proc.returncode = 1
    monkeypatch.setattr(bridge.subprocess, "Popen", Mock(return_value=proc))
    class ImmediateThread:
        def __init__(self, target, **_kwargs):
            self.target = target
        def start(self):
            self.target()
    monkeypatch.setattr(bridge.threading, "Thread", ImmediateThread)
    args = Mock(output=str(tmp_path / "gc_live.json"), interval=0.5)
    assert bridge.run_ant(args) == 1
    output = capsys.readouterr()
    assert "Exit-Code 1" in output.out
    assert "No ANT+ dongle" in output.err
    assert "No ANT+ dongle" in (tmp_path / "data/ant-scanner.log").read_text()
    proc.wait.assert_called_once()
    for handler in list(logging.getLogger("bicycle.ant-scanner").handlers):
        handler.close()
        logging.getLogger("bicycle.ant-scanner").removeHandler(handler)


def test_slow_twitch_login_does_not_block_startup_or_health(tmp_path, config):
    config["twitch"]["third_party_emotes"] = False
    rt = make_runtime(tmp_path, config)
    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()
        async def slow_auth():
            entered.set()
            await release.wait()
        rt._prepare_twitch_auth = slow_auth
        try:
            await asyncio.wait_for(rt.start(), timeout=0.1)
            await entered.wait()
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(rt)), base_url="http://test") as client:
                health = await client.get("/api/health")
                assert health.status_code == 200 and health.json()["twitch_starting"]
                assert (await client.get("/api/state")).status_code == 200
            assert all(not task.done() for task in rt._tasks if task.get_name() in {"tick-loop", "telemetry-loop"})
        finally:
            await rt.stop()
        assert not rt._twitch_preparing
        assert not rt._tasks
    asyncio.run(scenario())


def test_twitch_startup_exception_leaves_local_loops_running(tmp_path, config):
    config["twitch"]["third_party_emotes"] = False
    rt = make_runtime(tmp_path, config)
    async def failed_auth():
        raise httpx.ConnectTimeout("")
    rt._prepare_twitch_auth = failed_auth
    async def scenario():
        await rt.start()
        task = next(t for t in rt._tasks if t.get_name() == "twitch-startup")
        await task
        assert "ConnectTimeout" in rt.twitch.last_error
        assert rt._running and not rt._twitch_preparing
        assert all(not t.done() for t in rt._tasks if t.get_name() in {"tick-loop", "telemetry-loop"})
        await rt.stop()
    asyncio.run(scenario())


@pytest.mark.skipif(os.name == "nt", reason="POSIX process restart integration; Windows flags checked separately")
def test_real_launcher_recovers_bridge_and_backend_separately(tmp_path, config):
    root = Path(__file__).resolve().parents[1]
    shutil.copy(root / "launcher.py", tmp_path)
    shutil.copy(root / "bridge.py", tmp_path)
    shutil.copytree(root / "backend", tmp_path / "backend", ignore=shutil.ignore_patterns("__pycache__"))
    config["twitch"]["third_party_emotes"] = False
    config["features"]["twitch_integration"] = False
    import json
    (tmp_path / "config").mkdir()
    (tmp_path / "web/static").mkdir(parents=True)
    (tmp_path / "config/challenge_config.json").write_text(json.dumps(config))
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = os.environ.copy()
    for key in list(env):
        if key.startswith("TWITCH_"):
            env.pop(key)
    proc = subprocess.Popen([sys.executable, "launcher.py", "--mode", "test", "--port", str(port), "--no-browser"],
                            cwd=tmp_path, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    log = tmp_path / "data/launcher.log"
    def pids(name):
        return re.findall(name+r" gestartet \(PID (\d+)\)", log.read_text() if log.exists() else "")
    def wait_until(predicate):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if predicate():
                return
            assert proc.poll() is None, log.read_text() if log.exists() else "Launcher exited"
            time.sleep(0.05)
        raise AssertionError(log.read_text())
    def health():
        try:
            return httpx.get(f"http://127.0.0.1:{port}/api/health", timeout=0.3, trust_env=False).status_code == 200
        except httpx.RequestError:
            return False
    try:
        wait_until(lambda: len(pids("bridge")) == len(pids("backend")) == 1 and health())
        os.kill(int(pids("bridge")[0]), signal.SIGTERM)
        wait_until(lambda: len(pids("bridge")) == 2 and health())
        assert len(pids("backend")) == 1
        os.kill(int(pids("backend")[0]), signal.SIGTERM)
        wait_until(lambda: len(pids("backend")) == 2 and health())
        assert len(pids("bridge")) == 2
        assert "Exit-Code" in log.read_text()
    finally:
        proc.terminate()
        proc.wait(timeout=15)
    assert proc.returncode == 0
    assert "Bewusster Stop" in log.read_text()
    for name in ("bridge", "backend"):
        for pid in pids(name):
            with pytest.raises(ProcessLookupError):
                os.kill(int(pid), 0)
