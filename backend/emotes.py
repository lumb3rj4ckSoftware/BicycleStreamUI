from __future__ import annotations

import re
from typing import Any

import httpx


_TOKEN_RE = re.compile(r"[^\s]+")


def twitch_emote_url(emote_id: str, scale: str = "3.0") -> str:
    return f"https://static-cdn.jtvnw.net/emoticons/v2/{emote_id}/default/dark/{scale}"


class ThirdPartyEmoteResolver:
    """Best-effort 7TV/BTTV/FFZ resolver. Failures never block boss hits."""

    def __init__(self, broadcaster_id: str = ""):
        self.broadcaster_id = broadcaster_id
        self.emotes: dict[str, dict[str, Any]] = {}
        self.last_errors: list[str] = []

    def _add(self, code: str, url: str, provider: str, emote_id: str = "") -> None:
        if code and url:
            if url.startswith("//"):
                url = "https:" + url
            self.emotes[code] = {"code": code, "url": url, "provider": provider, "id": emote_id}

    async def refresh(self) -> None:
        self.last_errors.clear()
        async with httpx.AsyncClient(timeout=4.0) as client:
            await self._refresh_bttv(client)
            await self._refresh_ffz(client)
            await self._refresh_7tv(client)

    async def _refresh_bttv(self, client: httpx.AsyncClient) -> None:
        try:
            r = await client.get("https://api.betterttv.net/3/cached/emotes/global")
            r.raise_for_status()
            for e in r.json() if isinstance(r.json(), list) else []:
                self._add(e.get("code", ""), f"https://cdn.betterttv.net/emote/{e.get('id')}/3x", "BTTV", e.get("id", ""))
            if self.broadcaster_id:
                r = await client.get(f"https://api.betterttv.net/3/cached/users/twitch/{self.broadcaster_id}")
                if r.status_code == 200:
                    data = r.json()
                    for e in [*(data.get("channelEmotes") or []), *(data.get("sharedEmotes") or [])]:
                        self._add(e.get("code", ""), f"https://cdn.betterttv.net/emote/{e.get('id')}/3x", "BTTV", e.get("id", ""))
        except Exception as exc:
            self.last_errors.append(f"BTTV: {exc}")

    async def _refresh_ffz(self, client: httpx.AsyncClient) -> None:
        try:
            urls = ["https://api.frankerfacez.com/v1/set/global"]
            if self.broadcaster_id:
                urls.append(f"https://api.frankerfacez.com/v1/room/id/{self.broadcaster_id}")
            for url in urls:
                r = await client.get(url)
                if r.status_code != 200:
                    continue
                data = r.json()
                sets = data.get("sets") or {}
                for s in sets.values():
                    for e in s.get("emoticons", []):
                        urls_obj = e.get("urls") or {}
                        image = urls_obj.get("4") or urls_obj.get("2") or urls_obj.get("1")
                        self._add(e.get("name", ""), image or "", "FFZ", str(e.get("id", "")))
        except Exception as exc:
            self.last_errors.append(f"FFZ: {exc}")

    async def _refresh_7tv(self, client: httpx.AsyncClient) -> None:
        try:
            endpoints = ["https://7tv.io/v3/emote-sets/global"]
            if self.broadcaster_id:
                endpoints.append(f"https://7tv.io/v3/users/twitch/{self.broadcaster_id}")
            for url in endpoints:
                r = await client.get(url)
                if r.status_code != 200:
                    continue
                data = r.json()
                set_obj = data.get("emote_set", data)
                for e in set_obj.get("emotes", []) if isinstance(set_obj, dict) else []:
                    host = e.get("data", {}).get("host", {}) or {}
                    files = host.get("files") or []
                    image = ""
                    if files and host.get("url"):
                        webp = [f for f in files if str(f.get("name", "")).endswith(".webp")]
                        best = max(webp or files, key=lambda f: int(f.get("width", 0) or 0)).get("name", "")
                        base = str(host["url"])
                        if base.startswith("//"):
                            base = "https:" + base
                        elif not base.startswith(("http://", "https://")):
                            base = "https://" + base.lstrip("/")
                        image = f"{base.rstrip('/')}/{best}"
                    self._add(e.get("name", ""), image, "7TV", str(e.get("id", "")))
        except Exception as exc:
            self.last_errors.append(f"7TV: {exc}")

    def first_in_text(self, text: str) -> dict[str, Any] | None:
        for match in _TOKEN_RE.finditer(text or ""):
            raw = match.group(0)
            # Chat punctuation around an emote should not defeat recognition.
            candidates = (raw, raw.strip(".,!?;:()[]{}<>\"'"))
            for token in candidates:
                if token in self.emotes:
                    out = dict(self.emotes[token])
                    out["text"] = token
                    return out
        return None


def first_emote_from_fragments(fragments: list[dict[str, Any]] | None, resolver: ThirdPartyEmoteResolver | None = None) -> dict[str, Any] | None:
    for fragment in fragments or []:
        if fragment.get("type") == "emote" and fragment.get("emote"):
            em = fragment["emote"]
            emote_id = str(em.get("id", ""))
            if emote_id:
                return {
                    "id": emote_id,
                    "code": fragment.get("text", ""),
                    "text": fragment.get("text", ""),
                    "provider": "Twitch",
                    "url": twitch_emote_url(emote_id),
                }
        if resolver and fragment.get("type") == "text":
            found = resolver.first_in_text(fragment.get("text", ""))
            if found:
                return found
    return None


def emotes_from_fragments(fragments, resolver=None, text=""):
    """Preserve every occurrence and its order. Damage stays once per message."""
    result = []
    for fragment in fragments or []:
        if fragment.get("type") == "emote":
            emote = first_emote_from_fragments([fragment])
            if emote:
                # EventSub normally sends one emote per fragment. Also support
                # an adjacent run of the same emote inside a single fragment.
                words = str(fragment.get("text", "")).split()
                count = len(words) if words and len(set(words)) == 1 else 1
                result.extend(dict(emote) for _ in range(count))
        elif resolver and fragment.get("type") == "text":
            for token in _TOKEN_RE.findall(fragment.get("text", "")):
                emote = resolver.first_in_text(token)
                if emote:
                    result.append(emote)
    if resolver and not fragments:
        for token in _TOKEN_RE.findall(text):
            emote = resolver.first_in_text(token)
            if emote:
                result.append(emote)
    return result
