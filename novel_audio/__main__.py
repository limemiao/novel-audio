from __future__ import annotations

import argparse
import json
import sys
import threading
from pathlib import Path

from .books import Book, Chapter, read_book
from .converter import convert_book
from .engines import Cancelled, EdgeEngine, SystemEngine, system_voices
from .settings import load_settings


def main():
    parser = argparse.ArgumentParser(description="小说转音频：无参数启动本地 Web 工作台")
    sub = parser.add_subparsers(dest="command")
    web = sub.add_parser("web", help="启动本地 Web 工作台")
    web.add_argument("--port", type=int, default=8788)
    web.add_argument("--no-browser", action="store_true")
    sub.add_parser("desktop", help="启动旧版 Tkinter 桌面界面")
    inspect = sub.add_parser("inspect", help="查看 EPUB/TXT 章节")
    inspect.add_argument("file", type=Path)
    sub.add_parser("voices", help="列出本机离线声音")
    convert = sub.add_parser("convert", help="导出章节 MP3")
    convert.add_argument("file", type=Path)
    convert.add_argument("--engine", choices=["system", "edge"], default="system")
    convert.add_argument("--voice")
    convert.add_argument("--rate", type=int, choices=range(-50, 101), metavar="-50..100", default=0)
    selection = convert.add_mutually_exclusive_group()
    selection.add_argument("--chapters", type=int, nargs="+", help="章节编号，从 1 开始；默认第 1 章")
    selection.add_argument("--all", action="store_true")
    convert.add_argument("--preview", type=int, metavar="CHARS", help="只转换首个选中章节的前 N 字")
    convert.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        if not args.command or args.command == "web":
            from .web import main as web_main
            web_main(getattr(args, "port", 8788), not getattr(args, "no_browser", False))
        elif args.command == "desktop":
            from .gui import main as gui_main
            gui_main()
        elif args.command == "voices":
            print("\n".join(system_voices()))
        elif args.command == "inspect":
            book = read_book(args.file)
            print(json.dumps({"title": book.title, "chapters": [{"number": i + 1, "title": c.title, "characters": len(c.text)} for i, c in enumerate(book.chapters)]}, ensure_ascii=False, indent=2))
        elif args.command == "convert":
            book = read_book(args.file)
            indices = list(range(len(book.chapters))) if args.all else [i - 1 for i in (args.chapters or [1])]
            if any(i < 0 or i >= len(book.chapters) for i in indices):
                raise ValueError("章节编号超出范围，请先运行 inspect")
            assets = Path(load_settings()["assets"])
            output = args.output or assets / ("preview" if args.preview is not None else "output")
            if args.preview is not None:
                if args.preview < 1:
                    raise ValueError("试听字数必须大于 0")
                chapter = book.chapters[indices[0]]
                book = Book(book.path, book.title, (Chapter("试听-" + chapter.title, chapter.text[:args.preview]),))
                indices = [0]
            if args.engine == "system":
                voices = system_voices()
                voice = args.voice or next((v for v in voices if "Chinese" in v), voices[0] if voices else "")
                if not voice:
                    raise ValueError("未找到系统语音")
                engine = SystemEngine(voice, args.rate)
            else:
                engine = EdgeEngine(args.voice or "zh-CN-XiaoxiaoNeural", args.rate)
            for path in convert_book(book, indices, engine, output, threading.Event(), lambda done, total, message: print(f"[{done}/{total}] {message}", flush=True)):
                print(path)
    except KeyboardInterrupt:
        print("已中止。已完成的分段可在下次运行时复用。", file=sys.stderr)
        return 130
    except (Exception, Cancelled) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
