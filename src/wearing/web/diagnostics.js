"use strict";
/* 脱敏诊断（Web）：对齐 diagnostics-contract.md 与 App diagnostics-client.ts（只读参考）。
   关键差异（本轮复核修正）：
   - 不原样导出服务端 JSON：按 App diagnosticSnapshot 的白名单重建投影对象，
     服务端新增字段不会进入预览/下载；identity 校验后保留、其余身份标识不进导出。
   - AbortController：切换身份取消在途请求；Blob URL 下载后 revoke。 */
(() => {
  if (document.documentElement.classList.contains("mobile-host")) return;
  const $ = id => document.getElementById(id);
  const esc = text => String(text ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const taskPhases = new Set(["draft", "queued", "starting", "running", "waiting_for_approval", "stopping", "connection_lost", "ambiguous", "failed", "stopped", "completed_unverified", "verified", "closed", "unknown"]);
  const phases = new Set(["idle", "downloading", "installing", "ready", "running", "failed", "stopped", "unknown"]);
  const serverErrors = new Set(["engine_connection_lost", "run_state_unknown", "run_failed", "stop_unconfirmed", "operation_failed"]);
  let report = null, blobUrl = null, inFlight = null, lastEpoch = 0;

  const invalid = () => {throw new Error("诊断回执无法核对，请重试。");};
  const object = v => v && typeof v === "object" && !Array.isArray(v) ? v : invalid();
  const option = (v, set) => typeof v === "string" && set.has(v) ? v : invalid();
  const bool = v => typeof v === "boolean" ? v : invalid();
  const maybeBool = v => v === null ? null : bool(v);
  const integer = (v, max) => Number.isSafeInteger(v) && v >= 0 && v <= max ? v : invalid();
  const iso = v => {if (typeof v !== "string" || !/^\d{4}-\d\d-\d\dT/.test(v) || !Number.isFinite(Date.parse(v))) invalid(); return new Date(v).toISOString();};
  const maybeIso = v => v === null ? null : iso(v);
  const reference = v => {if (typeof v !== "string" || !/^(?:[a-f0-9]{32}|run_[a-f0-9]{32}|ref_[a-f0-9]{16})$/.test(v)) invalid(); return v;};
  const rows = (v, limit) => {if (!Array.isArray(v) || v.length > limit) invalid(); return v;};

  /** 白名单投影：永远新建对象，服务端升级无法夹带日志/凭据进导出。 */
  function project(rawValue, identity) {
    const raw = object(rawValue);
    if (raw.schema !== 1 || raw.identity_id !== identity || !/^[a-f0-9]{32}$/.test(String(raw.report_id))) invalid();
    const service = object(raw.service), runtime = object(raw.runtime), connectors = object(runtime.connectors);
    const probe = object(raw.engine_probe), devices = object(raw.devices), tasks = object(raw.tasks);
    if (tasks.limit !== 30 || tasks.long_phase_seconds !== 900) invalid();
    const connector = key => {const row = object(connectors[key]); return {phase: option(row.phase, phases), active: maybeBool(row.active), error_present: bool(row.error_present)};};
    return {schema: 1, report_id: raw.report_id, identity_id: identity, captured_at: iso(raw.captured_at),
      service: {state: option(service.state, new Set(["reachable"])), version: typeof service.version === "string" && service.version.length <= 24 ? service.version : null, deployment: option(service.deployment, new Set(["local", "cloud", "synthetic", "unknown"]))},
      runtime: {state: option(runtime.state, new Set(["observed", "unavailable"])), observed_at: iso(runtime.observed_at), phase: option(runtime.phase, phases), installed: maybeBool(runtime.installed), running: maybeBool(runtime.running), error_present: bool(runtime.error_present), connectors: {files: connector("files"), phone: connector("phone"), computer: connector("computer")}},
      engine_probe: {state: option(probe.state, new Set(["reachable", "unavailable", "not_configured", "not_observed", "timeout"])), observed_at: maybeIso(probe.observed_at)},
      devices: {state: option(devices.state, new Set(["observed", "not_observed", "unavailable"])), observed_at: maybeIso(devices.observed_at), truncated: bool(devices.truncated), items: rows(devices.items, 30).map(value => {const d = object(value); return {kind: option(d.kind, new Set(["computer", "phone", "browser", "desktop", "android", "ios", "other"])), connected: maybeBool(d.connected), online: maybeBool(d.online), paused: maybeBool(d.paused), control_pending: maybeBool(d.control_pending), needs_review: maybeBool(d.needs_review), last_seen_at: maybeIso(d.last_seen_at)};})},
      tasks: {limit: 30, long_phase_seconds: 900, truncated: bool(tasks.truncated), items: rows(tasks.items, 30).map(value => {const t = object(value); return {task_id: reference(t.task_id), run_id: t.run_id === null ? null : reference(t.run_id), phase: option(t.phase, taskPhases), attempt: integer(t.attempt, 100000), created_at: maybeIso(t.created_at), record_updated_at: maybeIso(t.record_updated_at), last_state_event_at: maybeIso(t.last_state_event_at), seconds_without_state_change: t.seconds_without_state_change === null ? null : integer(t.seconds_without_state_change, 86400), needs_progress_check: bool(t.needs_progress_check), error_category: t.error_category === null ? null : option(t.error_category, serverErrors)};})}};
  }
  window.WearingDiagnosticsProject = project;

  function summarize(data) {
    const probe = data.engine_probe, devices = data.devices;
    const rowsOut = [
      ["服务", `${data.service.deployment} · ${data.service.version || "?"}`],
      ["运行环境", data.runtime.state],
      ["引擎探测", {reachable: "本次 HTTP 可达", not_configured: "未配置", not_observed: "未观测", timeout: "超时", unavailable: "不可用"}[probe.state] || probe.state],
      ["设备", devices.state === "not_observed" ? "未观测（无真实租约不推断在线）" : `${devices.items.length} 项资源${devices.truncated ? "（已截断）" : ""}`],
      ["最近任务", `${data.tasks.items.length} 项${data.tasks.truncated ? "（已截断）" : ""}${data.tasks.items.some(t => t.needs_progress_check) ? " · 有任务需核对进展" : ""}`],
    ];
    return rowsOut.map(([k, v]) => `<div class="me-row me-row-static"><div><strong>${esc(k)}</strong></div><span class="me-state">${esc(String(v))}</span></div>`).join("");
  }

  function teardown() {
    if (blobUrl) {URL.revokeObjectURL(blobUrl); blobUrl = null;}
  }

  async function generate() {
    // 切换身份取消在途请求；旧报告与新身份无关。
    if (lastEpoch !== state.identityEpoch) {if (inFlight) inFlight.abort(); teardown(); report = null;}
    lastEpoch = state.identityEpoch;
    const controller = new AbortController();
    inFlight = controller;
    const host = $("diagnostics-body");
    host.innerHTML = '<p class="field-help">正在读取（至多 5 秒只读检查）……</p>';
    const epoch = state.identityEpoch;
    try {
      const raw = await fetch("/api/diagnostics", {headers: {"X-Wearing-Identity": state.identityId}, signal: controller.signal}).then(r => r.json());
      if (epoch !== state.identityEpoch) return;
      const data = project(raw, state.identityId);
      if (epoch !== state.identityEpoch) return;
      report = data;
      teardown();
      const json = JSON.stringify(data, null, 2);
      blobUrl = URL.createObjectURL(new Blob([json], {type: "application/json"}));
      host.innerHTML = `<div class="me-group">${summarize(data)}</div>
        <div class="brief-actions diag-actions">
          <details class="setup-guide"><summary>预览投影 JSON（白名单字段）</summary><pre class="cloud-doc-pre">${esc(json)}</pre></details>
          <a class="secondary" href="${blobUrl}" download="pajio-diagnostics-${esc(String(data.report_id).slice(0, 8))}.json">下载 JSON</a>
          <button class="text-button" type="button" data-diagnostics-regen>重新生成</button>
        </div>
        <p class="field-help">导出为白名单投影：不含身份名称、地址、令牌或原始错误文本；仅本机保存，无自动上传。</p>`;
      host.querySelector("[data-diagnostics-regen]").addEventListener("click", generate);
      await renderHealthHistory();
    } catch (error) {
      if (epoch !== state.identityEpoch || error?.name === "AbortError") return;
      host.innerHTML = `<p class="pj-error">${esc(error.message)}</p><button class="text-button" type="button" data-diagnostics-regen>重试</button><p class="field-help">离线时无法读取服务状态；报告会如实标注缺失来源。</p>`;
      host.querySelector("[data-diagnostics-regen]")?.addEventListener("click", generate);
    }
  }

  /* ---------- 持久健康历史（health-history-contract） ---------- */
  const statusLabels = {ok: "正常", fault: "故障", review: "需核对", waiting: "等待决定", inactive: "未运行", ended: "已结束", unknown: "未知", not_configured: "未配置"};
  const componentLabels = {runtime: "运行环境", engine: "引擎", devices: "设备", task: "任务", collector: "采集"};
  async function renderHealthHistory(samplesCursor, eventsCursor) {
    const host = document.getElementById("health-history-body");
    if (!host) return;
    host.innerHTML = '<p class="field-help">正在读取健康历史……</p>';
    try {
      const params = new URLSearchParams();
      if (samplesCursor) params.set("samples_cursor", samplesCursor);
      if (eventsCursor) params.set("events_cursor", eventsCursor);
      const data = await api("/api/diagnostics/history" + (params.size ? "?" + params : ""));
      const samples = data.samples || [], events = data.events || [];
      host.innerHTML = `
        <details class="setup-guide" open><summary>最近观测（${samples.length}）</summary>
        ${samples.map(row => `<div class="me-row me-row-static"><div><strong>${new Date(row.observed_at).toLocaleString("zh-CN")}</strong><small>${(row.components || []).map(c => `${componentLabels[c.component] || c.component}:${statusLabels[c.status] || c.status}`).join(" · ")}</small></div></div>`).join("") || '<p class="field-help">还没有观测记录。</p>'}
        ${data.next_samples_cursor ? '<button class="text-button" type="button" data-health-samples-more>更早观测</button>' : ""}
        </details>
        <details class="setup-guide"><summary>状态事件（${events.length}）</summary>
        ${events.map(row => `<div class="me-row me-row-static"><div><strong>${new Date(row.observed_at).toLocaleString("zh-CN")}</strong><small>${esc(row.kind)} · ${componentLabels[row.component] || row.component}${row.code ? " · " + esc(row.code) : ""}</small></div></div>`).join("") || '<p class="field-help">还没有状态事件。</p>'}
        ${data.next_events_cursor ? '<button class="text-button" type="button" data-health-events-more>更早事件</button>' : ""}
        </details>
        <p class="field-help">读取历史不发起探测；观测间隔约 ${Math.round((data.coverage?.sample_interval_seconds || 300) / 60)} 分钟，保留 ${Math.round((data.coverage?.retention_seconds || 604800) / 86400)} 天。未采样期间不补造历史。</p>`;
      host.querySelector("[data-health-samples-more]")?.addEventListener("click", () => renderHealthHistory(data.next_samples_cursor));
      host.querySelector("[data-health-events-more]")?.addEventListener("click", () => renderHealthHistory(undefined, data.next_events_cursor));
    } catch (error) {host.innerHTML = `<p class="field-help">${esc(error.message)}</p>`;}
  }
  async function createSupportExport() {
    const button = document.querySelector("[data-health-export]");
    busy(button, async () => {
      const keyName = `pajio.health-export-request:v1:${state.identityId}`;
      let key = null; try {key = window.WearingStore.get(keyName);} catch {}
      if (!key || !/^[A-Za-z0-9_-]{16,120}$/.test(key)) {key = window.WearingIds.uuid().replaceAll("-", ""); window.WearingStore.set(keyName, key);}
      const receipt = await api("/api/diagnostics/exports", {method: "POST", body: JSON.stringify({request_key: key, category: "performance"})});
      if (!/^[a-f0-9]{32}$/.test(String(receipt.id || "")) || !/^[a-f0-9]{64}$/.test(String(receipt.sha256 || "")) || !/^pajio-diagnostics-[a-f0-9]{32}\.json$/.test(String(receipt.filename || ""))) throw new Error("导出回执不完整，请重试。");
      window.WearingStore.remove(keyName);
      document.getElementById("health-export-result").innerHTML = `支持包已创建：${esc(receipt.filename)} · ${(receipt.bytes / 1024).toFixed(1)} KB · SHA256 ${esc(String(receipt.sha256).slice(0, 12))}… · 有效期 24 小时。<div class="brief-actions"><a class="secondary" href="/api/diagnostics/exports/${encodeURIComponent(receipt.id)}/file" download>下载支持包</a></div><p class="field-help">下载不等于已分享或已发支持；没有自动发送。</p>`;
    }, document.getElementById("health-export-result"));
  }
  document.addEventListener("click", event => {
    if (event.target.closest("[data-health-export]")) {createSupportExport(); return;}
  });

  window.addEventListener("pagehide", teardown);
  window.WearingDiagnostics = {generate, teardown};
})();
