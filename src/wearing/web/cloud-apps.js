"use strict";
/* 飞书个人账号 Device OAuth（Web）：与聊天机器人配置分开。
   对齐 src/wearing/cloud_apps_api.py 与 App NativeCloudAppsPanel/cloud-apps-model（只读参考）：
   凭据仅存在于表单内存，提交即清空，不写入任何浏览器存储；
   不自动发起真实账号授权——授权、轮询、检查、解除都是用户显式点击。
   授权链接必须是官方 feishu.cn 域。App 宿主不注册。 */
(() => {
  if (document.documentElement.classList.contains("mobile-host")) return;
  const $ = id => document.getElementById(id);
  const esc = text => String(text ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const stateLabels = {not_configured: "未配置", configured: "已配置应用，待授权", authorizing: "等待你在飞书完成授权",
    authorization_expired: "授权入口已过期", connected: "已连接", expired: "授权已过期"};
  let snapshot = null, pollTimer = 0, filesFolder = null, filesPage = null;

  const officialFeishuUrl = value => {
    try {const url = new URL(value); return url.protocol === "https:" && !url.username && !url.password && !url.port && (url.hostname === "feishu.cn" || url.hostname.endsWith(".feishu.cn"));} catch {return false;}
  };
  function validateState(data) {
    if (!data || data.provider !== "feishu" || !stateLabels[data.state] || typeof data.configured !== "boolean" || typeof data.revocation_pending !== "boolean") return null;
    if (data.authorization && (!officialFeishuUrl(data.authorization.url) || typeof data.authorization.user_code !== "string")) return null;
    return data;
  }
  async function call(path, {method = "GET", body} = {}) {
    return api("/api/cloud-apps/feishu" + path, {...(method === "GET" ? {} : {method, body: body === undefined ? "{}" : JSON.stringify(body)})});
  }

  function render() {
    const host = $("cloud-apps-body");
    if (!snapshot) {host.innerHTML = '<p class="field-help">正在读取……</p>'; return;}
    const s = snapshot;
    const caps = (s.capabilities || []).map(cap => `<li>${esc(cap.label)}：${cap.authorized ? "已授权" : cap.requested ? "已申请，待授权" : "未申请"}</li>`).join("");
    let body = "";
    if (s.state === "not_configured") {
      body = `<form id="cloud-config-form" class="pj-panel">
        <h3>配置飞书应用凭据</h3><p class="pj-caption">使用你在飞书开放平台创建的自建应用；凭据只提交到本机服务，不保存在这台设备。</p>
        <label class="field-help" for="cloud-app-id">App ID（cli_ 开头）</label><input id="cloud-app-id" autocomplete="off" required>
        <label class="field-help" for="cloud-secret">App Secret</label><input id="cloud-secret" type="password" autocomplete="off" required>
        <p class="pj-caption">读取范围（至少一项）</p>
        <label class="memory-check"><input type="checkbox" name="cloud-feature" value="documents" checked>云文档与知识库（只读）</label>
        <label class="memory-check"><input type="checkbox" name="cloud-feature" value="calendar">日历与日程（只读）</label>
        <button class="secondary msg-submit" type="submit">保存应用配置</button></form>`;
    } else if (s.state === "authorizing" && s.authorization) {
      const remain = Math.max(0, Math.round(s.authorization.expires_at - Date.now() / 1000));
      body = `<div class="pj-panel"><h3>在飞书完成授权</h3>
        <p class="pj-caption">打开官方授权页，确认显示的码与下面一致；${remain > 0 ? `剩余 ${Math.ceil(remain / 60)} 分钟` : "即将过期"}。</p>
        <p class="cloud-user-code">${esc(s.authorization.user_code)}</p>
        <div class="brief-actions"><a class="secondary" href="${esc(s.authorization.url)}" target="_blank" rel="noreferrer">打开飞书授权页</a>
        <button class="text-button" type="button" data-cloud-poll>我已确认，检查结果</button></div></div>`;
    } else if (s.state === "connected") {
      body = `<div class="pj-panel"><h3>已连接${s.account_name ? "：" + esc(s.account_name) : ""}</h3>
        <ul class="cloud-caps">${caps}</ul>
        <div class="brief-actions"><button class="text-button" type="button" data-cloud-check>检查连接</button>
        <button class="text-button" type="button" data-cloud-disconnect data-revision="${esc(s.revision || "")}" data-confirm="0">解除连接</button></div></div>
        <div id="cloud-resources"><button class="pj-load-more" type="button" data-cloud-files>读取云文档</button>
        <button class="pj-load-more" type="button" data-cloud-calendars>读取日历</button></div>`;
    } else {
      body = `<div class="pj-panel"><h3>${esc(stateLabels[s.state])}</h3>
        ${s.error ? `<p class="pj-error">${esc(s.error)}</p>` : ""}
        ${caps ? `<ul class="cloud-caps">${caps}</ul>` : ""}
        <div class="brief-actions">
        ${s.state !== "authorization_expired" && s.revision ? `<button class="secondary" type="button" data-cloud-authorize data-revision="${esc(s.revision)}">${s.state === "expired" ? "重新授权" : "连接飞书（官方授权）"}</button>` : ""}
        ${s.state === "authorization_expired" && s.revision ? `<button class="secondary" type="button" data-cloud-authorize data-revision="${esc(s.revision)}">重新获取授权入口</button>` : ""}
        ${s.configured && s.revision ? `<button class="text-button" type="button" data-cloud-disconnect data-revision="${esc(s.revision)}" data-confirm="0">解除连接</button>` : ""}
        ${s.revocation_pending ? '<p class="field-help">上一次解除仍在撤销中，请先完成撤销。</p>' : ""}</div></div>`;
    }
    host.innerHTML = body + '<p id="cloud-feedback" class="inline-feedback" role="status"></p>';
  }

  async function refresh() {
    try {
      const data = validateState(await call(""));
      if (!data) throw new Error("飞书连接状态回执不完整，请重试。");
      snapshot = data;
      render();
      schedulePoll();
    } catch (error) {
      if (!(error instanceof StaleIdentity)) {
        $("cloud-apps-body").innerHTML = `<p class="pj-error" role="status">${esc(error.message)}</p><button class="text-button" type="button" data-cloud-retry>重试</button>`;
      }
    }
  }
  function schedulePoll() {
    clearTimeout(pollTimer);
    if (snapshot?.state === "authorizing" && snapshot.authorization) {
      pollTimer = setTimeout(async () => {
        try {snapshot = validateState(await call("/poll", {method: "POST", body: {authorization_id: snapshot.authorization.id}})) || snapshot; render(); schedulePoll();}
        catch {schedulePoll();}
      }, Math.max(5, snapshot.authorization.interval) * 1000);
    }
  }

  document.addEventListener("click", async event => {
    const authorize = event.target.closest("[data-cloud-authorize]");
    if (authorize) {
      busy(authorize, async () => {snapshot = validateState(await call("/authorize", {method: "POST", body: {revision: authorize.dataset.revision}})) || snapshot; render(); schedulePoll();}, $("cloud-feedback"));
      return;
    }
    if (event.target.closest("[data-cloud-poll]")) {
      const button = event.target.closest("[data-cloud-poll]");
      busy(button, async () => {snapshot = validateState(await call("/poll", {method: "POST", body: {authorization_id: snapshot.authorization.id}})) || snapshot; render(); schedulePoll();}, $("cloud-feedback"));
      return;
    }
    if (event.target.closest("[data-cloud-check]")) {
      const button = event.target.closest("[data-cloud-check]");
      busy(button, async () => {snapshot = validateState(await call("/check", {method: "POST"})) || snapshot; render();}, $("cloud-feedback"));
      return;
    }
    const disconnect = event.target.closest("[data-cloud-disconnect]");
    if (disconnect) {
      if (disconnect.dataset.confirm !== "1") {disconnect.dataset.confirm = "1"; disconnect.textContent = "确认解除？将在飞书撤销授权"; setTimeout(() => {disconnect.dataset.confirm = "0"; disconnect.textContent = "解除连接";}, 4000); return;}
      busy(disconnect, async () => {await call("", {method: "DELETE", body: {revision: disconnect.dataset.revision}}); await refresh();}, $("cloud-feedback"));
      return;
    }
    if (event.target.closest("[data-cloud-retry]")) {refresh(); return;}
    if (event.target.closest("[data-cloud-files]")) {renderFiles(); return;}
    if (event.target.closest("[data-cloud-calendars]")) {renderCalendars(); return;}
    const folder = event.target.closest("[data-cloud-folder]");
    if (folder) {filesFolder = folder.dataset.cloudFolder || null; filesPage = null; renderFiles(); return;}
    if (event.target.closest("[data-cloud-more-files]")) {renderFiles(filesPage); return;}
    const doc = event.target.closest("[data-cloud-doc]");
    if (doc) {renderDocument(doc.dataset.cloudDoc, doc.dataset.cloudKind || "docx"); return;}
    if (event.target.closest("[data-cloud-more-doc]")) {renderDocument(window.__cloudDoc.id, window.__cloudDoc.kind, window.__cloudDoc.offset); return;}
    const events = event.target.closest("[data-cloud-events]");
    if (events) {renderEvents(events.dataset.cloudCalendar); return;}
  });

  document.addEventListener("submit", async event => {
    const form = event.target.closest("#cloud-config-form");
    if (!form) return;
    event.preventDefault();
    const app_id = form.querySelector("#cloud-app-id").value.trim();
    const secret = form.querySelector("#cloud-secret").value;
    const features = [...form.querySelectorAll("[name=cloud-feature]:checked")].map(node => node.value);
    const error = !/^cli_[A-Za-z0-9]{6,80}$/.test(app_id) || !/^[A-Za-z0-9_-]{12,160}$/.test(secret) ? "请核对飞书 App ID 与 App Secret。" : !features.length ? "请选择文档或日历。" : null;
    if (error) {form.querySelector("#cloud-secret").value = ""; $("cloud-feedback").textContent = error; return;}
    busy(form.querySelector(".msg-submit"), async () => {
      try {snapshot = validateState(await call("", {method: "PUT", body: {app_id, secret, features}})) || snapshot;}
      finally {form.querySelector("#cloud-secret").value = ""; form.querySelector("#cloud-app-id").value = "";}
      render();
    }, $("cloud-feedback"));
  });

  async function renderFiles(pageToken = null) {
    const host = $("cloud-resources");
    host.innerHTML = '<p class="field-help">正在读取云文档……</p>';
    try {
      const query = new URLSearchParams({...(filesFolder ? {folder_token: filesFolder} : {}), ...(pageToken ? {page_token: pageToken} : {})});
      const data = await call("/files" + (query.size ? "?" + query : ""));
      filesPage = data.has_more ? data.next_page_token : null;
      host.innerHTML = `${filesFolder ? '<button class="text-button" type="button" data-cloud-folder="">返回根目录</button>' : ""}
        ${(data.items || []).map(item => item.type === "folder"
          ? `<button class="pj-card" type="button" data-cloud-folder="${esc(item.token)}"><div><strong>📁 ${esc(item.name)}</strong></div></button>`
          : `<button class="pj-card" type="button" data-cloud-doc="${esc(item.token)}"><div><strong>${esc(item.name)}</strong><small>打开全文</small></div></button>`).join("") || '<p class="field-help">这里还没有文件。</p>'}
        ${filesPage ? '<button class="pj-load-more" type="button" data-cloud-more-files>加载更多</button>' : ""}`;
    } catch (error) {host.innerHTML = `<p class="pj-error">${esc(error.message)}</p><button class="text-button" type="button" data-cloud-files>重试</button>`;}
  }

  async function renderDocument(documentId, kind, offset = 0) {
    const host = $("cloud-resources");
    host.innerHTML = '<p class="field-help">正在读取文档……</p>';
    try {
      const query = new URLSearchParams({document: documentId, kind, offset: String(offset)});
      const data = await call("/document?" + query);
      window.__cloudDoc = {id: documentId, kind, offset: data.next_offset};
      host.innerHTML = `<button class="text-button" type="button" data-cloud-files>回到文件列表</button>
        <h4>${esc(data.title || "未命名文档")}</h4>
        <div class="cloud-doc"><pre>${esc(data.content)}</pre></div>
        <p class="field-help">${data.offset + data.content.length}/${data.total_characters} 字</p>
        ${data.next_offset !== null && data.next_offset !== undefined ? '<button class="pj-load-more" type="button" data-cloud-more-doc>继续读取</button>' : ""}`;
    } catch (error) {host.innerHTML = `<p class="pj-error">${esc(error.message)}</p>`;}
  }

  async function renderCalendars() {
    const host = $("cloud-resources");
    host.innerHTML = '<p class="field-help">正在读取日历……</p>';
    try {
      const data = await call("/calendars");
      host.innerHTML = (data.items || []).map(cal =>
        `<button class="pj-card" type="button" data-cloud-events="${esc(cal.calendar_id)}"><div><strong>${esc(cal.summary_alias || cal.summary || "日历")}</strong><small>读取未来 7 天日程</small></div></button>`).join("") || '<p class="field-help">没有可读的日历。</p>';
    } catch (error) {host.innerHTML = `<p class="pj-error">${esc(error.message)}</p>`;}
  }

  async function renderEvents(calendarId) {
    const host = $("cloud-resources");
    host.innerHTML = '<p class="field-help">正在读取日程……</p>';
    try {
      const start = Math.floor(Date.now() / 1000);
      const query = new URLSearchParams({calendar_id: calendarId, start_time: String(start), end_time: String(start + 7 * 86400)});
      const data = await call("/events?" + query);
      host.innerHTML = '<button class="text-button" type="button" data-cloud-calendars>回到日历列表</button>' +
        (data.items || []).map(ev => `<div class="pj-card pj-card-block"><strong>${esc(ev.summary || "（无标题）")}</strong>${ev.start_time?.date || ev.start_time?.timestamp ? `<small>${esc(ev.start_time.date || new Date(Number(ev.start_time.timestamp) * 1000).toLocaleString("zh-CN"))}</small>` : ""}${ev.location?.name ? `<small>📍 ${esc(ev.location.name)}</small>` : ""}</div>`).join("") || '<p class="field-help">未来 7 天没有日程。</p>';
    } catch (error) {host.innerHTML = `<p class="pj-error">${esc(error.message)}</p>`;}
  }

  window.WearingCloudApps = {refresh};
})();
