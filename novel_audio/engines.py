from __future__ import annotations

import asyncio
import json
import os
import subprocess
import tempfile
import threading
import time
from pathlib import Path


class Cancelled(Exception):
    pass


def check_cancel(cancel: threading.Event):
    if cancel.is_set():
        raise Cancelled("已停止；已完成的分段将在下次继续时复用")


def run_process(args: list[str], cancel: threading.Event, timeout: float = 180) -> str:
    check_cancel(cancel)
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", errors="replace", creationflags=flags)
    started = time.monotonic()
    try:
        while True:
            check_cancel(cancel)
            if time.monotonic() - started > timeout:
                raise TimeoutError("操作超时，请重试或缩短文本")
            try:
                stdout, stderr = process.communicate(timeout=0.15)
                break
            except subprocess.TimeoutExpired:
                continue
        if process.returncode:
            raise RuntimeError((stderr or stdout or "语音处理失败")[-1800:])
        return stdout.strip().lstrip("\ufeff")
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate()


SAPI_SCRIPT = Path(__file__).with_name("sapi.ps1")


def sapi_command(*args: str) -> list[str]:
    return ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(SAPI_SCRIPT), *args]


def system_voices() -> list[str]:
    if os.name != "nt":
        return []
    result = json.loads(run_process(sapi_command("-Mode", "list"), threading.Event(), 20))
    return [result] if isinstance(result, str) else result


class SystemEngine:
    name = "system"
    extension = ".wav"

    def __init__(self, voice: str, rate: int = 0):
        self.voice, self.rate = voice, rate

    def synthesize(self, text: str, destination: Path, cancel: threading.Event):
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".txt", dir=destination.parent, delete=False) as source:
            source.write(text)
            text_path = Path(source.name)
        try:
            run_process(sapi_command("-Mode", "speak", "-Voice", self.voice, "-Rate", str(round(self.rate / 10)), "-TextFile", str(text_path), "-OutputFile", str(destination)), cancel)
        finally:
            text_path.unlink(missing_ok=True)


EDGE_VOICES = {
    "晓晓 · 普通话女声": "zh-CN-XiaoxiaoNeural",
    "晓伊 · 普通话女声": "zh-CN-XiaoyiNeural",
    "云希 · 普通话男声": "zh-CN-YunxiNeural",
    "云健 · 普通话男声": "zh-CN-YunjianNeural",
    "晓曼 · 粤语女声": "zh-HK-HiuMaanNeural",
    "晓臻 · 台湾女声": "zh-TW-HsiaoChenNeural",
}


class EdgeEngine:
    name = "edge"
    extension = ".mp3"

    def __init__(self, voice: str, rate: int = 0):
        self.voice, self.rate = voice, rate

    def synthesize(self, text: str, destination: Path, cancel: threading.Event):
        try:
            import edge_tts
        except ImportError as exc:
            raise RuntimeError("在线语音依赖尚未安装，请运行 install-online.cmd 后重新启动程序") from exc

        async def save():
            task = asyncio.create_task(edge_tts.Communicate(text, self.voice, rate=f"{self.rate:+d}%", connect_timeout=15, receive_timeout=30).save(str(destination)))
            try:
                started = time.monotonic()
                while not task.done():
                    check_cancel(cancel)
                    if time.monotonic() - started > 150:
                        raise TimeoutError("在线语音请求超时")
                    await asyncio.sleep(0.1)
                await task
            finally:
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)

        for attempt in range(3):
            check_cancel(cancel)
            try:
                asyncio.run(save())
                return
            except Cancelled:
                raise
            except Exception:
                if attempt == 2:
                    raise
                if cancel.wait(2 ** attempt):
                    check_cancel(cancel)
