/* Tool observations, independent of the model's written citations. */
function researchMarkup(research, scope = "") {
  if (!research || (!research.items?.length && !research.unavailable)) return "";
  const escape = text => String(text ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const formatTime = value => {
    const stamp = new Date(value);
    return Number.isNaN(stamp.valueOf()) ? "时间未记录" : stamp.toLocaleString("zh-CN", {month:"numeric",day:"numeric",hour:"2-digit",minute:"2-digit",second:"2-digit"});
  };
  const key = value => `data-research-key="${escape(scope+":"+value)}"`;
  const icon = path => `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="${path}"/></svg>`;
  const chevron = icon("m9 5 7 7-7 7");
  const names = {query:"搜索", found:"搜索摘要", read:"已读取", failed:"未能读取", empty:"暂无来源"};
  const all = (research.items || []).filter(item => item && names[item.status]);
  const sources = new Map();
  for (const item of all.filter(r => r.url)) {
    const old = sources.get(item.url);
    if (!old || item.status !== "found") sources.set(item.url, {...item, title:old?.title || item.title});
  }
  const rows = [...sources.values()].sort((a,b) => Number(b.status === "read") - Number(a.status === "read"));
  const appItems = (research.items || []).filter(item => item?.kind === "app");
  const apps = new Map();
  for (const item of appItems.filter(item => item.status === "observed" && item.package && Array.isArray(item.lines))) {
    const id = `${item.resource_id}:${item.package}`;
    if (!apps.has(id)) apps.set(id, []);
    const group = apps.get(id);
    if (!group.some(row => row.observation_id === item.observation_id)) group.push(item);
  }
  const appMarkup = [...apps.entries()].map(([id, rows]) => `<li class="research-app"><div class="research-source-heading"><span class="research-source-icon" aria-hidden="true">${icon("M8 3h8a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2Zm3 14h2")}</span><div><strong class="research-title">${escape(rows[0].title || rows[0].package)}</strong><span class="research-state">App 屏幕文字 · ${rows.length} 次查看</span></div></div><div class="research-observations">${rows.map((item, index) => `<details ${key(id+":"+item.observation_id)}><summary><span>查看 ${String(index+1).padStart(2,"0")}</span><time datetime="${escape(item.observed_at)}">${escape(formatTime(item.observed_at))}</time>${chevron}</summary><div class="research-screen" tabindex="0" role="region" aria-label="第 ${index+1} 次查看的屏幕文字">${item.detail?`<p>${escape(item.detail)}</p>`:""}<ul>${item.lines.map(line => `<li>${escape(line)}</li>`).join("")}</ul>${item.truncated?"<p>这次内容较多，只保留了部分文字。</p>":""}</div></details>`).join("")}</div></li>`).join("");
  const appNotes = appItems.filter(item => item.status !== "observed").map(item => `<div class="research-observation-note"><div><strong>${escape(item.title)}</strong>${item.observed_at?`<time>${escape(formatTime(item.observed_at))}</time>`:""}</div>${item.detail?`<p>${escape(item.detail)}</p>`:""}</div>`).join("");
  const markup = rows.map(item => {
    let link = null;
    try { const u = new URL(item.url); if (["https:", "http:"].includes(u.protocol) && !u.username && !u.password) link = u; } catch {}
    return `<li class="research-web"><span class="research-state">${names[item.status]}${item.cached?" · 缓存":""}</span>${link?`<a href="${escape(link.href)}" target="_blank" rel="noopener noreferrer">${escape(item.title || link.hostname)}<span class="sr-only">（在新标签页打开）</span></a>`:`<span class="research-title">${escape(item.title)}</span>`}<small>${link?escape(link.hostname)+" · ":""}${escape(formatTime(item.observed_at))}${item.detail?" · "+escape(item.detail):""}</small></li>`;
  }).join("");
  const queries = all.filter(r => r.status === "query");
  const notes = all.filter(r => !r.url && r.status !== "query").map(r => `<p>${escape(r.title)}</p>`).join("");
  const trail = queries.length ? `<details class="research-queries" ${key("queries")}><summary>搜索过程${chevron}</summary>${queries.map(r => `<p>${names[r.status]} · ${escape(r.title)}</p>`).join("")}</details>` : "";
  const counts = [apps.size?`${apps.size} 个 App`:"", sources.size?`${sources.size} 个网页来源`:""].filter(Boolean).join(" · ");
  const appTitles = [...apps.values()].map(group => group[0].title || group[0].package);
  const preview = appTitles.slice(0, 2).join("、") + (appTitles.length>2?"等":"") || (sources.size?`${sources.size} 个网页来源`:"查看记录");
  return `<details class="research-receipts" ${key("all")}><summary>${icon("M4 5h6a3 3 0 0 1 3 3v12a4 4 0 0 0-4-2H4V5Zm16 0h-4a3 3 0 0 0-3 3v12a4 4 0 0 1 4-2h3V5Z")}<span class="research-summary-title">查看依据<span class="sr-only">${counts?" · "+counts:""}</span></span><span class="research-preview" aria-hidden="true">${escape(preview)}</span><span class="research-disclosure">${chevron}</span></summary><div class="research-body"><ul class="research-sources">${appMarkup}${markup}</ul>${appNotes}${notes}${trail}<p class="research-caption">屏幕文字仅含当时可见内容；时间为查看时间。搜索摘要与缓存不代表实时信息。</p>${research.omitted?`<p class="research-caption">另有 ${escape(research.omitted)} 条工具记录超过保存上限，未保留在此列表中。</p>`:""}${research.unavailable?'<p class="research-caption">部分来源记录暂时无法读取，当前列表可能不完整。</p>':""}</div></details>`;
}
if (typeof module !== "undefined") module.exports = {researchMarkup};
