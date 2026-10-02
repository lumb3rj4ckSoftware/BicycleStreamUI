from __future__ import annotations

from typing import Any, Protocol


class EventExtension(Protocol):
    name: str
    enabled: bool
    def on_event(self, event_type: str, payload: dict[str, Any]) -> None: ...


class BettingModule:
    """Reserved hook only. Deliberately disabled; no betting/economy logic is implemented."""
    name = "BettingModule"
    enabled = False

    def on_event(self, event_type: str, payload: dict[str, Any]) -> None:
        return None


class MilestoneDedicationModule:
    """Reserved hook only. Deliberately disabled."""
    name = "MilestoneDedicationModule"
    enabled = False

    def on_event(self, event_type: str, payload: dict[str, Any]) -> None:
        return None
