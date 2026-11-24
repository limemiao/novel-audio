"use strict";
const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const icon = (name) => `<svg class="icon" aria-hidden="true"><use href="#i-${name}"/></svg>`;
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const fmt = n => Number(n).toLocaleString("zh-CN");
const activeStatus = status => ["queued", "running", "cancelling"].includes(status);
const statusName = {queued:"排队中", running:"制作中", cancelling:"正在停止", completed:"已完成", cancelled:"已停止", failed:"未完成"};
const state = {books:[], series:[], config:null, book:null, selectedId:null, selected:new Set(), engine:"system", lastVoice:{}, page:1, pageSize:12, jobs:[], audio:[], view:"library", submitting:false, watched:new Map(), currentAudio:null, loadSequence:0, initialized:false};
let toastTimer;

async function api(path, options = {}) {
  const response = await fetch(path, {cache:"no-store", ...options});
  if (!response.ok) {
    let message = `请求失败（${response.status}）`;
    try { message = (await response.json()).error || message; } catch {}
    throw new Error(message);
  }
  return response.json();
}
function post(path, data) {
  return api(path, {method:"POST", headers:{"Content-Type":"application/json", "X-Novel-Audio":"local"}, body:JSON.stringify(data)});
}
function adaptVoiceConfig(config) {
  // Static files update immediately; a running older service may still return the old schema.
  return {...config, edge_voices:(config.edge_voices || []).map(v => ({...v, locale:v.locale || v.id.match(/^([a-z]{2,3}-[A-Z]{2}(?:-[a-z]+)?)-/)?.[1] || "und", gender:v.gender || (v.label.includes("男声") ? "Male" : "Female")}))};
}
function toast(message, error = false) {
  clearTimeout(toastTimer);
  const element = $("#toast");
  element.textContent = message;
  element.className = `toast${error ? " error" : ""}`;
  toastTimer = setTimeout(() => element.classList.add("hidden"), error ? 7500 : 4200);
}
function empty(title, text, symbol="book", action="") {
  return `<div class="empty-state">${icon(symbol)}<h3>${esc(title)}</h3><p>${esc(text)}</p>${action}</div>`;
}
function changeView(view) {
  state.view = view;
  ["library","tasks","audio"].forEach(key => $(`#${key}-view`).classList.toggle("hidden", key !== view));
  $$(".sidebar [data-view]").forEach(button => button.classList.toggle("active", button.dataset.view === view));
  $("#hero").classList.toggle("hidden", view !== "library");
  $("#page-label").textContent = {library:"小说书架", tasks:"制作任务", audio:"我的音频"}[view];
  window.scrollTo({top:0, behavior:"smooth"});
}
function updateLibrary(data) {
  state.books = data.books;
  state.series = data.series;
  $("#hero-books").textContent = fmt(data.books.length);
  $("#nav-books").textContent = fmt(data.books.length);
  $("#hero-series").textContent = fmt(data.series.length);
  $("#book-count").textContent = fmt(data.books.length);
  const current = $("#series-filter").value;
  $("#series-filter").innerHTML = '<option value="">全部系列</option>' + data.series.map(s => `<option value="${esc(s)}">${esc(s)}</option>`).join("");
  if (data.series.includes(current)) $("#series-filter").value = current;
  $("#library-short").textContent = data.library.split(/[\\/]/).slice(-2).join(" / ");
  $("#library-short").title = data.library;
  renderBooks();
}
function renderBooks() {
  const query = $("#search").value.trim().toLowerCase();
  const series = $("#series-filter").value;
  const matches = state.books.filter(book => (!series || book.series === series) && `${book.title} ${book.series}`.toLowerCase().includes(query));
  const pages = Math.max(1, Math.ceil(matches.length / state.pageSize));
  state.page = Math.min(state.page, pages);
  const visible = matches.slice((state.page - 1) * state.pageSize, state.page * state.pageSize);
  $("#shelf-description").textContent = query || series ? `找到 ${fmt(matches.length)} 本小说` : "一些好故事，等一个好声音";
  $("#book-grid").innerHTML = visible.length ? visible.map(book => `<button class="book-card${book.id === state.selectedId ? " active" : ""}" data-book="${book.id}" aria-label="选择 ${esc(book.title)}" aria-pressed="${book.id === state.selectedId}"><div class="book-cover"><img src="${book.cover}" alt="${esc(book.title)}封面" loading="lazy" decoding="async"><span class="cover-format">${esc(book.format)}</span><span class="cover-selected">${icon("check")}</span></div><div><h3 title="${esc(book.title)}">${esc(book.title)}</h3><span class="series-label">${esc(book.series)}</span></div></button>`).join("") : empty("书架上暂时没有这本书", query || series ? "换个关键词，或看看其他系列。" : "点击右上角「导入小说」，添加你的第一本 EPUB / TXT。");
  $("#page-summary").textContent = matches.length ? `第 ${(state.page - 1) * state.pageSize + 1}–${Math.min(state.page * state.pageSize, matches.length)} 本 / 共 ${fmt(matches.length)} 本` : "暂无小说";
  $("#page-number").textContent = `${state.page} / ${pages}`;
  $("#prev-page").disabled = state.page <= 1;
  $("#next-page").disabled = state.page >= pages;
}
async function selectBook(id, focusStudio = false) {
  const sequence = ++state.loadSequence;
  state.selectedId = id;
  state.book = null;
  state.selected.clear();
  renderBooks();
  const basic = state.books.find(book => book.id === id);
  $("#selected-book").innerHTML = `<img src="/api/books/${id}/cover" alt="小说封面"><div><span class="field-eyebrow">当前选择</span><h3>${esc(basic?.title || "正在打开小说")}</h3><p>正在读取章节…</p></div>`;
  $("#chapter-list").innerHTML = '<div class="loading-state"><span class="spinner"></span>正在打开章节</div>';
  updateSelection();
  try {
    const book = await api(`/api/books/${id}`);
    if (sequence !== state.loadSequence) return;
    state.book = book;
    if (book.chapters.length) state.selected.add(0);
    $("#selected-book h3").textContent = book.title;
    $("#selected-book p").textContent = `${book.chapters.length} 个章节 · ${(book.characters / 10000).toFixed(1)} 万字符`;
    renderChapters();
    try { localStorage.setItem("novel-audio-book", id); } catch {}
  } catch (error) {
    if (sequence !== state.loadSequence) return;
    $("#selected-book p").textContent = "这本书暂时无法朗读";
    $("#chapter-list").innerHTML = `<div class="chapter-empty">${esc(error.message)}</div>`;
    toast(error.message, true);
  }
  updateSelection();
  if (focusStudio && window.innerWidth <= 780) $(".workbench").scrollIntoView({behavior:"smooth", block:"start"});
}
function renderChapters() {
  if (!state.book) return;
  $("#chapter-list").innerHTML = state.book.chapters.map(chapter => `<div class="chapter-row"><label><input type="checkbox" data-chapter="${chapter.index}" ${state.selected.has(chapter.index) ? "checked" : ""} aria-label="选择章节 ${esc(chapter.title)}"><span class="chapter-index">${String(chapter.index + 1).padStart(2,"0")}</span><span title="${esc(chapter.title)}">${esc(chapter.title)}</span></label><button data-read="${chapter.index}" aria-label="预览 ${esc(chapter.title)}">预览</button></div>`).join("");
}
function updateSelection() {
  const selected = state.book?.chapters.filter(chapter => state.selected.has(chapter.index)) || [];
  $("#selection-count").textContent = selected.length ? `${selected.length} / ${state.book.chapters.length}` : "0";
  $("#selected-characters").textContent = selected.length ? `已选 ${selected.length} 章 · ${fmt(selected.reduce((sum, c) => sum + c.characters, 0))} 字符` : "尚未选择章节";
  $("#select-all").textContent = state.book && selected.length === state.book.chapters.length ? "取消全选" : "全选";
  const valid = selected.length > 0 && !state.submitting && $("#voice").value && (state.engine !== "edge" || state.config?.edge_available);
  $("#preview-button").disabled = !valid;
  $("#generate-button").disabled = !valid;
}
function selectEngine(engine) {
  const previousVoices = state.engine === "edge" ? state.config?.edge_voices : state.config?.system_voices;
  if (previousVoices?.some(v => v.id === $("#voice").value)) state.lastVoice[state.engine] = $("#voice").value;
  state.engine = engine;
  $$("[data-engine]").forEach(button => button.classList.toggle("active", button.dataset.engine === engine));
  const online = engine === "edge";
  const voices = online ? state.config?.edge_voices || [] : state.config?.system_voices || [];
  $("#voice-filters").classList.toggle("hidden", !online);
  $("#engine-state").textContent = online ? "在线合成" : "本地合成";
  $("#engine-note").textContent = online ? state.config?.edge_available ? "需要联网，待朗读文字会发送到微软语音服务。" : "请运行 install-online.cmd 安装在线语音，随后重启服务。" : voices.length ? "使用本机语音，文字留在你的电脑。" : "未找到系统语音，请安装 Windows 中文语音包。";
  $("#engine-note").classList.toggle("online", online);
  if (online && state.config && !state.config.voice_catalog) $("#engine-note").textContent = "服务仍是旧版。关闭启动窗口，重新运行 run.cmd 后可选择完整音色；在线语音会发送文字到微软服务。";
  $("#refresh-voices").disabled = !state.config?.voice_catalog;
  renderVoices();
}
const localeLabels = {"zh-CN":"普通话 · 中国大陆", "zh-HK":"粤语 · 香港", "zh-TW":"国语 · 台湾", "zh-CN-liaoning":"中文 · 辽宁", "zh-CN-shaanxi":"中文 · 陕西"};
const languageNames = new Intl.DisplayNames(["zh-CN"], {type:"language"});
function localeLabel(locale) {
  if (localeLabels[locale]) return localeLabels[locale];
  try { return languageNames.of(locale) || locale; } catch { return locale; }
}
function populateVoiceFilters() {
  const current = $("#voice-locale").value || "zh";
  const locales = [...new Set((state.config?.edge_voices || []).map(v => v.locale))].sort((a, b) => Number(!a.startsWith("zh-")) - Number(!b.startsWith("zh-")) || localeLabel(a).localeCompare(localeLabel(b), "zh-CN"));
  $("#voice-locale").innerHTML = '<option value="zh">中文 · 全部地区</option><option value="all">全部语言</option>' + locales.map(locale => `<option value="${esc(locale)}">${esc(localeLabel(locale))}</option>`).join("");
  $("#voice-locale").value = ["zh", "all", ...locales].includes(current) ? current : "zh";
}
function renderVoices() {
  const online = state.engine === "edge";
  const all = online ? state.config?.edge_voices || [] : state.config?.system_voices || [];
  const locale = $("#voice-locale").value;
  const gender = $("#voice-gender").value;
  const query = $("#voice-search").value.trim().toLowerCase();
  const voices = online ? all.filter(v => (locale === "all" || (locale === "zh" ? v.locale.startsWith("zh-") : v.locale === locale)) && (gender === "all" || v.gender === gender) && `${v.id} ${v.label} ${localeLabel(v.locale)}`.toLowerCase().includes(query)) : all;
  const preferred = state.lastVoice[state.engine] || (online ? "zh-CN-XiaoxiaoNeural" : state.config?.default_voice);
  $("#voice").innerHTML = voices.length ? voices.map(v => `<option value="${esc(v.id)}">${esc(v.label)}</option>`).join("") : '<option value="">没有匹配的音色，请调整筛选</option>';
  if (voices.some(v => v.id === preferred)) $("#voice").value = preferred;
  $("#voice").disabled = !voices.length;
  $("#voice-count").textContent = `${voices.length} 个匹配 / 共 ${all.length} 个音色`;
  const catalog = state.config?.voice_catalog;
  $("#voice-count").title = catalog ? `${catalog.source === "live" ? "已联网更新" : catalog.source === "cache" ? "上次更新目录" : "内置音色目录"} · ${catalog.updated_at.slice(0,10)}` : "";
  updateSelection();
}
async function readChapter(index) {
  if (!state.selectedId) return;
  $("#reader-title").textContent = "正在读取章节…";
  $("#reader-text").textContent = "";
  $("#reader-dialog").showModal();
  try {
    const chapter = await api(`/api/books/${state.selectedId}/chapters/${index}`);
    $("#reader-title").textContent = chapter.title;
    $("#reader-text").textContent = chapter.text + (chapter.truncated ? "\n\n……仅预览前 20,000 字符，制作时使用完整正文。" : "");
  } catch (error) { $("#reader-text").textContent = error.message; }
}
async function submit(preview, retryData = null) {
  if (!retryData && (!state.book || !state.selected.size || state.submitting)) return;
  state.submitting = true;
  updateSelection();
  try {
    const data = retryData || {book_id:state.selectedId, chapters:[...state.selected].sort((a,b) => a-b), engine:state.engine, voice:$("#voice").value, rate:Number($("#rate").value), preview};
    const job = await post("/api/jobs", data);
    state.watched.set(job.id, job.preview);
    toast(job.preview ? "正在准备试听，完成后会出现在底部播放器。" : "已加入制作队列，随时可以在「制作任务」查看进度。");
    await poll();
  } catch (error) { toast(error.message, true); }
  finally { state.submitting = false; updateSelection(); }
}
function jobProgress(job) {
  return job.status === "completed" ? 100 : job.total ? Math.min(99, Math.round(job.done / job.total * 100)) : 0;
}
function renderJobs() {
  const active = state.jobs.filter(job => activeStatus(job.status));
  $("#nav-jobs").textContent = active.length;
  $("#task-count").textContent = state.jobs.length;
  $("#tasks-list").innerHTML = state.jobs.length ? state.jobs.map(job => `<article class="task-card"><div class="task-symbol">${icon(job.preview ? "headphones" : "wave")}</div><div class="task-body"><div class="task-top"><h3>${esc(job.title)}</h3><span class="status-pill ${job.status}">${statusName[job.status] || job.status}</span></div><p class="task-meta">${job.preview ? "180 字试听" : `${job.chapters.length} 个章节`} · ${job.engine === "edge" ? "自然语音" : "离线语音"} · ${esc(job.voice.replace("Microsoft ", "").replace(" Desktop - Chinese (Simplified)", ""))} · ${new Date(job.created * 1000).toLocaleString("zh-CN", {month:"2-digit", day:"2-digit", hour:"2-digit", minute:"2-digit"})}</p><div class="progress-track" role="progressbar" aria-label="转换进度" aria-valuenow="${jobProgress(job)}" aria-valuemin="0" aria-valuemax="100"><div class="progress-fill" style="width:${jobProgress(job)}%"></div></div><div class="task-message">${esc(job.message)}</div><div class="task-actions">${activeStatus(job.status) ? `<button class="button quiet compact" data-cancel="${job.id}" ${job.status === "cancelling" ? "disabled" : ""}>${job.status === "queued" ? "取消排队" : "停止并保留进度"}</button>` : ""}${["failed","cancelled"].includes(job.status) ? `<button class="button secondary compact" data-retry="${job.id}">${icon("refresh")}继续制作</button>` : ""}${job.outputs.length ? `<button class="button secondary compact" data-audio="${job.outputs[0]}">${icon("play")}播放${job.preview ? "试听" : "首章"}</button><button class="text-button" data-view="audio">查看音频</button>` : ""}</div></div></article>`).join("") : empty("好故事，值得一个好声音", "挑选小说和朗读声音，开始你的第一段有声旅程。", "wave", '<button class="button primary compact" data-view="library">从书架开始</button>');
  const current = active[0] || state.jobs.find(job => state.watched.has(job.id));
  const inline = $("#inline-job");
  inline.classList.toggle("hidden", !current);
  if (current) inline.innerHTML = `<p>${current.preview ? "试听" : "制作"} · ${esc(current.message)}</p><div class="progress-track"><div class="progress-fill" style="width:${jobProgress(current)}%"></div></div><button class="text-button" data-view="tasks">查看任务 ${icon("arrow")}</button>`;
}
function renderAudio() {
  $("#nav-audio").textContent = state.audio.length;
  $("#audio-count").textContent = state.audio.length;
  const filter = $("#audio-filter").value;
  const files = state.audio.filter(file => filter === "all" || file.kind === filter);
  $("#audio-list").innerHTML = files.length ? files.map(file => `<article class="audio-item"><button class="audio-play" data-audio="${file.id}" aria-label="播放 ${esc(file.title)}">${icon("play")}</button><div><h3>${esc(file.title.replace(/^\d+-/, ""))}</h3><p>${esc(file.book)}</p></div><span class="status-pill">${file.kind === "preview" ? "试听" : "章节"}</span><span class="audio-size">${(file.size / 1024 / 1024).toFixed(1)} MB</span><a class="icon-button" href="${file.url}?download=1" title="下载 MP3" aria-label="下载 ${esc(file.title)}">${icon("download")}</a></article>`).join("") : empty("这里，将收藏你的有声故事", "完成制作后，章节和试听都会自动出现在这里。", "headphones", '<button class="button primary compact" data-view="library">去制作第一本</button>');
}
let polling = false;
async function poll() {
  if (polling) return;
  polling = true;
  try {
    const [jobs, files] = await Promise.all([api("/api/jobs"), api("/api/audio")]);
    const jobsChanged = JSON.stringify(jobs) !== JSON.stringify(state.jobs);
    const audioChanged = JSON.stringify(files) !== JSON.stringify(state.audio);
    state.jobs = jobs;
    state.audio = files;
    if (jobsChanged || !state.initialized) renderJobs();
    if (audioChanged || !state.initialized) renderAudio();
    state.initialized = true;
    $("#connection-label").textContent = "本地服务已连接";
    for (const job of jobs) {
      if (!state.watched.has(job.id) || activeStatus(job.status)) continue;
      if (job.status === "completed") {
        if (state.watched.get(job.id) && job.outputs.length) {
          await playAudio(job.outputs[0]);
        } else toast(`制作完成：${job.outputs.length} 个章节已保存。`);
      } else if (job.status === "failed") toast(job.message, true);
      state.watched.delete(job.id);
    }
  } catch (error) { $("#connection-label").textContent = "连接中断，请检查本地服务"; }
  finally { polling = false; }
}
async function playAudio(id) {
  let file = state.audio.find(item => item.id === id);
  if (!file) {
    try { state.audio = await api("/api/audio"); renderAudio(); file = state.audio.find(item => item.id === id); }
    catch (error) { toast(error.message, true); return; }
  }
  if (!file) { toast("这段音频已被移动或删除。", true); return; }
  state.currentAudio = file;
  $("#player-title").textContent = file.title.replace(/^\d+-/, "");
  $("#player-subtitle").textContent = file.book;
  $("#player-download").href = `${file.url}?download=1`;
  $("#player-download").classList.remove("disabled");
  $("#play-button").disabled = false;
  const audio = $("#audio");
  if (audio.getAttribute("src") !== file.url) {
    audio.src = file.url;
    audio.playbackRate = Number($("#playback-rate").value);
  }
  try { await audio.play(); }
  catch { toast("音频已就绪，点击底部播放按钮开始收听。"); }
}
function clock(seconds) {
  if (!Number.isFinite(seconds)) return "0:00";
  return `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2,"0")}`;
}
async function upload(file) {
  if (!file) return;
  if (file.size > 64 * 1024 * 1024) { toast("文件超过 64 MB，请先拆分。", true); return; }
  const button = $("#import-button");
  button.disabled = true;
  try {
    toast("正在导入并解析小说…");
    const result = await api("/api/import", {method:"POST", headers:{"Content-Type":"application/octet-stream", "X-Novel-Audio":"local", "X-Filename":encodeURIComponent(file.name)}, body:file});
    updateLibrary(await api("/api/library"));
    $("#search").value = "";
    $("#series-filter").value = "我的导入";
    state.page = 1;
    renderBooks();
    changeView("library");
    await selectBook(result.id);
    toast("小说已导入，原始文件保持不变。");
  } catch (error) { toast(error.message, true); }
  finally { button.disabled = false; $("#file-input").value = ""; }
}

