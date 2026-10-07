"use strict";
/* Web/桌面 Today 迁移的新增视图与工具：记忆、我的、对话搜索。
   App 宿主（?host=mobile）由原生壳持有导航与搜索，本模块在其下不注册任何行为；
   life.js 仅在普通网页进入 memory/me 视图时调用 window.WearingViews.render。 */
(() => {
  if (document.documentElement.classList.contains("mobile-host")) return;
  const $ = id => document.getElementById(id);
  const esc = text => String(text ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const reduceMotion = () => matchMedia?.("(prefers-reduced-motion: reduce)").matches === true;
  let memoryEntries = [];

  // 今天入口的日历图标显示本地当日日期。
  const dayLabel = $("nav-today-day");
  if (dayLabel) dayLabel.textContent = String(new Date().getDate());

  $("nav-settings").addEventListener("click", () => showSettings());

  /* ---------- 记忆 ---------- */
  async function renderMemory(container) {
    const epoch = state.identityEpoch;
    const key = "memory:" + state.identityId;
    if (container.dataset.viewKey === key) return;
    container.innerHTML = '<p class="life-empty">正在找回记着的事情……</p>';
    let data = null, failure = false;
    try { data = await api("/api/memory"); }
    catch (error) { if (!(error instanceof StaleIdentity)) failure = true; }
    if (epoch !== state.identityEpoch) return;
    let workspace = null;
    try { workspace = await api("/api/workspace"); } catch { workspace = null; }
    if (epoch !== state.identityEpoch) return;
    const read = `读取于 ${new Date().toLocaleTimeString("zh-CN", {hour: "2-digit", minute: "2-digit"})}`;
    memoryEntries = [];
    // available=false 的身份没有 targets 字段；与聊天面板一致，按真实回执呈现而不是当作空列表。
    const unavailable = data && !data.available ? (data.message || "这个身份的记忆暂未开启。") : null;
    const groups = data?.available ? ["user", "memory"].map(target => {
      const group = data.targets[target];
      const title = target === "user" ? "关于你" : "一起积累的经验";
      const rows = (group?.entries || []).map(entry => {
        const index = memoryEntries.push(entry) - 1;
        return `<div class="memory-entry"><p>${esc(entry)}</p><button class="text-button" data-correct-memory="${index}">这条需要纠正</button></div>`;
      }).join("");
      const body = !group?.enabled ? '<p class="field-help">这部分记忆已关闭；原记录仍保留。</p>'
        : rows || '<p class="field-help">还没有记下内容。</p>';
      return `<section class="memory-card"><h2>${title}</h2><p class="memory-read">${read} · 当前身份</p>${body}</section>`;
    }).join("") : "";
    const intro = failure
      ? '<section class="memory-intro"><h2>记忆</h2><p>暂时读不到记忆，原记录仍保留；稍后再试一次。</p></section>'
      : unavailable
      ? `<section class="memory-intro"><h2>记忆</h2><p>${esc(unavailable)}</p></section>`
      : '<section class="memory-intro"><h2>记忆</h2><p>Wearing 为当前身份记下的偏好和经验。发现记错了，可以在对话里纠正。</p></section>';
    const files = workspace ? workspace.files.slice(0, 8).map(file =>
      `<a class="file-row" download href="/api/workspace/file?identity=${encodeURIComponent(state.identityId)}&path=${encodeURIComponent(file.path)}"><span>${esc(file.path)}</span><small>${file.size < 1024 ? file.size + " B" : (file.size / 1024).toFixed(1) + " KB"} · 下载</small></a>`).join("")
      : '<p class="field-help">文件目录暂时读不到。</p>';
    const fileNote = workspace?.truncated ? '<p class="field-help">目录内容较多，先显示部分文件。</p>'
      : workspace && !workspace.files.length ? '<p class="field-help">还没有文件。让 Wearing 帮你把一个想法写下来试试。</p>' : "";
    container.dataset.viewKey = key;
    container.innerHTML = `${intro}${groups}
      <section class="memory-files"><div class="life-section-heading"><h2>资料文件</h2><button class="text-button" data-open-files>查看全部文件</button></div>${files}${fileNote}
      <p class="field-help">工作区只读预览；完整目录在文件面板里。</p></section>`;
  }

  /* ---------- 我的：账户卡与真实连接状态 ---------- */
  async function renderMe(container) {
    const epoch = state.identityEpoch;
    const key = "me:" + state.identityId + ":" + state.connected;
    if (container.dataset.viewKey === key) return;
    const identity = state.identities.find(i => i.id === state.identityId);
    const space = state.deployment === "cloud" ? "云端实例 · 一直连接着" : "个人空间 · 这台电脑";
    let runtime = null;
    try { runtime = await api("/api/runtime"); } catch { runtime = null; }
    if (epoch !== state.identityEpoch) return;
    await loadComputer().catch(() => {});
    if (state.identityId === "daily") await loadPhone().catch(() => {});
    if (epoch !== state.identityEpoch) return;
    const computer = state.computer;
    const phones = typeof phoneState !== "undefined" ? phoneState?.resources : null;
    const cap = (title, icon, stateClass, text, action = "") =>
      `<section class="me-cap"><h3><svg viewBox="0 0 24 24" aria-hidden="true">${icon}</svg>${title}</h3><p><span class="cap-state ${stateClass}">${text}</span></p>${action}</section>`;
    const engineText = runtime?.error ? runtime.error
      : runtime?.phase === "running" ? "本地引擎运行中"
      : runtime?.phase === "starting" ? "本地引擎正在启动"
      : runtime?.installed ? "已安装，等待启动" : "尚未安装";
    const engineState = runtime?.phase === "running" ? "cap-ok" : runtime?.installed ? "cap-warn" : "cap-unknown";
    const modelText = runtime?.model?.state === "configured" ? "已配置，可在此对话" : runtime ? "待配置 API Key" : "状态未知";
    const filesText = runtime?.files?.active ? "已接通" : runtime?.files?.installed ? "已准备，待引擎启动" : runtime?.files?.error ? runtime.files.error : "未启用";
    const filesState = runtime?.files?.active ? "cap-ok" : "cap-unknown";
    const computerText = !computer ? "状态未知"
      : computer.connector?.enrolled ? (computer.control?.holder === "human" ? "已接入 · 你正在接管" : "已接入，可在对话里交代")
      : computer.ready ? "权限就绪，待接入" : computer.installed ? "驱动已装，等待系统授权" : "未接入";
    const computerState = computer?.connector?.enrolled ? "cap-ok" : computer ? "cap-warn" : "cap-unknown";
    const phoneText = !phones ? "未检查" : phones.length
      ? `已接入 ${phones.length} 部，${phones.filter(p => p.online).length} 部在线`
      : "尚未接入";
    const phoneStateClass = phones?.length ? "cap-ok" : "cap-unknown";
    container.dataset.viewKey = key;
    container.innerHTML = `
      <article class="me-card"><div class="me-card-backdrop" aria-hidden="true"></div>
        <div><h2>${esc(identity?.name || "日常")}</h2>
        <p class="me-space">${esc(identity?.description || "")}</p>
        <p class="me-line"><span class="connection-dot ${state.connected ? "online" : ""}" aria-hidden="true"></span>${esc($("connection-label").textContent || "连接 Wearing")}</p>
        <p class="me-space">${esc(space)}</p>
        <div class="me-actions"><button class="secondary" id="me-identities">切换身份</button><button class="secondary" id="me-settings">连接与设置</button></div>
        <div data-wardrobe-slot hidden></div></div>
      </article>
      <!-- ponytail: 衣橱（睡衣形象切换）入口预留位，品牌定稿后在此挂载；现在不渲染占位 UI。 -->
      <div class="me-grid">
        ${cap("本地引擎", '<rect x="4" y="7" width="16" height="12" rx="3"/><path d="M9 7V5h6v2"/>', engineState, esc(engineText), '<button class="text-button" data-me-open="settings">查看</button>')}
        ${cap("模型服务", '<path d="M12 3v18M3 12h18"/>', runtime?.model?.state === "configured" ? "cap-ok" : "cap-warn", modelText, '<button class="text-button" data-me-open="settings">配置</button>')}
        ${cap("这台电脑", '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M9 20h6m-3-4v4"/>', computerState, esc(computerText), '<button class="text-button" data-me-open="settings">查看</button>')}
        ${cap("手机", '<rect x="7" y="2.5" width="10" height="19" rx="3"/><path d="M11 18.5h2"/>', phoneStateClass, esc(phoneText), '<button class="text-button" data-me-open="settings">接入</button>')}
        ${cap("文件空间", '<path d="M3.5 8V6.5a2 2 0 0 1 2-2h4l2 3H19a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5.5a2 2 0 0 1-2-2V8Z"/>', filesState, esc(filesText), '<button class="text-button" data-me-open="settings">管理</button>')}
        ${cap("记忆", '<path d="M12 5a3.5 3.5 0 0 0-3.5 3.5c0 .6.15 1.16.4 1.65A3.5 3.5 0 0 0 5.5 13.5 3.5 3.5 0 0 0 9 17c.9 0 1.72-.34 2.34-.9L12 15.5l.66.6c.62.56 1.44.9 2.34.9a3.5 3.5 0 0 0 3.5-3.5 3.5 3.5 0 0 0-3.4-3.35c.25-.5.4-1.05.4-1.65A3.5 3.5 0 0 0 12 5Z"/>', "cap-ok", "为当前身份独立保存", '<button class="text-button" data-me-open="memory">查看记忆</button>')}
      </div>`;
    $("me-identities").addEventListener("click", showIdentities);
    $("me-settings").addEventListener("click", showSettings);
    container.querySelectorAll("[data-me-open]").forEach(button => button.addEventListener("click", () => {
      if (button.dataset.meOpen === "memory") window.WearingLife?.openView("memory");
      else showSettings();
    }));
  }

  let rendered = "";
  window.WearingViews = {
    render(view, container) {
      if (view !== rendered) { rendered = view; delete container.dataset.viewKey; }
      if (view === "memory") renderMemory(container);
      else if (view === "me") renderMe(container);
    },
    // 身份切换会清空 life-content，但不清理这里的跳过标记；不重置会在切回时卡在加载态。
    reset() { rendered = ""; },
  };
  $("life-content").addEventListener("click", event => {
    const correct = event.target.closest("[data-correct-memory]");
    if (correct) {
      const entry = memoryEntries[Number(correct.dataset.correctMemory)];
      if (entry === undefined) return;
      activateComposer({identity: state.identityId});
      window.WearingLife?.openView("chat");
      $("message-input").value = `这条记忆需要纠正：${entry}\n正确的是：`;
      $("message-input").dispatchEvent(new Event("input"));
      $("message-input").focus();
      return;
    }
    if (event.target.closest("[data-open-files]")) { openPanel("files-panel"); loadFiles().catch(() => {}); }
  });

  /* ---------- 对话搜索（当前会话内查找，不发送任何请求） ---------- */
  const panel = document.createElement("section");
  panel.className = "web-search";
  panel.hidden = true;
  panel.setAttribute("role", "search");
  panel.setAttribute("aria-label", "搜索当前对话");
  const input = document.createElement("input");
  input.type = "search"; input.placeholder = "搜索对话"; input.maxLength = 200;
  input.setAttribute("aria-label", "搜索对话内容"); input.autocomplete = "off";
  const count = document.createElement("span");
  count.setAttribute("role", "status"); count.setAttribute("aria-live", "polite");
  const makeButton = (label, handler) => {
    const button = document.createElement("button");
    button.type = "button"; button.textContent = label;
    button.addEventListener("click", handler);
    return button;
  };
  const previous = makeButton("上一处", () => navigate(-1));
  const next = makeButton("下一处", () => navigate(1));
  const done = makeButton("完成", () => closeSearch());
  panel.append(input, count, previous, next, done);
  document.body.append(panel);
  let matches = [], selected = -1, open = false;
  function clearMatches() {
    matches.forEach(node => node.classList.remove("web-search-match", "web-search-current"));
    matches = []; selected = -1;
  }
  function navigate(direction) {
    if (!matches.length) return;
    matches[selected]?.classList.remove("web-search-current");
    selected = (selected + direction + matches.length) % matches.length;
    const match = matches[selected];
    match.classList.add("web-search-current");
    match.scrollIntoView({block: "center", behavior: reduceMotion() ? "auto" : "smooth"});
    count.textContent = `${selected + 1} / ${matches.length}`;
  }
  function findMatches(scroll = true) {
    clearMatches();
    const query = input.value.trim().toLocaleLowerCase();
    if (query) {
      matches = [...$("messages").querySelectorAll(".user-bubble, .assistant-copy")]
        .filter(node => node.textContent.toLocaleLowerCase().includes(query));
      matches.forEach(node => node.classList.add("web-search-match"));
    }
    previous.disabled = next.disabled = !matches.length;
    count.textContent = query ? (matches.length ? `${matches.length} 处` : "没有找到") : "搜索当前对话";
    if (scroll && matches.length) { selected = 0; navigate(0); }
  }
  function openSearch() {
    open = true; panel.hidden = false; input.focus(); findMatches(false);
  }
  function closeSearch() {
    open = false; input.blur(); panel.hidden = true; clearMatches();
  }
  input.addEventListener("input", () => findMatches());
  input.addEventListener("keydown", event => {
    if (event.key === "Escape") closeSearch();
    if (event.key === "Enter") { event.preventDefault(); navigate(event.shiftKey ? -1 : 1); }
  });
  // 会话重绘会重建气泡节点，命中的高亮需要重算。
  new MutationObserver(() => { if (open) findMatches(false); }).observe($("messages"), {childList: true});
  $("open-search").addEventListener("click", () => {
    if (!state.messages.length) { notice("这段对话还没有内容。"); return; }
    openSearch();
  });
})();
