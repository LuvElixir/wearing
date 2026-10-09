"use strict";
/* Generated pages stay outside the application DOM, including while polling. */
(() => {
  const escape = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const names = {dashboard:"数据看板", diagram:"关系图", interactive:"交互网页"};
  const icon = '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="3"/><path d="M3 9h18M8 13v3m4-4v4m4-2v2"/></svg>';
  window.artifactMarkup = (items = []) => items.length ? `<div class="artifact-results">${items.map(item => `<button class="artifact-card" data-artifact="${escape(item.id)}"><span class="artifact-symbol">${icon}</span><span class="artifact-card-copy"><strong>${escape(item.title)}</strong><span>${escape(item.summary)}</span><small>${escape(names[item.presentation] || "交互结果")} · 版本 ${escape(item.revision)}<span class="artifact-open-label">展开查看</span></small></span><svg class="artifact-arrow" viewBox="0 0 24 24" aria-hidden="true"><path d="m9 5 7 7-7 7"/></svg></button>`).join("")}</div>` : "";

  let sequence = 0, timer = null;
  const panel = document.getElementById("artifact-panel");
  const body = document.getElementById("artifact-body");
  const status = document.getElementById("artifact-status");
  function clear() {
    sequence++;
    clearTimeout(timer);
    body.replaceChildren();
  }
  function url(id, action) {
    return `/api/artifacts/${encodeURIComponent(id)}/${action}?identity=${encodeURIComponent(state.identityId)}`;
  }
  async function open(id) {
    clear();
    const seq = sequence;
    status.textContent = "正在打开结果……";
    status.hidden = false;
    document.getElementById("artifact-title").textContent = "一起看看结果";
    document.getElementById("artifact-description").textContent = "";
    document.getElementById("artifact-evidence").hidden = true;
    document.getElementById("artifact-evidence").open = false;
    document.getElementById("artifact-download").hidden = true;
    document.getElementById("artifact-previous").hidden = true;
    if (!panel.open) openPanel("artifact-panel");
    try {
      const item = await api(`/api/artifacts/${encodeURIComponent(id)}`);
      if (seq !== sequence || !panel.open) return;
      document.getElementById("artifact-title").textContent = item.title;
      document.getElementById("artifact-description").textContent = `${names[item.presentation] || "交互结果"} · 版本 ${item.revision} · ${new Date(item.created_at).toLocaleString("zh-CN", {month:"numeric", day:"numeric", hour:"2-digit", minute:"2-digit"})}`;
      const download = document.getElementById("artifact-download");
      download.href = url(id, "download"); download.hidden = false;
      const previous = document.getElementById("artifact-previous");
      previous.hidden = !item.previous_id; previous.dataset.artifact = item.previous_id || "";
      document.getElementById("artifact-evidence-copy").innerHTML = `<p>${escape(item.summary)}</p>${[["依据",item.sources],["采用的假设",item.assumptions],["还需核对",item.limitations]].map(([title,items]) => items?.length ? `<section><h3>${title}</h3><ul>${items.map(value => `<li>${escape(value)}</li>`).join("")}</ul></section>` : "").join("")}<p class="artifact-check-note">文件已保存。页面呈现和内容正确性仍需核对；页面内的调整只用于试算。</p>`;
      document.getElementById("artifact-evidence").hidden = false;
      const frame = document.createElement("iframe");
      frame.title = item.title;
      frame.setAttribute("sandbox", "allow-scripts");
      frame.setAttribute("referrerpolicy", "no-referrer");
      frame.setAttribute("allow", "camera 'none'; microphone 'none'; geolocation 'none'; payment 'none'; usb 'none'");
      frame.addEventListener("load", () => {
        if (seq !== sequence) return;
        clearTimeout(timer); status.hidden = true;
      });
      frame.addEventListener("error", () => {
        if (seq === sequence) { clearTimeout(timer); status.hidden = false; status.textContent = "页面没有打开。可以下载文件，或关闭后重试。"; }
      });
      frame.src = url(id, "preview");
      body.append(frame);
      await mountChoices(id, item.revision, seq);
      timer = setTimeout(() => {
        if (seq === sequence) { status.hidden = false; status.textContent = "页面打开较慢，可以稍候或下载文件。"; }
      }, 12000);
    } catch (error) {
      if (seq !== sequence) return;
      status.textContent = error.message || "结果暂时无法打开，请稍后重试。";
    }
  }
  /* 结果选项（原生 UI，不向生成 HTML 开任何桥）：完整 instruction 预览 → 二次确认 →
     固定 request_key（身份+结果+选择持久，未知结果同请求取回）；409 保留输入与选择。 */
  let choiceRequest = null;
  function choiceKey(artifactId, choiceId) {return `pajio.artifact-choice:v1:${state.identityId}:${artifactId}:${choiceId}`;}
  async function mountChoices(artifactId, artifactRevision, seq) {
    const host = document.getElementById("artifact-choices");
    host.replaceChildren();
    try {
      const data = await api(`/api/artifacts/${encodeURIComponent(artifactId)}/choices`);
      if (seq !== sequence || !panel.open) return;
      if (!data.choices?.length) {host.hidden = true; return;}
      if (data.selection) {host.hidden = false; host.innerHTML = `<p class="field-help">已有选择：${escape(String(data.choices.find(c => c.id === data.selection.choice_id)?.label || data.selection.choice_id))}。后续任务${data.selection.queue_state === "queued" || data.selection.task_status === "queued" ? "已排队，尚未执行" : data.selection.task_status === "draft" ? "已保存，等待开始" : "进行中"}。</p>`; return;}
      if (data.newer_id) {host.hidden = false; host.innerHTML = '<p class="field-help">这份结果已有新版本，请打开最新版本后再选择。</p>'; return;}
      host.hidden = false;
      host.innerHTML = `<h3>选择下一步</h3>` + data.choices.map(choice => `
        <button type="button" class="pj-card artifact-choice" data-choice-id="${escape(choice.id)}">
          <div><strong>${escape(choice.label)}</strong></div>
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m9 6 6 6-6 6"/></svg>
        </button>`).join("") + `<div class="artifact-choice-detail" hidden></div><p class="inline-feedback" role="status" hidden></p>`;
      const detail = host.querySelector(".artifact-choice-detail");
      const feedback = host.querySelector(".inline-feedback");
      let selected = null;
      host.addEventListener("click", async event => {
        const pick = event.target.closest("[data-choice-id]");
        if (pick) {
          selected = pick.dataset.choiceId;
          const choice = data.choices.find(c => c.id === selected);
          detail.hidden = false;
          detail.innerHTML = `<p class="field-help">${escape(choice.instruction)}</p>
            <div class="brief-actions"><button class="secondary" type="button" data-choice-confirm>确认选择，继续处理</button></div>
            <p class="field-help">选择只准备后续任务；201 = 已排队，不是已经执行。</p>`;
          return;
        }
        const confirm = event.target.closest("[data-choice-confirm]");
        if (!confirm || !selected) return;
        confirm.disabled = true;
        const keyName = choiceKey(artifactId, selected);
        let requestKey = null; try {requestKey = window.WearingStore.get(keyName);} catch {}
        if (!requestKey || !/^[A-Za-z0-9_-]{16,100}$/.test(requestKey)) {requestKey = window.WearingIds.uuid().replaceAll("-", ""); window.WearingStore.set(keyName, requestKey);}
        try {
          const receipt = await api(`/api/artifacts/${encodeURIComponent(artifactId)}/choices`, {method: "POST", body: JSON.stringify({request_key: requestKey, choice_id: selected, artifact_revision: artifactRevision, selection_revision: data.revision})});
          if (receipt.artifact_id !== artifactId || receipt.request_key !== requestKey || receipt.choice_id !== selected) throw new Error("选择回执与本次请求不一致，已保留请求可取回。");
          window.WearingStore.remove(keyName);
          feedback.hidden = false; feedback.textContent = "已确认选择，后续任务已排队；结果会回到对话。";
          await loadConversation(true).catch(() => {});
          await mountChoices(artifactId, artifactRevision, seq);
        } catch (error) {
          if (error instanceof StaleIdentity) return;
          confirm.disabled = false;
          feedback.hidden = false; feedback.textContent = (error.message || "这次没有完成。") + " 你的选择保留，稍后可用同一请求重试。";
        }
      });
    } catch (error) {
      if (seq === sequence) {const host2 = document.getElementById("artifact-choices"); host2.hidden = false; host2.innerHTML = `<p class="field-help">${escape(error.message || "选项暂时读不到。")}</p>`;}
    }
  }

  panel.addEventListener("close", clear);
  document.addEventListener("click", event => {
    const button = event.target.closest("[data-artifact]");
    if (button?.dataset.artifact) open(button.dataset.artifact);
  });
  window.WearingArtifacts = {
    open,
    identityChanged() {
      clear();
      if (panel.open) panel.close();
      document.getElementById("artifact-library").replaceChildren();
    },
    async library() {
      const result = await api("/api/artifacts");
      const replaced = new Set(result.items.map(item => item.previous_id).filter(Boolean));
      const items = result.items.filter(item => !replaced.has(item.id));
      document.getElementById("artifact-library").innerHTML = items.length ? `<h3>可以展开的结果</h3>${window.artifactMarkup(items)}` : "";
    },
  };
})();
