from __future__ import annotations

import asyncio
import json
import os
import time
from collections import deque
from pathlib import Path
from typing import Any, Awaitable, Callable

import httpx
import websockets

from .utils import atomic_write_json


Callback = Callable[[dict[str, Any]], Awaitable[None]]

# This is the public Twitch client ID already used by the SteinHQ/TwitchChat public-client setup.
# It is not a secret. It can be overridden with TWITCH_CLIENT_ID or twitch.client_id in config.
DEFAULT_TWITCH_CLIENT_ID = "w48xhefd9ddp8pjl6xv77u9pb4re02"

# One broadcaster-account login can cover chat read/write, gift events and channel-point management.
REQUIRED_SCOPES = (
    "user:read:chat",
    "user:write:chat",
    "channel:read:subscriptions",
    "channel:manage:redemptions",
)


class TwitchAuthError(RuntimeError):
    """The account must grant Twitch access again."""


def error_detail(exc: Exception) -> str:
    # httpx timeouts frequently have an empty str(); retain a useful diagnosis.
    if isinstance(exc, httpx.TimeoutException):
        return f"{type(exc).__name__}: Twitch antwortet nicht rechtzeitig. Verbindung wird erneut versucht."
    return f"{type(exc).__name__}: {str(exc).strip() or 'Verbindungsfehler'}"


