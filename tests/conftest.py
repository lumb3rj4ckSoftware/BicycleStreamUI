from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.config import load_config
from backend.persistence import ChallengeStateStore, SQLiteStore
from backend.challenge import ChallengeService


@pytest.fixture
def config(tmp_path: Path):
    src = Path(__file__).resolve().parents[1] / "config" / "challenge_config.json"
    cfg = json.loads(src.read_text(encoding="utf-8"))
    return cfg


@pytest.fixture
def services(tmp_path: Path, config):
    state = ChallengeStateStore(tmp_path / "challenge.json")
    db = SQLiteStore(tmp_path / "test.sqlite")
    challenge = ChallengeService(config, state, db)
    return challenge, db
