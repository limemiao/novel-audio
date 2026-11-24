"""Validated Edge voice catalogs, with an offline snapshot and optional refresh."""
from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from .converter import write_json

CHINESE_NAMES = {
    "Xiaoxiao": "晓晓", "Xiaoyi": "晓伊", "Yunxi": "云希", "Yunjian": "云健",
    "Yunxia": "云夏", "Yunyang": "云扬", "Xiaobei": "晓北", "Xiaoni": "晓妮",
    "HiuGaai": "晓佳", "HiuMaan": "晓曼", "WanLung": "云龙",
    "HsiaoChen": "晓臻", "HsiaoYu": "晓雨", "YunJhe": "云哲",
}
LOCALES = {"zh-CN": "普通话", "zh-HK": "粤语 · 香港", "zh-TW": "国语 · 台湾", "zh-CN-liaoning": "中文 · 辽宁", "zh-CN-shaanxi": "中文 · 陕西"}
SNAPSHOT = Path(__file__).with_name("voice-catalog.json")


def normalize_voices(rows: list) -> list[dict]:
    if not isinstance(rows, list):
        raise ValueError("音色目录格式无效")
    voices = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        voice_id, locale, gender = row.get("ShortName"), row.get("Locale"), row.get("Gender")
        if not isinstance(voice_id, str) or not re.fullmatch(r"[A-Za-z0-9-]{3,160}Neural", voice_id):
            continue
        if not isinstance(locale, str) or not re.fullmatch(r"[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})+", locale):
            continue
        if gender not in {"Female", "Male"} or not voice_id.startswith(locale + "-"):
            continue
        raw_name = voice_id[len(locale) + 1:].removesuffix("Neural")
        name = CHINESE_NAMES.get(raw_name, raw_name) if locale.startswith("zh-") else raw_name
        gender_label = "女声" if gender == "Female" else "男声"
        voices[voice_id] = {"id": voice_id, "name": name, "label": f"{name} · {LOCALES.get(locale, locale)} · {gender_label}", "locale": locale, "gender": gender}
    if not voices:
        raise ValueError("语音服务未返回有效音色，已保留原目录")
    return sorted(voices.values(), key=lambda v: (v["id"] != "zh-CN-XiaoxiaoNeural", not v["locale"].startswith("zh-"), v["locale"], v["name"]))


def read_catalog(path: Path, source: str) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    # Always validate persisted metadata before allowing it into synthesis requests.
    voices = normalize_voices(data["voices"])
    return {"voices": voices, "updated_at": str(data.get("updated_at", "")), "source": source}


def load_catalog(assets: Path) -> dict:
    try:
        return read_catalog(assets / "edge-voices.json", "cache")
    except (OSError, ValueError, KeyError, TypeError):
        return read_catalog(SNAPSHOT, "bundled")


def refresh_catalog(assets: Path) -> dict:
    try:
        import edge_tts
    except ImportError as exc:
        raise ValueError("请先运行 install-online.cmd 安装在线语音依赖") from exc

    async def fetch():
        return await asyncio.wait_for(edge_tts.list_voices(), timeout=20)

    rows = asyncio.run(fetch())
    voices = normalize_voices(rows)
    updated_at = datetime.now(timezone.utc).isoformat()
    assets.mkdir(parents=True, exist_ok=True)
    write_json(assets / "edge-voices.json", {"updated_at": updated_at, "voices": rows})
    return {"voices": voices, "updated_at": updated_at, "source": "live"}
