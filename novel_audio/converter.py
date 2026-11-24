"""Resumable chapter conversion with atomic outputs and content fingerprints."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import threading
from pathlib import Path
from typing import Callable

from .books import Book, split_text
from .engines import check_cancel, run_process


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def slug(value: str, limit: int = 45) -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(" .")[:limit].rstrip(" .")
    if not value:
        return "untitled"
    if value.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
        value = "_" + value
    return value


def write_json(path: Path, value):
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def valid_file(path: Path, expected: str | None) -> bool:
    return bool(expected and path.is_file() and path.stat().st_size > 0 and file_digest(path) == expected)


def merge_audio(chunks: list[Path], destination: Path, cancel: threading.Event, ffmpeg: str):
    # Only generated, relative ASCII names enter the concat file.
    listing = chunks[0].parent / "concat.txt"
    listing.write_text("\n".join(f"file '{p.name}'" for p in chunks), encoding="utf-8")
    temporary = destination.with_suffix(".partial.mp3")
    try:
        run_process([ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-f", "concat", "-safe", "1", "-i", str(listing), "-vn", "-c:a", "libmp3lame", "-b:a", "96k", str(temporary)], cancel, timeout=600)
        check_cancel(cancel)
        if not temporary.is_file() or temporary.stat().st_size < 100:
            raise RuntimeError("合并没有生成有效音频")
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
        listing.unlink(missing_ok=True)


def convert_book(book: Book, indices: list[int], engine, output_root: Path,
                 cancel: threading.Event, progress: Callable[[int, int, str], None] = lambda *_: None,
                 ffmpeg: str | None = None) -> list[Path]:
    ffmpeg = ffmpeg or shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("未找到 FFmpeg，请将 ffmpeg.exe 加入 PATH 后重启程序")
    indices = sorted(set(indices))
    if not indices or any(i < 0 or i >= len(book.chapters) for i in indices):
        raise ValueError("请选择有效章节")
    jobs = [(i, split_text(book.chapters[i].text)) for i in indices]
    total, completed = sum(len(parts) for _, parts in jobs), 0
    book_key = digest(str(book.path.resolve()).encode())[:8]
    directory = output_root / f"{slug(book.title)}-{book_key}"
    directory.mkdir(parents=True, exist_ok=True)
    results = []
    for index, parts in jobs:
        check_cancel(cancel)
        chapter = book.chapters[index]
        if not parts:
            raise ValueError(f"章节没有正文：{chapter.title}")
        settings = {"version": 1, "engine": engine.name, "voice": engine.voice, "rate": engine.rate, "chunk_size": 1200, "text_sha256": digest(chapter.text.encode())}
        key = digest(json.dumps(settings, sort_keys=True).encode())[:12]
        folder = directory / f"{index + 1:04d}-{slug(chapter.title, 32)}-{key}"
        folder.mkdir(exist_ok=True)
        # Exclusive per-chapter lock also protects separate app instances.
        lock = folder / ".lock"
        try:
            handle = lock.open("x")
        except FileExistsError as exc:
            raise RuntimeError(f"章节正在被其他任务使用。如上次程序异常退出，确认没有转换任务后删除：{lock}") from exc
        try:
            handle.close()
            manifest_path = folder / "manifest.json"
            try:
                state = json.loads(manifest_path.read_text(encoding="utf-8"))
                if state.get("settings") != settings or not isinstance(state.get("chunks"), dict):
                    state = {}
            except (FileNotFoundError, ValueError):
                state = {}
            if not state:
                state = {"title": chapter.title, "settings": settings, "chunks": {}}
            output = folder / f"{index + 1:04d}-{slug(chapter.title, 32)}.mp3"
            if valid_file(output, state.get("output_sha256")):
                completed += len(parts)
                progress(completed, total, f"复用已完成章节：{chapter.title}")
                results.append(output)
                continue
            chunk_dir = folder / ".chunks"
            chunk_dir.mkdir(exist_ok=True)
            paths = []
            for number, text in enumerate(parts):
                check_cancel(cancel)
                chunk = chunk_dir / f"{number:05d}{engine.extension}"
                paths.append(chunk)
                if not valid_file(chunk, state["chunks"].get(chunk.name)):
                    progress(completed, total, f"{chapter.title} · 分段 {number + 1}/{len(parts)}")
                    partial = chunk.with_suffix(".partial" + engine.extension)
                    try:
                        engine.synthesize(text, partial, cancel)
                        check_cancel(cancel)
                        if not partial.is_file() or partial.stat().st_size < 100:
                            raise RuntimeError("语音引擎返回空音频")
                        partial.replace(chunk)
                    finally:
                        partial.unlink(missing_ok=True)
                    state["chunks"][chunk.name] = file_digest(chunk)
                    write_json(manifest_path, state)
                completed += 1
                progress(completed, total, f"已完成 {completed}/{total} 段")
            progress(completed, total, f"正在合并：{chapter.title}")
            merge_audio(paths, output, cancel, ffmpeg)
            state["output_sha256"] = file_digest(output)
            write_json(manifest_path, state)
            results.append(output)
        finally:
            lock.unlink(missing_ok=True)
    progress(total, total, f"完成，共 {len(results)} 个章节 MP3")
    return results
