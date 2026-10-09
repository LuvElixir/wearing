"use strict";
/* Pajio 持久每日简报（Web）：版本化 brief、真实任务回执与图文成果。
   对齐 docs/evidence/pajio-core-20261007/briefings-contract.md 与 App BriefPanel 语义：
   request_key 在发出请求前持久化，未知结果用同一 key+body 取回；前台每 5 秒读取，
   后台停止；不预填聊天草稿。App 宿主不注册。 */
(() => {
  if (document.documentElement.classList.contains("mobile-host")) return;
  const $ = id => document.getElementById(id);
  const esc = text => String(text ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const tz = () => Intl.DateTimeFormat().resolvedOptions().timeZone || "Asia/Shanghai";
  const localDay = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; };
  const clock = value => new Date(value).toLocaleTimeString("zh-CN", {hour: "2-digit", minute: "2-digit"});
  const stateLabels = {not_started: "尚未开始", queued: "已排队", running: "正在整理", needs_attention: "需要查看进展",
    ready: "图文已生成", text_only: "文字已返回，图文未交付", failed: "这次没有完成", stopped: "已停止"};
  const activeStates = new Set(["not_started", "queued", "running"]);
  const journalKey = () => `pajio-brief:v1:${state.identityId}`;
  let timer = 0, loading = false;

  function readJournal() { try { return JSON.parse(window.WearingStore.get(journalKey()) || "null"); } catch { return null; } }
  function writeJournal(entry) { try { window.WearingStore.set(journalKey(), JSON.stringify(entry)); } catch {} }
  function clearJournal() { try { window.WearingStore.remove(journalKey()); } catch {} }

  function schedule() {
    clearTimeout(timer);
    if (!$("brief-panel").open || document.hidden) return;
    timer = setTimeout(() => load(), 5000);
  }

  async function load() {
    if (loading) return;
    loading = true;
    const epoch = state.identityEpoch;
    try {
      const query = new URLSearchParams({date: $("brief-date").value || localDay(), timezone: tz()});
      const data = await api("/api/briefings?" + query);
      if (epoch !== state.identityEpoch) return;
      render(data);
    } catch (error) {
      if (epoch === state.identityEpoch && !(error instanceof StaleIdentity)) {
        $("brief-feedback").textContent = error.message || "暂时读不到简报，稍后重试。";
        clearTimeout(timer);
        timer = setTimeout(load, 15000);
      }
      return;
    } finally { loading = false; }
    schedule();
  }

  function sourcesLine(item) {
    const s = item.sources;
    if (!s) return "";
    const parts = Object.entries(s).filter(([, v]) => v && typeof v === "object").map(([k, v]) => `${k}:${v.count ?? v.state ?? "?"}`).slice(0, 4);
    return parts.length ? `来源快照 · ${parts.join(" · ")}` : "";
  }

  function renderItem(item) {
    const label = stateLabels[item.state] || item.state;
    const artifacts = (item.artifacts || []).map(a => `<button class="text-button" data-brief-artifact="${esc(a.id)}" type="button">打开图文（${esc(a.title || a.kind || "结果")}）</button>`).join("");
    const task = item.task_id ? `<button class="text-button" data-brief-task="${esc(item.task_id)}" type="button">查看这件事</button>` : "";
    const sources = sourcesLine(item);
    return `<article class="pj-card brief-item" data-state="${esc(item.state)}">
      <div class="brief-item-head">
        <strong>第 ${item.version} 版 · ${esc(label)}</strong>
        <small>${esc(clock(item.updated_at))}</small>
      </div>
      ${item.output ? `<small class="brief-output">${esc(item.output.slice(0, 400))}${item.output.length > 400 ? "…" : ""}</small>` : ""}
      ${item.error ? `<small class="brief-error">${esc(item.error)}</small>` : ""}
      ${sources ? `<small class="brief-sources">${esc(sources)}</small>` : ""}
      <div class="brief-actions">${artifacts}${task}</div>
    </article>`;
  }

  function render(data) {
    $("brief-feedback").textContent = "";
    const items = data.items || [];
    $("brief-list").innerHTML = items.length ? items.map(renderItem).join("") :
      '<p class="pj-note">今天还没有简报。点「整理今天的简报」开始第一版。</p>';
    const busy = items.some(item => activeStates.has(item.state));
    $("brief-create").textContent = busy ? "正在整理…" : items.length ? "重新整理一版" : "整理今天的简报";
    $("brief-create").disabled = busy;
    $("brief-base").value = items.length ? String(items[0].version) : "0";
  }

  async function create() {
    const date = $("brief-date").value || localDay();
    const body = {date, timezone: tz(), request_key: window.WearingIds.uuid().replaceAll("-", ""), base_version: Number($("brief-base").value || 0)};
    // 发出请求前持久化：未知结果用同一 key+body 取回同一次请求。
    writeJournal(body);
    $("brief-create").disabled = true;
    $("brief-feedback").textContent = "正在提交这一次整理请求…";
    const epoch = state.identityEpoch;
    try {
      const receipt = await api("/api/briefings", {method: "POST", body: JSON.stringify(body)});
      if (epoch !== state.identityEpoch) return;
      if (!receipt || receipt.identity_id !== state.identityId || receipt.date !== body.date || receipt.request_key !== body.request_key) {
        $("brief-feedback").textContent = "回执与本次请求不一致，已保留请求记录，可安全重试取回。";
        return;
      }
      clearJournal();
      $("brief-feedback").textContent = `已登记第 ${receipt.version} 版，状态：${stateLabels[receipt.state] || receipt.state}。`;
      await load();
    } catch (error) {
      if (epoch !== state.identityEpoch || error instanceof StaleIdentity) return;
      $("brief-feedback").textContent = (error.message || "这次请求结果未知。") + " 将用同一请求取回，不会重复整理。";
      $("brief-create").disabled = false;
    }
  }

  async function resumePending() {
    const pending = readJournal();
    if (!pending) return;
    $("brief-feedback").textContent = "发现未确认的整理请求，正在取回这一次请求…";
    const epoch = state.identityEpoch;
    try {
      const receipt = await api("/api/briefings", {method: "POST", body: JSON.stringify(pending)});
      if (epoch !== state.identityEpoch) return;
      if (receipt && receipt.identity_id === state.identityId && receipt.request_key === pending.request_key) clearJournal();
      $("brief-feedback").textContent = "已取回上一次整理请求。";
      await load();
    } catch (error) {
      if (epoch === state.identityEpoch && !(error instanceof StaleIdentity)) {
        $("brief-feedback").textContent = "上一次请求仍未确认，稍后会继续用同一请求取回。";
      }
    }
  }

  function open() {
    $("brief-date").value = localDay();
    openPanel("brief-panel");
    loadPreferences().catch(() => {});
    resumeAutomation().catch(() => {});
    load().then(resumePending);
  }

  $("brief-close").addEventListener("click", () => closePanel("brief-panel"));
  $("brief-panel").addEventListener("close", () => clearTimeout(timer));
  document.addEventListener("visibilitychange", () => { if (!document.hidden && $("brief-panel").open) load(); else clearTimeout(timer); });
  $("brief-refresh").addEventListener("click", () => load());
  $("brief-date").addEventListener("change", () => load());
  $("brief-create").addEventListener("click", () => create());

  /* ---------- 简报偏好（briefing-preferences-contract） ---------- */
  const sourceLabels = {event: "日程", task: "任务", note: "笔记", files: "文件空间", feishu: "飞书"};
  const stateLabels2 = {available: "可用", empty: "暂无内容", failed: "读取失败", authorized: "已授权（未证明已读取）", not_connected: "未连接", unavailable: "未安装读取器"};
  let prefRevision = 0, prefRequestKey = null;
  const prefKey = () => `pajio.brief-pref-request:v1:${state.identityId}`;
  async function loadPreferences() {
    const host = $("brief-preferences");
    try {
      const data = await api("/api/briefings/preferences");
      prefRevision = data.preferences?.revision ?? 0;
      let saved = null; try {saved = window.WearingStore.get(prefKey());} catch {}
      prefRequestKey = saved && /^[A-Za-z0-9_-]{16,120}$/.test(saved) ? saved : null;
      const prefs = data.preferences || {interests: [], priorities: "", sources: ["event", "task", "note", "files"], max_items: 3};
      const sources = data.available_sources || [];
      host.innerHTML = `
        <details class="setup-guide"><summary>简报偏好（读取于 ${new Date().toLocaleTimeString("zh-CN", {hour: "2-digit", minute: "2-digit"})}）</summary>
        <form id="brief-pref-form" class="pj-panel">
          <label class="field-help" for="bp-interests">我的兴趣（最多 8 项，逗号分隔，每项 1–60 字）</label>
          <input id="bp-interests" maxlength="600" value="${esc((prefs.interests || []).join(", "))}">
          <label class="field-help" for="bp-priorities">关注重点（最多 1000 字）</label>
          <textarea id="bp-priorities" rows="3" maxlength="1000">${esc(prefs.priorities || "")}</textarea>
          <p class="field-help">来源（1–5 项）</p>
          ${sources.map(src => `<label class="memory-check"><input type="checkbox" name="bp-source" value="${esc(src.id)}" ${(prefs.sources || []).includes(src.id) ? "checked" : ""} ${src.state === "unavailable" ? "disabled" : ""}>${esc(src.label || sourceLabels[src.id] || src.id)} · ${esc(stateLabels2[src.state] || src.state)}${src.count !== undefined ? "（" + src.count + "）" : ""}${src.truncated ? "+" : ""}</label>`).join("")}
          <label class="field-help" for="bp-max">首屏重点数量（1–3）</label>
          <select id="bp-max">${[1, 2, 3].map(n => `<option value="${n}" ${prefs.max_items === n ? "selected" : ""}>${n}</option>`).join("")}</select>
          <button class="secondary msg-submit" type="submit">保存偏好</button>
          <p class="inline-feedback" role="status"></p>
        </form>
        <div id="brief-automation" aria-label="每天自动准备简报"></div></details>`;
      $("brief-pref-form").addEventListener("submit", savePreferences);
      renderAutomation().catch(() => {});
    } catch (error) {host.innerHTML = `<p class="field-help">${esc(error.message)}</p>`;}
  }
  async function savePreferences(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const feedback = form.querySelector(".inline-feedback");
    const interests = [...new Set(form.querySelector("#bp-interests").value.split(/[,，]/).map(v => v.trim()).filter(Boolean))].slice(0, 8);
    if (interests.some(v => v.length > 60)) {feedback.textContent = "每项兴趣最多 60 字。"; return;}
    const sources = [...form.querySelectorAll("[name=bp-source]:checked")].map(n => n.value);
    if (!sources.length || sources.length > 5) {feedback.textContent = "请选择 1–5 个来源。"; return;}
    const body = {interests, priorities: form.querySelector("#bp-priorities").value.slice(0, 1000), sources,
      max_items: Number(form.querySelector("#bp-max").value), revision: prefRevision,
      request_key: prefRequestKey || (prefRequestKey = window.WearingIds.uuid().replaceAll("-", ""), window.WearingStore.set(prefKey(), prefRequestKey), prefRequestKey)};
    busy(form.querySelector(".msg-submit"), async () => {
      try {
        const result = await api("/api/briefings/preferences", {method: "POST", body: JSON.stringify(body)});
        if (result.request_key !== body.request_key) throw new Error("回执与本次请求不一致，请重试。");
        prefRevision = result.revision;
        feedback.textContent = "偏好已保存。";
        await loadPreferences();
      } catch (error) {
        if (error.status === 409) {feedback.textContent = (error.message || "") + " 已重新读取最新版，请核对后再保存。"; prefRequestKey = null; window.WearingStore.remove(prefKey()); await loadPreferences(); return;}
        throw error;
      }
    }, feedback);
  }
  /* ---------- 每天自动准备简报（briefing-automation-contract） ---------- */
  const dayStateLabels = {pending: "等待中", claimed: "已领取", generated: "已生成", skipped: "已跳过", used_existing: "沿用当天手动简报"};
  let autoData = null;
  const autoJournalKey = () => `pajio-brief-auto-request:v1:${state.identityId}`;
  function readAutoJournal() { try { return JSON.parse(window.WearingStore.get(autoJournalKey()) || "null"); } catch { return null; } }
  function writeAutoJournal(body) { try { window.WearingStore.set(autoJournalKey(), JSON.stringify(body)); } catch {} }
  function clearAutoJournal() { try { window.WearingStore.remove(autoJournalKey()); } catch {} }

  async function renderAutomation(preferred = null) {
    const host = $("brief-automation");
    if (!host) return;
    const epoch = state.identityEpoch;
    let data = null, failure = "";
    try { data = await api("/api/briefing-automation"); } catch (error) { failure = error.message || "自动简报设置暂时读不到。"; }
    if (epoch !== state.identityEpoch) return;
    autoData = data;
    if (!data) { host.innerHTML = `<p class="field-help">${esc(failure)}</p>`; return; }
    const values = preferred || {enabled: data.enabled, time: data.local_time, grace: data.grace_minutes, timezone: data.timezone || tz()};
    const prefNote = data.preferences_revision == null
      ? "自动安排尚未绑定偏好版本；开启保存时会记录当前偏好。"
      : `自动安排使用偏好版本 ${data.preferences_revision}` + (data.enabled && prefRevision && data.preferences_revision !== prefRevision ? `（当前偏好版本 ${prefRevision}；保存偏好后需再保存自动安排才会扩大来源）` : "");
    const receipts = (data.receipts || []).slice(0, 7).map(r =>
      `<li>${esc(r.local_date)} · ${esc(dayStateLabels[r.state] || r.state)}${r.briefing ? ` · 简报第 ${r.briefing.version} 版（${esc(stateLabels[r.briefing.state] || r.briefing.state)}）` : ""}</li>`).join("");
    host.innerHTML = `<details class="setup-guide"><summary>每天自动准备简报${data.enabled ? " · 已开启" : ""}</summary>
      <form id="brief-auto-form" class="pj-panel">
        <label class="memory-check"><input class="ba-enabled" type="checkbox" ${values.enabled ? "checked" : ""}>每天自动准备简报</label>
        <label class="field-help" for="ba-time">每天的时间（按所选时区的钟点）</label>
        <input class="ba-time" id="ba-time" type="time" value="${esc(values.time)}" required>
        <label class="field-help" for="ba-grace">补做窗口（错过时间后多久内仍补当天）</label>
        <select class="ba-grace" id="ba-grace">${[30, 60, 120].map(m => `<option value="${m}" ${values.grace === m ? "selected" : ""}>${m} 分钟</option>`).join("")}</select>
        <details><summary>时区设置（当前 ${esc(values.timezone)}）</summary><label class="field-help" for="ba-tz">IANA 时区；已保存设置固定使用所选时区，旅行时不自行改变。</label><input class="ba-tz" id="ba-tz" maxlength="80" value="${esc(values.timezone)}"></details>
        <p class="field-help">${esc(prefNote)}</p>
        ${data.needs_resave ? '<p class="field-help">定时规则在别处改过；请重新保存自动安排后才会按新授权执行。</p>' : ""}
        ${data.enabled ? `<p class="field-help">下一次：${esc(data.next_run || "待安排")}${data.schedule_status ? ` · 定时状态 ${esc(data.schedule_status)}` : ""}</p>` : ""}
        <p class="inline-feedback" role="status"></p>
        <button class="secondary msg-submit" type="submit">保存自动安排</button>
      </form>
      ${receipts ? `<section class="pj-section"><p class="pj-section-title">最近回执 · 最多 7 条</p><ul class="pj-note">${receipts}</ul></section>` : ""}
      <p class="pj-note">由常驻服务在到期时自动整理；手机或网页关闭不影响已安排的轮次，保存不会立即生成简报。</p></details>`;
    $("brief-auto-form").addEventListener("submit", saveAutomation);
  }

  async function saveAutomation(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const feedback = form.querySelector(".inline-feedback");
    const timezone = form.querySelector(".ba-tz").value.trim() || tz();
    try { new Intl.DateTimeFormat("en-US", {timeZone: timezone}); } catch { feedback.textContent = "请填写有效的 IANA 时区。"; return; }
    const local_time = form.querySelector(".ba-time").value || "08:00";
    if (!/^(?:[01]\d|2[0-3]):[0-5]\d$/.test(local_time)) { feedback.textContent = "请选择每天的时间。"; return; }
    const body = {revision: autoData?.revision ?? 0, request_key: window.WearingIds.uuid().replaceAll("-", ""),
      enabled: form.querySelector(".ba-enabled").checked, local_time, timezone,
      grace_minutes: Number(form.querySelector(".ba-grace").value), preferences_revision: prefRevision};
    // 发出请求前持久化：未知结果用同一 key+body 取回同一次保存。
    writeAutoJournal(body);
    busy(form.querySelector(".msg-submit"), async () => {
      try {
        const receipt = await api("/api/briefing-automation", {method: "POST", body: JSON.stringify(body)});
        if (!receipt || receipt.request_key !== body.request_key || receipt.revision !== body.revision + 1)
          throw new Error("回执与本次保存不一致，已保留请求，可安全重试取回。");
        clearAutoJournal();
        feedback.textContent = `自动安排已保存${receipt.enabled ? "" : "（已关闭）"}${receipt.next_run ? `；下一次 ${receipt.next_run}` : ""}。`;
        await renderAutomation();
      } catch (error) {
        if (error.status === 409) {
          clearAutoJournal();
          feedback.textContent = (error.message || "自动简报已在别处修改。") + " 已重新读取最新设置，请核对后再保存。";
          await renderAutomation({enabled: body.enabled, time: body.local_time, grace: body.grace_minutes, timezone: body.timezone});
          return;
        }
        throw error;
      }
    }, feedback);
  }

  async function resumeAutomation() {
    const pending = readAutoJournal();
    if (!pending) return;
    try {
      const receipt = await api("/api/briefing-automation", {method: "POST", body: JSON.stringify(pending)});
      if (receipt && receipt.request_key === pending.request_key) {
        clearAutoJournal();
        $("brief-feedback").textContent = "上一次自动安排保存已确认。";
        await renderAutomation();
      }
    } catch (error) {
      if (error && error.status) clearAutoJournal();
    }
  }

  $("brief-list").addEventListener("click", event => {
    const artifact = event.target.closest("[data-brief-artifact]");
    if (artifact) { window.WearingArtifacts?.open?.(artifact.dataset.briefArtifact); return; }
    const task = event.target.closest("[data-brief-task]");
    if (task) { closePanel("brief-panel"); window.WearingActivity?.openTask(task.dataset.briefTask)?.catch(() => {}); }
  });
  window.WearingBriefings = {open, load};
})();
