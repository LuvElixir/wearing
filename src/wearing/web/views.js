"use strict";
/* Pajio Web/桌面视图：今天（真实任务进展）、任务（limit/cursor 分页）、我的（账户与外观个性化）。
   App 宿主（?host=mobile）由原生壳持有这些页面，本模块在其下不注册任何行为；
   life.js 仅在普通网页进入 today/tasks/memory/me 视图时调用 window.WearingViews。 */
(() => {
  if (document.documentElement.classList.contains("mobile-host")) return;
  const $ = id => document.getElementById(id);
  const esc = text => String(text ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const reduceMotion = () => matchMedia?.("(prefers-reduced-motion: reduce)").matches === true;
  const clock = value => new Date(value).toLocaleTimeString("zh-CN", {hour: "2-digit", minute: "2-digit"});
  let memoryEntries = [];
  const memoryRevisions = {};
  const memorySettings = {};

  // 今天入口的日历图标显示本地当日日期。
  const dayLabel = $("nav-today-day");
  if (dayLabel) dayLabel.textContent = String(new Date().getDate());
  $("nav-settings").addEventListener("click", () => showSettings());

  /* ---------- 活动条目的状态语义 ---------- */
  const tone = item => item.bucket === "attention" ? "attention"
    : item.bucket === "active" ? "active"
    : item.bucket === "waiting" ? "muted"
    : ["failed", "unknown"].includes(item.status) ? "danger"
    : ["stopped", "closed_by_user", "closed"].includes(item.status) ? "muted" : "success";
  const historyKind = item => ["failed", "stopped", "closed", "closed_by_user", "unknown"].includes(item.status);
  function activityRow(item) {
    const activeTone = ["starting", "running", "waiting_for_approval"].includes(item.status);
    const cancellable = item.queued && item.queue_state !== "cancelled";
    return `<button class="pj-card" data-activity-task="${esc(item.task_id)}" type="button">
      <div><span class="pj-status" data-tone="${tone(item)}">${esc(item.label)}${item.unread ? " · 未读" : ""}</span><strong>${esc(item.title)}</strong>${item.summary && item.bucket !== "active" && item.bucket !== "waiting" ? `<small>${esc(item.summary)}</small>` : ""}</div>
      ${activeTone || cancellable ? `<span class="brief-actions"><button class="text-button" type="button" data-task-stop="${esc(item.task_id)}">停止</button>${cancellable ? `<button class="text-button" type="button" data-task-cancel="${esc(item.task_id)}">撤回</button>` : ""}</span>` : ""}
      <svg viewBox="0 0 24 24" aria-hidden="true" class="chev"><path d="m9 6 6 6-6 6"/></svg></button>`;
  }
  const limited = (shown, total) => total > shown ? `<p class="pj-note">当前显示 ${shown} 项，共 ${total} 项；点任务页可以看完整列表。</p>` : "";

  async function fetchActivity(query) {
    const search = new URLSearchParams(query);
    return api("/api/activity" + (search.size ? "?" + search : {}));
  }

  /* ---------- 今天：真实任务、返回结果与需介入，不伪造简报 ---------- */
  async function renderToday(container) {
    const epoch = state.identityEpoch;
    const key = "today:" + state.identityId;
    if (container.dataset.viewKey === key) return;
    container.innerHTML = '<p class="life-empty">正在读取今天的进展……</p>';
    const [activity, life] = await Promise.all([
      fetchActivity({limit: 20}).catch(() => null),
      api("/api/life?include_deleted=true").catch(() => null),
    ]);
    if (epoch !== state.identityEpoch) return;
    container.dataset.viewKey = key;
    const date = new Date().toLocaleDateString("zh-CN", {month: "long", day: "numeric", weekday: "long"});
    if (!activity && !life) {
      container.innerHTML = `<p class="pj-meta">${date}</p><p class="life-empty">暂时读不到今天的进展，稍后再试一次。</p>`;
      return;
    }
    const items = [...(activity?.items || [])].sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at));
    const attention = items.filter(i => i.bucket === "attention");
    const delivered = items.filter(i => i.bucket === "results").slice(0, 3);
    const active = items.filter(i => i.bucket === "active").slice(0, 3);
    const waiting = items.filter(i => i.bucket === "waiting").slice(0, 3);
    const history = items.filter(historyKind).slice(0, 3);
    const today = new Date(); const pad = n => String(n).padStart(2, "0");
    const localDay = `${today.getFullYear()}-${pad(today.getMonth() + 1)}-${pad(today.getDate())}`;
    const dayStart = new Date(localDay + "T00:00"); const dayEnd = new Date(dayStart); dayEnd.setDate(dayEnd.getDate() + 1);
    const events = (life?.items || []).filter(i => i.kind === "event" && !i.deleted_at && (i.all_day ? i.start_at <= localDay && i.end_at > localDay : new Date(i.start_at) < dayEnd && new Date(i.end_at) > dayStart)).sort((a, b) => a.start_at.localeCompare(b.start_at));
    const openTasks = (life?.items || []).filter(i => i.kind === "task" && !i.completed && !i.deleted_at);
    const meta = activity ? `任务进展读取于 ${clock(activity.checked_at)}` : "任务进展暂未读取";
    const section = (title, count, body) => body ? `<section class="pj-section"><p class="pj-section-title">${title}${count != null ? ` <span class="pj-count">· ${count}</span>` : ""}</p>${body}</section>` : "";
    container.innerHTML = `
      <p class="pj-meta">${date} · ${meta}<button class="pj-refresh" data-today-refresh type="button" aria-label="更新今日概览">↻</button></p>
      ${section("等你处理", activity?.counts.attention || 0, attention.map(item => `
        <button class="pj-card" data-activity-task="${esc(item.task_id)}" type="button"><div><span class="pj-status" data-tone="attention">${esc(item.label)}</span><strong>${esc(item.title)}</strong>${item.summary ? `<small>${esc(item.summary)}</small>` : ""}</div>
        <svg viewBox="0 0 24 24" aria-hidden="true" class="chev"><path d="M7 17 17 7M9 7h8v8"/></svg></button>`).join("") + limited(attention.length, activity?.counts.attention || 0)) || (activity ? '<p class="pj-note">目前没有需要你处理的步骤。</p>' : "")}
      ${section("最近返回的内容", null, delivered.map(activityRow).join(""))}
      ${section("正在推进", activity?.counts.active || 0, active.map(activityRow).join("") + limited(active.length, activity?.counts.active || 0))}
      ${section("已排队", activity?.counts.waiting || 0, waiting.map(activityRow).join("") + limited(waiting.length, activity?.counts.waiting || 0))}
      ${section("历史记录", null, history.map(activityRow).join(""))}
      ${activity?.has_more ? '<p class="pj-note">任务进展仅包含最近读取到的部分记录。</p>' : ""}
      <section class="pj-section"><p class="pj-section-title">今日安排</p>
        ${events.length ? events.map(item => `<button class="pj-card" data-life-open="${esc(item.id)}" type="button"><div><strong>${esc(item.title)}</strong><small>${item.all_day ? "全天" : clock(item.start_at) + " – " + clock(item.end_at)}</small></div></button>`).join("") : '<p class="pj-note">目前没有已同步的今日日程。</p>'}
        <p class="pj-note">来自本机已同步记录 · ${events.length} 项日程 · ${openTasks.length} 件未完成待办${!state.connected ? " · 当前连接不可用" : ""}</p></section>
      <button class="pj-card" data-briefing-open type="button"><div><strong>今日图文简报</strong><small>基于已连接的真实来源整理，每一版都留在这里，可回看与打开图文。</small></div>
      <svg viewBox="0 0 24 24" aria-hidden="true" class="chev"><path d="M7 17 17 7M9 7h8v8"/></svg></button>
      <button class="pj-card" data-quick-capture type="button"><div><strong>补记一条记录</strong><small>随手记下念头、待办或日程，可以带上图片与录音。</small></div>
      <svg viewBox="0 0 24 24" aria-hidden="true" class="chev"><path d="M12 5v14M5 12h14"/></svg></button>`;
  }

  const briefingDraft = "请根据我已连接且有权限访问的信息，整理今天的图文简报：接下来的安排、需要我决定的事、最新进展。区分事实和建议，附来源与更新时间；没有数据的部分请直说。";

  /* ---------- 任务：真实分页（limit/cursor，409 保留当前内容） ---------- */
  /** 纯函数：把下一页并入当前快照；跨页去重，总数与已载分开。 */
  function appendActivityPage(base, next) {
    const seen = new Set(base.items.map(item => item.task_id));
    return {...base, items: [...base.items, ...next.items.filter(item => !seen.has(item.task_id))],
      checked_at: next.checked_at, total: next.total, counts: next.counts, unread: next.unread,
      filtered_total: next.filtered_total ?? next.total, next_cursor: next.next_cursor ?? null, has_more: next.has_more};
  }
  async function renderTasks(container) {
    if (!container) return;
    const epoch = state.identityEpoch;
    let snapshot = null, expired = false, error = "", busy = false;
    const render = () => {
      const frozenNote = expired ? "。正在查看历史记录，点刷新可查看最新进展。" : "";
      container.innerHTML = `
        <p class="pj-section-title">交给 Pajio 的事<button class="pj-refresh" data-tasks-refresh type="button" aria-label="刷新任务"${busy ? " disabled" : ""}>${busy ? "…" : "↻"}</button></p>
        ${error ? `<p class="pj-note" role="status">${esc(error)}</p>` : ""}
        ${!snapshot && !error ? '<p class="life-empty">正在找回你的任务…</p>' : ""}
        ${snapshot?.total === 0 ? '<p class="life-empty">交代过的事，都会留在这里。处理到哪一步、有什么结果，回来就能看到。</p>' : ""}
        ${snapshot && snapshot.total > 0 ? Object.entries({attention: "等你处理", active: "正在推进", waiting: "已排队", results: "已有结果"}).map(([bucket, title]) => {
          const items = snapshot.items.filter(item => item.bucket === bucket);
          return items.length ? `<section class="pj-section"><p class="pj-section-title">${title} <span class="pj-count">· ${snapshot.counts[bucket] ?? items.length}</span></p>${items.map(activityRow).join("")}${limited(items.length, snapshot.counts[bucket] ?? items.length)}</section>` : "";
        }).join("") : ""}
        ${snapshot ? `<p class="pj-note">已显示 ${snapshot.items.length} / ${snapshot.filtered_total ?? snapshot.total} 项 · 读取于 ${clock(snapshot.checked_at)}${frozenNote}</p>` : ""}
        ${snapshot?.next_cursor ? `<button class="pj-load-more" data-tasks-more type="button"${busy ? " disabled" : ""}>${busy ? "正在读取…" : expired ? "刷新任务" : "加载更多任务"}</button>` : snapshot?.has_more ? '<p class="pj-note">当前服务仅提供最近任务，完整过程保留在对话中。</p>' : ""}
        <button class="pj-load-more" data-open-keeps-entry type="button">持续推进的事 · 目标与定时</button>`;
    };
    const load = async () => {
      busy = true; error = ""; render();
      try { snapshot = await fetchActivity({limit: 20}); expired = false; }
      catch (cause) { if (!(cause instanceof StaleIdentity)) error = "暂时读不到任务，请检查连接后重试。"; }
      finally { if (epoch === state.identityEpoch) { busy = false; render(); } }
    };
    const loadMore = async () => {
      if (!snapshot?.next_cursor || busy) return;
      busy = true; render();
      // 冻结当前快照作为游标基线；共享轮询不会把新首页拼进历史页。
      const base = snapshot;
      try {
        const next = await fetchActivity({limit: 20, cursor: base.next_cursor});
        snapshot = appendActivityPage(base, next); expired = false;
      } catch (cause) {
        if (cause instanceof StaleIdentity) return;
        expired = cause?.status === 409;
        error = expired ? "列表已有变化，点刷新后继续查看。当前内容仍会保留。" : "暂时没有读到更多任务，可以重试。";
      } finally { if (epoch === state.identityEpoch) { busy = false; render(); } }
    };
    container.addEventListener("click", event => {
      if (event.target.closest("[data-tasks-refresh]")) { expired = false; void load(); }
      else if (event.target.closest("[data-tasks-more]")) { void (expired ? load() : loadMore()); }
    });
    await load();
  }

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
    const read = `读取于 ${clock(new Date().toISOString())}`;
    for (const target of ["user", "memory"]) {
      memoryRevisions[target] = data?.targets?.[target]?.revision || null;
      memorySettings[target] = data?.targets?.[target]?.settings_revision || null;
    }
    memoryEntries = [];
    // available=false 的身份没有 targets 字段；按真实回执呈现而不是当作空列表。
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
      const editable = typeof group?.revision === "string";
      const entriesCount = (group?.entries || []).length;
      const tools = editable ? `<div class="memory-tools"><button class="text-button" type="button" data-memory-add="${target}">添加一条</button>${entriesCount ? `<button class="text-button" type="button" data-memory-clear="${target}">清空本页条目</button>` : ""}${memorySettings[target] ? `<button class="text-button" type="button" data-memory-toggle="${target}" data-enabled="${group?.enabled !== false ? "1" : ""}">${group?.enabled !== false ? "暂停使用" : "恢复使用"}</button>` : ""}</div>` : "";
      const rowsEditable = (group?.entries || []).map((entry, index) => {
        const base = `<div class="memory-entry"><p>${esc(entry)}</p><button class="text-button" data-correct-memory="${index}">这条需要纠正</button></div>`;
        if (!editable) return base;
        return `<div class="memory-entry"><p>${esc(entry)}</p><span class="memory-entry-actions"><button class="text-button" data-memory-edit="${target}:${index}">编辑</button><button class="text-button" data-memory-remove="${target}:${index}">删除</button></span></div>`;
      }).join("");
      const bodyEditable = !group?.enabled ? '<p class="field-help">这部分记忆已关闭；原记录仍保留。</p>'
        : rowsEditable || '<p class="field-help">还没有记下内容。</p>';
      return `<section class="memory-card" data-memory-target="${target}"><h2>${title}</h2><p class="memory-read">${read} · 当前身份${editable ? " · 可直接编辑" : ""}</p>${bodyEditable}${tools}</section>`;
    }).join("") : "";
    const intro = failure
      ? '<section class="memory-intro"><h2>记忆</h2><p>暂时读不到记忆，原记录仍保留；稍后再试一次。</p></section>'
      : unavailable
      ? `<section class="memory-intro"><h2>记忆</h2><p>${esc(unavailable)}</p></section>`
      : '<section class="memory-intro"><h2>记忆</h2><p>Pajio 为当前身份记下的偏好和经验。发现记错了，可以在对话里纠正。</p></section>';
    const files = workspace ? workspace.files.slice(0, 8).map(file =>
      `<a class="file-row" download href="/api/workspace/file?identity=${encodeURIComponent(state.identityId)}&path=${encodeURIComponent(file.path)}"><span>${esc(file.path)}</span><small>${file.size < 1024 ? file.size + " B" : (file.size / 1024).toFixed(1) + " KB"} · 下载</small></a>`).join("")
      : '<p class="field-help">文件目录暂时读不到。</p>';
    const fileNote = workspace?.truncated ? '<p class="field-help">目录内容较多，先显示部分文件。</p>'
      : workspace && !workspace.files.length ? '<p class="field-help">还没有文件。让 Pajio 帮你把一个想法写下来试试。</p>' : "";
    container.dataset.viewKey = key;
    container.innerHTML = `${intro}${groups}
      <section class="memory-card"><h2>对话引用范围</h2><p class="memory-read">选择哪些历史对话不再作为后续回答来源</p>
        <button class="text-button" type="button" data-sources-open>查看对话引用范围</button>
        <p class="field-help">排除后历史仍保留可查看；已保存的记忆、文件与目标不受影响。</p></section>
      <section class="memory-files"><div class="life-section-heading"><h2>资料文件</h2><button class="text-button" data-open-files>查看全部文件</button></div>${files}${fileNote}
      <p class="field-help">工作区只读预览；完整目录在文件面板里。</p></section>`;
  }

  /* ---------- 我的：真实账户摘要、能力分组与外观个性化 ---------- */
  let meSection = "";
  let mePreview = null;
  async function renderMe(container) {
    const epoch = state.identityEpoch;
    const key = "me:" + state.identityId + ":" + meSection;
    if (container.dataset.viewKey === key) return;
    container.dataset.viewKey = key;
    const identity = state.identities.find(i => i.id === state.identityId);
    const space = state.deployment === "cloud" ? "云端实例" : "个人空间";
    let runtime = null, model = null;
    try { runtime = await api("/api/runtime"); } catch { runtime = null; }
    if (epoch !== state.identityEpoch) return;
    try { model = await api("/api/model"); } catch { model = null; }
    await loadComputer().catch(() => {});
    if (state.identityId === "daily") await loadPhone().catch(() => {});
    if (epoch !== state.identityEpoch) return;
    if (meSection === "skills") { await renderSkills(container); return; }
    if (meSection === "wardrobe") { renderWardrobe(container); return; }
    if (meSection === "appearance") { renderAppearance(container); return; }
    const provider = model?.providers?.find(p => p.id === model.provider)?.name || model?.provider || (state.connected ? "尚未确认" : "连接后查看");
    const computer = state.computer;
    const phones = typeof phoneState !== "undefined" ? phoneState?.resources : null;
    const row = (title, detail, icon, state, action) => `
      <button class="me-row" type="button" ${action ? `data-me-action="${action}"` : ""}>
        <svg viewBox="0 0 24 24" aria-hidden="true">${icon}</svg>
        <div><strong>${title}</strong>${detail ? `<small>${detail}</small>` : ""}</div>
        ${state ? `<span class="me-state">${state}</span>` : ""}${action ? '<svg viewBox="0 0 24 24" aria-hidden="true" class="chev"><path d="m9 6 6 6-6 6"/></svg>' : ""}
      </button>`;
    container.innerHTML = `
      <article class="me-account">
        <div class="me-account-top">${window.WearingPajio.wordmarkMarkup(76)}${window.WearingPajio.starMarkup(22)}</div>
        <div class="me-identity"><h2>${esc(identity?.name || "日常")}</h2><small>${esc(space)}</small></div>
        <div class="me-service"><span><span class="connection-dot ${state.connected ? "online" : ""}" aria-hidden="true"></span>${esc($("connection-label").textContent || "连接 Pajio")}</span><span>模型服务 · ${esc(provider)}</span></div>
      </article>
      <p class="me-group-label">能力与连接</p>
      <div class="me-group">
        ${row("连接应用", "文件空间、应用账号与本机能力", '<path d="M10 14a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-1.5 1.5"/><path d="M14 10a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7L12.5 19"/>', runtime?.files?.active ? "文件已启用" : "", "settings")}
        ${row("设备", "手机、电脑与执行设备", '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M9 20h6m-3-4v4"/>', computer?.connector?.enrolled ? "已接入电脑" : phones?.length ? `${phones.length} 部手机` : "", "settings")}
        ${row("技能", "真实目录：安装、启用与停用", '<path d="m12 3 2.4 5.4L20 10l-5.6 1.6L12 17l-2.4-5.4L4 10l5.6-1.6Z"/>', "", "skills")}
      </div>
      <p class="me-group-label">数据与身份</p>
      <div class="me-group">
        ${row("身份管理", "切换对话、记忆与文件所属身份", '<circle cx="12" cy="8" r="3.6"/><path d="M5.5 20a6.5 6.5 0 0 1 13 0"/>', "", "identities")}
        ${row("资料与文件", "原件和完成的结果，都留在这里", '<path d="M3.5 8V6.5a2 2 0 0 1 2-2h4l2 3H19a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5.5a2 2 0 0 1-2-2V8Z"/>', "", "files")}
        ${row("链接收藏", "保存网页链接，需要时再打开", '<path d="M10 14a5 5 0 0 0 7.5.5l2-2a5 5 0 0 0-7-7l-1 1"/><path d="M14 10a5 5 0 0 0-7.5-.5l-2 2a5 5 0 0 0 7 7l1-1"/>', "", "bookmarks")}
      </div>
      <p class="me-group-label">连接与沟通</p>
      <div class="me-group">${row("聊天工具", "飞书 / Telegram 机器人配置与启停", '<path d="M21 12a8 8 0 0 1-8 8H4l2-3a8 8 0 1 1 15-5Z"/>', "", "settings")}</div>
      <p class="me-group-label">偏好设置</p>
      <div class="me-group">
        ${row("外观与个性化", "显示模式与陪伴形象", '<path d="M4 7h9m-9 5h16M4 17h12"/>', "", "appearance")}
      </div>
      <p class="me-privacy"><svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true"><path d="M12 3 5 6v5c0 4.5 3 8 7 9.5 4-1.5 7-5 7-9.5V6Z"/></svg>由你选择分享什么，重要操作由你确认。</p>`;
  }

  function renderAppearance(container) {
    const {theme} = window.WearingPajio;
    const options = [{id: "day", label: "浅色", icon: '<circle cx="12" cy="12" r="4"/><path d="M12 3v2m0 14v2M3 12h2m14 0h2M5.6 5.6l1.4 1.4m10 10 1.4 1.4m0-12.8-1.4 1.4m-10 10L5.6 18.4"/>'},
      {id: "night", label: "深色", icon: '<path d="M20 14.5A8.5 8.5 0 0 1 9.5 4 8.5 8.5 0 1 0 20 14.5Z"/>'},
      {id: "system", label: "跟随系统", icon: '<rect x="3" y="4" width="14" height="12" rx="2"/><path d="M7 20h10"/>'}];
    container.innerHTML = `
      <button class="pj-back" type="button" data-me-back><svg viewBox="0 0 24 24" width="19" height="19" aria-hidden="true"><path d="m15 18-6-6 6-6"/></svg>返回我的</button>
      <div class="pj-panel"><h3>外观</h3><p class="pj-caption">跟随系统时，随设备的显示设置切换。</p>
        ${options.map(({id, label, icon}) => `<button class="pj-option" type="button" role="radio" aria-checked="${theme.preference === id}" data-theme-option="${id}"${theme.saving ? ' data-disabled="true"' : ""}><svg viewBox="0 0 24 24" aria-hidden="true">${icon}</svg><span>${label}</span>${theme.preference === id ? '<svg class="pj-check" viewBox="0 0 24 24" width="19" height="19" aria-hidden="true"><path d="m5 12 4 4L19 6"/></svg>' : ""}</button>`).join("")}
        ${theme.error ? `<p class="pj-error" role="status">${esc(theme.error)} <button class="text-button" type="button" data-theme-retry>重试</button></p>` : ""}</div>
      <button class="me-row me-wardrobe-entry" type="button" data-me-action="wardrobe">
        <div><strong>小熊的衣橱</strong><small>选一套喜欢的，陪你过今天。</small></div>
        ${window.WearingPajio.bearMarkup(window.WearingPajio.wardrobe.state.outfit, 76)}
        <svg viewBox="0 0 24 24" aria-hidden="true" class="chev"><path d="m9 6 6 6-6 6"/></svg></button>`;
  }

  /* 试衣帘换装：八图常驻叠放，目标图 decode 成功后才切换；快速连点只提交最新目标。
     蓝雾↔奶油月牙使用 Hypit 真实转身换装影片，结束帧即目标静图；其它组合仍走试衣帘。 */
  /* ---------- 我的清单（task-lists-contract） ---------- */
  const listState = {revision: null, lists: []};
  const listRequestKey = () => {
    const name = `pajio.task-list-request:v1:${state.identityId}`;
    let key = null; try {key = window.WearingStore.get(name);} catch {}
    if (!key || !/^[A-Za-z0-9_-]{16,120}$/.test(key)) {key = window.WearingIds.uuid().replaceAll("-", ""); window.WearingStore.set(name, key);}
    return key;
  };
  const listClearKey = () => {try {window.WearingStore.remove(`pajio.task-list-request:v1:${state.identityId}`);} catch {}};
  async function submitListChange(body) {
    const request_key = listRequestKey();
    const result = await api("/api/task-lists/change", {method: "POST", body: JSON.stringify({...body, revision: listState.revision, request_key})});
    if (result.request_key !== request_key || !(result.revision > listState.revision)) throw new Error("清单回执与本次请求不一致。");
    listClearKey();
    listState.revision = result.revision;
    return result;
  }
  const reloadLists = async () => {const data = await api("/api/task-lists"); listState.revision = data.revision; listState.lists = data.lists || []; return data;};
  async function renderTaskLists(host, listCount = 40) {
    if (!host) return;
    host.innerHTML = '<p class="field-help">正在读取清单……</p>';
    try {
      if (listState.revision === null) await reloadLists();
      const visible = listState.lists.filter(l => !l.archived_at);
      const shown = visible.slice(0, listCount);
      host.innerHTML = `<p class="me-group-label">我的清单（${visible.length}${listState.lists.length > visible.length ? ` · 已归档 ${listState.lists.length - visible.length}` : ""}）</p>
        <div class="me-group">${shown.map(list => `<div class="me-row me-row-static">
          <div><strong>${esc(list.name)}</strong><small>${list.open} 待办 / 共 ${list.total}</small></div>
          <span class="brief-actions">
            <button class="text-button" type="button" data-list-items="${esc(list.id)}">事项</button>
            <button class="text-button" type="button" data-list-add="${esc(list.id)}">添加</button>
            <button class="text-button" type="button" data-list-rename="${esc(list.id)}">改名</button>
            <button class="text-button" type="button" data-list-archive="${esc(list.id)}">归档</button>
          </span></div>`).join("") || '<p class="field-help">还没有清单。</p>'}</div>
        ${visible.length > listCount ? '<button class="text-button" type="button" data-lists-more>继续查看</button>' : ""}
        <div class="memory-confirm-row"><input id="tl-new-name" placeholder="新清单名称" maxlength="80"><button class="secondary" id="tl-create" type="button">新建清单</button></div>
        <p class="inline-feedback" id="tl-feedback" role="status"></p>
        <div id="tl-items"></div>`;
      const feedback = () => $("tl-feedback");
      $("tl-create")?.addEventListener("click", () => busy($("tl-create"), async () => {
        const name = $("tl-new-name").value.trim();
        if (!name) throw new Error("请填写清单名称。");
        await submitListChange({action: "create", name});
        await reloadLists();
        $("tl-new-name").value = "";
        feedback().textContent = "清单已创建。";
        await renderTaskLists(host);
      }, feedback()));
      host.querySelector("[data-lists-more]")?.addEventListener("click", () => renderTaskLists(host, listCount + 40));
      host.querySelectorAll("[data-list-items]").forEach(b => b.addEventListener("click", () => loadListItems(b.dataset.listItems, host)));
      host.querySelectorAll("[data-list-add]").forEach(b => b.addEventListener("click", () => {
        const title = prompt("事项标题（1–200 字）");
        if (!title?.trim()) return;
        busy(b, async () => {
          await submitListChange({action: "add", list_id: b.dataset.listAdd, title: title.trim().slice(0, 200)});
          await reloadLists();
          $("tl-feedback").textContent = "已添加。";
          await renderTaskLists(host);
          await loadListItems(b.dataset.listAdd, host);
        }, feedback());
      }));
      host.querySelectorAll("[data-list-rename]").forEach(b => b.addEventListener("click", () => {
        const current = listState.lists.find(l => l.id === b.dataset.listRename)?.name || "";
        const name = prompt("新名称", current);
        if (!name?.trim() || name.trim() === current) return;
        busy(b, async () => {
          await submitListChange({action: "rename", list_id: b.dataset.listRename, name: name.trim().slice(0, 80)});
          await reloadLists();
          $("tl-feedback").textContent = "已改名。";
          await renderTaskLists(host);
        }, feedback());
      }));
      host.querySelectorAll("[data-list-archive]").forEach(b => b.addEventListener("click", () => {
        b.dataset.confirm = (Number(b.dataset.confirm || 0) + 1).toString();
        if (b.dataset.confirm === "1") {b.textContent = "确认归档？"; setTimeout(() => {b.dataset.confirm = ""; b.textContent = "归档";}, 4000); return;}
        busy(b, async () => {
          await submitListChange({action: "archive", list_id: b.dataset.listArchive});
          await reloadLists();
          $("tl-feedback").textContent = "已归档（事项保留，可恢复）。";
          await renderTaskLists(host);
        }, feedback());
      }));
    } catch (error) {host.innerHTML = `<p class="field-help">${esc(error.message)}</p>`;}
  }
  async function loadListItems(listId, host, offset = 0) {
    const itemsHost = $("tl-items");
    if (!itemsHost) return;
    itemsHost.innerHTML = '<p class="field-help">正在读取事项……</p>';
    try {
      const params = new URLSearchParams({offset: String(offset), limit: "100"});
      if (offset > 0 && listState.revision !== null) params.set("revision", String(listState.revision));
      const data = await api(`/api/task-lists/${encodeURIComponent(listId)}/items?` + params);
      itemsHost.innerHTML = `<p class="me-group-label">${esc(data.list?.name || "清单")} 事项</p>
        <div class="me-group">${(data.items || []).map(item => `<div class="me-row me-row-static ${item.completed ? "life-row is-complete" : ""}">
          <button class="text-button" type="button" data-item-toggle="${esc(item.id)}" data-list="${esc(listId)}">${item.completed ? "取消完成" : "完成"}</button>
          <div><strong>${esc(item.title)}</strong><small>${item.completed ? "已完成" : "待办"}</small></div>
        </div>`).join("") || '<p class="field-help">清单为空。</p>'}</div>
        ${data.next_offset !== null && data.next_offset !== undefined ? '<button class="text-button" type="button" data-items-more>继续加载</button>' : ""}
        <p class="inline-feedback" id="tl-items-feedback" role="status"></p>`;
      itemsHost.querySelectorAll("[data-item-toggle]").forEach(b => b.addEventListener("click", () => {
        busy(b, async () => {
          const recordId = b.dataset.itemToggle;
          const current = await api(`/api/life/${recordId}`);
          await api(`/api/life/${recordId}`, {method: "PATCH", body: JSON.stringify({revision: current.revision, patch: {completed: !current.completed}})});
          $("tl-items-feedback").textContent = current.completed ? "已恢复待办。" : "已完成。";
          listState.revision = null;
          await reloadLists();
          await renderTaskLists(host);
          await loadListItems(listId, host);
        }, $("tl-items-feedback"));
      }));
      itemsHost.querySelector("[data-items-more]")?.addEventListener("click", () => loadListItems(listId, host, data.next_offset));
    } catch (error) {itemsHost.innerHTML = `<p class="field-help">${esc(error.message)}</p>`;}
  }

  const filmPair = (from, to) => (from === "mist-blue" && to === "cream-moon") || (from === "cream-moon" && to === "mist-blue");
  function mountWardrobeStage(host) {
    const {outfits, bearMarkup, bearReady} = window.WearingPajio;
    const reduced = matchMedia("(prefers-reduced-motion: reduce)");
    host.innerHTML = `<div class="stage-frame" aria-hidden="true">
      ${outfits.map(item => `<div class="stage-bear" data-stage-bear="${item.id}">${bearMarkup(item.id, 218)}</div>`).join("")}
      <div class="stage-film" hidden></div>
      <div class="stage-curtain stage-curtain-left"><i></i><i></i><i></i></div>
      <div class="stage-curtain stage-curtain-right"><i></i><i></i><i></i></div>
    </div>`;
    const layers = new Map([...host.querySelectorAll("[data-stage-bear]")].map(el => [el.dataset.stageBear, el]));
    const curtains = [...host.querySelectorAll(".stage-curtain")];
    const filmHost = host.querySelector(".stage-film");
    let shown = null, pending = null, busy = false, timer = 0, film = null;
    function commit(id) {
      layers.forEach((el, key) => el.classList.toggle("is-shown", key === id));
      shown = id;
    }
    function clearFilm() {
      if (!film) return;
      film.stopped = true;
      film.video.pause();
      filmHost.hidden = true;
      filmHost.innerHTML = "";
      film = null;
    }
    // 影片失败立即提交目标静图；正常结束经 220ms 末帧淡出（对齐 WardrobeFilm）后提交。
    // 离开页面由容器销毁兜底，不自动保存穿搭。
    function playFilm(from, to, onFinish) {
      clearFilm();
      filmHost.hidden = false;
      const {bearMarkup} = window.WearingPajio;
      filmHost.innerHTML = `<div class="film-under" hidden>${bearMarkup(to, 218)}</div>
        <div class="film-video"><video muted playsinline preload="auto" disablepictureinpicture src="/assets/motion/${from === "mist-blue" ? "blue-to-cream" : "cream-to-blue"}.mp4"></video></div>
        <div class="film-cover">${bearMarkup(from, 218)}</div>`;
      const video = filmHost.querySelector("video");
      const under = filmHost.querySelector(".film-under");
      const cover = filmHost.querySelector(".film-cover");
      const wrapper = filmHost.querySelector(".film-video");
      film = {video, stopped: false};
      let finished = false;
      video.addEventListener("loadeddata", () => {
        if (video.readyState >= 2) {under.hidden = false; cover.hidden = true;}
      });
      const finish = () => {if (film && !film.stopped && !finished) {finished = true; onFinish();}};
      video.addEventListener("ended", () => {
        if (!film || film.stopped || finished) return;
        wrapper.classList.add("is-done");
        setTimeout(finish, 230);
      });
      video.addEventListener("error", finish);
      const onVisibility = () => {if (!film || film.stopped) return; document.hidden ? video.pause() : video.play().catch(finish);};
      document.addEventListener("visibilitychange", onVisibility);
      film.cleanup = () => document.removeEventListener("visibilitychange", onVisibility);
      video.play().catch(finish);
      return () => {film?.cleanup?.(); clearFilm();};
    }
    async function show(id) {
      if (id === shown && !busy && !film) return;
      pending = id;
      await bearReady(id);
      if (pending !== id) return;
      if (reduced.matches) {clearFilm(); commit(id); curtains.forEach(el => el.classList.remove("is-closed")); return;}
      if (pending === shown) {clearFilm(); return;}
      if (filmPair(shown, pending)) {
        // 影片覆盖在静图之上；快速连点会经 clearFilm 取消并回到常规路径。
        playFilm(shown, pending, () => {clearFilm(); commit(pending);});
        return;
      }
      if (busy) return;
      clearFilm();
      busy = true;
      curtains.forEach(el => el.classList.add("is-closed"));
      timer = setTimeout(() => {
        commit(pending);
        requestAnimationFrame(() => {
          curtains.forEach(el => el.classList.remove("is-closed"));
          timer = setTimeout(() => {
            busy = false;
            if (pending !== shown) show(pending);
          }, 320);
        });
      }, 190);
    }
    return {show};
  }

  function renderWardrobe(container) {
    const {wardrobe, outfits, outfitById, bearMarkup} = window.WearingPajio;
    const preview = () => mePreview || wardrobe.state.outfit;
    container.innerHTML = `
      <button class="pj-back" type="button" data-me-back-appearance><svg viewBox="0 0 24 24" width="19" height="19" aria-hidden="true"><path d="m15 18-6-6 6-6"/></svg>返回外观与个性化</button>
      <div class="wardrobe-stage"><div class="wardrobe-stage-slot" data-wardrobe-stage></div><h3 data-outfit-name></h3><p data-outfit-detail></p></div>
      <div class="wardrobe-rail-heading"><span>挑一套试穿</span><span>8 套</span></div>
      <div class="wardrobe-rail" role="radiogroup" aria-label="睡衣款式">
        ${outfits.map(item => `<button class="wardrobe-option" type="button" role="radio" aria-pressed="false" aria-label="${esc(item.name)}，预览这套睡衣，点穿这套后保存" data-outfit-preview="${item.id}">${bearMarkup(item.id, 100)}<span class="pj-name"><span class="swatch" data-swatch="${item.swatch}"></span>${esc(item.name)}</span></button>`).join("")}
      </div>
      <button class="wardrobe-apply" type="button" data-outfit-save></button>
      ${wardrobe.state.error ? `<p class="pj-error" role="status">${esc(wardrobe.state.error)}</p>` : ""}
      <p class="wardrobe-footnote">穿搭保存在这台设备，跟随当前身份。随时可以再换。</p>`;
    container.querySelectorAll(".swatch[data-swatch]").forEach(el => {el.style.background = el.dataset.swatch;});
    const stage = mountWardrobeStage(container.querySelector("[data-wardrobe-stage]"));
    const apply = container.querySelector("[data-outfit-save]");
    function refresh() {
      const id = preview(), outfit = outfitById(id), changed = id !== wardrobe.state.outfit;
      container.querySelector("[data-outfit-name]").textContent = outfit.name;
      container.querySelector("[data-outfit-detail]").textContent = outfit.detail;
      container.querySelectorAll("[data-outfit-preview]").forEach(button => button.setAttribute("aria-pressed", String(button.dataset.outfitPreview === id)));
      apply.disabled = !changed || wardrobe.state.saving;
      apply.textContent = wardrobe.state.saving ? "正在保存…" : changed ? `穿上${outfit.name}并显示小熊` : "已穿上";
    }
    refresh();
    stage.show(preview());
    container.addEventListener("click", async event => {
      const option = event.target.closest("[data-outfit-preview]");
      if (option) {mePreview = option.dataset.outfitPreview; stage.show(mePreview); refresh(); return;}
      if (event.target.closest("[data-outfit-save]")) {
        const ok = await wardrobe.save(preview());
        if (ok) mePreview = null;
        refresh();
      }
    });
  }

  // 技能与聊天工具接真实路由（QA 未挂载时如实显示服务返回，不假装目录）。
  async function renderSkills(container) {
    container.innerHTML = '<p class="life-empty">正在读取技能目录……</p>';
    try {
      const data = await api("/api/skills");
      const rows = list => list.map(item => `<div class="me-row me-row-static">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m12 3 2.4 5.4L20 10l-5.6 1.6L12 17l-2.4-5.4L4 10l5.6-1.6Z"/></svg>
        <div><strong>${esc(item.name)}</strong><small>${esc(item.id)} · ${esc(item.revision || "")}</small></div>
        <span class="me-state">${item.enabled === false ? "已停用" : item.enabled === true ? "已启用" : ""}</span>
        ${item.installed === false ? `<button class="text-button" type="button" data-skill-install="${esc(item.id)}" data-revision="${esc(item.revision || "")}">安装</button>` : `<button class="text-button" type="button" data-skill-toggle="${esc(item.id)}" data-enabled="${item.enabled !== false}" data-revision="${esc(item.revision || "")}">${item.enabled === false ? "启用" : "停用"}</button><button class="text-button" type="button" data-skill-remove="${esc(item.id)}">移除</button>`}
      </div>`).join("");
      container.innerHTML = `<button class="pj-back" type="button" data-me-back><svg viewBox="0 0 24 24" width="19" height="19" aria-hidden="true"><path d="m15 18-6-6 6-6"/></svg>返回我的</button>
        <div class="me-group">${rows(data.installed || [])}</div>
        <p class="me-group-label">目录（固定版本）</p>
        <div class="me-group">${rows((data.catalog || []).filter(i => !i.installed))}</div>`;
    } catch (error) { container.innerHTML = `<p class="pj-note" role="status">${esc(error.message)}</p>`; }
  }
  async function renderMessaging(container) {
    container.innerHTML = '<p class="life-empty">正在读取聊天工具……</p>';
    try {
      const data = await api("/api/messaging");
      container.innerHTML = `<button class="pj-back" type="button" data-me-back-messaging><svg viewBox="0 0 24 24" width="19" height="19" aria-hidden="true"><path d="m15 18-6-6 6-6"/></svg>返回设置</button>` +
        (data.channels || []).map(ch => `<div class="me-group msg-provider">
          <div class="me-row me-row-static">
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M21 12a8 8 0 0 1-8 8H4l2-3a8 8 0 1 1 15-5Z"/></svg>
            <div><strong>${esc(ch.name)}</strong><small>${ch.configured ? (ch.enabled ? "已启用" : "已配置，未启用") : "未配置"}${ch.uncertain_replies ? " · " + ch.uncertain_replies + " 条待核对" : ""}${ch.error ? " · " + esc(ch.error) : ""}</small></div>
            <span class="me-state">${esc(ch.state || "")}</span>
          </div>
          ${ch.configured ? `<div class="memory-tools">
            <button class="text-button" type="button" data-msg-toggle="${esc(ch.provider)}" data-enabled="${ch.enabled}" data-revision="${esc(ch.revision ?? "")}">${ch.enabled ? "停用" : "启用"}</button>
            <button class="text-button" type="button" data-msg-disconnect="${esc(ch.provider)}" data-revision="${esc(ch.revision ?? "")}">断开</button>
          </div>` : ""}
        </div>`).join("") +
        `<p class="me-group-label">配置新连接（凭据只提交到服务，不保存在这台设备）</p>
        <form class="pj-panel" data-msg-form="telegram"><h3>Telegram</h3>
          <label class="field-help" for="msg-tg-token">Bot Token</label><input id="msg-tg-token" type="password" autocomplete="off" required>
          <label class="field-help" for="msg-tg-users">允许的用户（逗号分隔，可空）</label><input id="msg-tg-users">
          <button class="secondary msg-submit" type="submit">验证并保存</button></form>
        <form class="pj-panel" data-msg-form="feishu"><h3>飞书</h3>
          <label class="field-help" for="msg-fs-app">App ID</label><input id="msg-fs-app" required>
          <label class="field-help" for="msg-fs-secret">App Secret</label><input id="msg-fs-secret" type="password" autocomplete="off" required>
          <button class="secondary msg-submit" type="submit">验证并保存</button></form>`;
    } catch (error) { container.innerHTML = `<p class="pj-note" role="status">${esc(error.message)}</p>`; }
  }

  let rendered = "";
  window.WearingViews = {
    renderMessaging,
    render(view, container) {
      if (view !== rendered) { rendered = view; delete container.dataset.viewKey; }
      if (view === "today") renderToday(container);
      else if (view === "memory") renderMemory(container);
      else if (view === "me") renderMe(container);
    },
    renderTasks, renderTaskLists,
    appendActivityPage,
    // 身份切换会清空 life-content，但不清理这里的跳过标记；不重置会在切回时卡在加载态。
    reset() { rendered = ""; meSection = ""; mePreview = null; },
  };

  document.addEventListener("click", async event => {
    if (event.target.closest("[data-today-refresh]")) {
      const container = $("life-content");
      delete container.dataset.viewKey;
      window.WearingViews.render("today", container);
      return;
    }
    if (event.target.closest("[data-quick-capture]")) { window.WearingLife?.quickCapture(); return; }
    if (event.target.closest("[data-open-keeps-entry]")) {
      openPanel("keeps-panel");
      await loadKeeps().catch(error => notice(error.message, true));
      return;
    }
    const stop = event.target.closest("[data-task-stop]");
    if (stop) {
      stop.dataset.confirm = (Number(stop.dataset.confirm || 0) + 1).toString();
      if (stop.dataset.confirm === "1") {stop.textContent = "确认停止？"; setTimeout(() => {stop.dataset.confirm = ""; stop.textContent = "停止";}, 4000); return;}
      busy(stop, async () => {
        await api(`/api/tasks/${stop.dataset.taskStop}/stop`, {method: "POST", body: "{}"});
        notice("停止请求已发出；等待停止回执。");
      });
      return;
    }
    const cancel = event.target.closest("[data-task-cancel]");
    if (cancel) {
      cancel.dataset.confirm = (Number(cancel.dataset.confirm || 0) + 1).toString();
      if (cancel.dataset.confirm === "1") {cancel.textContent = "确认撤回？"; setTimeout(() => {cancel.dataset.confirm = ""; cancel.textContent = "撤回";}, 4000); return;}
      busy(cancel, async () => {
        await api(`/api/tasks/${cancel.dataset.taskCancel}/cancel-message`, {method: "POST", body: "{}"});
        notice("撤回请求已发出。");
      });
      return;
    }
    const task = event.target.closest("[data-activity-task]");
    if (task) { window.WearingActivity.openTask(task.dataset.activityTask).catch(() => {}); return; }
    const briefingOpen = event.target.closest("[data-briefing-open]");
    if (briefingOpen) { window.WearingBriefings?.open(); return; }
    const briefing = event.target.closest("[data-briefing]");
    if (briefing) {
      activateComposer({identity: state.identityId});
      window.WearingLife?.openView("chat");
      $("message-input").value = briefingDraft;
      $("message-input").dispatchEvent(new Event("input"));
      $("message-input").focus();
      return;
    }
    const meAction = event.target.closest("[data-me-action]");
    if (meAction) {
      const action = meAction.dataset.meAction;
      if (action === "settings") showSettings();
      else if (action === "identities") showIdentities();
      else if (action === "files") { openPanel("files-panel"); loadFiles().catch(() => {}); }
      else if (action === "bookmarks") { window.WearingBookmarks?.open(); }
      else if (action === "appearance") { meSection = "appearance"; delete $("life-content").dataset.viewKey; renderMe($("life-content")).catch(() => {}); }
      else if (action === "wardrobe") { meSection = "wardrobe"; delete $("life-content").dataset.viewKey; renderMe($("life-content")).catch(() => {}); }
      else if (action === "skills") { meSection = "skills"; delete $("life-content").dataset.viewKey; renderMe($("life-content")).catch(() => {}); }
      return;
    }
    if (event.target.closest("[data-me-back]")) { meSection = ""; mePreview = null; }
    if (event.target.closest("[data-me-back-appearance]")) { meSection = "appearance"; mePreview = null; }
    const back = event.target.closest("[data-me-back],[data-me-back-appearance]");
    if (back) { delete $("life-content").dataset.viewKey; renderMe($("life-content")).catch(() => {}); return; }
    const themeOption = event.target.closest("[data-theme-option]");
    if (themeOption && !themeOption.dataset.disabled) {
      await window.WearingPajio.theme.setPreference(themeOption.dataset.themeOption);
      delete $("life-content").dataset.viewKey; renderMe($("life-content")).catch(() => {});
      return;
    }
    if (event.target.closest("[data-theme-retry]")) { window.WearingPajio.theme.reload(); delete $("life-content").dataset.viewKey; renderMe($("life-content")).catch(() => {}); return; }
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
    if (event.target.closest("[data-open-files]")) { openPanel("files-panel"); loadFiles().catch(() => {}); return; }
    // 技能移除（skills-remove-contract）：预览→完整影响确认→稳定 operation_id 重试→回执校验刷新。
    const removeEntry = event.target.closest("[data-skill-remove]");
    if (removeEntry) {
      const id = removeEntry.dataset.skillRemove;
      const card = removeEntry.closest(".me-group");
      const prev = card.querySelector(".skill-remove-zone");
      if (prev?.dataset.openFor === id) return; // 已展开
      card.querySelectorAll(".skill-remove-zone").forEach(n => n.remove());
      try {
        const preview = await api(`/api/skills/removal?id=${encodeURIComponent(id)}`);
        const zone = document.createElement("div");
        zone.className = "skill-remove-zone pj-panel";
        zone.dataset.openFor = id;
        zone.innerHTML = `<h3>移除技能「${esc(preview.name)}」</h3>
          <p class="pj-caption">将从当前身份移除已安装包；目录原版不受影响。移除后可随时重新安装。</p>
          <p class="field-help">包修订：${esc(String(preview.package_revision || "").slice(0, 16))}… · 操作编号：${esc(String(preview.operation_id).slice(0, 12))}…</p>
          <div class="memory-confirm-row">
            <button class="secondary" type="button" data-skill-remove-confirm>确认移除</button>
            <button class="text-button" type="button" data-skill-remove-cancel>取消</button>
          </div>
          <p class="inline-feedback" role="status" hidden></p>`;
        card.append(zone);
        const feedback = zone.querySelector(".inline-feedback");
        zone.querySelector("[data-skill-remove-cancel]").addEventListener("click", () => zone.remove());
        zone.querySelector("[data-skill-remove-confirm]").addEventListener("click", () => {
          const button = zone.querySelector("[data-skill-remove-confirm]");
          busy(button, async () => {
            try {
              const receipt = await api("/api/skills/remove", {method: "POST", body: JSON.stringify({id: preview.id, revision: preview.revision, package_revision: preview.package_revision, operation_id: preview.operation_id})});
              if (receipt.removed !== true || receipt.id !== preview.id || receipt.operation_id !== preview.operation_id || receipt.recovery_id !== preview.operation_id) throw new Error("移除回执不完整，未确认结果；稍后可用同一操作重试。");
              if ((receipt.snapshot?.installed || []).some(item => item.id === preview.id)) throw new Error("回执显示技能仍在目录中，未当作已移除。");
              feedback.hidden = false; feedback.textContent = "已移除。";
              delete $("life-content").dataset.viewKey;
              await renderMe($("life-content"));
            } catch (error) {
              if (error instanceof StaleIdentity) return;
              button.disabled = false;
              feedback.hidden = false;
              feedback.textContent = (error.message || "这次没有移除。") + (error.status === 423 ? " 当前身份有任务正在执行，完成后再来确认。" : " 未移除任何文件，可用同一操作重试。");
            }
          });
        });
      } catch (error) {
        if (!(error instanceof StaleIdentity)) notice(error.message, true);
      }
      return;
    }
    // 技能：真实目录安装/启停（revision 随请求）。
    const skillInstall = event.target.closest("[data-skill-install]");
    if (skillInstall) {
      busy(skillInstall, async () => {
        await api("/api/skills/install", {method: "POST", body: JSON.stringify({id: skillInstall.dataset.skillInstall, revision: skillInstall.dataset.revision || undefined})});
        delete $("life-content").dataset.viewKey; await renderMe($("life-content"));
      });
      return;
    }
    const skillToggle = event.target.closest("[data-skill-toggle]");
    if (skillToggle) {
      busy(skillToggle, async () => {
        await api("/api/skills/enabled", {method: "PATCH", body: JSON.stringify({id: skillToggle.dataset.skillToggle, enabled: skillToggle.dataset.enabled !== "true", revision: skillToggle.dataset.revision || undefined})});
        delete $("life-content").dataset.viewKey; await renderMe($("life-content"));
      });
      return;
    }
    // 聊天工具：启停/断开（revision）；配置表单提交时凭据仅存在于表单内存，成功即清空。
    const msgToggle = event.target.closest("[data-msg-toggle]");
    if (msgToggle) {
      busy(msgToggle, async () => {
        await api(`/api/messaging/${msgToggle.dataset.msgToggle}`, {method: "PATCH", body: JSON.stringify({enabled: msgToggle.dataset.enabled !== "true", revision: msgToggle.dataset.revision || null})});
        await window.WearingViews.renderMessaging(event.target.closest("[data-msg-host]") || $("messaging-body"));
        if (document.body.dataset.view === "me") { delete $("life-content").dataset.viewKey; await renderMe($("life-content")); }
      });
      return;
    }
    const msgDisconnect = event.target.closest("[data-msg-disconnect]");
    if (msgDisconnect && msgDisconnect.dataset.confirm !== "1") {
      msgDisconnect.dataset.confirm = "1"; msgDisconnect.textContent = "确认断开？";
      setTimeout(() => { msgDisconnect.dataset.confirm = ""; msgDisconnect.textContent = "断开"; }, 4000);
      return;
    }
    if (msgDisconnect) {
      busy(msgDisconnect, async () => {
        await api(`/api/messaging/${msgDisconnect.dataset.msgDisconnect}`, {method: "DELETE", body: JSON.stringify({revision: msgDisconnect.dataset.revision || null})});
        await window.WearingViews.renderMessaging($("messaging-body"));
      });
      return;
    }
    // 记忆直接编辑（PATCH /api/memory）：精确增改删；409 保留输入，读最新版后可再用。
    const edit = event.target.closest("[data-memory-edit]");
    if (edit) {
      const [target, indexText] = edit.dataset.memoryEdit.split(":");
      const card = edit.closest(".memory-card");
      const entry = memoryEntries[Number(indexText)];
      const revision = memoryRevisions[target];
      openMemoryEditor(card, target, {index: Number(indexText), content: entry}, revision);
      return;
    }
    const add = event.target.closest("[data-memory-add]");
    if (add) {
      const target = add.dataset.memoryAdd;
      openMemoryEditor(add.closest(".memory-card"), target, {content: ""}, memoryRevisions[target]);
      return;
    }
    const clear = event.target.closest("[data-memory-clear]");
    if (clear) {
      const target = clear.dataset.memoryClear;
      const card = clear.closest(".memory-card");
      card.querySelector(".memory-editor")?.remove();
      card.insertAdjacentHTML("beforeend", `<div class="memory-editor" data-memory-clear-confirm="${target}"><p class="field-help">清空本页显示的条目？不会删除其他记忆、对话或文件。</p><div class="memory-confirm-row"><button class="secondary" type="button" data-memory-clear-yes>清空本页条目</button><button class="text-button" type="button" data-memory-cancel>保留并返回</button></div></div>`);
      card.querySelector("[data-memory-clear-yes]").addEventListener("click", () => submitMemoryChange({target, action: "clear", revision: memoryRevisions[target], content: ""}, card));
      card.querySelector("[data-memory-cancel]").addEventListener("click", () => card.querySelector("[data-memory-clear-confirm]")?.remove());
      return;
    }
    const toggle = event.target.closest("[data-memory-toggle]");
    if (toggle) {
      const target = toggle.dataset.memoryToggle;
      const enable = toggle.dataset.enabled !== "1";
      // 暂停走二次确认；恢复直接执行。settings_revision 作为 CAS 随请求。
      if (!enable) {
        toggle.dataset.confirm = (Number(toggle.dataset.confirm || 0) + 1).toString();
        if (toggle.dataset.confirm === "1") {toggle.textContent = "确认暂停使用？"; setTimeout(() => {toggle.dataset.confirm = ""; toggle.textContent = "暂停使用";}, 4000); return;}
      }
      submitMemoryChange({target, action: "set_enabled", enabled: enable, revision: memoryRevisions[target], settings_revision: memorySettings[target], content: ""}, toggle.closest(".memory-card"));
      return;
    }
    const remove = event.target.closest("[data-memory-remove]");
    if (remove) {
      const [target, indexText] = remove.dataset.memoryRemove.split(":");
      const index = Number(indexText);
      const entry = memoryEntries[index];
      const revision = memoryRevisions[target];
      const host = remove.closest(".memory-card");
      host.insertAdjacentHTML("beforeend", `<div class="memory-editor" data-memory-confirm="${target}:${index}"><p class="field-help">删除这条：${esc(String(entry).slice(0, 60))}${String(entry).length > 60 ? "…" : ""}</p><div class="memory-confirm-row"><button class="secondary" type="button" data-memory-confirm-yes>确认删除</button><button class="text-button" type="button" data-memory-cancel>取消</button></div></div>`);
      host.querySelector("[data-memory-confirm-yes]").addEventListener("click", () => submitMemoryChange({target, action: "remove", revision, index, content: ""}, host));
      host.querySelector("[data-memory-cancel]").addEventListener("click", () => host.querySelector("[data-memory-confirm]")?.remove());
      return;
    }
  });
  function openMemoryEditor(card, target, draft, revision) {
    card.querySelector(".memory-editor")?.remove();
    const isEdit = typeof draft.index === "number";
    const form = document.createElement("form");
    form.className = "memory-editor note-form decision-card";
    form.innerHTML = `<label for="memory-edit-text">${isEdit ? "编辑这条记忆" : "添加一条记忆"}（最多 12000 字）</label>
      <textarea id="memory-edit-text" rows="4" maxlength="12000" required>${esc(draft.content)}</textarea>
      <div class="memory-editor-row"><button class="secondary" type="submit">保存到记忆</button><button class="text-button" type="button" data-memory-cancel>取消</button></div>
      <p class="inline-feedback" role="status" hidden></p>`;
    // 离页草稿：同一身份+分区+条目在会话内保留未保存输入。
    const draftId = `pajio-memory-draft:v1:${state.identityId}:${target}:${typeof draft.index === "number" ? draft.index : "new"}`;
    try {
      const saved = window.WearingStore.get(draftId);
      if (saved && !isEdit) form.querySelector("#memory-edit-text").value = saved;
    } catch {}
    form.querySelector("#memory-edit-text").addEventListener("input", () => {window.WearingStore.set(draftId, form.querySelector("#memory-edit-text").value);});
    form.dataset.memoryDraftId = draftId;
    card.append(form);
    form.querySelector("[data-memory-cancel]").addEventListener("click", () => form.remove());
    form.addEventListener("submit", async event => {
      event.preventDefault();
      await submitMemoryChange({target, action: isEdit ? "replace" : "add", revision,
        ...(isEdit ? {index: draft.index} : {}), content: form.querySelector("#memory-edit-text").value}, card, form);
    });
    form.querySelector("textarea").focus();
  }
  async function submitMemoryChange(change, card, form = null) {
    const feedback = form ? form.querySelector(".inline-feedback") : card.querySelector(".inline-feedback");
    try {
      const result = await api("/api/memory", {method: "PATCH", body: JSON.stringify(change)});
      if (result?.success === false) throw new Error(result.error || "记忆没有保存，请再试。");
      if (form?.dataset?.memoryDraftId) {try {window.WearingStore.remove(form.dataset.memoryDraftId);} catch {}}
      delete $("life-content").dataset.viewKey;
      await renderMemory($("life-content"));
      notice(change.action === "clear" ? "已清空本页条目。" : change.action === "set_enabled" ? (change.enabled ? "已恢复使用。" : "已暂停使用，内容仍保留。") : "记忆已更新。");
    } catch (error) {
      if (error instanceof StaleIdentity) return;
      // 409：保留表单输入，提示读最新版；再次提交沿用用户输入。
      if (feedback) { feedback.hidden = false; feedback.textContent = error.message || "记忆保存失败，输入已保留。"; }
      else notice(error.message || "记忆保存失败。", true);
    }
  }

  document.addEventListener("submit", async event => {
    const form = event.target.closest("[data-msg-form]");
    if (!form) return;
    event.preventDefault();
    const provider = form.dataset.msgForm;
    const secretField = form.querySelector('input[type=password]');
    const body = provider === "feishu"
      ? {app_id: form.querySelector("#msg-fs-app").value.trim(), secret: secretField.value}
      : {secret: secretField.value, ...(form.querySelector("#msg-tg-users").value.trim() ? {allowed_users: form.querySelector("#msg-tg-users").value.split(",").map(s => s.trim()).filter(Boolean)} : {})};
    const button = form.querySelector(".msg-submit");
    busy(button, async () => {
      try {
        await api(`/api/messaging/${provider}`, {method: "PUT", body: JSON.stringify(body)});
      } finally {
        // 凭据不留在页面：提交结束立即清空密码字段（无论成败都不落任何存储）。
        secretField.value = "";
        form.querySelectorAll("input").forEach(input => { if (input.type === "password") input.value = ""; });
      }
      await window.WearingViews.renderMessaging($("messaging-body"));
    });
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
  const globalSection = document.createElement("div");
  globalSection.className = "web-search-global";
  globalSection.setAttribute("aria-label", "跨对象搜索结果");
  const globalTitle = document.createElement("p");
  globalTitle.className = "web-search-global-title";
  const globalList = document.createElement("div");
  globalList.className = "web-search-global-list";
  globalSection.append(globalTitle, globalList);
  panel.append(globalSection);
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
  let globalTimer = 0, globalQuery = "";
  const esc2 = esc;
  function renderGlobal(data) {
    const items = data.items || [];
    globalTitle.textContent = data.query ? `跨对象「${data.query}」${items.length ? "" : "没有找到"}` : "";
    globalList.replaceChildren();
    for (const item of items) {
      const row = document.createElement("button");
      row.type = "button";
      row.className = "web-search-hit";
      row.innerHTML = `<strong>${esc2(item.title || "")}</strong><small>${esc2(item.snippet || "")}</small><span class="web-search-kind">${esc2({task: "任务", record: "记录", message: "消息", chat_import: "聊天来源"}[item.kind] || item.kind)}${item.record_kind ? " · " + esc2({note: "笔记", task: "待办", event: "日程"}[item.record_kind] || item.record_kind) : ""}</span>`;
      row.addEventListener("click", () => openSearchTarget(item));
      globalList.append(row);
    }
    if (data.next_cursor) {
      const more = document.createElement("button");
      more.type = "button"; more.className = "text-button"; more.textContent = "继续查找";
      more.addEventListener("click", () => loadGlobal(data.next_cursor));
      globalList.append(more);
    }
  }
  async function loadGlobal(cursor) {
    const query = input.value.trim();
    if (!query || query.length > 120) {globalTitle.textContent = ""; globalList.replaceChildren(); return;}
    const params = new URLSearchParams({q: query, kind: "all", limit: "20", ...(cursor ? {cursor} : {})});
    try {
      const data = await api("/api/search?" + params);
      if (input.value.trim() !== query) return; // 查询已变化，丢弃迟到结果
      renderGlobal(data);
    } catch (error) {
      if (!(error instanceof StaleIdentity)) globalTitle.textContent = error.message || "跨对象搜索暂时不可用。";
    }
  }
  async function openSearchTarget(item) {
    closeSearch();
    if (item.target?.kind === "chat_import") {if (window.WearingChatImport?.openSearchResult?.(item.target)) return;}
    if (item.target?.kind === "task") {window.WearingActivity?.openTask?.(item.target.task_id)?.catch(() => {}); return;}
    if (item.target?.kind === "record") {
      const record = await api("/api/life/" + item.target.record_id).catch(() => null);
      if (record) {window.WearingLife?.openView({note: "notes", task: "tasks", event: "calendar"}[record.kind] || "notes");
        setTimeout(() => document.querySelector(`[data-life-open="${item.target.record_id}"]`)?.click(), 400);}
      return;
    }
    if (item.target?.kind === "message") {
      const message = await api("/api/search/messages/" + encodeURIComponent(item.target.message_id)).catch(() => null);
      if (message) {window.WearingActivity?.openTask?.(message.task_id)?.catch(() => {});}
      return;
    }
  }
  input.addEventListener("input", () => {findMatches(); clearTimeout(globalTimer); globalTimer = setTimeout(() => loadGlobal(), 250);});
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
