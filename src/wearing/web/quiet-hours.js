"use strict";
/* 安静时段（Web）：对齐 quiet-hours-contract.md。
   GET/POST /api/notifications/preferences?installation_id=…：revision CAS（409 保留输入、
   重读核对后由用户再次保存）；开始=结束拒绝；时段由服务端在发出前计算，
   本页不声称已推送或已静音。installation_id 每安装稳定（localStorage 非个人内容键）。 */
(() => {
  if (document.documentElement.classList.contains("mobile-host")) return;
  const $ = id => document.getElementById(id);
  const esc = text => String(text ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const INSTALL_KEY = "pajio.installation:v1";
  function installationId() {
    let id = null; try {id = localStorage.getItem(INSTALL_KEY);} catch {}
    if (!id || !/^[A-Za-z0-9_-]{8,80}$/.test(id)) {id = window.WearingIds.uuid(); try {localStorage.setItem(INSTALL_KEY, id);} catch {}}
    return id;
  }
  const minute = value => {const [h, m] = value.split(":").map(Number); return h * 60 + (m || 0);};
  const hhmm = value => `${String(Math.floor(value / 60)).padStart(2, "0")}:${String(value % 60).padStart(2, "0")}`;

  async function load() {
    const host = $("quiet-hours-body");
    try {
      const data = await api(`/api/notifications/preferences?installation_id=${encodeURIComponent(installationId())}`);
      render(data);
    } catch (error) {
      if (!(error instanceof StaleIdentity)) host.innerHTML = `<p class="field-help">${esc(error.message)}</p>`;
    }
  }

  function render(data) {
    const tz = data.timezone || "Asia/Shanghai";
    $("quiet-hours-body").innerHTML = `
      <form id="quiet-hours-form" class="pj-panel">
        <label class="memory-check"><input type="checkbox" id="qh-enabled" ${data.enabled ? "checked" : ""}>开启安静时段</label>
        <p class="field-help">安静时段内不发送通知，任务照常运行、本页结果随时可看；时段结束后只发送仍有效的进展，过期内容不补发。通知登记到期时，需要重新登录并开启通知后才会恢复；保存不保证手机已经显示。</p>
        <div class="schedule-fields">
          <label>开始<input type="time" id="qh-start" value="${hhmm(data.start_minute ?? 1320)}" required></label>
          <label>结束<input type="time" id="qh-end" value="${hhmm(data.end_minute ?? 480)}" required></label>
        </div>
        <label>时区<input id="qh-timezone" value="${esc(tz)}" required></label>
        <input type="hidden" id="qh-revision" value="${Number(data.revision ?? 0)}">
        <button class="secondary msg-submit" type="submit">保存</button>
      </form>`;
    $("quiet-hours-form").addEventListener("submit", save);
  }

  async function save(event) {
    event.preventDefault();
    const feedback = $("quiet-hours-feedback");
    const start = minute($("qh-start").value), end = minute($("qh-end").value);
    if (start === end) {feedback.textContent = "开始与结束不能相同。"; return;}
    const body = {installation_id: installationId(), revision: Number($("qh-revision").value || 0),
      enabled: $("qh-enabled").checked, start_minute: start, end_minute: end, timezone: $("qh-timezone").value.trim()};
    const button = $("quiet-hours-form").querySelector(".msg-submit");
    busy(button, async () => {
      const result = await api(`/api/notifications/preferences?installation_id=${encodeURIComponent(body.installation_id)}`, {method: "POST", body: JSON.stringify(body)});
      feedback.textContent = result.enabled ? "已保存。安静时段结束后会发送仍有效的进展；通知登记到期时，需要重新登录并开启通知。" : "已关闭安静时段。";
      render(result);
    }, feedback); // 409/失败：表单输入保留，feedback 显示原因，用户重读后再保存
  }

  window.WearingQuietHours = {load};
})();
