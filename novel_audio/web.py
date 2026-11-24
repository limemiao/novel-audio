"""Loopback-only web workbench; shares the desktop conversion engine."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import queue
import re
import socket
import threading
import time
import uuid
import webbrowser
import zipfile
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit
from urllib.request import urlopen
from xml.etree import ElementTree as ET

from .books import Book, Chapter, archive_path, local, read_book, scan_library
from .converter import convert_book, slug, write_json
from .engines import Cancelled, EdgeEngine, SystemEngine, system_voices
from .settings import load_settings
from .voices import load_catalog, refresh_catalog

STATIC = Path(__file__).with_name("web_static")
MAX_UPLOAD = 64 * 1024 * 1024


def identifier(path: Path) -> str:
    return hashlib.sha256(str(path.resolve()).encode()).hexdigest()[:20]


@lru_cache(maxsize=4)
def cached_book(path: str, modified: int) -> Book:
    return read_book(Path(path))


def cover_image(path: Path) -> tuple[bytes, str]:
    if path.suffix.lower() != ".epub":
        raise FileNotFoundError("没有封面")
    with zipfile.ZipFile(path) as archive:
        container = ET.fromstring(archive.read("META-INF/container.xml"))
        opf_path = next(e.attrib["full-path"] for e in container.iter() if local(e.tag) == "rootfile")
        opf = ET.fromstring(archive.read(opf_path))
        cover_id = next((e.get("content") for e in opf.iter() if local(e.tag) == "meta" and e.get("name") == "cover"), "")
        items = [e for e in opf.iter() if local(e.tag) == "item" and e.get("media-type", "").startswith("image/")]
        item = next((e for e in items if e.get("id") == cover_id or "cover-image" in e.get("properties", "").split()), None)
        if item is None:
            item = next((e for e in items if "cover" in e.get("href", "").lower()), None)
        if item is None:
            raise FileNotFoundError("没有封面")
        name = archive_path(str(Path(opf_path).parent).replace("\\", "/"), item.attrib["href"])
        if archive.getinfo(name).file_size > 15 * 1024 * 1024:
            raise ValueError("封面过大")
        mime = item.get("media-type", "image/jpeg")
        if mime not in {"image/jpeg", "image/png", "image/webp", "image/gif"}:
            raise FileNotFoundError("封面格式不支持")
        return archive.read(name), mime


class Workbench:
    def __init__(self, settings=None):
        self.settings = settings or load_settings()
        self.assets = Path(self.settings["assets"])
        self.library = Path(self.settings["library"])
        self.lock = threading.RLock()
        self.catalog_lock = threading.Lock()
        self.voice_catalog = load_catalog(self.assets)
        self.paths: dict[str, Path] = {}
        self.jobs: list[dict] = []
        self.cancels: dict[str, threading.Event] = {}
        self.queue = queue.Queue()
        self.audio_paths: dict[str, Path] = {}
        self.closed = False
        self.state_path = self.assets / "web-jobs.json"
        try:
            self.jobs = json.loads(self.state_path.read_text(encoding="utf-8"))
            for job in self.jobs:
                if job["status"] in {"queued", "running", "cancelling"}:
                    job.update(status="cancelled", message="服务已重启；重新提交相同设置可继续已保存的分段。")
        except (OSError, ValueError, TypeError, KeyError):
            self.jobs = []
        self.voices_error = ""
        try:
            self.voices = system_voices()
        except Exception as exc:
            self.voices, self.voices_error = [], str(exc)
        self.refresh()
        self.worker = threading.Thread(target=self.work, daemon=True, name="novel-audio-worker")
        self.worker.start()

    def save_jobs(self):
        self.assets.mkdir(parents=True, exist_ok=True)
        write_json(self.state_path, self.jobs)

    def refresh(self):
        paths = scan_library(self.library)
        upload_root = self.assets / "imports"
        if upload_root.exists():
            paths += scan_library(upload_root)
        paths = sorted(set(paths), key=lambda p: (p.parent.name, p.name))
        with self.lock:
            self.paths = {identifier(p): p for p in paths}

    def library_data(self):
        with self.lock:
            books = [{"id": key, "title": p.stem, "series": (p.stem.split("-")[0] if p.parent == self.library else p.parent.name) if self.library in p.parents else "我的导入", "format": p.suffix[1:].upper(), "cover": f"/api/books/{key}/cover"} for key, p in self.paths.items()]
        # Put a few different series at the front; the rest remain searchable.
        featured, rest, seen = [], [], set()
        preferred = sorted(books, key=lambda b: (0 if "魔王2099" in b["title"] and "第一卷" in b["title"] else 1, b["series"], b["title"]))
        for book in preferred:
            if book["series"] not in seen and len(featured) < 12:
                featured.append(book)
                seen.add(book["series"])
            else:
                rest.append(book)
        return {"books": featured + rest, "series": sorted({b["series"] for b in books}), "library": str(self.library)}

    def path_for(self, key):
        with self.lock:
            path = self.paths.get(key)
        if path is None:
            raise FileNotFoundError("书籍不存在，请刷新书库")
        return path

    def book_for(self, key):
        path = self.path_for(key)
        return cached_book(str(path), path.stat().st_mtime_ns)

    def book_data(self, key):
        book = self.book_for(key)
        return {"id": key, "title": book.title, "characters": sum(len(c.text) for c in book.chapters), "chapters": [{"index": i, "title": c.title, "characters": len(c.text)} for i, c in enumerate(book.chapters)]}

    def config(self):
        default = next((v for v in self.voices if "Chinese" in v), self.voices[0] if self.voices else "")
        catalog = self.voice_catalog
        return {"library": str(self.library), "output": str(self.assets / "output"), "system_voices": [{"id": v, "label": "慧慧 · 普通话" if "Huihui" in v else "Haruka · 日语" if "Haruka" in v else "Zira · 英语" if "Zira" in v else v} for v in self.voices], "default_voice": default, "edge_voices": catalog["voices"], "voice_catalog": {"updated_at": catalog["updated_at"], "source": catalog["source"]}, "edge_available": importlib.util.find_spec("edge_tts") is not None, "voice_error": self.voices_error}

    def refresh_voices(self):
        if not self.catalog_lock.acquire(blocking=False):
            raise ValueError("音色目录正在刷新，请稍候")
        try:
            catalog = refresh_catalog(self.assets)
            self.voice_catalog = catalog
            return self.config()
        except Exception as exc:
            raise ValueError("刷新失败，已保留现有音色目录。请检查联网状态及在线依赖。") from exc
        finally:
            self.catalog_lock.release()

    def audio_data(self):
        entries, paths = [], {}
        for kind in ("output", "preview"):
            root = self.assets / kind
            if not root.exists():
                continue
            for path in root.rglob("*.mp3"):
                if ".chunks" in path.parts or path.name.endswith(".partial.mp3"):
                    continue
                key = identifier(path)
                stat = path.stat()
                paths[key] = path
                entries.append({"id": key, "title": path.stem, "book": re.sub(r"-[0-9a-f]{8}$", "", path.relative_to(root).parts[0]), "kind": kind, "size": stat.st_size, "modified": stat.st_mtime, "url": f"/api/audio/{key}"})
        with self.lock:
            self.audio_paths = paths
        return sorted(entries, key=lambda item: item["modified"], reverse=True)

    def job_data(self):
        with self.lock:
            return json.loads(json.dumps(self.jobs))

    def submit(self, data):
        book_id = data.get("book_id")
        book = self.book_for(book_id)
        indices = data.get("chapters", [])
        if not isinstance(indices, list) or not indices or any(type(i) is not int or not 0 <= i < len(book.chapters) for i in indices):
            raise ValueError("请选择有效章节")
        rate = data.get("rate", 0)
        if type(rate) is not int or not -50 <= rate <= 100:
            raise ValueError("语速应在 -50 到 100 之间")
        name, voice = data.get("engine"), data.get("voice")
        if name == "system" and voice in self.voices:
            pass
        elif name == "edge" and voice in {v["id"] for v in self.voice_catalog["voices"]}:
            if importlib.util.find_spec("edge_tts") is None:
                raise ValueError("请先运行 install-online.cmd 安装在线语音依赖")
        else:
            raise ValueError("请选择有效语音")
        with self.lock:
            if sum(j["status"] in {"queued", "running", "cancelling"} for j in self.jobs) >= 20:
                raise ValueError("队列已满，请等待当前任务完成")
            job = {"id": uuid.uuid4().hex, "book_id": book_id, "title": book.title, "chapters": sorted(set(indices)), "engine": name, "voice": voice, "rate": rate, "preview": bool(data.get("preview", False)), "status": "queued", "done": 0, "total": 0, "message": "等待转换", "created": time.time(), "outputs": []}
            self.jobs.insert(0, job)
            self.cancels[job["id"]] = threading.Event()
            self.save_jobs()
            self.queue.put((job, book))
            return dict(job)

    def cancel_job(self, key):
        with self.lock:
            job = next((j for j in self.jobs if j["id"] == key), None)
            if job is None:
                raise FileNotFoundError("任务不存在")
            if job["status"] in {"queued", "running", "cancelling"}:
                self.cancels[key].set()
                job["status"] = "cancelled" if job["status"] == "queued" else "cancelling"
                job["message"] = "已取消" if job["status"] == "cancelled" else "正在停止，保留已完成分段…"
                self.save_jobs()
            return dict(job)

    def work(self):
        while True:
            item = self.queue.get()
            if item is None:
                return
            job, book = item
            cancel = self.cancels[job["id"]]
            if cancel.is_set():
                continue
            with self.lock:
                job.update(status="running", message="准备合成…")
            def progress(done, total, message):
                with self.lock:
                    job.update(done=done, total=total, message=message)
            try:
                engine = SystemEngine(job["voice"], job["rate"]) if job["engine"] == "system" else EdgeEngine(job["voice"], job["rate"])
                indices = job["chapters"]
                if job["preview"]:
                    chapter = book.chapters[indices[0]]
                    book = Book(book.path, book.title, (Chapter("试听-" + chapter.title, chapter.text[:180]),))
                    indices = [0]
                paths = convert_book(book, indices, engine, self.assets / ("preview" if job["preview"] else "output"), cancel, progress)
                with self.lock:
                    job.update(status="completed", message="试听已就绪" if job["preview"] else f"已生成 {len(paths)} 个章节", outputs=[identifier(p) for p in paths])
            except Cancelled:
                with self.lock:
                    job.update(status="cancelled", message="已停止，重新提交相同设置可继续转换")
            except Exception as exc:
                with self.lock:
                    job.update(status="failed", message=str(exc))
            finally:
                with self.lock:
                    self.save_jobs()

    def shutdown(self):
        self.closed = True
        with self.lock:
            for event in self.cancels.values():
                event.set()
        self.queue.put(None)
        self.worker.join(timeout=10)


class Handler(BaseHTTPRequestHandler):
    server_version = "NovelAudio/0.2"

    @property
    def app(self):
        return self.server.app

    def log_message(self, *_):
        pass

    def allowed(self, mutate=False):
        expected = f"127.0.0.1:{self.server.server_port}"
        hosts = {expected, f"localhost:{self.server.server_port}"}
        if self.headers.get("Host") not in hosts:
            self.send_json({"error": "仅允许本机访问"}, 403)
            return False
        origin = self.headers.get("Origin")
        if origin and origin not in {f"http://{h}" for h in hosts}:
            self.send_json({"error": "跨站请求被拒绝"}, 403)
            return False
        if mutate and self.headers.get("X-Novel-Audio") != "local":
            self.send_json({"error": "请求缺少本地应用标识"}, 403)
            return False
        return True

    def respond(self, data, mime, status=200, headers=None):
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; media-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; object-src 'none'; frame-ancestors 'none'")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def send_json(self, data, status=200):
        self.respond(json.dumps(data, ensure_ascii=False).encode(), "application/json; charset=utf-8", status)

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        if not self.allowed():
            return
        try:
            self.route_get()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        except FileNotFoundError as exc:
            self.send_json({"error": str(exc)}, 404)
        except (ValueError, KeyError, zipfile.BadZipFile, ET.ParseError) as exc:
            self.send_json({"error": str(exc)}, 400)
        except Exception as exc:
            self.send_json({"error": str(exc)}, 500)

    def route_get(self):
        path = urlsplit(self.path).path
        if path in {"/", "/app.js", "/style.css", "/favicon.svg"}:
            target = STATIC / ("index.html" if path == "/" else path[1:])
            mime = {".js": "text/javascript", ".css": "text/css", ".html": "text/html", ".svg": "image/svg+xml"}[target.suffix]
            self.respond(target.read_bytes(), mime + "; charset=utf-8")
        elif path == "/api/config":
            self.send_json(self.app.config())
        elif path == "/api/library":
            self.send_json(self.app.library_data())
        elif path == "/api/jobs":
            self.send_json(self.app.job_data())
        elif path == "/api/audio":
            self.send_json(self.app.audio_data())
        elif match := re.fullmatch(r"/api/books/([a-f0-9]{20})(?:/(cover|chapters/\d+))?", path):
            key, action = match.groups()
            if action == "cover":
                try:
                    data, mime = cover_image(self.app.path_for(key))
                except (FileNotFoundError, ValueError, KeyError, zipfile.BadZipFile, ET.ParseError):
                    data, mime = (STATIC / "cover-fallback.svg").read_bytes(), "image/svg+xml"
                self.respond(data, mime)
            elif action:
                book = self.app.book_for(key)
                index = int(action.split("/")[-1])
                if index >= len(book.chapters):
                    raise ValueError("章节不存在")
                chapter = book.chapters[index]
                self.send_json({"title": chapter.title, "text": chapter.text[:20000], "truncated": len(chapter.text) > 20000})
            else:
                self.send_json(self.app.book_data(key))
        elif match := re.fullmatch(r"/api/audio/([a-f0-9]{20})", path):
            self.app.audio_data()
            target = self.app.audio_paths.get(match[1])
            if target is None:
                raise FileNotFoundError("音频不存在")
            self.stream_audio(target, "download" in urlsplit(self.path).query)
        else:
            raise FileNotFoundError("页面不存在")

    def stream_audio(self, path: Path, download=False):
        size = path.stat().st_size
        start, end, status = 0, size - 1, 200
        byte_range = self.headers.get("Range")
        if byte_range:
            match = re.fullmatch(r"bytes=(\d*)-(\d*)", byte_range)
            if not match or not any(match.groups()):
                self.respond(b"", "audio/mpeg", 416, {"Content-Range": f"bytes */{size}"})
                return
            a, b = match.groups()
            if a:
                start, end = int(a), min(int(b), size - 1) if b else size - 1
            else:
                start = max(0, size - int(b))
            if start > end or start >= size or (not a and b == "0"):
                self.respond(b"", "audio/mpeg", 416, {"Content-Range": f"bytes */{size}"})
                return
            status = 206
        self.send_response(status)
        self.send_header("Content-Type", "audio/mpeg")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Content-Disposition", f"{'attachment' if download else 'inline'}; filename*=UTF-8''{quote(path.name)}")
        self.send_header("X-Content-Type-Options", "nosniff")
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if self.command == "HEAD":
            return
        with path.open("rb") as stream:
            stream.seek(start)
            remaining = end - start + 1
            while remaining:
                chunk = stream.read(min(65536, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def do_POST(self):
        if not self.allowed(mutate=True):
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= MAX_UPLOAD:
                raise ValueError("请求为空或超过 64 MB")
            raw = self.rfile.read(length)
            path = urlsplit(self.path).path
            if path == "/api/import":
                filename = Path(unquote(self.headers.get("X-Filename", ""))).name
                suffix = Path(filename).suffix.lower()
                if suffix not in {".epub", ".txt"}:
                    raise ValueError("仅支持 EPUB / TXT 文件")
                folder = self.app.assets / "imports" / hashlib.sha256(raw).hexdigest()[:12]
                folder.mkdir(parents=True, exist_ok=True)
                target = folder / f"{slug(Path(filename).stem, 70)}{suffix}"
                temporary = folder / f"{uuid.uuid4().hex}{suffix}"
                try:
                    temporary.write_bytes(raw)
                    read_book(temporary)
                    temporary.replace(target)
                finally:
                    temporary.unlink(missing_ok=True)
                self.app.refresh()
                self.send_json({"id": identifier(target)}, 201)
                return
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError("请求必须是 JSON 对象")
            if path == "/api/jobs":
                self.send_json(self.app.submit(data), 201)
            elif path == "/api/voices/refresh":
                self.send_json(self.app.refresh_voices())
            elif match := re.fullmatch(r"/api/jobs/([a-f0-9]{32})/cancel", path):
                self.send_json(self.app.cancel_job(match[1]))
            elif path == "/api/library/refresh":
                self.app.refresh()
                self.send_json(self.app.library_data())
            else:
                raise FileNotFoundError("接口不存在")
        except (ValueError, KeyError, TypeError, zipfile.BadZipFile, ET.ParseError) as exc:
            self.send_json({"error": str(exc)}, 400)
        except FileNotFoundError as exc:
            self.send_json({"error": str(exc)}, 404)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        except Exception as exc:
            self.send_json({"error": str(exc)}, 500)


class LocalServer(ThreadingHTTPServer):
    # On Windows SO_REUSEADDR can silently bind a second server to the same port.
    allow_reuse_address = False

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def create_server(port=8788, settings=None):
    server = LocalServer(("127.0.0.1", port), Handler)
    try:
        server.app = Workbench(settings)
    except Exception:
        server.server_close()
        raise
    return server


def main(port=8788, open_browser=True):
    try:
        server = create_server(port)
    except OSError:
        if open_browser:
            try:
                with urlopen(f"http://127.0.0.1:{port}/api/config", timeout=2) as response:
                    if response.headers.get("Server", "").startswith("NovelAudio/"):
                        webbrowser.open(f"http://127.0.0.1:{port}")
                        print("已打开正在运行的听书工坊。", flush=True)
                        return
            except OSError:
                pass
        raise
    url = f"http://127.0.0.1:{server.server_port}"
    print(f"听书工坊 Web 已启动：{url}\n按 Ctrl+C 停止服务。", flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.app.shutdown()
        server.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8788)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    main(args.port, not args.no_browser)
