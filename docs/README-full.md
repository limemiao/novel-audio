# 听书工坊 · Novel Audio

> 这是导出前的完整说明。仓库中未包含其中提到的书库内容、音频成品和个人配置。

本地 Web 小说转音频工作台。暖白与深绿色的封面书架，配音面板、任务队列和底部播放器集中在一个页面。
直接读取 `library` 的 EPUB，选择章节和声音，试听后导出每章一个 MP3。
也支持 UTF-8、UTF-16 和 GB18030 编码 TXT。兼容桌面浏览器与窄窗口布局。

## 启动

本机已具备 Python 3.11、Tkinter、Windows 中文语音和 FFmpeg，离线模式无需安装第三方 Python 包。

双击 **`run.cmd`**，会启动本地服务并自动打开浏览器：**http://127.0.0.1:8788**。
保留启动时的命令窗口；按 Ctrl+C 停止服务。重复双击会打开已经运行的工作台。
也可以在本目录执行：

```powershell
python -m novel_audio
```

在线依赖可安装到 `assets\.venv`，`run.cmd` 会优先使用它。
已用示例 EPUB 的完整序章验证离线转换，成品在默认 `output` 目录，约 6 分 50 秒。
完整验证记录见 [docs/validation.md](validation.md)。
Web 版实现与验证记录见 [docs/web.md](web.md)。

1. 在「小说书架」搜索书名，或按系列筛选，点击封面选择小说。
2. 在右侧「配音工作台」选择声音、调整语速，勾选章节；「预览」可查看章节正文。
3. 点击「试听 180 字」，完成后在底部播放器试听，支持拖动进度、调节音量与播放速度。
4. 点击「开始制作」，在「制作任务」查看进度或停止任务。
5. 成品自动出现在「我的音频」，可播放或下载 MP3；本机原件仍保存在书库目录。
6. 用「导入小说」添加 EPUB / TXT，单文件上限 64 MB。导入副本保存在 `assets`，原文件不改动。
7. 停止或失败后可点击任务的「继续制作」，复用已经校验的音频分段。

默认只选第一章。可以为不同小说分别添加任务，按队列串行执行，最多同时排队 20 个任务。
浏览器关闭不影响后台转换；服务停止会中断当前任务，已完成的音频分段仍保留。
服务重启后，未完成的历史任务显示为停止，点击「继续制作」重新加入队列。

工作台仅监听本机 `127.0.0.1`，无需登录或远程部署。手机尺寸布局适合窄窗口；默认不向局域网手机开放访问。

```powershell
# 指定端口 / 不自动打开浏览器
python -m novel_audio web --port 8788 --no-browser

# 保留旧版桌面入口
python -m novel_audio desktop
```

## 语音选项

| 引擎 | 特点 | 安装 |
|---|---|---|
| 系统语音（默认） | 完全离线，使用 Windows SAPI；本机可选 Huihui 中文、Zira 英语、Haruka 日语 | 无额外依赖 |
| Edge 在线语音 | 提供晓晓、云希等神经网络声音，通常更自然；无需配置 API Key | 双击 `install-online.cmd`，完成后重启 |

Web 工作台选择「自然语音」后，可按语言 / 地区、性别筛选，也可以搜索声音名称或 ID。
2026-11-17 的音色目录包含 **318 个音色，其中中文 14 个**，包括普通话的云扬、云夏，
辽宁的晓北、陕西的晓妮，以及香港粤语和台湾中文声音。选中后点击「试听 180 字」比较效果。
「刷新音色」会联网更新目录；刷新失败时保留已有列表。离线系统语音的数量取决于 Windows 已安装的声音。
如果页面仍只显示原来的 6 个在线音色，请关闭旧服务的启动窗口，再重新双击 `run.cmd`。

**选择 Edge 在线语音会将待朗读文本发送到微软的在线服务。** 需要联网；其接口和可用声音可能变化，
不能保证长期可用。请求失败时最多尝试 3 次，已有分段保留。系统语音可作为离线替代。