class TwitchGateway:
    EVENTSUB_URL = "wss://eventsub.wss.twitch.tv/ws"
    HELIX = "https://api.twitch.tv/helix"
    OAUTH_VALIDATE = "https://id.twitch.tv/oauth2/validate"
    OAUTH_DEVICE = "https://id.twitch.tv/oauth2/device"
    OAUTH_TOKEN = "https://id.twitch.tv/oauth2/token"
    OAUTH_REVOKE = "https://id.twitch.tv/oauth2/revoke"

    def __init__(
        self,
        *,
        on_chat: Callback,
        on_gift: Callback,
        on_raid: Callback,
        on_redemption: Callback,
        auth_path: str | Path | None = None,
        client_id: str = "",
    ):
        self.auth_path = Path(auth_path) if auth_path else None
        self._auth: dict[str, Any] = self._load_auth()
        self.client_id = (
            os.getenv("TWITCH_CLIENT_ID", "").strip()
            or str(client_id or "").strip()
            or str(self._auth.get("client_id", "")).strip()
            or DEFAULT_TWITCH_CLIENT_ID
        )
        self.token = str(self._auth.get("access_token", "") or os.getenv("TWITCH_USER_ACCESS_TOKEN", "")).strip().removeprefix("oauth:")
        self.refresh_token = str(self._auth.get("refresh_token", "")).strip()
        self.broadcaster_id = str(self._auth.get("broadcaster_id", "") or os.getenv("TWITCH_BROADCASTER_ID", "")).strip()
        self.bot_user_id = str(self._auth.get("bot_user_id", "") or os.getenv("TWITCH_BOT_USER_ID", "")).strip() or self.broadcaster_id
        self.eventsub_user_id = str(self._auth.get("eventsub_user_id", "") or os.getenv("TWITCH_EVENTSUB_USER_ID", "")).strip() or self.bot_user_id
        self.reward_id = str(self._auth.get("medipack_reward_id", "") or os.getenv("TWITCH_MEDIPACK_REWARD_ID", "")).strip()
        self.login = str(self._auth.get("login", "")).strip()
        self.scopes: list[str] = list(self._auth.get("scopes") or [])
        self.expires_at = float(self._auth.get("expires_at", 0.0) or 0.0)
        self.on_chat = on_chat
        self.on_gift = on_gift
        self.on_raid = on_raid
        self.on_redemption = on_redemption
        self.running = False
        self.connected = False
        self.last_error = ""
        self.reward_error = ""
        self._seen_ids: deque[tuple[str, float]] = deque(maxlen=5000)
        self._seen_set: set[str] = set()
        self._device_flow: dict[str, Any] | None = None
        self._auth_lock = asyncio.Lock()
        self._poll_lock = asyncio.Lock()
        self._reauth_required = False
        self._validation_pending = bool(self._auth.get("validation_pending", False))

    def _load_auth(self) -> dict[str, Any]:
        if not self.auth_path or not self.auth_path.exists():
            return {}
        try:
            raw = json.loads(self.auth_path.read_text(encoding="utf-8"))
            return raw if isinstance(raw, dict) else {}
        except Exception:
            return {}

    def _save_auth(self) -> None:
        if not self.auth_path:
            return
        payload = {
            "client_id": self.client_id,
            "access_token": self.token,
            "refresh_token": self.refresh_token,
            "broadcaster_id": self.broadcaster_id,
            "bot_user_id": self.bot_user_id,
            "eventsub_user_id": self.eventsub_user_id,
            "medipack_reward_id": self.reward_id,
            "login": self.login,
            "scopes": list(self.scopes),
            "expires_at": self.expires_at,
            "updated_at": time.time(),
            "validation_pending": self._validation_pending,
        }
        self.auth_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(self.auth_path, payload)
        try:
            os.chmod(self.auth_path, 0o600)
        except OSError:
            pass

    def _clear_auth_file(self) -> None:
        if self.auth_path and self.auth_path.exists():
            try:
                self.auth_path.unlink()
            except OSError:
                pass

    @property
    def required_scopes(self) -> tuple[str, ...]:
        return REQUIRED_SCOPES

    def missing_scopes(self) -> list[str]:
        current = set(self.scopes)
        return [scope for scope in self.required_scopes if scope not in current]

    def configured(self) -> bool:
        return bool(self.client_id and self.authenticated() and self.eventsub_user_id)

    def authenticated(self) -> bool:
        return bool(self.token and self.broadcaster_id and not self._reauth_required and not self._validation_pending)

    def status(self) -> dict[str, Any]:
        device = None
        if self._device_flow:
            remaining = max(0, int(self._device_flow["expires_at"] - time.time()))
            device = {
                "active": remaining > 0,
                "user_code": self._device_flow.get("user_code", ""),
                "verification_uri": self._device_flow.get("verification_uri", ""),
                "expires_in": remaining,
                "interval": int(self._device_flow.get("interval", 5)),
            }
        return {
            "configured": self.configured(),
            "authenticated": self.authenticated(),
            "has_token": bool(self.token),
            "reauth_required": self._reauth_required,
            "validation_pending": self._validation_pending,
            "connected": self.connected,
            "client_id": self.client_id,
            "broadcaster_id": self.broadcaster_id,
            "bot_user_id": self.bot_user_id,
            "eventsub_user_id": self.eventsub_user_id,
            "login": self.login,
            "scopes": self.scopes,
            "required_scopes": list(self.required_scopes),
            "missing_scopes": self.missing_scopes(),
            "expires_in": max(0, int(self.expires_at - time.time())) if self.expires_at else None,
            "last_error": self.last_error,
            "medipack_reward_id": self.reward_id,
            "reward_error": self.reward_error,
            "device_auth": device,
        }

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}", "Client-Id": self.client_id, "Content-Type": "application/json"}

    async def _request(self, method: str, url: str, *, headers: dict[str, str] | None = None, params: Any = None, data: Any = None, json_body: Any = None, timeout: float = 8.0) -> httpx.Response:
        async with httpx.AsyncClient(timeout=timeout) as client:
            return await client.request(method, url, headers=headers, params=params, data=data, json=json_body)

    async def validate_token(self, *, refresh_on_401: bool = True) -> bool:
        if not self.token:
            self.last_error = "Kein Twitch Access Token vorhanden"
            return False
        checked_token = self.token
        try:
            r = await self._request("GET", self.OAUTH_VALIDATE, headers={"Authorization": f"OAuth {checked_token}"}, timeout=15)
            if checked_token != self.token:
                return await self.validate_token(refresh_on_401=False)
            if r.status_code == 401 and refresh_on_401 and self.refresh_token:
                if await self.refresh_access_token(expected_token=checked_token):
                    return await self.validate_token(refresh_on_401=False)
            if r.status_code != 200:
                if r.status_code == 401:
                    self._reauth_required = True
                    self.connected = False
                self.last_error = f"OAuth validate: HTTP {r.status_code}: {r.text[:240]}"
                return False
            body = r.json()
            token_client = str(body.get("client_id", ""))
            if token_client and token_client != self.client_id:
                self._reauth_required = True
                self.last_error = "OAuth Token gehört zu einer anderen Twitch Client-ID"
                return False
            self.scopes = list(body.get("scopes") or [])
            self.broadcaster_id = str(body.get("user_id", "") or self.broadcaster_id)
            self.login = str(body.get("login", "") or self.login)
            self.bot_user_id = self.bot_user_id or self.broadcaster_id
            self.eventsub_user_id = self.eventsub_user_id or self.bot_user_id
            expires_in = int(body.get("expires_in", 0) or 0)
            self.expires_at = time.time() + expires_in if expires_in else self.expires_at
            missing = self.missing_scopes()
            self.last_error = f"Fehlende Twitch-Scopes: {', '.join(missing)}" if missing else ""
            self._reauth_required = bool(missing)
            self._validation_pending = False
            self._save_auth()
            return not missing
        except Exception as exc:
            self.last_error = f"OAuth validate: {error_detail(exc)}"
            return False

    async def refresh_access_token(self, *, expected_token: str | None = None) -> bool:
        if not self.refresh_token or not self.client_id:
            return False
        async with self._auth_lock:
            if expected_token is not None and self.token != expected_token:
                return bool(self.token)
            old_refresh = self.refresh_token
            try:
                r = await self._request(
                    "POST",
                    self.OAUTH_TOKEN,
                    data={
                        "client_id": self.client_id,
                        "grant_type": "refresh_token",
                        "refresh_token": old_refresh,
                    },
                    timeout=15,
                )
                if r.status_code != 200:
                    if r.status_code in (400, 401):
                        self._reauth_required = True
                        self.connected = False
                    self.last_error = f"OAuth refresh: HTTP {r.status_code}: {r.text[:240]}"
                    return False
                body = r.json()
                new_token = str(body.get("access_token", "")).strip()
                if not new_token:
                    raise RuntimeError("Twitch hat keinen Access Token zurückgegeben")
                self.token = new_token
                # Device-flow refresh tokens are single-use; always replace with the newly returned one.
                self.refresh_token = str(body.get("refresh_token", "") or old_refresh).strip()
                self.scopes = list(body.get("scope") or self.scopes)
                expires_in = int(body.get("expires_in", 0) or 0)
                self.expires_at = time.time() + expires_in if expires_in else 0.0
                self.last_error = ""
                self._reauth_required = False
                self._save_auth()
                return bool(self.token)
            except Exception as exc:
                self.last_error = f"OAuth refresh: {error_detail(exc)}"
                return False

    async def start_device_authorization(self) -> dict[str, Any]:
        async with self._poll_lock:
            return await self._start_device_authorization()

    async def _start_device_authorization(self) -> dict[str, Any]:
        if not self.client_id:
            raise RuntimeError("Twitch Client-ID fehlt")
        r = await self._request(
            "POST",
            self.OAUTH_DEVICE,
            data={"client_id": self.client_id, "scopes": " ".join(self.required_scopes)},
            timeout=15,
        )
        if r.status_code != 200:
            raise RuntimeError(f"Twitch Device Login: HTTP {r.status_code}: {r.text[:300]}")
        body = r.json()
        expires = int(body.get("expires_in", 0) or 0)
        self._device_flow = {
            "device_code": str(body["device_code"]),
            "user_code": str(body["user_code"]),
            "verification_uri": str(body["verification_uri"]),
            "interval": max(1, int(body.get("interval", 5) or 5)),
            "expires_at": time.time() + expires,
            "next_poll_at": 0.0,
        }
        self._validation_pending = False
        return {"ok": True, "status": "pending", **self.status()["device_auth"]}

    async def poll_device_authorization(self) -> dict[str, Any]:
        # Browsers may poll twice; a device code can only be exchanged once.
        async with self._poll_lock:
            return await self._poll_device_authorization()

    async def _finish_device_validation(self) -> dict[str, Any]:
        if not await self.validate_token(refresh_on_401=False):
            if self._reauth_required:
                self._validation_pending = False
                self._device_flow = None
                self._save_auth()
                raise TwitchAuthError(self.last_error + ". Bitte erneut mit Twitch anmelden.")
            return {"ok": True, "status": "validating", "retry_after": 5, "message": self.last_error}
        self._device_flow = None
        self._save_auth()
        return {"ok": True, "status": "authorized", "twitch": self.status()}

    async def _poll_device_authorization(self) -> dict[str, Any]:
        if self._validation_pending:
            return await self._finish_device_validation()
        flow = self._device_flow
        if self.authenticated() and (not flow or flow.get("token_received")):
            self._device_flow = None
            return {"ok": True, "status": "authorized", "twitch": self.status()}
        if not flow:
            return {"ok": False, "status": "not_started"}
        now = time.time()
        if now >= float(flow["expires_at"]):
            self._device_flow = None
            return {"ok": False, "status": "expired"}
        if now < float(flow.get("next_poll_at", 0)):
            return {"ok": True, "status": "pending", "retry_after": max(1, int(flow["next_poll_at"] - now))}
        flow["next_poll_at"] = now + int(flow.get("interval", 5))
        try:
            async with self._auth_lock:
                r = await self._request(
                    "POST", self.OAUTH_TOKEN,
                    data={"client_id": self.client_id, "scopes": " ".join(self.required_scopes),
                          "device_code": flow["device_code"],
                          "grant_type": "urn:ietf:params:oauth:grant-type:device_code"}, timeout=15,
                )
                if r.status_code == 200:
                    body = r.json()
                    new_token = str(body.get("access_token", "")).strip()
                    if not new_token:
                        raise RuntimeError("Twitch hat keinen Access Token zurückgegeben")
                    self.token = new_token
                    self.refresh_token = str(body.get("refresh_token", "")).strip()
                    self.scopes = list(body.get("scope") or [])
                    self.expires_at = time.time() + int(body.get("expires_in", 0) or 0)
                    # Never associate a new token with the previous account's IDs.
                    self.broadcaster_id = self.bot_user_id = self.eventsub_user_id = self.login = ""
                    self._reauth_required = False
                    self._validation_pending = True
                    flow["token_received"] = True
                    self._save_auth()
        except httpx.RequestError as exc:
            self.last_error = f"Twitch Device Login: {error_detail(exc)}"
            return {"ok": True, "status": "pending", "retry_after": 5, "message": self.last_error}
        if r.status_code == 400:
            try:
                message = str(r.json().get("message") or r.json().get("error", "")).lower()
            except Exception:
                message = r.text.lower()
            if "authorization_pending" in message:
                return {"ok": True, "status": "pending", "retry_after": int(flow.get("interval", 5))}
            if "slow_down" in message:
                flow["interval"] = int(flow.get("interval", 5)) + 5
                flow["next_poll_at"] = now + flow["interval"]
                return {"ok": True, "status": "pending", "retry_after": int(flow["interval"])}
            if "expired" in message or "access_denied" in message:
                self._device_flow = None
                return {"ok": False, "status": "expired"}
            raise RuntimeError(f"Twitch Device Login: {r.text[:300]}")
        if r.status_code != 200:
            raise RuntimeError(f"Twitch Device Login: HTTP {r.status_code}: {r.text[:300]}")
        return await self._finish_device_validation()

    async def logout(self, *, revoke: bool = True) -> None:
        async with self._poll_lock:
            async with self._auth_lock:
                await self._logout(revoke=revoke)

    async def _logout(self, *, revoke: bool = True) -> None:
        old_token = self.token
        if revoke and old_token and self.client_id:
            try:
                await self._request("POST", self.OAUTH_REVOKE, data={"client_id": self.client_id, "token": old_token}, timeout=6)
            except Exception:
                pass
        self.token = ""
        self.refresh_token = ""
        self.broadcaster_id = ""
        self.bot_user_id = ""
        self.eventsub_user_id = ""
        self.login = ""
        self.scopes = []
        self.expires_at = 0.0
        self.reward_id = ""
        self.connected = False
        self._device_flow = None
        self._validation_pending = False
        self._reauth_required = False
        self._clear_auth_file()

    async def _api_request(self, method: str, path: str, *, params: Any = None, json_body: Any = None, retry_auth: bool = True) -> httpx.Response:
        if not self.token or self._reauth_required:
            raise TwitchAuthError("Twitch-Anmeldung ist ungültig. Bitte im Adminmenü erneut mit Twitch anmelden.")
        sent_token = self.token
        try:
            r = await self._request(method, f"{self.HELIX}{path}", headers=self._headers(), params=params, json_body=json_body, timeout=15)
        except httpx.RequestError as exc:
            raise RuntimeError(f"Twitch API {method} {path}: {error_detail(exc)}. Anfrage fehlgeschlagen; bitte erneut versuchen.") from exc
        if r.status_code == 401:
            if retry_auth:
                renewed = self.token != sent_token
                if not renewed and self.refresh_token:
                    renewed = await self.refresh_access_token(expected_token=sent_token)
                if renewed:
                    return await self._api_request(method, path, params=params, json_body=json_body, retry_auth=False)
            self._reauth_required = True
            self.connected = False
            self.last_error = "Twitch hat die Anmeldung abgelehnt (HTTP 401). Bitte im Adminmenü erneut mit Twitch anmelden."
            raise TwitchAuthError(self.last_error)
        return r

    async def _subscribe(self, session_id: str, event_type: str, condition: dict[str, str], version: str = "1") -> None:
        body = {"type": event_type, "version": version, "condition": condition, "transport": {"method": "websocket", "session_id": session_id}}
        r = await self._api_request("POST", "/eventsub/subscriptions", json_body=body)
        if r.status_code not in {202, 409}:
            raise RuntimeError(f"EventSub {event_type}: HTTP {r.status_code}: {r.text[:300]}")

    async def _create_subscriptions(self, session_id: str) -> None:
        await self._subscribe(session_id, "channel.chat.message", {"broadcaster_user_id": self.broadcaster_id, "user_id": self.eventsub_user_id})
        await self._subscribe(session_id, "channel.subscription.gift", {"broadcaster_user_id": self.broadcaster_id})
        await self._subscribe(session_id, "channel.raid", {"to_broadcaster_user_id": self.broadcaster_id})
        condition = {"broadcaster_user_id": self.broadcaster_id}
        if self.reward_id:
            condition["reward_id"] = self.reward_id
        await self._subscribe(session_id, "channel.channel_points_custom_reward_redemption.add", condition)

    def _dedupe(self, message_id: str) -> bool:
        if not message_id:
            return False
        if message_id in self._seen_set:
            return True
        self._seen_set.add(message_id)
        self._seen_ids.append((message_id, time.time()))
        while self._seen_ids and time.time() - self._seen_ids[0][1] > 3600:
            old, _ = self._seen_ids.popleft()
            self._seen_set.discard(old)
        return False

    async def process_notification(self, message: dict[str, Any]) -> None:
        metadata = message.get("metadata") or {}
        if self._dedupe(str(metadata.get("message_id", ""))):
            return
        payload = message.get("payload") or {}
        subscription = payload.get("subscription") or {}
        event = payload.get("event") or {}
        etype = subscription.get("type") or metadata.get("subscription_type")
        event["_eventsub_message_id"] = metadata.get("message_id", "")
        if etype == "channel.chat.message":
            await self.on_chat(event)
        elif etype == "channel.subscription.gift":
            await self.on_gift(event)
        elif etype == "channel.raid":
            await self.on_raid(event)
        elif etype == "channel.channel_points_custom_reward_redemption.add":
            await self.on_redemption(event)

    async def run(self) -> None:
        if not self.configured():
            self.last_error = "Twitch-Anmeldung fehlt"
            return
        self.running = True
        url = self.EVENTSUB_URL
        backoff = 2
        while self.running:
            try:
                if not await self.validate_token():
                    if self._reauth_required:
                        break
                    await asyncio.sleep(backoff)
                    backoff = min(30, backoff * 2)
                    continue
                async with websockets.connect(url, ping_interval=None, close_timeout=3) as ws:
                    self.connected = True
                    backoff = 2
                    async for raw in ws:
                        msg = json.loads(raw)
                        mtype = (msg.get("metadata") or {}).get("message_type")
                        if mtype == "session_welcome":
                            session_id = msg["payload"]["session"]["id"]
                            await self._create_subscriptions(session_id)
                        elif mtype == "notification":
                            await self.process_notification(msg)
                        elif mtype == "session_reconnect":
                            url = msg["payload"]["session"].get("reconnect_url") or self.EVENTSUB_URL
                            break
                        elif mtype == "revocation":
                            sub = msg.get("payload", {}).get("subscription", {})
                            self.last_error = f"EventSub revoked: {sub.get('type')} / {sub.get('status')}"
                    self.connected = False
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self.connected = False
                self.last_error = error_detail(exc)
                if self._reauth_required:
                    break
                await asyncio.sleep(backoff)
                backoff = min(30, backoff * 2)
        self.connected = False

    async def maintain_auth(self) -> None:
        """Validate the maintained OAuth session hourly and refresh public-client tokens when needed."""
        next_check = time.time() + 3600
        while True:
            await asyncio.sleep(60)
            try:
                now = time.time()
                expiring = bool(self.expires_at and self.expires_at <= now + 60)
                if self.token and not self._reauth_required and (now >= next_check or expiring or self._validation_pending or not self.authenticated()):
                    if expiring and self.refresh_token:
                        await self.refresh_access_token(expected_token=self.token)
                    await self.validate_token()
                    next_check = now + 3600
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.last_error = f"OAuth maintenance: {error_detail(exc)}"

    async def stop(self) -> None:
        self.running = False

    async def send_chat(self, message: str) -> bool:
        if not self.configured() or not self.bot_user_id:
            return False
        body = {"broadcaster_id": self.broadcaster_id, "sender_id": self.bot_user_id, "message": message[:500]}
        try:
            r = await self._api_request("POST", "/chat/messages", json_body=body)
            if r.status_code not in {200, 202}:
                self.last_error = f"Send chat HTTP {r.status_code}: {r.text[:200]}"
                return False
            data = r.json().get("data") or []
            if data and data[0].get("is_sent") is False:
                self.last_error = "Chat abgewiesen: " + str(data[0].get("drop_reason") or "unbekannt")
                return False
            return True
        except Exception as exc:
            self.last_error = f"Send chat: {error_detail(exc)}"
            return False

    async def list_custom_rewards(self, *, manageable_only: bool = False) -> list[dict[str, Any]]:
        r = await self._api_request(
            "GET",
            "/channel_points/custom_rewards",
            params={"broadcaster_id": self.broadcaster_id, "only_manageable_rewards": str(bool(manageable_only)).lower()},
        )
        if r.status_code != 200:
            raise RuntimeError(f"Custom Rewards: HTTP {r.status_code}: {r.text[:300]}")
        return list(r.json().get("data") or [])

    async def ensure_medipack_reward(self, *, title: str, cost: int, prompt: str = "") -> dict[str, Any]:
        if not self.configured():
            raise RuntimeError("Twitch ist nicht angemeldet")
        if "channel:manage:redemptions" not in self.scopes:
            raise RuntimeError("Twitch-Scope channel:manage:redemptions fehlt")
        title = (title or "Medipak").strip()[:45]
        prompt = (prompt or "").strip()[:200]
        cost = max(1, int(cost))
        try:
            manageable = await self.list_custom_rewards(manageable_only=True)
            if self.reward_id:
                current = next((x for x in manageable if str(x.get("id")) == self.reward_id), None)
                if current:
                    self.reward_error = ""
                    return current
                self.reward_id = ""
                self._save_auth()
            by_title = next((x for x in manageable if str(x.get("title", "")).casefold() == title.casefold()), None)
            if by_title:
                self.reward_id = str(by_title["id"])
                self.reward_error = ""
                self._save_auth()
                return by_title
            # Detect a title collision with a reward this application cannot manage.
            all_rewards = await self.list_custom_rewards(manageable_only=False)
            foreign = next((x for x in all_rewards if str(x.get("title", "")).casefold() == title.casefold()), None)
            if foreign:
                raise RuntimeError(
                    f"Es existiert bereits eine Kanalbelohnung '{title}', die nicht von dieser App verwaltet werden kann. "
                    "Bitte diese einmal in Twitch löschen/umbenennen oder im Admin einen anderen Titel wählen."
                )
            body = {
                "title": title,
                "cost": cost,
                "prompt": prompt,
                "is_enabled": True,
                "is_user_input_required": False,
                "should_redemptions_skip_request_queue": False,
            }
            r = await self._api_request(
                "POST",
                "/channel_points/custom_rewards",
                params={"broadcaster_id": self.broadcaster_id},
                json_body=body,
            )
            if r.status_code not in {200, 201}:
                raise RuntimeError(f"Medipak erstellen: HTTP {r.status_code}: {r.text[:300]}")
            data = list(r.json().get("data") or [])
            if not data:
                raise RuntimeError("Twitch hat keine erstellte Medipak-Belohnung zurückgegeben")
            reward = data[0]
            self.reward_id = str(reward.get("id", ""))
            self.reward_error = ""
            self._save_auth()
            return reward
        except Exception as exc:
            self.reward_error = "Medipak-Belohnung prüfen/anlegen: " + error_detail(exc)
            raise

    async def update_medipack_reward(self, *, title: str, cost: int, prompt: str = "") -> dict[str, Any]:
        if not self.reward_id:
            return await self.ensure_medipack_reward(title=title, cost=cost, prompt=prompt)
        body = {"title": (title or "Medipak").strip()[:45], "cost": max(1, int(cost)), "prompt": (prompt or "").strip()[:200], "is_enabled": True, "should_redemptions_skip_request_queue": False}
        r = await self._api_request(
            "PATCH",
            "/channel_points/custom_rewards",
            params={"broadcaster_id": self.broadcaster_id, "id": self.reward_id},
            json_body=body,
        )
        if r.status_code == 404:
            self.reward_id = ""
            self._save_auth()
            return await self.ensure_medipack_reward(title=body["title"], cost=body["cost"], prompt=body["prompt"])
        if r.status_code != 200:
            raise RuntimeError(f"Medipak aktualisieren: HTTP {r.status_code}: {r.text[:300]}")
        data = list(r.json().get("data") or [])
        self.reward_error = ""
        return data[0] if data else {"id": self.reward_id, **body}

    async def list_medipack_redemptions(self, *, status: str = "UNFULFILLED", first: int = 50) -> list[dict[str, Any]]:
        if not self.reward_id:
            return []
        status = str(status).upper()
        if status not in {"UNFULFILLED", "FULFILLED", "CANCELED"}:
            raise ValueError("Ungültiger Redemption-Status")
        r = await self._api_request(
            "GET",
            "/channel_points/custom_rewards/redemptions",
            params={
                "broadcaster_id": self.broadcaster_id,
                "reward_id": self.reward_id,
                "status": status,
                "sort": "NEWEST",
                "first": max(1, min(50, int(first))),
            },
        )
        if r.status_code == 404:
            return []
        if r.status_code != 200:
            raise RuntimeError(f"Medipak Redemptions: HTTP {r.status_code}: {r.text[:300]}")
        return list(r.json().get("data") or [])

    async def update_redemption_status(self, redemption_id: str, status: str) -> dict[str, Any]:
        if not self.reward_id:
            raise RuntimeError("Medipak-Belohnung existiert nicht")
        status = str(status).upper()
        if status not in {"CANCELED", "FULFILLED"}:
            raise ValueError("Status muss CANCELED oder FULFILLED sein")
        r = await self._api_request(
            "PATCH",
            "/channel_points/custom_rewards/redemptions",
            params={"broadcaster_id": self.broadcaster_id, "reward_id": self.reward_id, "id": redemption_id},
            json_body={"status": status},
        )
        if r.status_code != 200:
            raise RuntimeError(f"Medipak Redemption {status}: HTTP {r.status_code}: {r.text[:300]}")
        data = list(r.json().get("data") or [])
        return data[0] if data else {"id": redemption_id, "status": status}

    async def refund_redemption(self, redemption_id: str) -> dict[str, Any]:
        return await self.update_redemption_status(redemption_id, "CANCELED")

    async def delete_medipack_reward(self, *, refund_unfulfilled: bool = True) -> dict[str, Any]:
        if not self.reward_id:
            return {"ok": True, "deleted": False, "refunded": 0}
        reward_id = self.reward_id
        refunded = 0
        if refund_unfulfilled:
            # Cancel in batches until no UNFULFILLED items remain. Deleting a reward directly
            # would otherwise mark open redemptions fulfilled instead of refunding the points.
            for _ in range(100):
                pending = await self.list_medipack_redemptions(status="UNFULFILLED", first=50)
                if not pending:
                    break
                for redemption in pending:
                    rid = str(redemption.get("id", ""))
                    if not rid:
                        continue
                    await self.refund_redemption(rid)
                    refunded += 1
                if len(pending) < 50:
                    break
        r = await self._api_request(
            "DELETE",
            "/channel_points/custom_rewards",
            params={"broadcaster_id": self.broadcaster_id, "id": reward_id},
        )
        if r.status_code not in {204, 404}:
            raise RuntimeError(f"Medipak löschen: HTTP {r.status_code}: {r.text[:300]}")
        self.reward_id = ""
        self.reward_error = ""
        self._save_auth()
        return {"ok": True, "deleted": r.status_code == 204, "refunded": refunded, "reward_id": reward_id}
