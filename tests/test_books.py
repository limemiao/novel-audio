import tempfile
import unittest
import zipfile
from pathlib import Path

from novel_audio.books import archive_path, html_text, read_book, split_text


class BookTests(unittest.TestCase):
    def test_html_excludes_metadata_ruby_and_images(self):
        heading, text = html_text('''<html><head><title>不读标题</title><style>不读样式</style></head>
        <body><h1>序章</h1><p>她说：<ruby>你好<rt>ni hao</rt><rp>(</rp></ruby>。</p>
        <p><img src="a.jpg" alt="不读插图"/></p><script>不读代码</script><nav>不读导航</nav></body></html>'''.encode())
        self.assertEqual(heading, "序章")
        self.assertEqual(text, "序章\n她说：你好。")

    def test_spine_order_and_illustration_filter(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "book.epub"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("META-INF/container.xml", '<container><rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles></container>')
                archive.writestr("OEBPS/content.opf", '''<package><metadata><title>测试书</title></metadata><manifest>
                <item id="a" href="Text/a.xhtml" media-type="application/xhtml+xml"/>
                <item id="b" href="Text/b.xhtml" media-type="application/xhtml+xml"/>
                <item id="image" href="Text/image.xhtml" media-type="application/xhtml+xml"/>
                <item id="nav" href="Text/nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
                </manifest><spine><itemref idref="b"/><itemref idref="image"/><itemref idref="nav"/><itemref idref="a"/></spine></package>''')
                archive.writestr("OEBPS/Text/a.xhtml", "<h1>第二章</h1><p>第二段正文。</p>")
                archive.writestr("OEBPS/Text/b.xhtml", "<h1>第一章</h1><p>第一段正文。</p>")
                archive.writestr("OEBPS/Text/image.xhtml", '<h1>彩页</h1><img src="a.jpg"/>')
            book = read_book(path)
            self.assertEqual(book.title, "测试书")
            self.assertEqual([c.title for c in book.chapters], ["第一章", "第二章"])

    def test_txt_encodings_and_chapters(self):
        text = "第一章 开始\n你好，世界。\n第二章 后来\n还有故事。"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "novel.txt"
            for encoding in ["utf-8-sig", "utf-16", "gb18030"]:
                with self.subTest(encoding=encoding):
                    path.write_bytes(text.encode(encoding))
                    book = read_book(path)
                    self.assertEqual(len(book.chapters), 2)
                    self.assertIn("还有故事", book.chapters[1].text)

    def test_split_keeps_non_whitespace_and_bounds(self):
        for text in [("一句话。“另一句。”\n" * 1000), "甲" * 3001, "A" * 1199 + "。末尾"]:
            parts = split_text(text)
            self.assertTrue(all(0 < len(p) <= 1200 for p in parts))
            self.assertEqual("".join("".join(parts).split()), "".join(text.split()))

    def test_archive_hrefs(self):
        self.assertEqual(archive_path("OEBPS", "Text/%E7%AB%A0.xhtml#part"), "OEBPS/Text/章.xhtml")
        for href in ["../../secret", "/secret", "https://example.com/a", "..\\secret"]:
            with self.assertRaises(ValueError):
                archive_path("OEBPS", href)

    def test_empty_text_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "empty.txt"
            path.write_text(" \n ", encoding="utf-8")
            with self.assertRaises(ValueError):
                read_book(path)


if __name__ == "__main__":
    unittest.main()
