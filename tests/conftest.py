"""Fixtures compartidas para todos los tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture
def config():
    return yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))


@pytest.fixture
def clean_data_dir():
    for sub in ("pending", "published", "rejected"):
        d = ROOT / "data" / sub
        if d.exists():
            for f in d.glob("*.json"):
                if not f.name.startswith("."):
                    f.unlink()
    yield
    for sub in ("pending", "published", "rejected"):
        d = ROOT / "data" / sub
        if d.exists():
            for f in d.glob("*.json"):
                if not f.name.startswith("."):
                    f.unlink()
