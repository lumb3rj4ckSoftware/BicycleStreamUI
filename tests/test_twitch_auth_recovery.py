from __future__ import annotations

import asyncio
import json
import time
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.twitch import REQUIRED_SCOPES, TwitchAuthError
from test_twitch_auth_rewards import gateway, make_runtime, response


def validation(gw):
    return response(200, {"client_id": gw.client_id, "user_id": "new-account", "login": "new-login",
                          "scopes": list(REQUIRED_SCOPES), "expires_in": 1000})


def device_flow(gw):
    gw._device_flow = {"device_code": "single-use", "user_code": "CODE", "expires_at": time.time()+60,
                       "interval": 1, "next_poll_at": 0}


def test_new_token_survives_validation_timeout_and_restart(tmp_path, monkeypatch):
    gw = gateway(tmp_path)
    gw.token = "old-token"
    gw.broadcaster_id = gw.bot_user_id = gw.eventsub_user_id = "old-account"
    device_flow(gw)
    exchanges = 0

    async def request(method, url, **kwargs):
        nonlocal exchanges
        if url == gw.OAUTH_TOKEN:
            exchanges += 1
            return response(200, {"access_token": "new-token", "refresh_token": "new-refresh",
                                  "scope": list(REQUIRED_SCOPES), "expires_in": 1000})
        raise httpx.ReadTimeout("")

    monkeypatch.setattr(gw, "_request", request)
    result = asyncio.run(gw.poll_device_authorization())
    assert result["status"] == "validating"
    assert "ReadTimeout" in result["message"]
    saved = json.loads(gw.auth_path.read_text())
    assert saved["access_token"] == "new-token" and saved["refresh_token"] == "new-refresh"
    assert saved["broadcaster_id"] == "" and saved["validation_pending"] is True
    assert not gw.authenticated()

    restarted = gateway(tmp_path)
    async def recovered(method, url, **kwargs):
        assert url == restarted.OAUTH_VALIDATE  # Never exchange the consumed code again.
        return validation(restarted)
    monkeypatch.setattr(restarted, "_request", recovered)
    assert asyncio.run(restarted.poll_device_authorization())["status"] == "authorized"
    assert restarted.broadcaster_id == restarted.bot_user_id == restarted.eventsub_user_id == "new-account"
    assert exchanges == 1


def test_pending_login_recovers_without_restart_or_second_exchange(tmp_path, monkeypatch):
    gw = gateway(tmp_path)
    device_flow(gw)
    calls = []
    async def request(method, url, **kwargs):
        calls.append(url)
        if url == gw.OAUTH_TOKEN:
            return response(200, {"access_token": "new-token", "refresh_token": "refresh"})
        if calls.count(gw.OAUTH_VALIDATE) == 1:
            raise httpx.ConnectTimeout("")
        return validation(gw)
    monkeypatch.setattr(gw, "_request", request)
    async def scenario():
        assert (await gw.poll_device_authorization())["status"] == "validating"
        assert (await gw.poll_device_authorization())["status"] == "authorized"
    asyncio.run(scenario())
    assert calls.count(gw.OAUTH_TOKEN) == 1


def test_parallel_401s_rotate_refresh_token_once(tmp_path, monkeypatch):
    gw = gateway(tmp_path)
    gw.token, gw.refresh_token = "expired", "refresh-old"
    gw.broadcaster_id = gw.bot_user_id = gw.eventsub_user_id = "account"
    count = 0
    async def request(method, url, **kwargs):
        nonlocal count
        if url == gw.OAUTH_TOKEN:
            count += 1
            await asyncio.sleep(0.01)
            assert kwargs["data"]["refresh_token"] == "refresh-old"
            return response(200, {"access_token": "fresh", "refresh_token": "refresh-new"})
        if kwargs["headers"]["Authorization"] == "Bearer expired":
            await asyncio.sleep(0)
            return response(401, {"message": "Invalid OAuth token"})
        return response(200, {"data": []})
    monkeypatch.setattr(gw, "_request", request)
    async def scenario():
        replies = await asyncio.gather(gw._api_request("GET", "/one"), gw._api_request("GET", "/two"))
        assert all(r.status_code == 200 for r in replies)
    asyncio.run(scenario())
    assert count == 1 and gw.refresh_token == "refresh-new"


def test_rejected_refresh_enables_new_login(tmp_path, monkeypatch):
    gw = gateway(tmp_path)
    gw.token, gw.refresh_token, gw.broadcaster_id = "expired", "invalid-refresh", "account"
    async def request(method, url, **kwargs):
        return response(400 if url == gw.OAUTH_TOKEN else 401, {"message": "Invalid OAuth token"})
    monkeypatch.setattr(gw, "_request", request)
    with pytest.raises(TwitchAuthError, match="erneut"):
        asyncio.run(gw._api_request("GET", "/channel_points/custom_rewards/redemptions"))
    assert not gw.authenticated() and gw.status()["reauth_required"]


def test_validate_401_without_refresh_marks_logged_out(tmp_path, monkeypatch):
    gw = gateway(tmp_path)
    gw.token, gw.broadcaster_id = "invalid", "account"
    monkeypatch.setattr(gw, "_request", AsyncMock(return_value=response(401)))
    assert not asyncio.run(gw.validate_token())
    assert not gw.authenticated()


def test_admin_auth_error_is_actionable_401(tmp_path, config):
    rt = make_runtime(tmp_path, config)
    rt.admin_action = AsyncMock(side_effect=TwitchAuthError("Bitte erneut mit Twitch anmelden."))
    with TestClient(create_app(rt)) as client:
        result = client.post("/api/admin/action", json={"action": "twitch_redemptions", "payload": {}})
    assert result.status_code == 401 and "erneut" in result.json()["detail"]


def test_telemetry_retries_partial_write(tmp_path, config, monkeypatch):
    rt = make_runtime(tmp_path, config)
    path = rt._bridge_path()
    path.write_text("")
    rt._running = True
    rt.process_telemetry = AsyncMock()
    async def sleep(delay):
        if delay == 0.05:
            path.write_text('{"distance": 0.28, "speed": 38.3}')
        else:
            rt._running = False
    monkeypatch.setattr("backend.runtime.asyncio.sleep", sleep)
    asyncio.run(rt._telemetry_loop())
    rt.process_telemetry.assert_awaited_once_with({"distance": 0.28, "speed": 38.3})
    assert not rt.telemetry_health["last_error"]


def test_background_validation_does_not_reexchange_device_code(tmp_path, monkeypatch):
    gw = gateway(tmp_path)
    device_flow(gw)
    gw._device_flow["token_received"] = True
    gw.token = "new"
    gw._validation_pending = True
    monkeypatch.setattr(gw, "_request", AsyncMock(return_value=validation(gw)))
    assert asyncio.run(gw.validate_token())
    assert asyncio.run(gw.poll_device_authorization())["status"] == "authorized"
    assert gw._request.await_count == 1
