from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx

from backend.runtime import StreamRuntime
from backend.trainer import FakeTrainerAdapter
from backend.twitch import REQUIRED_SCOPES, TwitchGateway


async def noop(_event):
    return None


def response(status: int, payload=None, text: str = "") -> httpx.Response:
    if payload is not None:
        return httpx.Response(status, json=payload)
    return httpx.Response(status, text=text)


def gateway(tmp_path: Path) -> TwitchGateway:
    return TwitchGateway(
        on_chat=noop,
        on_gift=noop,
        on_raid=noop,
        on_redemption=noop,
        auth_path=tmp_path / "twitch_auth.json",
        client_id="test-client",
    )


def test_device_login_persists_token_and_ids(tmp_path, monkeypatch):
    gw = gateway(tmp_path)
    calls = []

    async def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        if url == gw.OAUTH_DEVICE:
            return response(200, {
                "device_code": "device-1",
                "user_code": "ABCD1234",
                "verification_uri": "https://www.twitch.tv/activate?public=true&device-code=ABCD1234",
                "expires_in": 1800,
                "interval": 1,
            })
        if url == gw.OAUTH_TOKEN:
            return response(200, {
                "access_token": "access-1",
                "refresh_token": "refresh-1",
                "expires_in": 14400,
                "scope": list(REQUIRED_SCOPES),
                "token_type": "bearer",
            })
        if url == gw.OAUTH_VALIDATE:
            return response(200, {
                "client_id": "test-client",
                "login": "steinhq",
                "user_id": "12345",
                "scopes": list(REQUIRED_SCOPES),
                "expires_in": 14300,
            })
        raise AssertionError(url)

    monkeypatch.setattr(gw, "_request", fake_request)
    started = asyncio.run(gw.start_device_authorization())
    assert started["status"] == "pending"
    assert started["user_code"] == "ABCD1234"

    authorized = asyncio.run(gw.poll_device_authorization())
    assert authorized["status"] == "authorized"
    assert gw.configured()
    assert gw.broadcaster_id == "12345"
    assert gw.bot_user_id == "12345"
    assert gw.eventsub_user_id == "12345"
    assert gw.missing_scopes() == []
    assert "access_token" not in gw.status()

    saved = json.loads((tmp_path / "twitch_auth.json").read_text(encoding="utf-8"))
    assert saved["access_token"] == "access-1"
    assert saved["refresh_token"] == "refresh-1"
    assert saved["broadcaster_id"] == "12345"
    assert len(calls) == 3


def test_reward_create_refund_and_safe_delete(tmp_path, monkeypatch):
    gw = gateway(tmp_path)
    gw.token = "token"
    gw.refresh_token = "refresh"
    gw.broadcaster_id = "12345"
    gw.bot_user_id = "12345"
    gw.eventsub_user_id = "12345"
    gw.scopes = list(REQUIRED_SCOPES)
    pending_once = True
    calls = []

    async def fake_api(method, path, *, params=None, json_body=None, retry_auth=True):
        nonlocal pending_once
        calls.append((method, path, params, json_body))
        if method == "GET" and path == "/channel_points/custom_rewards":
            return response(200, {"data": []})
        if method == "POST" and path == "/channel_points/custom_rewards":
            return response(200, {"data": [{"id": "reward-1", "title": "Medipak", "cost": 500}]})
        if method == "GET" and path.endswith("/redemptions"):
            if pending_once:
                pending_once = False
                return response(200, {"data": [{"id": "redeem-1", "status": "UNFULFILLED", "user_name": "Viewer"}]})
            return response(200, {"data": []})
        if method == "PATCH" and path.endswith("/redemptions"):
            assert json_body == {"status": "CANCELED"}
            return response(200, {"data": [{"id": params["id"], "status": "CANCELED"}]})
        if method == "DELETE" and path == "/channel_points/custom_rewards":
            return response(204)
        raise AssertionError((method, path, params, json_body))

    monkeypatch.setattr(gw, "_api_request", fake_api)
    reward = asyncio.run(gw.ensure_medipack_reward(title="Medipak", cost=500, prompt="Boss"))
    assert reward["id"] == "reward-1"
    assert gw.reward_id == "reward-1"

    deleted = asyncio.run(gw.delete_medipack_reward(refund_unfulfilled=True))
    assert deleted["deleted"] is True
    assert deleted["refunded"] == 1
    assert gw.reward_id == ""
    patch_call = next(x for x in calls if x[0] == "PATCH")
    assert patch_call[2]["id"] == "redeem-1"