document.addEventListener("click", async event => {
  const view = event.target.closest("[data-view]");
  if (view) { changeView(view.dataset.view); return; }
  const book = event.target.closest("[data-book]");
  if (book) { await selectBook(book.dataset.book, true); return; }
  const reader = event.target.closest("[data-read]");
  if (reader) { await readChapter(Number(reader.dataset.read)); return; }
  const engine = event.target.closest("[data-engine]");
  if (engine) { selectEngine(engine.dataset.engine); return; }
  const cancel = event.target.closest("[data-cancel]");
  if (cancel) {
    cancel.disabled = true;
    try { await post(`/api/jobs/${cancel.dataset.cancel}/cancel`, {}); await poll(); }
    catch (error) { toast(error.message, true); cancel.disabled = false; }
    return;
  }
  const retry = event.target.closest("[data-retry]");
  if (retry) {
    const job = state.jobs.find(j => j.id === retry.dataset.retry);
    if (job) await submit(job.preview, {book_id:job.book_id, chapters:job.chapters, engine:job.engine, voice:job.voice, rate:job.rate, preview:job.preview});
    return;
  }
  const play = event.target.closest("[data-audio]");
  if (play) await playAudio(play.dataset.audio);
  if (event.target.closest(".dialog-close")) event.target.closest("dialog").close();
});
$("#chapter-list").addEventListener("change", event => {
  const input = event.target.closest("[data-chapter]");
  if (!input) return;
  const index = Number(input.dataset.chapter);
  if (input.checked) state.selected.add(index); else state.selected.delete(index);
  updateSelection();
});
$("#select-all").addEventListener("click", () => {
  if (!state.book) return;
  if (state.selected.size === state.book.chapters.length) state.selected.clear();
  else state.selected = new Set(state.book.chapters.map(c => c.index));
  renderChapters(); updateSelection();
});
$("#search").addEventListener("input", () => { state.page = 1; renderBooks(); });
$("#series-filter").addEventListener("change", () => { state.page = 1; renderBooks(); });
$("#prev-page").addEventListener("click", () => { state.page--; renderBooks(); });
$("#next-page").addEventListener("click", () => { state.page++; renderBooks(); });
$("#grid-view").addEventListener("click", () => { $("#book-grid").classList.remove("list-mode"); $("#grid-view").classList.add("selected"); $("#list-view").classList.remove("selected"); });
$("#list-view").addEventListener("click", () => { $("#book-grid").classList.add("list-mode"); $("#list-view").classList.add("selected"); $("#grid-view").classList.remove("selected"); });
$("#rate").addEventListener("input", () => { const rate = Number($("#rate").value); $("#rate-label").textContent = `${rate === 0 ? "标准" : rate < 0 ? "舒缓" : "轻快"} · ${rate > 0 ? "+" : ""}${rate}%`; });
$("#voice").addEventListener("change", () => { state.lastVoice[state.engine] = $("#voice").value; updateSelection(); });
$("#voice-locale").addEventListener("change", renderVoices);
$("#voice-gender").addEventListener("change", renderVoices);
$("#voice-search").addEventListener("input", renderVoices);
$("#refresh-voices").addEventListener("click", async () => {
  const button = $("#refresh-voices");
  button.disabled = true;
  button.textContent = "正在刷新…";
  try {
    state.config = adaptVoiceConfig(await post("/api/voices/refresh", {}));
    populateVoiceFilters();
    renderVoices();
    toast(`音色目录已更新，共 ${state.config.edge_voices.length} 个音色。`);
  } catch (error) { toast(error.message, true); }
  finally { button.disabled = false; button.innerHTML = `刷新音色${icon("refresh")}`; }
});
$("#preview-button").addEventListener("click", () => submit(true));
$("#generate-button").addEventListener("click", () => submit(false));
$("#audio-filter").addEventListener("change", renderAudio);
$("#import-button").addEventListener("click", () => $("#file-input").click());
$("#file-input").addEventListener("change", event => upload(event.target.files[0]));
$("#settings-button").addEventListener("click", () => $("#settings-dialog").showModal());
$("#settings-top").addEventListener("click", () => $("#settings-dialog").showModal());
$("#refresh-button").addEventListener("click", async () => {
  $("#refresh-button").disabled = true;
  try { updateLibrary(await post("/api/library/refresh", {})); toast("书库已刷新。"); }
  catch (error) { toast(error.message, true); }
  finally { $("#refresh-button").disabled = false; }
});
const audio = $("#audio");
audio.volume = 0.8;
$("#play-button").addEventListener("click", () => { if (!audio.paused) audio.pause(); else audio.play().catch(() => toast("无法播放，请检查音频文件。", true)); });
for (const name of ["play","pause","ended"]) audio.addEventListener(name, () => { $("#play-button").innerHTML = icon(audio.paused ? "play" : "pause"); $("#play-button").setAttribute("aria-label", audio.paused ? "播放" : "暂停"); });
for (const name of ["timeupdate","loadedmetadata","durationchange"]) audio.addEventListener(name, () => {
  $("#current-time").textContent = clock(audio.currentTime);
  $("#duration").textContent = clock(audio.duration);
  $("#seek").disabled = !Number.isFinite(audio.duration);
  $("#seek").value = Number.isFinite(audio.duration) && audio.duration > 0 ? audio.currentTime / audio.duration * 1000 : 0;
});
audio.addEventListener("error", () => { if (audio.src) toast("音频加载失败，文件可能已被移动。", true); });
$("#seek").addEventListener("input", event => { if (Number.isFinite(audio.duration)) audio.currentTime = Number(event.target.value) / 1000 * audio.duration; });
$("#volume").addEventListener("input", event => { audio.volume = Number(event.target.value); });
$("#playback-rate").addEventListener("change", event => { audio.playbackRate = Number(event.target.value); });

async function initialize() {
  try {
    const [config, library] = await Promise.all([api("/api/config"), api("/api/library")]);
    state.config = adaptVoiceConfig(config);
    populateVoiceFilters();
    $("#settings-library").textContent = config.library;
    $("#settings-output").textContent = config.output;
    updateLibrary(library);
    selectEngine("system");
    let last;
    try { last = localStorage.getItem("novel-audio-book"); } catch {}
    const initial = state.books.find(book => book.id === last) || state.books[0];
    if (initial) await selectBook(initial.id);
    await poll();
  } catch (error) {
    $("#book-grid").innerHTML = empty("书库暂时没有连接", error.message, "folder", '<button class="button secondary compact" id="retry-connect">重新连接</button>');
    $("#retry-connect")?.addEventListener("click", initialize);
    toast(error.message, true);
  }
}
initialize();
setInterval(poll, 2000);
