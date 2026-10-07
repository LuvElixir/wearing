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
      timer = setTimeout(() => {
        if (seq === sequence) { status.hidden = false; status.textContent = "页面打开较慢，可以稍候或下载文件。"; }
      }, 12000);
    } catch (error) {
      if (seq !== sequence) return;
      status.textContent = error.message || "结果暂时无法打开，请稍后重试。";
    }
  }
  panel.addEventListener("close", clear);
  document.addEventListener("click", event => {
    const button = event.target.closest("[data-artifact]");
    if (button?.dataset.artifact) open(button.dataset.artifact);
  });
  window.WearingArtifacts = {
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
