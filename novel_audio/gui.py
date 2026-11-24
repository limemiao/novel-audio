from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from .books import Book, Chapter, read_book, scan_library
from .converter import convert_book
from .engines import Cancelled, EDGE_VOICES, EdgeEngine, SystemEngine, system_voices
from .settings import load_settings


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("听书工坊 · Novel Audio")
        self.geometry("1180x800")
        self.minsize(960, 680)
        self.configure(bg="#f2f5f8")
        self.option_add("*Font", ("Microsoft YaHei UI", 10))
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background="#f2f5f8")
        style.configure("TLabel", background="#f2f5f8")
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 23, "bold"), foreground="#183c4c")
        style.configure("TButton", padding=(12, 7))
        style.configure("Accent.TButton", background="#166b66", foreground="white")
        style.map("Accent.TButton", background=[("active", "#205f5b")])
        settings = load_settings()
        self.library = tk.StringVar(value=settings["library"])
        self.output = tk.StringVar(value=str(Path(settings["assets"]) / "output"))
        self.assets = Path(settings["assets"])
        self.search = tk.StringVar()
        self.engine_choice = tk.StringVar(value="系统语音 · 离线")
        self.voice_choice = tk.StringVar()
        self.rate = tk.IntVar(value=0)
        self.status = tk.StringVar(value="正在扫描书库…")
        self.book_info = tk.StringVar(value="选择一本小说开始")
        self.hint = tk.StringVar(value="离线合成：使用 Windows 已安装语音，文本保留在本机。")
        self.paths: list[Path] = []
        self.visible_paths: list[Path] = []
        self.book: Book | None = None
        self.voices: list[str] = []
        self.busy = False
        self.closing = False
        self.cancel = threading.Event()
        self.events = queue.Queue()
        self.controls: list[tuple[tk.Widget, str]] = []
        self.last_results: list[Path] = []
        self.build()
        self.search.trace_add("write", lambda *_: self.filter_books())
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.after(100, self.drain)
        self.after(150, self.refresh)
        threading.Thread(target=self.discover_voices, daemon=True).start()

    def button(self, parent, text, command, **options):
        widget = ttk.Button(parent, text=text, command=command, **options)
        self.controls.append((widget, "normal"))
        return widget

    def build(self):
        main = ttk.Frame(self, padding=22)
        main.pack(fill="both", expand=True)
        ttk.Label(main, text="听书工坊", style="Title.TLabel").pack(anchor="w")
        ttk.Label(main, text="从书架到耳边  ·  EPUB / TXT  ·  分章导出 MP3  ·  中断后继续").pack(anchor="w", pady=(4, 18))
        locations = ttk.Frame(main)
        locations.pack(fill="x")
        locations.columnconfigure(1, weight=1)
        for row, (label, variable, command) in enumerate((("小说书库", self.library, self.choose_library), ("音频目录", self.output, self.choose_output))):
            ttk.Label(locations, text=label, width=10).grid(row=row, column=0, sticky="w", pady=4)
            entry = ttk.Entry(locations, textvariable=variable)
            entry.grid(row=row, column=1, sticky="ew", padx=8)
            self.controls.append((entry, "normal"))
            self.button(locations, "选择目录", command).grid(row=row, column=2, padx=4)
        self.button(locations, "刷新书库", self.refresh).grid(row=0, column=3)
        self.button(locations, "导入文件", self.import_file).grid(row=1, column=3)
        panels = ttk.Panedwindow(main, orient="horizontal")
        panels.pack(fill="both", expand=True, pady=16)
        left = ttk.Frame(panels, padding=(0, 0, 10, 0))
        right = ttk.Frame(panels, padding=(10, 0, 0, 0))
        panels.add(left, weight=2)
        panels.add(right, weight=3)
        ttk.Label(left, text="本地书架 · 搜索书名或系列").pack(anchor="w")
        search = ttk.Entry(left, textvariable=self.search)
        search.pack(fill="x", pady=8)
        self.controls.append((search, "normal"))
        self.books_list = self.listbox(left, "browse")
        self.books_list.bind("<<ListboxSelect>>", self.select_book)
        ttk.Label(right, textvariable=self.book_info, wraplength=570).pack(anchor="w", pady=(0, 8))
        self.chapters_list = self.listbox(right, "extended", height=7, expand=False)
        self.chapters_list.bind("<<ListboxSelect>>", self.select_chapter)
        selection = ttk.Frame(right)
        selection.pack(fill="x", pady=5)
        self.button(selection, "全选章节", self.select_all).pack(side="left")
        ttk.Label(selection, text="  Ctrl / Shift 多选；下方预览首个选中章节").pack(side="left")
        self.preview = ScrolledText(right, wrap="word", height=8, relief="flat", padx=12, pady=10, bg="#ffffff", fg="#30434d", state="disabled")
        self.preview.pack(fill="both", expand=True, pady=(5, 0))
        options = ttk.Frame(main)
        options.pack(fill="x")
        ttk.Label(options, text="语音引擎").pack(side="left")
        engines = ttk.Combobox(options, textvariable=self.engine_choice, values=["系统语音 · 离线", "Edge 语音 · 在线"], width=19, state="readonly")
        engines.pack(side="left", padx=8)
        engines.bind("<<ComboboxSelected>>", lambda _: self.update_voices())
        self.controls.append((engines, "readonly"))
        self.voice_box = ttk.Combobox(options, textvariable=self.voice_choice, state="readonly", width=45)
        self.voice_box.pack(side="left", padx=(0, 14), fill="x", expand=True)
        self.controls.append((self.voice_box, "readonly"))
        ttk.Label(options, text="语速 %").pack(side="left")
        speed = ttk.Spinbox(options, from_=-50, to=100, increment=10, width=6, textvariable=self.rate)
        speed.pack(side="left", padx=8)
        self.controls.append((speed, "normal"))
        ttk.Label(main, textvariable=self.hint).pack(anchor="w", pady=8)
        actions = ttk.Frame(main)
        actions.pack(fill="x")
        self.button(actions, "试听前 180 字", lambda: self.generate(True)).pack(side="left")
        self.button(actions, "生成选中章节", self.generate, style="Accent.TButton").pack(side="left", padx=8)
        self.stop_button = ttk.Button(actions, text="停止并保留进度", command=self.cancel.set, state="disabled")
        self.stop_button.pack(side="left")
        self.button(actions, "打开音频目录", self.open_output).pack(side="right")
        self.progress = ttk.Progressbar(main, mode="determinate")
        self.progress.pack(fill="x", pady=(14, 7))
        ttk.Label(main, textvariable=self.status, wraplength=1100).pack(anchor="w")

    def listbox(self, parent, mode, height=14, expand=True):
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=expand)
        box = tk.Listbox(frame, selectmode=mode, exportselection=False, height=height, relief="flat", borderwidth=0, bg="white", fg="#30434d", selectbackground="#166b66", activestyle="none")
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=box.yview)
        box.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        box.pack(fill="both", expand=True)
        self.controls.append((box, "normal"))
        return box

    def discover_voices(self):
        try:
            self.events.put(("voices", system_voices()))
        except Exception as exc:
            self.events.put(("voice_error", str(exc)))

    def update_voices(self):
        online = self.engine_choice.get().startswith("Edge")
        values = list(EDGE_VOICES) if online else self.voices
        self.voice_box.configure(values=values)
        default = next((v for v in values if "Chinese" in v or "Huihui" in v), values[0] if values else "")
        self.voice_choice.set(default)
        self.hint.set("在线合成：待朗读文本会发送到微软服务；需要联网并安装在线依赖。" if online else "离线合成：文本保留在本机。系统语速按档位近似调整，每 10% 对应一档。")

    def set_busy(self, busy):
        self.busy = busy
        for control, normal_state in self.controls:
            control.configure(state="disabled" if busy else normal_state)
        self.stop_button.configure(state="normal" if busy else "disabled")

    def task(self, work, done):
        if self.busy:
            return
        self.cancel = threading.Event()
        self.set_busy(True)

        def run():
            try:
                self.events.put(("done", done, work()))
            except Cancelled as exc:
                self.events.put(("cancelled", str(exc)))
            except Exception as exc:
                self.events.put(("error", str(exc)))
        threading.Thread(target=run, daemon=True).start()

    def drain(self):
        try:
            while True:
                event = self.events.get_nowait()
                if event[0] == "progress":
                    _, done, total, message = event
                    self.progress.configure(maximum=max(total, 1), value=done)
                    self.status.set(message)
                elif event[0] == "voices":
                    self.voices = event[1]
                    if not self.engine_choice.get().startswith("Edge"):
                        self.update_voices()
                elif event[0] == "voice_error":
                    self.hint.set("系统语音读取失败：" + event[1])
                elif event[0] == "done":
                    self.set_busy(False)
                    if not self.closing:
                        event[1](event[2])
                elif event[0] in {"error", "cancelled"}:
                    self.set_busy(False)
                    self.status.set(event[1])
                    if event[0] == "error" and not self.closing:
                        messagebox.showerror("操作未完成", event[1], parent=self)
        except queue.Empty:
            pass
        if self.closing and not self.busy:
            self.destroy()
            return
        self.after(100, self.drain)

    def choose_library(self):
        result = filedialog.askdirectory(initialdir=self.library.get(), parent=self)
        if result:
            self.library.set(result)
            self.refresh()

    def choose_output(self):
        result = filedialog.askdirectory(initialdir=self.output.get(), parent=self)
        if result:
            self.output.set(result)

    def refresh(self):
        root = Path(self.library.get())
        self.status.set("正在扫描 EPUB / TXT 文件…")
        def done(paths):
            self.paths = paths
            self.filter_books()
            self.status.set(f"书库已就绪，共 {len(paths)} 本；选择小说查看章节。PDF 暂不支持。")
        self.task(lambda: scan_library(root), done)

    def filter_books(self):
        if self.busy:
            return
        query = self.search.get().strip().casefold()
        self.visible_paths = [p for p in self.paths if query in str(p).casefold()]
        self.books_list.delete(0, "end")
        for path in self.visible_paths:
            self.books_list.insert("end", path.stem)

    def import_file(self):
        result = filedialog.askopenfilename(initialdir=self.library.get(), filetypes=[("小说文件", "*.epub *.txt"), ("所有文件", "*.*")], parent=self)
        if result:
            self.load_book(Path(result))

    def select_book(self, _event=None):
        if not self.busy and self.books_list.curselection():
            self.load_book(self.visible_paths[self.books_list.curselection()[0]])

    def load_book(self, path):
        self.status.set("正在提取章节正文…")
        def done(book):
            self.book = book
            self.chapters_list.delete(0, "end")
            for i, chapter in enumerate(book.chapters):
                self.chapters_list.insert("end", f"{i + 1:02d}  {chapter.title}  ·  {len(chapter.text):,} 字符")
            self.book_info.set(f"{book.title}  ·  {len(book.chapters)} 个章节")
            self.chapters_list.selection_set(0)
            self.select_chapter()
            self.status.set("可先试听，再选择需要生成的章节。")
        self.task(lambda: read_book(path), done)

    def select_chapter(self, _event=None):
        if self.book and self.chapters_list.curselection():
            chapter = self.book.chapters[self.chapters_list.curselection()[0]]
            self.preview.configure(state="normal")
            self.preview.delete("1.0", "end")
            self.preview.insert("1.0", chapter.text[:12000] + ("\n\n……（仅预览前 12000 字，生成使用完整正文）" if len(chapter.text) > 12000 else ""))
            self.preview.configure(state="disabled")

    def select_all(self):
        self.chapters_list.selection_set(0, "end")
        self.select_chapter()

    def generate(self, preview=False):
        if self.busy:
            return
        indices = list(self.chapters_list.curselection())
        if not self.book or not indices:
            messagebox.showinfo("选择章节", "请先选择小说和需要朗读的章节。", parent=self)
            return
        try:
            rate = self.rate.get()
            if not -50 <= rate <= 100:
                raise ValueError()
        except (ValueError, tk.TclError):
            messagebox.showerror("语速无效", "请输入 -50 到 100 之间的整数。", parent=self)
            return
        voice = self.voice_choice.get()
        if not voice:
            messagebox.showerror("没有可用声音", "请选择可用声音，或安装 Windows 中文语音包。", parent=self)
            return
        online = self.engine_choice.get().startswith("Edge")
        engine = EdgeEngine(EDGE_VOICES[voice], rate) if online else SystemEngine(voice, rate)
        book = self.book
        destination = Path(self.output.get()).expanduser()
        if preview:
            chapter = book.chapters[indices[0]]
            book = Book(book.path, book.title, (Chapter("试听-" + chapter.title, chapter.text[:180]),))
            indices = [0]
            destination = self.assets / "preview"
        def progress(done, total, message):
            self.events.put(("progress", done, total, message))
        def done(paths):
            self.last_results = paths
            self.status.set(f"已生成 {len(paths)} 个 MP3：{paths[0].parent.parent}")
            if preview:
                try:
                    os.startfile(paths[0])
                except OSError as exc:
                    messagebox.showinfo("试听已保存", f"无法启动默认播放器：{exc}\n文件：{paths[0]}", parent=self)
        self.progress.configure(value=0)
        self.status.set("准备合成音频…")
        self.task(lambda: convert_book(book, indices, engine, destination, self.cancel, progress), done)

    def open_output(self):
        directory = Path(self.output.get()).expanduser()
        try:
            directory.mkdir(parents=True, exist_ok=True)
            os.startfile(directory)
        except OSError as exc:
            messagebox.showerror("无法打开目录", str(exc), parent=self)

    def close(self):
        if self.busy:
            self.closing = True
            self.cancel.set()
            self.status.set("正在停止任务并保存进度…")
        else:
            self.destroy()


def main():
    App().mainloop()
