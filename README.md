# 听书工坊 · Novel Audio

把本地小说转成 MP3 的 Web 工作台。直接读取 EPUB（也支持 UTF-8 / UTF-16 / GB18030 TXT），
在浏览器里完成选书、选声、试听、排队和导出；每章一个 MP3，支持中断后续转。

## 功能

- 封面书架、系列筛选、书名搜索、章节预览。
- Windows SAPI 离线语音 + Edge 在线神经网络语音，可试听 180 字。
- 任务队列、后台转换、进度与停止、失败继续、SHA-256 分段校验。
- 成品播放、下载、按章输出；Web 导入 EPUB / TXT。
- 同一份源码提供 Web 工作台、旧桌面 GUI 和命令行三种入口。
- 纯标准库 Web 服务，无需前端构建、Node.js 或数据库。

## 环境要求

- Windows 10 / 11。
- Python 3.11 或更高版本。
- FFmpeg / FFprobe 在 `PATH` 中。
- 离线合成使用 Windows SAPI 语音（例如 Huihui 中文、Zira 英语、Haruka 日语）。
- 在线合成可选安装 `edge-tts`；无需 API Key。

## 安装

离线模式不需要安装第三方 Python 包：

```powershell
python -m novel_audio
```

启用 Edge 在线语音：

```powershell
# 创建 assets\.venv 并安装 edge-tts
install-online.cmd
```

也可以手动安装：

```powershell
python -m pip install -r requirements-online.txt
```

浏览器 QA 的可选依赖见 `requirements-dev.txt`（Playwright）。

## 配置

`config.json` 只有两个字段，修改后重启服务：

```json
{
  "library": "library",
  "assets": "assets"
}
```

- `library`：EPUB / TXT 书库目录，只读，不会被修改。
- `assets`：输出、试听、导入、任务历史和可选虚拟环境的根目录。

两个目录默认都是相对项目根目录的路径，并已加入 `.gitignore`。

## 快速开始

1. 双击 `run.cmd`，或执行 `python -m novel_audio`。
2. 浏览器打开 <http://127.0.0.1:8788>。
3. 在书架选书，在配音面板选声音、语速和章节。
4. 「试听 180 字」确认效果，然后「开始制作」。
5. 在「我的音频」播放或下载 MP3。

工作台只监听 `127.0.0.1`；浏览器关闭不会中断后台转换。服务停止会中断当前任务，
已完成的分段仍保留，重启后可「继续制作」。

## 语音引擎

| 引擎 | 特点 | 安装 |
|---|---|---|
| 系统语音（默认） | 完全离线，使用 Windows SAPI；声音取决于系统已安装的语言包 | 无额外依赖 |
| Edge 在线语音 | 晓晓、云希等神经网络声音，通常更自然 | `install-online.cmd` |

选择 Edge 在线语音会把待朗读文本发送到微软的在线服务，需要联网，且接口和可用声音
可能变化。系统语音可作为离线替代。

## 命令行

```powershell
# 查看本机声音
python -m novel_audio voices

# 查看 EPUB 章节
python -m novel_audio inspect "library\某系列\某卷.epub"

# 用自带示例文本验证离线合成
python -m novel_audio convert examples\sample.txt --chapters 1

# 只生成前 180 字试听
python -m novel_audio convert "D:\books\某书.epub" --preview 180

# 指定章节 / 整卷
python -m novel_audio convert "D:\books\某书.epub" --chapters 1 2 3
python -m novel_audio convert "D:\books\某书.epub" --all
```

其他 Web 参数：

```powershell
# 指定端口、不自动打开浏览器
python -m novel_audio web --port 8788 --no-browser

# 旧版桌面界面
python -m novel_audio desktop
```

## 目录结构

```text
novel-audio/
├─ novel_audio/
│  ├─ books.py          # EPUB/TXT 导入、章节解析与分段
│  ├─ engines.py        # 语音引擎调度
│  ├─ sapi.ps1          # Windows SAPI 合成
│  ├─ converter.py      # 缓存、取消、分段与 MP3 合并
│  ├─ voices.py         # 在线音色目录、缓存与刷新
│  ├─ web.py            # 本地 HTTP 服务与任务队列
│  ├─ web_static/       # 无需构建的 HTML/CSS/JS
│  ├─ gui.py            # 旧桌面界面
│  └─ __main__.py       # 启动与命令行入口
├─ docs/                # Web、验证记录与完整说明
├─ examples/sample.txt
├─ tests/
├─ config.json
├─ run.cmd
└─ install-online.cmd
```

新增语音引擎只需实现 `name`、`extension`、`voice`、`rate` 和
`synthesize(text, destination, cancel)`。

## 输出与缓存

- 正式音频：`assets\output`
- 试听音频：`assets\preview`
- Web 导入文件：`assets\imports`
- 任务历史：`assets\web-jobs.json`
- 每章 `.chunks` 保存续转分段，`manifest.json` 记录配置和 SHA-256。
- 改变文本、声音或语速会生成独立结果，不覆盖旧配置的音频。
- 强制终止可能遗留 `.lock`；确认没有任务运行后删除对应锁文件即可。

## 已知限制

- 仅支持常见 EPUB；PDF、图片扫描版和加密 EPUB 不支持。
- 统一旁白朗读，不含角色识别、配音分配、声音克隆或背景音乐。
- 章节标题和正文质量取决于原 EPUB。
- 长章节按约 1200 字符分段，优先在段落或句末断开。

## 测试

```powershell
python -m unittest discover -s tests -v
```

浏览器冒烟测试见 `tests/browser_smoke.py` 和 `tests/browser_voices.py`。

## 更多文档

- [docs/validation.md](docs/validation.md)：首版验证记录
- [docs/web.md](docs/web.md)：Web 工作台实现与验证
- [docs/README-full.md](docs/README-full.md)：整理前的完整说明

## 许可

本仓库未附带开源许可证。使用前请自行确认依赖组件和语音服务的许可条款。