界面语速范围为 -50 到 +100。Edge 按百分比调整；SAPI 按每 10 对应一档近似调整，并非精确百分比。
目前统一旁白朗读，不含角色自动识别、配音分配、声音克隆或背景音乐。

## 文件位置

- 代码：项目根目录
- 默认小说来源：`library`，只读原始小说，不复制、不改写 EPUB。
- 正式音频：`assets\output`
- 试听音频：`assets\preview`
- 在线模式可选 Python 环境：`assets\.venv`
- 验证结果：`assets\qa`
- Web 导入文件：`assets\imports`
- Web 任务历史：`assets\web-jobs.json`
- 在线音色目录缓存：`assets\edge-voices.json`；未缓存时使用项目内置目录 `novel_audio/voice-catalog.json`，启动时无需联网。

`config.json` 配置默认书库和资源根目录，修改后需重启服务。网页的「工作台设置」显示当前路径。
`run.cmd` 与 `install-online.cmd` 的可选环境路径独立写在脚本中，迁移机器时也要相应修改。

输出结构：书名与来源标识 / 章节编号、标题与配置标识 / 章节 MP3。
每章目录中的 `.chunks` 保存续转分段，`manifest.json` 记录配置和 SHA-256 校验值。
完成音频可直接拷贝给播放器；如确定不再续转，可手动删除该章 `.chunks` 以释放空间。
改变文本、声音或语速会生成独立结果，不覆盖旧配置的音频。
强制断电、杀进程可能遗留 `.lock`；确认没有任务运行后，删除报错中指出的锁文件即可重试。

## EPUB 读取方式与边界

- 按 OPF spine 的顺序提取章节，不按压缩包文件名排序；一份 spine 正文条目对应一个音频章节。
- 优先使用正文标题，其次使用 EPUB 2 NCX 标题；其余条目按节编号命名。
- 忽略封面、纯插图、导航、样式和脚本；ruby 注音只朗读正文。
- 长章节以约 1200 字符为上限分段，优先在段落或句末断开，再用 FFmpeg 编码合并为 96 kbps MP3。
- 当前支持常见 UTF-8 EPUB，PDF、图片扫描版、加密 EPUB 暂不支持。
- 标题和正文依赖原 EPUB 质量；开始整卷转换前建议查看章节预览。
- 离线合成时，当前分段会短暂写入输出目录的临时 TXT，完成或正常取消后删除。
- 缓存仍包含语音内容；强制终止进程可能遗留临时文件，相关目录应按个人文件管理。

## 命令行

```powershell
# 查看本机声音与章节
python -m novel_audio voices
python -m novel_audio inspect "library\某系列\某卷.epub"

# 使用自带短文本验证离线合成
python -m novel_audio convert examples\sample.txt --chapters 1

# 只生成前 180 字试听，默认保存到 preview
python -m novel_audio convert "D:\路径\小说.epub" --preview 180

# 选定章节 / 整卷；输出目录可用 --output 指定
python -m novel_audio convert "D:\路径\小说.epub" --chapters 1 2 3
python -m novel_audio convert "D:\路径\小说.epub" --all

# 安装在线依赖后，使用可选环境运行
assets\.venv\Scripts\python.exe -m novel_audio convert examples\sample.txt --engine edge --voice zh-CN-YunxiNeural

# 无联网需求的逻辑测试
python -m unittest discover -s tests -v
```

## 代码结构

`books.py` 负责导入与分段；`engines.py` / `sapi.ps1` 负责语音合成；`converter.py`
负责缓存、取消和 MP3 合并；`web.py` 提供本地 HTTP 服务与任务队列；`web_static/`
包含无需构建的 HTML/CSS/JavaScript；`gui.py` 保留旧桌面界面；`__main__.py` 提供启动和命令行入口。
`voices.py` 负责在线音色目录的校验、缓存与手动刷新。
新增引擎只需实现 `name`、`extension`、`voice`、`rate` 和 `synthesize(text, destination, cancel)`。

## 下一步

- 引入本地神经网络 TTS，改善离线自然度。
- 角色与对白分析、每角色选声。
- 整卷 M4B 和章节标记。
