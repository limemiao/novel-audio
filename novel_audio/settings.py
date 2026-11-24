import json
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent


def load_settings() -> dict:
    return json.loads((PROJECT / "config.json").read_text(encoding="utf-8"))
