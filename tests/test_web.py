import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen
from unittest.mock import patch

from novel_audio.engines import Cancelled
from novel_audio.web import create_server, identifier


class WebTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.library = self.root / "books"
        self.library.mkdir()
        self.source = self.library / "sample.txt"
        self.source.write_text("第一章 清晨\n窗外的雨停了。\n第二章 远行\n我们出发吧。", encoding="utf-8")
        self.assets = self.root / "assets"
        with patch("novel_audio.web.system_voices", return_value=["test-voice"]):
            self.server = create_server(0, {"library": str(self.library), "assets": str(self.assets)})
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.app.shutdown()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def request(self, path, data=None, headers=None):
        headers = headers or {}
        if isinstance(data, dict):
            data = json.dumps(data).encode()
            headers = {"X-Novel-Audio":"local", "Content-Type":"application/json", **headers}
        request = Request(self.url + path, data=data, headers=headers)
        try:
            with urlopen(request, timeout=5) as response:
                return response.status, dict(response.headers), response.read()
        except HTTPError as response:
            return response.code, dict(response.headers), response.read()

    def data(self):
        return {"book_id":identifier(self.source), "chapters":[0], "engine":"system", "voice":"test-voice", "rate":0}

    def await_status(self, job_id, statuses):
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            job = next(j for j in self.server.app.job_data() if j["id"] == job_id)
            if job["status"] in statuses:
                return job
            time.sleep(.02)
        self.fail("Task did not reach expected status")

    def test_catalog_and_chapter_content(self):
        status, _, body = self.request("/api/library")
        self.assertEqual(status, 200)
        books = json.loads(body)["books"]
        self.assertEqual(len(books), 1)
        key = books[0]["id"]
        self.assertEqual(len(json.loads(self.request(f"/api/books/{key}")[2])["chapters"]), 2)
        self.assertIn("窗外", json.loads(self.request(f"/api/books/{key}/chapters/0")[2])["text"])
        self.assertEqual(self.request("/../config.json")[0], 404)

    def test_cross_site_mutations_and_invalid_jobs_rejected(self):
        self.assertEqual(self.request("/api/jobs", b"{}")[0], 403)
        self.assertEqual(self.request("/api/jobs", self.data(), {"Origin":"https://example.com"})[0], 403)
        self.assertEqual(self.request("/api/config", headers={"Host":"attacker.test"})[0], 403)
        for changes in [{"chapters":[-1]}, {"chapters":[]}, {"chapters":[True]}, {"rate":101}, {"voice":"missing"}]:
            self.assertEqual(self.request("/api/jobs", {**self.data(), **changes})[0], 400)

    def test_upload_validates_and_preserves_source(self):
        original = self.source.read_bytes()
        headers = {"X-Novel-Audio":"local", "X-Filename":quote("上传示例.txt")}
        status, _, body = self.request("/api/import", "第一章\n上传后的正文。".encode(), headers)
        self.assertEqual(status, 201)
        book = self.server.app.book_for(json.loads(body)["id"])
        self.assertEqual(book.title, "上传示例")
        self.assertEqual(self.source.read_bytes(), original)
        headers["X-Filename"] = "broken.epub"
        self.assertEqual(self.request("/api/import", b"not a zip", headers)[0], 400)
        self.assertFalse(list((self.assets / "imports").rglob("*.epub")))

    def test_audio_range_and_download(self):
        audio = self.assets / "output" / "book" / "chapter.mp3"
        audio.parent.mkdir(parents=True)
        audio.write_bytes(bytes(range(256)) * 4)
        key = identifier(audio)
        status, headers, body = self.request(f"/api/audio/{key}", headers={"Range":"bytes=10-19"})
        self.assertEqual(status, 206)
        self.assertEqual(body, bytes(range(10,20)))
        self.assertEqual(headers["Content-Range"], "bytes 10-19/1024")
        self.assertEqual(self.request(f"/api/audio/{key}", headers={"Range":"bytes=-4"})[2], bytes(range(252,256)))
        self.assertEqual(self.request(f"/api/audio/{key}", headers={"Range":"bytes=2000-"})[0], 416)
        self.assertIn("attachment", self.request(f"/api/audio/{key}?download=1")[1]["Content-Disposition"])
        chunk = audio.parent / ".chunks" / "00000.mp3"
        chunk.parent.mkdir()
        chunk.write_bytes(b"hidden chunk")
        self.assertEqual(len(json.loads(self.request("/api/audio")[2])), 1)

    def test_queue_completion_and_persistent_history(self):
        def convert(book, indices, engine, output, cancel, progress):
            progress(1, 1, "完成")
            path = output / "book" / "chapter.mp3"
            path.parent.mkdir(parents=True)
            path.write_bytes(b"test-audio")
            return [path]
        with patch("novel_audio.web.convert_book", side_effect=convert):
            status, _, body = self.request("/api/jobs", self.data())
            self.assertEqual(status, 201)
            job = self.await_status(json.loads(body)["id"], {"completed"})
            self.assertEqual(len(job["outputs"]), 1)
            self.assertTrue(self.server.app.state_path.exists())

    def test_running_and_queued_cancellation(self):
        entered = threading.Event()
        def convert(book, indices, engine, output, cancel, progress):
            entered.set()
            cancel.wait(4)
            raise Cancelled()
        with patch("novel_audio.web.convert_book", side_effect=convert):
            first = self.server.app.submit(self.data())
            self.assertTrue(entered.wait(2))
            second = self.server.app.submit(self.data())
            self.server.app.cancel_job(second["id"])
            self.assertEqual(self.await_status(second["id"], {"cancelled"})["status"], "cancelled")
            self.server.app.cancel_job(first["id"])
            self.assertEqual(self.await_status(first["id"], {"cancelled"})["status"], "cancelled")

    def test_expanded_voice_can_be_submitted_and_unknown_voice_rejected(self):
        config = json.loads(self.request("/api/config")[2])
        self.assertIn("zh-CN-YunyangNeural", {v["id"] for v in config["edge_voices"]})
        with patch("novel_audio.web.importlib.util.find_spec", return_value=True), patch("novel_audio.web.convert_book", side_effect=RuntimeError("mock synthesis")):
            data = {**self.data(), "engine":"edge", "voice":"zh-CN-YunyangNeural"}
            status, _, body = self.request("/api/jobs", data)
            self.assertEqual(status, 201)
            self.await_status(json.loads(body)["id"], {"failed"})
            self.assertEqual(self.request("/api/jobs", {**data, "voice":"zh-CN-InventedNeural"})[0], 400)

    def test_refresh_failure_keeps_catalog(self):
        before = self.server.app.config()["edge_voices"]
        with patch("novel_audio.web.refresh_catalog", side_effect=TimeoutError()):
            status, _, body = self.request("/api/voices/refresh", {})
            self.assertEqual(status, 400)
            self.assertIn("保留", json.loads(body)["error"])
        self.assertEqual(self.server.app.config()["edge_voices"], before)

    def test_second_server_cannot_share_port(self):
        with self.assertRaises(OSError):
            create_server(self.server.server_port, {"library":str(self.library), "assets":str(self.assets)})


if __name__ == "__main__":
    unittest.main()
