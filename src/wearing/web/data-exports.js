"use strict";
/* 当前身份数据导出（Web）：创建/列表找回/下载校验/有效期/遗漏说明。
   对齐 identity_export_api.py 与 App data-export.ts（只读参考）：
   POST {request_key} 幂等（localStorage 按身份+键持久，跨标签页同一键）；
   下载校验 size 与 zip MIME；遗漏逐条呈现，不假装完整。凭据零存储。 */
(() => {
  if (document.documentElement.classList.contains("mobile-host")) return;
  const $ = id => document.getElementById(id);
  const esc = text => String(text ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const KEY = () => `pajio.data-export:v1:${state.identityId}`;
  function readKey() { try { return window.WearingStore.get(KEY()); } catch { return null; } }
  function writeKey(key) { try { window.WearingStore.set(KEY(), key); } catch {} }

  const valid = (item, identity) => item && /^[0-9a-f]{32}$/.test(item.id) && item.identity_id === identity
    && /^[0-9a-f]{64}$/.test(item.sha256) && /^pajio-data-[0-9a-f]{8}\.zip$/.test(item.filename)
    && Number.isFinite(item.created_at) && Number.isFinite(item.expires_at) && item.expires_at > item.created_at
    && Number.isSafeInteger(item.size) && item.size > 0 && item.size <= 15 * 1024 * 1024
    && item.omitted !== undefined;

  function row(item) {
    const minutes = Math.max(0, Math.round((item.expires_at * 1000 - Date.now()) / 60000));
    const omitted = (item.omitted || []).map(o => `<li>${esc(o.section)}${o.path ? " · " + esc(o.path) : ""}：${esc(o.reason)}</li>`).join("");
    const counts = Object.entries(item.counts || {}).map(([k, v]) => `${esc(k)} ${v}`).join(" · ");
    return `<div class="pj-card pj-card-block">
      <div class="brief-item-head"><strong>${esc(item.filename)}</strong><small>${(item.size / 1024).toFixed(1)} KB · 剩余 ${minutes} 分钟</small></div>
      <small class="brief-sources">${counts || "无记录"}${item.workspace_count ? ` · 工作区清单 ${item.workspace_count} 项` : ""} · SHA256 ${esc(item.sha256.slice(0, 12))}…</small>
      ${omitted ? `<details class="setup-guide"><summary>未包含的内容（${item.omitted.length} 项）</summary><ul>${omitted}</ul></details>` : '<small class="brief-sources">无遗漏项。</small>'}
      <div class="brief-actions"><a class="secondary" href="/api/data-exports/${item.id}/file" download>下载 ZIP</a></div>
    </div>`;
  }

  async function load() {
    try {
      const data = await api("/api/data-exports");
      const items = ((Array.isArray(data) ? data : data.items || data.exports) || []).filter(item => valid(item, state.identityId));
      $("data-export-body").innerHTML = (items.length ? items.map(row).join("") : '<p class="field-help">还没有可下载的数据副本；点「生成数据副本」打包当前身份在服务端保存的数据。</p>')
        + (items.length ? '<button class="primary" id="data-export-create" type="button">生成新的数据副本</button>' : '<button class="primary" id="data-export-create" type="button">生成数据副本</button>');
      $("data-export-create").addEventListener("click", create);
      $("data-export-feedback").textContent = "";
    } catch (error) {
      if (!(error instanceof StaleIdentity)) $("data-export-body").innerHTML = `<p class="field-help">${esc(error.message)}</p>`;
    }
  }

  async function create() {
    const button = $("data-export-create");
    busy(button, async () => {
      let key = readKey();
      if (!key || !/^[A-Za-z0-9_-]{16,120}$/.test(key)) {key = window.WearingIds.uuid().replaceAll("-", ""); writeKey(key);}
      const result = await api("/api/data-exports", {method: "POST", body: JSON.stringify({request_key: key})});
      if (!valid(result, state.identityId)) throw new Error("导出回执不完整，请稍后在列表中找回。");
      $("data-export-feedback").textContent = `已生成 ${result.filename}，有效期 30 分钟。`;
      await load();
    }, $("data-export-feedback"));
  }

  window.WearingDataExports = {load};
})();