def make_runtime(tmp_path, config):
    root = tmp_path
    (root / "config").mkdir()
    (root / "data").mkdir()
    (root / "web" / "static").mkdir(parents=True)
    (root / "config" / "challenge_config.json").write_text(json.dumps(config), encoding="utf-8")
    return StreamRuntime(root=root, trainer_adapter=FakeTrainerAdapter())


def test_invalid_medipack_redemptions_are_refunded(tmp_path, config):
    rt = make_runtime(tmp_path, config)
    rt.config["features"]["twitch_integration"] = True
    rt.config["features"]["medipaks"] = True
    rt.twitch.reward_id = "reward-1"
    rt.twitch.refund_redemption = AsyncMock(return_value={"id": "red-1", "status": "CANCELED"})

    event = {
        "id": "red-1",
        "user_id": "u1",
        "user_login": "viewer",
        "user_name": "Viewer",
        "reward": {"id": "reward-1", "title": "Medipak"},
    }
    asyncio.run(rt.on_twitch_redemption(event))
    rt.twitch.refund_redemption.assert_awaited_once_with("red-1")

    rt.twitch.refund_redemption.reset_mock()
    rt.boss.start("small", 20, 1)
    first = dict(event, id="red-2")
    second = dict(event, id="red-3")
    asyncio.run(rt.on_twitch_redemption(first))
    rt.twitch.refund_redemption.assert_not_awaited()
    asyncio.run(rt.on_twitch_redemption(second))
    rt.twitch.refund_redemption.assert_awaited_once_with("red-3")


def test_admin_reward_update_persists_settings_and_enables_auto_create(tmp_path, config):
    rt = make_runtime(tmp_path, config)
    rt.twitch.update_medipack_reward = AsyncMock(return_value={"id": "reward-1", "title": "Boss Heal", "cost": 777})
    rt._restart_twitch_task = AsyncMock()

    result = asyncio.run(rt.admin_action("twitch_reward_update", {
        "title": "Boss Heal",
        "cost": 777,
        "prompt": "Gibt dem Bossfight Zeit zurück",
    }))

    assert result["ok"] is True
    saved = json.loads((tmp_path / "config" / "challenge_config.json").read_text(encoding="utf-8"))
    assert saved["twitch"]["medipack_reward_title"] == "Boss Heal"
    assert saved["twitch"]["medipack_reward_cost"] == 777
    assert saved["twitch"]["medipack_reward_prompt"] == "Gibt dem Bossfight Zeit zurück"
    assert saved["twitch"]["medipack_auto_create"] is True
    rt.twitch.update_medipack_reward.assert_awaited_once()
    rt._restart_twitch_task.assert_awaited_once()


def test_admin_reward_delete_refunds_and_keeps_reward_deleted_after_restart(tmp_path, config):
    rt = make_runtime(tmp_path, config)
    rt.twitch.delete_medipack_reward = AsyncMock(return_value={"ok": True, "deleted": True, "refunded": 2})
    rt._restart_twitch_task = AsyncMock()

    result = asyncio.run(rt.admin_action("twitch_reward_delete", {"refund_unfulfilled": True}))

    assert result["deleted"] is True
    assert result["refunded"] == 2
    saved = json.loads((tmp_path / "config" / "challenge_config.json").read_text(encoding="utf-8"))
    assert saved["twitch"]["medipack_auto_create"] is False
    rt.twitch.delete_medipack_reward.assert_awaited_once_with(refund_unfulfilled=True)
    rt._restart_twitch_task.assert_awaited_once()
