"use strict";
/* 待核对决定（Web）：持久确认卡片的重新核对与继续。
   对齐 confirmation_api.py 与 App pending-decisions.ts（只读参考）：
   GET /api/confirmations {items}；POST /api/confirmations/{id}/resume {revision,request_key}；
   仅 can_resume=true 且 state=needs_recheck 时提供「重新核对并继续」；回执必须 authorized:false
   且带原/恢复 task 与合法 delivery；超时旧授权不复用。request_key 以
   身份+卡片+revision 为粒度持久保存，跨失败重试不换新键。App 宿主不注册。 */
(() => {
  if (document.documentElement.classList.contains("mobile-host")) return;
  const $ = id => document.getElementById(id);
  const esc = text => String(text ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const stateLabels = {pending: "等你确认", sending: "正在核对确认结果", unknown: "确认结果待核对",
    needs_recheck: "等待重新核对", recovering: "正在重新核对",
    executing: "正在执行已确认的操作", execution_unknown: "需核对原结果（不可恢复，只能查看）"};
  const keyFor = row => `confirmation.resume:v1:${state.identityId}:${row.id}:${row.revision}`;
  // 键持久化到 localStorage：标签页关闭/重开后仍是同一键；键内只有 UUID，不含凭据。
  function readKey(row) { try { return window.WearingStore.get(keyFor(row)); } catch { return null; } }
  function writeKey(row, key) { try { window.WearingStore.set(keyFor(row), key); } catch {} }

  const valid = row => row && /^decision_[a-f0-9]{32}$/.test(row.id) && row.identity_id === state.identityId
    && /^[-a-zA-Z0-9_]{1,64}$/.test(row.task_id || "") && Number.isSafeInteger(row.revision) && row.revision >= 1
    && typeof row.state === "string" && typeof row.can_resume === "boolean"
    && row.card && ["title", "action", "impact"].every(k => typeof row.card[k] === "string");

  async function load() {
    try {
      const data = await api("/api/confirmations");
      const items = (data.items || []).filter(valid);
      const host = $("decisions-list");
      host.innerHTML = items.length ? items.map(row => `
        <div class="pj-card pj-card-block" data-decision="${esc(row.id)}">
          <strong>${esc(row.card.title)}</strong>
          <small>${esc(row.card.action)} · ${esc(row.card.impact)}</small>
          <small class="brief-sources">${esc(stateLabels[row.state] || "查看记录")}${row.recovery_task_id ? " · 原任务进行中" : ""}</small>
          ${row.can_resume && row.state === "needs_recheck"
            ? `<div class="brief-actions"><button class="secondary" type="button" data-decision-resume="${esc(row.id)}" data-revision="${row.revision}">重新核对并继续</button></div>`
            : row.state === "needs_recheck" ? '<small class="brief-sources">原任务结束后才能重新核对。</small>' : ""}
        </div>`).join("") : '<p class="field-help">没有等待核对的确认。</p>';
      $("decisions-feedback").textContent = "";
    } catch (error) {
      if (!(error instanceof StaleIdentity)) $("decisions-feedback").textContent = error.message || "暂时读不到确认记录。";
    }
  }

  document.addEventListener("click", async event => {
    const button = event.target.closest("[data-decision-resume]");
    if (!button) return;
    const id = button.dataset.decisionResume;
    busy(button, async () => {
      const row = {id, revision: Number(button.dataset.revision)};
      // 同一身份/卡片/版本跨失败持久保存；同次重试绝不生成新键。
      let key = readKey(row);
      if (!key || !/^[A-Za-z0-9_-]{16,120}$/.test(key)) {key = window.WearingIds.uuid().replaceAll("-", ""); writeKey(row, key);}
      const result = await api(`/api/confirmations/${encodeURIComponent(id)}/resume`, {method: "POST", body: JSON.stringify({revision: row.revision, request_key: key})});
      if (!result || result.authorized !== false || !result.task || !["live_confirmation", "waiting_for_original", "queued", "saved", "submitted"].includes(String(result.delivery))) {
        throw new Error("重新核对的回执不完整，未确认结果；稍后可用同一请求重试。");
      }
      // 成功也保留 key：同 scope/卡片/revision 永远同键，迟到重放不会创建第二次恢复。
      $("decisions-feedback").textContent = "已重新核对并继续；结果会回到对话。";
      await load();
      await loadConversation(true).catch(() => {});
      window.WearingActivity?.openTask?.(result.task.id)?.catch(() => {});
    }, $("decisions-feedback"));
  });

  window.WearingDecisions = {load};
})();
