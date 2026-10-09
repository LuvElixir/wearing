"use strict";
/* 账户注销（Web）：对齐 account-deletion-control/gateway-contract 与 App AccountDeletionPanel/
   account-deletion-recovery/account-work（只读参考）。
   账户围栏 = gateway origin + user_id（不是身份 id）；旧无归属凭证视为受限（不参与清理判定）。
   提交前持久受限查询凭证；受理即停本账户业务（轮询/语音/发送/异步写回经冻结门），
   重载后凭保存凭证恢复只读状态页；not_submitted 可恢复正常业务。 */
(() => {
  if (document.documentElement.classList.contains("mobile-host")) return;
  const $ = id => document.getElementById(id);
  const esc = text => String(text ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const waitingCodes = new Set(["adapter_unconfigured", "adapter_failed", "adapter_mismatch", "invalid_receipt", "ownership_changed", "instance_busy", "provider_unavailable", "backup_retained", "fixture_busy", "unsafe_storage", "incomplete_registry"]);
  const actionLabels = {erase_private: "个人空间 · 清理账户内容、原件及索引；备份按实际回执处理", leave_shared: "共享空间 · 退出你的成员关系，共同内容保留", blocked: "归属尚未确认 · 暂不能注销"};
  const stateLabels = {awaiting_operator: "申请已收到，等待执行清理", frozen: "账户已冻结，等待数据清理", waiting: "正在执行清理"};

  // ---- 账户围栏：origin + user_id。user_id 只来自可信 plan 回执，绝不从身份 id 推断。 ----
  let accountFence = null;
  const fenceKey = fence => `pajio.deletion-recovery:v1:${fence.origin}|user_${fence.user_id}`;
  function saveFence(fence) {
    // 受限凭证必须确认持久成功——失败返回 false，调用方禁止进入提交路径。
    return window.WearingStore.set(fenceKey(fence), JSON.stringify(fence)) === true;
  }
  function loadFence() {
    const mark = `pajio.deletion-recovery:v1:${location.origin}|user_`;
    const out = [];
    try {
      const backend = window.WearingStore.backend;
      const scoped = window.WearingStore.mode === "scoped";
      const strip = scoped ? ("pajio:" + (window.WearingStore.scope || "") + ":").length : 0;
      for (let index = 0; index < (backend.length ?? 0); index++) {
        const rawKey = backend.key(index);
        if (rawKey === null) continue;
        const key = scoped ? rawKey.slice(strip) : rawKey;
        if (!key || !key.startsWith(mark)) continue;
        try {const value = JSON.parse(window.WearingStore.get(key) || "null"); if (value?.receipt_token && value?.user_id) out.push(value);} catch {}
      }
    } catch {}
    return out;
  }
  function isOwned(rawKey, fence) {
    // scoped 模式的真实业务键 = `pajio:<64hex storage_scope>:<name>`。scope 由可信
    // bootstrap.storage_scope 提供（gateway 构造），同一账户稳定；据此精确前缀清理。
    // local 模式无 scope——键不含归属段，旧凭证保留限制：不清理任何 local 键。
    if (window.WearingStore.mode !== "scoped") return false;
    const scope = window.WearingStore.scope || "";
    const prefix = `pajio:${scope}:`;
    return rawKey.startsWith(prefix);
  }
  function clearAccountCaches(fence) {
    try {
      const keepKey = fenceKey(fence), keep = window.WearingStore.get(keepKey);
      const backend = window.WearingStore.backend, scoped = window.WearingStore.mode === "scoped";
      const strip = scoped ? ("pajio:" + (window.WearingStore.scope || "") + ":").length : 0;
      const targets = [];
      for (let index = 0; index < (backend.length ?? 0); index++) targets.push(backend.key(index));
      for (const rawKey of targets) {
        if (rawKey === null) continue;
        // scoped：按账户 scope 前缀精确清理业务键（WearingStore.key(name) 即该前缀+name）。
        // local：isOwned 恒 false，不清理。
        const businessPrefix = window.WearingStore.mode === "scoped" ? window.WearingStore.key("") : null;
        if (businessPrefix === null) continue;
        if (!rawKey.startsWith(businessPrefix) || rawKey.startsWith(businessPrefix + "pajio.deletion-recovery")) continue;
        if (rawKey.includes("wearing-chat-draft") || rawKey.includes("wearing-voice-received") || rawKey.includes("wearing-native-draft")
          || rawKey.includes("onboarding-draft:v1") || rawKey.includes("onboarding-request:v1")
          || rawKey.includes("chat-import-draft:v1") || rawKey.includes("chat-import-pending:v1")) {
          try {backend.removeItem(rawKey);} catch {}
        }
      }
      if (keep !== null) window.WearingStore.set(keepKey, keep);
    } catch {}
  }

  // ---- 业务冻结门：注销受理后停止本账户的轮询/发送/语音/异步写回；not_submitted 恢复。 ----
  let frozen = false;
  const workGates = new Set();
  function registerWorkGate(gate) {workGates.add(gate); return () => workGates.delete(gate);}
  function workAllowed() {return !frozen;}
  async function freezeAccountWork() {
    frozen = true;
    workGeneration++; // 同步提升代数：旧异步回调写回前比对代数，不写回冻结前状态
    try {state.polling = false;} catch {}
    try {state.sending = false;} catch {}
    await Promise.allSettled([...workGates].map(gate => gate.stop()));
  }
  let workGeneration = 0;
  const generation = () => workGeneration;
  function unfreezeAccountWork() {frozen = false;}

  const object = v => v && typeof v === "object" && !Array.isArray(v) ? v : null;
  function validPlan(value) {
    const data = object(value);
    if (!data || !Array.isArray(data.tenants) || !data.tenants.length) return null;
    for (const row of data.tenants) if (!object(row) || typeof row.tenant_id !== "string" || !["erase_private", "leave_shared", "blocked"].includes(row.action)) return null;
    const key = typeof data.request_key === "string" && /^[A-Za-z0-9_-]{16,120}$/.test(data.request_key) ? data.request_key : null;
    const revision = typeof data.plan_revision === "string" && /^[a-f0-9]{64}$/.test(data.plan_revision) ? data.plan_revision : null;
    const token = typeof data.receipt_token === "string" && /^pdr1\.[A-Za-z0-9_.-]{16,}$/.test(data.receipt_token) ? data.receipt_token : null;
    const user = typeof data.user_id === "string" && /^user_[a-f0-9]{32}$/.test(data.user_id) ? data.user_id : null;
    if (!key || !revision || !token || !user) return null; // 必需字段缺失/不合法即整份计划无效
    return {tenants: data.tenants, blockers: Array.isArray(data.blockers) ? data.blockers : [], ready: data.ready === true,
      revision, request_key: key, receipt_token: token, user_id: user,
      reauth_required: data.reauth_required === true};
  }
  function validStatus(value, fence) {
    if (!object(value)) return null;
    if (value.state === "not_submitted" && value.code === "not_submitted") return {state: "not_submitted", code: "not_submitted"};
    if (!/^[a-f0-9]{32}$/.test(String(value.id)) || value.request_key !== fence.request_key || value.plan_revision !== fence.plan_revision) return null;
    if (["awaiting_operator", "frozen", "waiting"].includes(value.state) && waitingCodes.has(value.code) && value.data_erased === false) return value;
    if (value.state === "completed" && value.code === "verified" && value.data_erased === true) return value;
    return null; // 未知回执一律拒绝，不假成功
  }

  // ---- 网关请求：同源 cookie 会话；POST 携带网关 CSRF 头（值来自服务端 cookie，本页只读）。 ----
  async function gatewayFetch(path, {method = "GET", body, token, csrf} = {}) {
    return fetch(path, {method, ...(body !== undefined ? {body: JSON.stringify(body)} : {}),
      headers: {...(body !== undefined ? {"Content-Type": "application/json"} : {}),
        ...(csrf ? {"x-wearing-csrf": csrf} : {}),
        ...(token ? {Authorization: `Bearer ${token}`} : {})},
      credentials: "include", redirect: "error"});
  }
  let cachedCsrf = null;
  async function csrfToken() {
    // gateway.py:417 —— CSRF 值来自 GET /auth/session 的 csrf 字段。
    if (cachedCsrf) return cachedCsrf;
    try {
      const response = await fetch("/auth/session", {credentials: "include"});
      if (!response.ok) return null;
      const data = await response.json();
      if (typeof data?.csrf === "string" && data.csrf.length >= 16) {cachedCsrf = data.csrf; return cachedCsrf;}
    } catch {}
    return null;
  }

  async function refreshPlan() {
    $("deletion-body").innerHTML = '<p class="field-help">正在读取注销范围……</p>';
    try {
      const response = await gatewayFetch("/auth/account-deletion/plan");
      const data = await response.json().catch(() => null);
      if (!response.ok) throw new Error(typeof data?.detail === "string" ? data.detail : "当前入口未提供账户注销能力（云账户登录后可用）。");
      const plan = validPlan(data);
      if (!plan) throw new Error("注销计划回执不完整，请稍后重试。");
      accountFence = {origin: location.origin, user_id: plan.user_id, request_key: plan.request_key, plan_revision: plan.revision, receipt_token: plan.receipt_token, phase: "pending"};
      if (!saveFence(accountFence)) throw new Error("注销查询凭证未能保存在本机，暂不能提交；请检查存储后重试。"); // 先保存受限查询凭证，再允许任何提交
      render(plan, null);
    } catch (error) { $("deletion-body").innerHTML = `<p class="field-help">${esc(error.message)}</p><button class="text-button" type="button" data-deletion-retry>重试</button>`; }
  }

  async function queryStatus(fence = accountFence) {
    if (!fence) {await refreshPlan(); return;}
    $("deletion-body").innerHTML = '<p class="field-help">正在查询注销状态……</p>';
    try {
      const response = await gatewayFetch("/auth/account-deletion/status", {token: fence.receipt_token});
      const data = await response.json().catch(() => null);
      if (!response.ok) throw new Error(typeof data?.detail === "string" ? data.detail : "当前入口未提供注销状态查询（需云端账户网关）。");
      const status = validStatus(data, fence);
      if (!status) throw new Error("注销状态回执与保存的凭证不一致，请核对后再试。");
      if (status.state === "not_submitted") {
        unfreezeAccountWork(); // 服务尚未收到申请：本账户业务可正常继续
        render(null, status, fence);
        return;
      }
      accountFence = {...fence, phase: "submitted"};
      saveFence(accountFence); // 已提交态回写：此处持久失败不回滚服务端状态，查询凭证仍以 plan 版为准
      await freezeAccountWork();
      clearAccountCaches(accountFence);
      render(null, status, accountFence);
    } catch (error) { $("deletion-body").innerHTML = `<p class="field-help">${esc(error.message)}</p><button class="text-button" type="button" data-deletion-retry>重试</button>`; }
  }

  async function reauth() {
    try {
      const csrf = await csrfToken();
      const response = await gatewayFetch("/auth/account-deletion/reauth", {method: "POST", body: {}, ...(csrf ? {csrf} : {})});
      const data = await response.json().catch(() => null);
      if (!response.ok || typeof data?.authorize_url !== "string") throw new Error("暂时无法开始重新验证，请稍后重试。");
      location.assign(data.authorize_url);
    } catch (error) { $("deletion-feedback").textContent = error.message; }
  }

  async function submit() {
    const button = $("deletion-confirm");
    busy(button, async () => {
      if (!accountFence) throw new Error("查询凭证尚未保存，请先刷新注销范围。");
      try {
        const csrf = await csrfToken();
        const response = await gatewayFetch("/auth/account-deletion/request", {method: "POST",
          body: {request_key: accountFence.request_key, plan_revision: accountFence.plan_revision, receipt_token: accountFence.receipt_token, confirm: "DELETE"},
          ...(csrf ? {csrf} : {})});
        if (response.status !== 202) {
          const data = await response.json().catch(() => null);
          $("deletion-feedback").textContent = typeof data?.detail === "string" ? data.detail : "提交结果未确认；正在用保存的凭证查询这一次申请。";
        }
      } catch { $("deletion-feedback").textContent = "提交响应未送达；正在用保存的凭证查询这一次申请。"; }
      // 无论响应是否送达：先用同一凭证查询，绝不盲目重复提交。
      await queryStatus();
    }, $("deletion-feedback"));
  }

  function render(plan, status, fence = accountFence) {
    const host = $("deletion-body");
    if (status) {
      if (status.state === "not_submitted") {
        host.innerHTML = `<p class="field-help">服务尚未收到这次注销申请，本账户业务可以继续使用。可重新验证身份、查看计划后再确认。</p>
          <div class="brief-actions"><button class="text-button" type="button" data-deletion-retry>重新查看注销范围</button></div>`;
        return;
      }
      const completed = status.state === "completed";
      host.innerHTML = `<div class="pj-panel"><h3>${completed ? "账户清理已完成" : stateLabels[status.state] || "申请处理中"}</h3>
        <p class="pj-caption">${completed ? "服务已核对登记范围内的清理结果；共享空间其他成员内容保留，最小身份注销记录保留。" : "账户业务访问已停止。实际数据清理还在等待执行，当前尚未确认删除完成。"}</p>
        ${!completed && status.code === "adapter_unconfigured" ? '<p class="field-help">清理服务尚未配置，申请与查询凭证已保存。</p>' : ""}
        ${status.id ? `<p class="field-help">申请编号：${esc(status.id)}</p>` : ""}
        <div class="brief-actions"><button class="text-button" type="button" data-deletion-refresh>刷新清理进度</button></div></div>
        <p class="field-help">注销查询凭证只用于查看此申请，不会恢复业务访问。</p>`;
      return;
    }
    if (!plan) return;
    host.innerHTML = `
      <p class="field-help">注销会停止这个账户的业务访问。个人空间按范围清理；共享空间只退出成员关系。浏览器中该账户的草稿与缓存也会清理；其他账户不受影响。</p>
      <div class="pj-panel"><h3>本次涉及 ${plan.tenants.length} 个空间</h3>
        ${plan.tenants.map(row => `<div class="me-row me-row-static"><div><strong>${esc(row.tenant_id)}</strong><small>${esc(actionLabels[row.action] || "")}</small></div></div>`).join("")}
        ${plan.blockers.length ? `<p class="pj-error">有 ${plan.blockers.length} 项归属尚未就绪，需要服务方核对后才能提交。</p>` : ""}
      </div>
      ${plan.reauth_required ? '<div class="brief-actions"><button class="secondary" type="button" id="deletion-reauth">重新验证身份</button></div><p class="field-help">提交前需要重新验证身份（将跳转到账户登录页）。</p>'
        : plan.ready ? `<p class="field-help">确认全部范围后，输入 DELETE 再提交。提交后会退出此账户，可凭本机保存的凭证查看进度。</p>
        <div class="memory-confirm-row"><input id="deletion-confirm-input" placeholder="DELETE" maxlength="6" autocomplete="off"><button class="secondary" id="deletion-confirm" type="button" disabled>确认注销账户</button></div>`
        : '<p class="field-help">当前计划尚未就绪，不能提交。</p>'}
      <p class="inline-feedback" id="deletion-feedback" role="status"></p>`;
    const input = $("deletion-confirm-input");
    if (input) input.addEventListener("input", () => {$("deletion-confirm").disabled = input.value !== "DELETE";});
    $("deletion-reauth")?.addEventListener("click", reauth);
    $("deletion-confirm")?.addEventListener("click", submit);
  }

  document.addEventListener("click", event => {
    if (event.target.closest("[data-deletion-retry]")) {refreshPlan(); return;} // 真实 plan 刷新（刷新会重建凭证），不做 status 循环
    if (event.target.closest("[data-deletion-refresh]")) queryStatus();
  });

  function start() {
    // 启动恢复：已保存的 submitted 凭证 → 先冻结业务，再只读查询状态（在业务轮询启动前）。
    const saved = loadFence();
    const submitted = saved.find(fence => fence.phase === "submitted");
    if (submitted) {accountFence = submitted; freezeAccountWork().then(() => queryStatus());}
    return Boolean(submitted);
  }
  function openPanel() {refreshPlan();}
  window.WearingDeletion = {start, openPanel, refreshPlan, queryStatus, loadFence, saveFence, validPlan, validStatus,
    clearAccountCaches, isOwned, workAllowed, registerWorkGate, freezeAccountWork, unfreezeAccountWork, csrfToken, generation,
    get fence() {return accountFence;}};
})();
