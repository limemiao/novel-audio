"""Read EPUB spine order and plain text without extracting archive files."""
from __future__ import annotations

import posixpath
import re
import zipfile
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree as ET


@dataclass(frozen=True)
class Chapter:
    title: str
    text: str


@dataclass(frozen=True)
class Book:
    path: Path
    title: str
    chapters: tuple[Chapter, ...]


def normalize(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\u200b", "")
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


class TextExtractor(HTMLParser):
    """Ignore metadata, images, ruby readings, scripts, and navigation."""
    BLOCKS = {"p", "div", "br", "section", "li", "h1", "h2", "h3", "h4", "blockquote"}
    HIDDEN = {"head", "script", "style", "nav", "rt", "rp", "svg"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden: list[str] = []
        self.parts: list[str] = []
        self.heading_parts: list[str] = []
        self.heading = False
        self.title = ""

    def handle_starttag(self, tag, attrs):
        if tag in self.HIDDEN:
            self.hidden.append(tag)
        if self.hidden:
            return
        if tag in self.BLOCKS:
            self.parts.append("\n")
        if tag in {"h1", "h2", "h3"} and not self.title:
            self.heading = True

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if self.hidden:
            if tag == self.hidden[-1]:
                self.hidden.pop()
            return
        if tag in self.BLOCKS:
            self.parts.append("\n")
        if tag in {"h1", "h2", "h3"} and self.heading:
            self.title = "".join(self.heading_parts).strip()
            self.heading = False

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)
            if self.heading:
                self.heading_parts.append(data)


def html_text(data: bytes) -> tuple[str, str]:
    parser = TextExtractor()
    parser.feed(data.decode("utf-8-sig"))
    return parser.title, normalize("".join(parser.parts))


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def archive_path(base: str, href: str) -> str:
    url = urlsplit(href)
    if url.scheme or url.netloc:
        raise ValueError("EPUB 包含外部章节链接")
    path = posixpath.normpath(posixpath.join(base, unquote(url.path)))
    if path.startswith(("/", "../")) or path == ".." or "\\" in path:
        raise ValueError("EPUB 章节路径无效")
    return path


def read_epub(path: Path) -> Book:
    with zipfile.ZipFile(path) as archive:
        def read(name: str) -> bytes:
            if archive.getinfo(name).file_size > 20_000_000:
                raise ValueError("单个 EPUB 文本条目超过 20 MB，请先拆分")
            return archive.read(name)

        container = ET.fromstring(read("META-INF/container.xml"))
        rootfile = next(e.attrib["full-path"] for e in container.iter() if local(e.tag) == "rootfile")
        rootfile = archive_path("", rootfile)
        opf = ET.fromstring(read(rootfile))
        base = posixpath.dirname(rootfile)
        title = next(("".join(e.itertext()).strip() for e in opf.iter() if local(e.tag) == "title"), path.stem)
        manifest = {e.attrib["id"]: e.attrib for e in opf.iter() if local(e.tag) == "item"}
        labels: dict[str, str] = {}
        for item in manifest.values():
            if item.get("media-type") == "application/x-dtbncx+xml":
                ncx_path = archive_path(base, item["href"])
                ncx = ET.fromstring(read(ncx_path))
                for point in ncx.iter():
                    if local(point.tag) != "navPoint":
                        continue
                    label = next(("".join(e.itertext()).strip() for e in point if local(e.tag) == "navLabel"), "")
                    src = next((e.get("src", "") for e in point if local(e.tag) == "content"), "")
                    if src and label:
                        labels.setdefault(archive_path(posixpath.dirname(ncx_path), src), label)
        chapters = []
        for ref in opf.iter():
            if local(ref.tag) != "itemref" or ref.get("linear") == "no":
                continue
            item = manifest.get(ref.get("idref", ""))
            if not item or "nav" in item.get("properties", "").split():
                continue
            if item.get("media-type") not in {"application/xhtml+xml", "text/html"}:
                continue
            entry = archive_path(base, item["href"])
            heading, text = html_text(read(entry))
            label = heading or labels.get(entry) or f"第 {len(chapters) + 1} 节"
            # Illustration-only pages sometimes contain just their heading.
            body = text[len(heading):].strip() if heading and text.startswith(heading) else text
            if not body or not any(c.isalnum() for c in body):
                continue
            if label.strip() in {"封面", "彩页", "插图", "目录", "Cover", "Contents"}:
                continue
            chapters.append(Chapter(label, text))
    if not chapters:
        raise ValueError("这本 EPUB 没有可朗读正文（可能是漫画或扫描版）")
    return Book(path.resolve(), title, tuple(chapters))


CHAPTER_LINE = re.compile(r"^(?:第[零〇一二三四五六七八九十百千万两\d]+[章节卷部回].*|(?:序章|序言|前言|楔子|后记|尾声|终章|番外).*|Chapter\s+\d+.*)$", re.I)


def read_txt(path: Path) -> Book:
    data = path.read_bytes()
    encodings = ["utf-16"] if data.startswith((b"\xff\xfe", b"\xfe\xff")) else ["utf-8-sig", "gb18030"]
    for encoding in encodings:
        try:
            text = normalize(data.decode(encoding))
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError("无法识别 TXT 编码，请另存为 UTF-8")
    chapters, lines = [], []
    title = "正文"
    for line in text.splitlines():
        if len(line) <= 80 and CHAPTER_LINE.fullmatch(line):
            if lines:
                chapters.append(Chapter(title, "\n".join(lines)))
            title, lines = line, [line]
        else:
            lines.append(line)
    if lines:
        chapters.append(Chapter(title, "\n".join(lines)))
    if not chapters:
        raise ValueError("文本文件为空")
    return Book(path.resolve(), path.stem, tuple(chapters))


def read_book(path: Path) -> Book:
    if path.suffix.lower() == ".epub":
        return read_epub(path)
    if path.suffix.lower() == ".txt":
        return read_txt(path)
    raise ValueError("目前支持 EPUB 和 TXT；PDF 请先提取为文本")


def scan_library(root: Path) -> list[Path]:
    if not root.is_dir():
        raise ValueError(f"书库目录不存在：{root}")
    return sorted((p for p in root.rglob("*") if p.suffix.lower() in {".epub", ".txt"} and p.is_file()), key=lambda p: str(p).casefold())


def split_text(text: str, limit: int = 1200) -> list[str]:
    """Bound requests, preferring paragraph/sentence boundaries; retain all text."""
    if limit < 32:
        raise ValueError("分段长度至少为 32")
    text = normalize(text)
    result = []
    while len(text) > limit:
        end = max(text.rfind(mark, limit // 2, limit) for mark in "\n。！？!?；;")
        end = end + 1 if end >= 0 else limit
        result.append(text[:end].strip())
        text = text[end:].strip()
    if text:
        result.append(text)
    return result
