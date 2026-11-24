# Web 工作台

运行 `python -m novel_audio web --no-browser` 后，打开 `http://127.0.0.1:8788`。
生产使用直接双击 `run.cmd`，无需前端构建、Node.js 或额外 Web 框架依赖。

## 实现

- Python 标准库 `ThreadingHTTPServer`，仅绑定 loopback；前端为原生 HTML/CSS/JavaScript。
- EPUB 封面按需从压缩包内读取；不解压原书，不依赖第三方图片链接。
- 章节解析使用现有导入模块，缓存最近四本书。
- 单工作线程串行处理跨书任务，每本书可选择多个章节。
- 浏览器每两秒同步任务与音频；任务历史保存在 `assets`，分段复用现有 SHA-256 缓存。
- 音频接口实现 Range / 206 / 416，支持浏览器跳转进度与下载。
- 上传限制 64 MB，验证 EPUB/TXT 后保存至 `assets`；原文件保持只读。
- 变更接口校验 Host、Origin 和自定义请求头，不开放 CORS，不接受任意路径读取。
- 当前任务记录没有自动清理功能；音频可在 `assets` 手动管理。

## 验证

```powershell
python -m unittest discover -s tests -v

# 可选浏览器 QA（复用本机 Edge，不下载浏览器）
assets\.venv\Scripts\python.exe -m pip install --no-cache-dir -r requirements/requirements-dev.txt
assets\.venv\Scripts\python.exe tests\browser_smoke.py
```

浏览器 QA 会在运行中的应用提交实际试听和章节导出任务，复用示例 EPUB 的序章缓存。
截图写入 `assets\qa\web`。
无头浏览器仅用于验证，用户使用普通浏览器打开本地地址。

## 2026-11-17 验证结果

- 18 项自动测试通过，含原有 12 项转换逻辑测试和新增 6 项 Web 接口测试。
- Web 测试覆盖书库/章节、非法请求、上传校验、音频 Range/下载、队列完成/历史持久化、运行中与排队任务取消。
- Edge 实测：封面加载、书名搜索、章节预览与全选、声音切换、真实离线试听、播放与拖动、下载、正式章节导出、任务和音频筛选、分页、空搜索结果、设置弹窗。
- 1440×1100 桌面与 390×844 窄屏布局验证通过，窄屏无横向溢出，未发现 JavaScript 页面异常。
- 本地服务已接入本地 EPUB 书库，仍使用原有 `assets` 音频与缓存。

桌面截图：`qa/web/desktop.png`；完整书架：`qa/web/desktop-full.png`；窄屏：`qa/web/mobile.png`。

## 2026-11-17 音色扩展验证

- 扩展后共 24 项自动测试通过，新增音色元数据校验、缓存回退、刷新失败保留、任务音色校验和端口独占测试。
- 在线目录实际获取 318 个音色，其中中文 14 个；启动加载缓存或内置快照，只有手动刷新才请求目录服务。
- 浏览器验证语言 / 地区与性别筛选、名称搜索、空结果禁用制作、引擎切换保留选择，以及刷新成功和失败。
- 桌面 1440×1100 与窄屏 390×844 均无横向溢出和 JavaScript 异常。
- 使用项目自带 `examples/sample.txt` 实际合成云扬和晓北，FFprobe 确认两份 MP3 有效；未逐一合成全部音色。
- Windows 服务独占监听端口，避免重复服务响应旧版配置。升级时应关闭旧服务窗口，再重新运行 `run.cmd`。

音色专项浏览器检查可使用独立端口，避免干扰正在使用的工作台：

```powershell
# 先在另一窗口启动：python -m novel_audio web --port 8791 --no-browser
$env:NOVEL_AUDIO_TEST_URL = 'http://127.0.0.1:8791'
assets\.venv\Scripts\python.exe tests\browser_voices.py
```

新增截图：`qa/web/voices-desktop.png`、`qa/web/voices-mobile.png`；合成验证音频：`qa/more-voices`。
