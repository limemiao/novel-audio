import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from novel_audio.books import Book, Chapter
from novel_audio.converter import convert_book, slug
from novel_audio.engines import Cancelled


class FakeEngine:
    name, extension, voice, rate = "test", ".wav", "voice-a", 0

    def __init__(self, fail_on=None, cancel_on=None):
        self.calls = 0
        self.fail_on = fail_on
        self.cancel_on = cancel_on

    def synthesize(self, text, destination, cancel):
        self.calls += 1
        destination.write_bytes(b"partial" if self.calls == self.fail_on else b"audio" * 100)
        if self.calls == self.fail_on:
            raise RuntimeError("模拟网络中断")
        if self.calls == self.cancel_on:
            cancel.set()


def fake_merge(chunks, destination, cancel, ffmpeg):
    destination.write_bytes(b"".join(p.read_bytes() for p in chunks))


class ConverterTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.book = Book(self.root / "novel.txt", "小说", (Chapter("第一章", "甲" * 2600),))
        self.merge = patch("novel_audio.converter.merge_audio", side_effect=fake_merge)
        self.merge.start()
        self.addCleanup(self.merge.stop)

    def convert(self, engine, book=None, cancel=None):
        return convert_book(book or self.book, [0], engine, self.root / "out", cancel or threading.Event(), ffmpeg="fake")

    def test_resume_after_failure_and_no_partial_export(self):
        engine = FakeEngine(fail_on=2)
        with self.assertRaises(RuntimeError):
            self.convert(engine)
        self.assertFalse(list(self.root.rglob("*.mp3")))
        self.assertFalse(list(self.root.rglob("*.partial.wav")))
        self.assertFalse(list(self.root.rglob(".lock")))
        resumed = FakeEngine()
        result = self.convert(resumed)
        self.assertEqual(resumed.calls, 2)
        self.assertEqual(len(result), 1)
        cached = FakeEngine()
        self.assertEqual(self.convert(cached), result)
        self.assertEqual(cached.calls, 0)

    def test_changed_voice_or_text_has_distinct_outputs(self):
        first = self.convert(FakeEngine())
        engine = FakeEngine()
        engine.voice = "voice-b"
        self.assertNotEqual(self.convert(engine), first)
        self.assertEqual(engine.calls, 3)
        book = Book(self.book.path, self.book.title, (Chapter("第一章", "乙" * 2600),))
        self.assertNotEqual(self.convert(FakeEngine(), book), first)

    def test_corrupt_chunk_is_regenerated(self):
        with self.assertRaises(RuntimeError):
            self.convert(FakeEngine(fail_on=2))
        next(self.root.rglob("00000.wav")).write_bytes(b"corrupt")
        engine = FakeEngine()
        self.convert(engine)
        self.assertEqual(engine.calls, 3)

    def test_cancel_cleans_incomplete_chunk_and_lock(self):
        with self.assertRaises(Cancelled):
            self.convert(FakeEngine(cancel_on=2))
        self.assertFalse(list(self.root.rglob("*.partial.wav")))
        self.assertFalse(list(self.root.rglob(".lock")))
        engine = FakeEngine()
        self.convert(engine)
        self.assertEqual(engine.calls, 2)

    def test_invalid_selection(self):
        for indices in [[], [-1], [1]]:
            with self.assertRaises(ValueError):
                convert_book(self.book, indices, FakeEngine(), self.root, threading.Event(), ffmpeg="fake")

    def test_windows_safe_names(self):
        self.assertEqual(slug("CON"), "_CON")
        self.assertEqual(slug("标题: 一/二?"), "标题_ 一_二_")
        self.assertTrue(slug(" . "))


if __name__ == "__main__":
    unittest.main()
