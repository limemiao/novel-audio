# 听书工坊 · Novel Audio

把自己的 EPUB 或 TXT 转成按章节组织的 MP3。工作台把书架、章节选择、声音试听、后台队列和播放器放在一个页面里，也可以从命令行批量转换。

## Windows 快速开始

安装 Python 3.11+，并把 FFmpeg 加入 PATH。离线合成使用 Windows SAPI，需要安装对应语言的系统语音。从仓库根目录启动：

```powershell
.\run.cmd
# 或以指定端口启动
python -m novel_audio web --port 8788 --no-browser
```

浏览器打开 <http://127.0.0.1:8788>。将 EPUB 放进 `library/`，或在页面导入 EPUB/TXT。选中一本书和所需章节，先试听，再加入制作队列。任务中断后可以继续，程序会复用校验通过的音频分段。

## 声音与命令行

| 引擎 | 用法 |
| --- | --- |
| Windows SAPI | 默认离线引擎，声音取决于系统安装的语音包 |
| Edge TTS | 运行 `install-online.cmd` 后重启。待朗读文本会发送给在线语音服务 |

```powershell
python -m novel_audio voices
python -m novel_audio inspect examples\sample.txt
python -m novel_audio convert examples\sample.txt --chapters 1
python -m novel_audio convert examples\sample.txt --preview 180
```

Windows 桌面入口是 `python -m novel_audio desktop`。Web 服务默认只在本机访问。

## 书库与产物

`config.json` 的 `library` 是 EPUB 扫描目录，`assets` 是输出与缓存目录。修改后请重启服务。默认目录布局如下。

| 路径 | 用途 |
| --- | --- |
| `library/` | 本地书库，由使用者提供 |
| `assets/output/`、`assets/preview/` | 正式音频与试听 |
| `assets/imports/` | 网页导入副本 |
| `assets/web-jobs.json` | 本地任务历史 |
| `assets/.venv/` | Windows 安装脚本使用的可选在线环境 |

程序按 EPUB spine 顺序读取正文，忽略纯插图和导航。暂不支持 PDF、扫描件或加密 EPUB。请把书库、导入材料和音频留在本机。

## 源码与验证

`novel_audio/` 包含书籍解析、合成、转换和 Web 服务。前端位于 `novel_audio/web_static/`，示例位于 `examples/`。在线语音和浏览器测试依赖分别放在 `requirements/requirements-online.txt` 与 `requirements/requirements-dev.txt`。

```powershell
python -m unittest discover -s tests -v
```

浏览器专项检查见 [Web 工作台说明](docs/web.md)，更多细节见 [完整手册](docs/README-full.md)。本仓库尚未附带开源许可证。
