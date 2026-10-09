"use strict";
/* 工作区文档编辑（Web）：对齐 workspace-text-edit-contract 与 App WorkspaceTextEditor（只读参考）。
   GET /api/workspace/text?path= 读取（revision/sha256/恢复历史/imports copy 模式）；
   POST 保存（base_revision+base_sha256+request_key 持久幂等；409 保留草稿并对比最新版；
   423 如实显示）；GET recovery 把版本放进草稿（需用户再确认保存）。 */
(() => {
  if (document.documentElement.classList.contains("mobile-host")) return;
  const $ = id => document.getElementById(id);
  const esc = text => String(text ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const requestKeyFor = path => {
    const keyName = `pajio.text-request:v1:${state.identityId}:${path}`;
    let key = null; try {key = window.WearingStore.get(keyName);} catch {}
    if (!key || !/^[A-Za-z0-9_-]{16,80}$/.test(key)) {key = window.WearingIds.uuid().replaceAll("-", ""); window.WearingStore.set(keyName, key);}
    return key;
  };
  const clearRequestKey = path => {try {window.WearingStore.remove(`pajio.text-request:v1:${state.identityId}:${path}`);} catch {}};
  const draftKey = path => `pajio.text-draft:v1:${state.identityId}:${path}`;

  async function open(path) {
    const host = document.querySelector("#artifact-body");
    closePanel("files-panel");
    if (!document.getElementById("text-editor-panel").open) openPanel("text-editor-panel");
    $("text-editor-title").textContent = path.split("/").pop() || path;
    $("text-editor-status").textContent = "正在打开文档……";
    $("text-editor-body").innerHTML = "";
    try {
      const data = await api(`/api/workspace/text?path=${encodeURIComponent(path)}`);
      if (data.identity_id !== state.identityId) throw new Error("回执身份不一致。");
      render(data);
    } catch (error) { $("text-editor-status").textContent = error.message || "暂时打不开这份文档。"; }
  }

  function render(data) {
    $("text-editor-status").textContent = "";
    const editable = data.editable === true; // 后端对 md/txt 返回 editable 布尔；其他类型无此字段或 false
    const copyMode = data.save_mode === "copy";
    $("text-editor-body").innerHTML = `
      <p class="field-help">${esc(data.path)} · ${(data.size / 1024).toFixed(1)} KB · 修改于 ${new Date(data.modified).toLocaleString("zh-CN")}${copyMode ? " · 导入原件，保存将另存可编辑副本" : ""}</p>
      ${data.blocked_reason ? `<p class="pj-error">${esc(data.blocked_reason)}</p>` : (!editable && !data.blocked_reason ? '<p class="field-help">这份文件类型不支持直接编辑；可下载或交给 Pajio。</p>' : "")}
      <textarea id="text-editor-area" rows="18" maxlength="65536" ${editable ? "" : "disabled"}>${esc(data.text)}</textarea>
      <div class="brief-actions">
        ${editable ? '<button class="secondary" id="text-editor-save" type="button">保存</button>' : ""}
        ${data.save_mode === "copy" ? '<p class="field-help">这份是导入原件：保存会创建 documents/ 下的可编辑副本，原件保持不变。</p>' : ""}
      </div>
      <p class="inline-feedback" id="text-editor-feedback" role="status"></p>
      ${data.history?.length ? `<details class="setup-guide"><summary>恢复版本（${data.history.length}）</summary>${data.history.map(v => `<div class="me-row me-row-static"><div><strong>${new Date(v.created_at).toLocaleString("zh-CN")}</strong></div><button class="text-button" type="button" data-text-recovery="${esc(v.id)}" data-text-path="${esc(data.path)}">把此版本放进草稿</button></div>`).join("")}</details>` : ""}
      <input type="hidden" id="text-editor-revision" value="${esc(data.revision)}">
      <input type="hidden" id="text-editor-sha" value="${esc(data.sha256)}">
      <input type="hidden" id="text-editor-path" value="${esc(data.path)}">`;
    let baseRevision = data.revision, baseSha = data.sha256, currentPath = data.path;
    const area = $("text-editor-area");
    // 本机草稿保留（离页不丢）；保存成功或按最新版继续时更新/清除
    const saved = window.WearingStore.get(draftKey(currentPath));
    if (saved && saved !== data.text && editable) {area.value = saved; $("text-editor-feedback").textContent = "已恢复未保存的编辑。";}
    area.addEventListener("input", () => window.WearingStore.set(draftKey(currentPath), area.value));
    $("text-editor-save")?.addEventListener("click", () => save());
    $("text-editor-body").querySelectorAll("[data-text-recovery]").forEach(button => button.addEventListener("click", async () => {
      try {
        const recovery = await api(`/api/workspace/text/recovery?path=${encodeURIComponent(button.dataset.textPath)}&version=${encodeURIComponent(button.dataset.textRecovery)}`);
        if (recovery.identity_id !== state.identityId) throw new Error("回执身份不一致。");
        area.value = recovery.text;
        window.WearingStore.set(draftKey(currentPath), recovery.text);
        $("text-editor-feedback").textContent = "此版本已放进草稿；再次点击保存才会真正恢复。";
      } catch (error) { $("text-editor-feedback").textContent = error.message; }
    }));
    async function save() {
      const body = {path: currentPath, text: area.value, base_revision: baseRevision, base_sha256: baseSha, request_key: requestKeyFor(currentPath)};
      busy($("text-editor-save"), async () => {
        try {
          const receipt = await api("/api/workspace/text", {method: "POST", body: JSON.stringify(body)});
          if (receipt.identity_id !== state.identityId || !/^[A-Za-z0-9_-]{16,80}$/.test(receipt.request_key) || receipt.request_key !== body.request_key) throw new Error("保存回执不完整或与本次请求不一致。");
          clearRequestKey(body.path);
          window.WearingStore.remove(draftKey(currentPath));
          currentPath = receipt.path; baseRevision = receipt.revision; baseSha = receipt.sha256;
          $("text-editor-feedback").textContent = receipt.save_mode === "copy" ? `已另存副本：${receipt.path}` : "已保存。";
          render({...receipt, text: area.value, modified: receipt.modified || data.modified, history: data.history, editable: true, save_mode: receipt.save_mode});
        } catch (error) {
          if (error.status === 409) {
            // 读取最新版并对比；用户文字保留，不自动覆盖。
            $("text-editor-feedback").textContent = (error.message || "文档已有变化。") + " 你的文字已保留。";
            try {
              const latest = await api(`/api/workspace/text?path=${encodeURIComponent(currentPath)}`);
              const latestLines = latest.text.split("\n"), myLines = area.value.split("\n");
              let firstDiff = -1;
              for (let i = 0; i < Math.max(latestLines.length, myLines.length); i++) if (latestLines[i] !== myLines[i]) {firstDiff = i + 1; break;}
              $("text-editor-body").insertAdjacentHTML("beforeend", `<details class="setup-guide" id="text-conflict"><summary>读取最新版并比较（首个差异行：${firstDiff > 0 ? "第 " + firstDiff + " 行" : "无差异"}）</summary><pre class="cloud-doc-pre">${esc(latest.text)}</pre>
                <div class="brief-actions"><button class="secondary" id="text-adopt-latest" type="button">按最新版继续编辑，保留我的文字</button></div></details>`);
              $("text-adopt-latest").addEventListener("click", () => {
                baseRevision = latest.revision; baseSha = latest.sha256;
                clearRequestKey(currentPath); // 换 base 需新 request_key
                $("text-conflict")?.remove();
                $("text-editor-feedback").textContent = "已按最新版更新基准；再次点击保存生效。";
              });
            } catch { /* 读取失败保留 409 提示 */ }
            return;
          }
          throw error;
        }
      }, $("text-editor-feedback"));
    }
  }

  document.addEventListener("click", event => {
    const edit = event.target.closest("[data-text-edit]");
    if (edit) {open(edit.dataset.textEdit); return;}
  });
  window.WearingTextEditor = {open};
})();
