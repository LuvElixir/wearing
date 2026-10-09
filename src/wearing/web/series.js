"use strict";
/* Pajio 自有重复日程（Web）：系列、例外与查询展开，单入口 POST /api/calendar-series。
   对齐 docs/evidence/pajio-core-20261007/calendar-series-contract.md：
   - 查询结果只合并展示，不写入普通 life 记录缓存；派生实例（recurrence_*）转入本面板处理。
   - request_key 先经 WearingStore 持久再发 HTTP；失败/结果未知沿用同一请求取原回执；
     已知 400/404/409/422 才允许换新编号重新保存。
   - revision CAS：409 保留输入，先读最新再二选一（保留我的输入 / 采用最新内容）。
   时间语义：系列保存当地日期/钟点 + IANA 时区；表单里的时间始终按所选时区的钟点填写，不做设备时区换算。 */
(() => {
  if (document.documentElement.classList.contains("mobile-host")) return;
  const $ = id => document.getElementById(id);
  const esc = text => String(text ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const deviceTz = () => Intl.DateTimeFormat().resolvedOptions().timeZone || "Asia/Shanghai";
  const freqLabels = {daily:"每天", weekly:"每周", monthly:"每月", yearly:"每年"};
  const weekLabels = ["一","二","三","四","五","六","日"];
  const pad = n => String(n).padStart(2,"0");
  const dayKey = d => `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}`;
  // panel 是本模块面板状态；勿与 app.js 的全局 state 同名。
  const panel = {identity:null, mode:null, series:null, occurrence:null, manager:null,
    decorateGen:0, calEvents:[], window:null, occurrences:[], truncated:false};

  async function post(command){return api("/api/calendar-series",{method:"POST",body:JSON.stringify(command)});}
  // 多槽请求账本（对齐合同键形态 series|new × occurrence|series）：每个操作各留一本，
  // 互不覆盖；同意图重试沿用原 request_key 重放完全相同请求。
  const slotOf = command => `${command.action}:${command.series_id||"new"}:${command.occurrence_key||""}`;
  const journalName = slot => `pajio-series-pending:v1:${state.identityId}:${slot}`;
  const fingerprint = command => JSON.stringify({...command,request_key:undefined});
  function readJournal(slot){try{return JSON.parse(window.WearingStore.get(journalName(slot))||"null");}catch{return null;}}
  function writeJournal(slot,entry){try{window.WearingStore.set(journalName(slot),JSON.stringify(entry));}catch{}}
  function clearJournal(slot){try{window.WearingStore.remove(journalName(slot));}catch{}}
  function setNote(text){const note=$("series-note");if(note)note.textContent=text||"";}

  async function mutate(command,{expectSeriesId=null}={}){
    const slot=slotOf(command);
    const pending=readJournal(slot);
    if(pending&&pending.identity===state.identityId){
      if(fingerprint(pending.command)===fingerprint(command)){
        command=pending.command;  // 同意图沿用原请求编号：失败/未知重放完全相同请求
      }else{
        try{await post(pending.command);}catch{}  // 换内容前尽力结算同槽旧账，原编号回执不丢
      }
    }
    writeJournal(slot,{identity:state.identityId,command});
    const receipt=await post(command);
    if(!receipt||typeof receipt.id!=="string"||(expectSeriesId&&receipt.id!==expectSeriesId))throw new Error("保存编号与回执不一致，请稍后重试。");
    clearJournal(slot);
    return receipt;
  }

  async function resumePending(slots){
    for(const slot of slots){
      const pending=readJournal(slot);
      if(!pending||pending.identity!==state.identityId)continue;
      setNote("有一次未确认的重复日程修改，正在用同一请求取回…");
      try{
        const receipt=await post(pending.command);
        if(receipt&&typeof receipt.id==="string"){clearJournal(slot);setNote("上一次修改已确认。");await repaintAfterResume(receipt);continue;}
      }catch(error){
        if(error&&error.status){clearJournal(slot);setNote(`上一次修改没有保存：${error.message||"请核对后重试。"}`);continue;}
      }
      setNote("上一次修改仍未确认，稍后会继续用同一请求取回。");
      return;
    }
  }
  async function repaintAfterResume(receipt){
    refreshCalendar();
    if(!receipt||!panel.mode)return;
    if(panel.mode==="occurrence"&&panel.series&&panel.occurrence&&panel.series.id===receipt.id)await refreshOccurrence().catch(()=>{});
    else if(panel.mode==="editor"&&panel.series&&panel.series.id===receipt.id){panel.series=await post({action:"get",series_id:receipt.id});renderEditor();}
    else if(panel.mode==="manager")await renderManager();
  }

  /* ---------- 时间展示 ---------- */
  function utcToWall(iso,tz){
    const parts=new Intl.DateTimeFormat("en-GB",{timeZone:tz,year:"numeric",month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit",hour12:false}).formatToParts(new Date(iso));
    const get=t=>parts.find(p=>p.type===t)?.value||"00";
    const hour=get("hour")==="24"?"00":get("hour");
    return `${get("year")}-${get("month")}-${get("day")}T${hour}:${get("minute")}`;
  }
  function wallText(wall,allDay){
    if(allDay)return `${Number(wall.slice(5,7))}月${Number(wall.slice(8,10))}日 · 全天`;
    return `${Number(wall.slice(5,7))}月${Number(wall.slice(8,10))}日 ${wall.slice(11)} 起`;
  }
  function occurrenceWhen(item){
    const tz=item.timezone||deviceTz();
    const start=item.all_day?item.start_at:utcToWall(item.start_at,tz);
    const label=wallText(start,item.all_day);
    return tz===deviceTz()?label:`${label}（按 ${tz}）`;
  }
  function agendaWhen(item){
    const tz=item.timezone||deviceTz();
    if(item.all_day)return `${Number(item.start_at.slice(5,7))}月${Number(item.start_at.slice(8,10))}日 · 全天`;
    const start=utcToWall(item.start_at,tz);
    const time=`${start.slice(11)}–${utcToWall(item.end_at,tz).slice(11)}`;
    return `${Number(start.slice(5,7))}月${Number(start.slice(8,10))}日 ${time}${tz===deviceTz()?"":"（"+tz+"）"} · 重复日程`;
  }
  function ruleText(series){
    const {rule,template}=series.body;
    const days=rule.frequency==="weekly"&&rule.weekdays.length?` · 周${rule.weekdays.map(d=>weekLabels[d]).join("、")}`:"";
    const stop=rule.count?` · 共 ${rule.count} 次`:rule.until?` · 至 ${rule.until}`:" · 持续";
    const time=template.all_day?"全天":`${template.start_local.slice(11)}–${template.end_local.slice(11)}`;
    return `${freqLabels[rule.frequency]}${rule.interval>1?` · 间隔 ${rule.interval}`:""}${days} · ${time}${stop}`;
  }
  function defaultWall(){const d=new Date();const day=dayKey(d);return [`${day}T09:00`,`${day}T10:00`];}
  function confirmStep(button,label){
    button.dataset.confirm=String(Number(button.dataset.confirm||0)+1);
    if(button.dataset.confirm==="1"){button.textContent=`确认${label}？`;setTimeout(()=>{if(button.dataset.confirm==="1"){button.dataset.confirm="";button.textContent=label;}},4000);return false;}
    button.dataset.confirm="";button.textContent=label;return true;
  }
  const newKey = () => window.WearingIds.uuid().replaceAll("-","");

  /* ---------- 系列管理列表 ---------- */
  async function openManager(){
    if(panel.identity!==state.identityId)resetPanel();
    panel.identity=state.identityId;panel.mode="manager";panel.series=null;panel.occurrence=null;
    $("series-title").textContent="重复日程";
    $("series-body").innerHTML='<p class="life-empty">正在读取重复日程…</p>';
    openPanel("series-panel");
    // 旧单槽键（第十九轮之前）一次性迁移：尽力结算后移除。
    const legacyName=`pajio-series-pending:v1:${state.identityId}`;
    let legacy=null;try{legacy=JSON.parse(window.WearingStore.get(legacyName)||"null");}catch{}
    if(legacy&&legacy.identity===state.identityId){try{await post(legacy.command);}catch{}window.WearingStore.remove(legacyName);}
    await resumePending(["create"]);
    await renderManager();
  }

  async function renderManager(after=null){
    const identity=state.identityId,epoch=state.identityEpoch;
    let data;
    try{data=await post({action:"list",include_deleted:true,...(after?{after}:{})});}
    catch(error){if(identity===state.identityId)$("series-body").innerHTML=`<p class="pj-note">${esc(error.message||"暂时读不到重复日程。")}</p>`;return;}
    if(identity!==state.identityId||epoch!==state.identityEpoch)return;
    const page={active:data.items.filter(s=>!s.deleted_at),deleted:data.items.filter(s=>s.deleted_at),next:data.next};
    if(after&&panel.manager){panel.manager.active.push(...page.active);panel.manager.deleted.push(...page.deleted);panel.manager.next=page.next;}
    else panel.manager=page;
    if(panel.mode==="manager")paintManager();
  }

  function paintManager(){
    const {active,deleted,next}=panel.manager||{active:[],deleted:[],next:null};
    const activeRows=active.map(s=>`<div class="pj-card"><div><strong>${esc(s.body.template.title)}</strong><small>${esc(ruleText(s))}${s.exceptions.length?` · 例外 ${s.exceptions.length}`:""} · 修订 ${s.revision}</small></div>
      <span class="brief-actions"><button class="text-button" type="button" data-series-edit="${s.id}">查看</button></span></div>`).join("");
    const deletedRows=deleted.map(s=>`<div class="pj-card"><div><strong>${esc(s.body.template.title)}</strong><small>${esc(ruleText(s))} · 修订 ${s.revision}</small></div>
      <span class="brief-actions"><button class="text-button" type="button" data-series-restore="${s.id}" data-series-revision="${s.revision}">恢复</button></span></div>`).join("");
    $("series-body").innerHTML=`<p class="pj-note">重复安排保存在当前身份；单次改动不影响整个系列。</p>
      <div class="brief-actions"><button class="primary" type="button" data-series-new="1">新建重复日程</button></div>
      <section class="pj-section"><p class="pj-section-title">活跃系列 · ${active.length}</p>${activeRows||'<p class="pj-note">还没有重复日程。新建一个，或回到日历慢慢安排。</p>'}</section>
      ${deleted.length?`<details class="setup-guide"><summary>已移除的系列 · ${deleted.length}</summary>${deletedRows}</details>`:""}
      ${next?`<button class="pj-load-more" type="button" data-series-more="${esc(next)}">继续加载（每页 50 个）</button>`:""}`;
  }

  /* ---------- 系列编辑器（新建 / 修改） ---------- */
  async function openEditorFor(seriesId){
    const identity=state.identityId;
    await resumePending([`update:${seriesId}`,`archive:${seriesId}`,`restore:${seriesId}`]);
    let series;
    try{series=await post({action:"get",series_id:seriesId});}
    catch(error){setNote(error.message||"这个系列暂时读不到。");return;}
    if(identity!==state.identityId)return;
    panel.mode="editor";panel.series=series;panel.occurrence=null;
    renderEditor();
  }

  function renderEditor(){
    const s=panel.series,create=!s;
    $("series-title").textContent=create?"新建重复日程":s.body.template.title;
    const t=create?{title:"",content:"",timezone:deviceTz(),all_day:false}:s.body.template;
    const r=create?{frequency:"weekly",interval:1,weekdays:[],count:null,until:null}:s.body.rule;
    const times=defaultWall();
    const startLocal=create?times[0]:t.start_local;
    const endLocal=create?times[1]:t.end_local;
    const endMode=r.count?"count":r.until?"until":"never";
    const exceptionRows=create?"":exceptionsMarkup(s);
    $("series-body").innerHTML=`<p class="brief-actions"><button class="text-button" type="button" data-series-back="1">← 返回列表</button></p>
      <form id="se-form" class="pj-panel">
      <label class="field-help" for="se-title">标题</label>
      <input id="se-title" maxlength="200" required value="${esc(t.title)}">
      <label class="life-check-label"><input id="se-all-day" type="checkbox" ${t.all_day?"checked":""}>全天（只占日期，不看钟点）</label>
      <div class="life-fields"><label>开始<input id="se-start" type="${t.all_day?"date":"datetime-local"}" required value="${esc(t.all_day?startLocal.slice(0,10):startLocal)}"></label><label>结束<input id="se-end" type="${t.all_day?"date":"datetime-local"}" required value="${esc(t.all_day?endLocal.slice(0,10):endLocal)}"></label></div>
      <label class="field-help" for="se-content">补充几句</label>
      <textarea id="se-content" rows="3" maxlength="12000">${esc(t.content)}</textarea>
      <details><summary>时区设置（当前 ${esc(t.timezone)}）</summary><label class="field-help" for="se-tz">IANA 时区；上面的时间始终按这个时区的钟点填写。</label><input id="se-tz" maxlength="80" value="${esc(t.timezone)}"></details>
      <p class="field-help">重复方式</p>
      <div class="se-grid">
        <label>频率<select id="se-freq">${Object.entries(freqLabels).map(([v,l])=>`<option value="${v}" ${r.frequency===v?"selected":""}>${l}</option>`).join("")}</select></label>
        <label>间隔<input id="se-interval" type="number" min="1" max="365" value="${r.interval}"></label>
      </div>
      <div class="se-week" id="se-week">${weekLabels.map((l,i)=>`<label><input type="checkbox" name="se-w" value="${i}" ${r.weekdays.includes(i)?"checked":""}>周${l}</label>`).join("")}</div>
      <p class="field-help">终止方式（次数与截止日期只能选一种）</p>
      <div class="se-grid">
        <label><input type="radio" name="se-end-mode" value="never" ${endMode==="never"?"checked":""}>持续</label>
        <label><input type="radio" name="se-end-mode" value="count" ${endMode==="count"?"checked":""}>固定次数</label>
        <input id="se-count" type="number" min="1" max="1000" placeholder="次数" value="${r.count||""}" ${endMode==="count"?"":"disabled"}>
        <label><input type="radio" name="se-end-mode" value="until" ${endMode==="until"?"checked":""}>最后开始日期</label>
        <input id="se-until" type="date" value="${r.until||""}" ${endMode==="until"?"":"disabled"}>
      </div>
      <p class="inline-feedback" role="status"></p>
      <div class="brief-actions"><button class="secondary msg-submit" type="submit">${create?"创建重复日程":"保存整个系列"}</button></div>
      ${!create&&!s.deleted_at?'<button class="text-button life-remove" type="button" data-series-archive="1">移除整个系列</button>':""}
      ${!create&&s.deleted_at?'<button class="secondary" type="button" data-series-unarchive="1">恢复整个系列</button>':""}
      </form>
      ${exceptionRows}`;
    const form=$("se-form");
    $("se-all-day").addEventListener("change",()=>{
      const allDay=$("se-all-day").checked;
      for(const id of ["se-start","se-end"]){const input=$(id),old=input.value;input.type=allDay?"date":"datetime-local";input.value=allDay?old.slice(0,10):(old?old.slice(0,10)+"T09:00":"");}
    });
    $("se-freq").addEventListener("change",syncWeekToggle);
    form.querySelectorAll('input[name="se-end-mode"]').forEach(radio=>radio.addEventListener("change",()=>{
      $("se-count").disabled=$("se-until").disabled=true;
      const mode=form.querySelector('input[name="se-end-mode"]:checked').value;
      if(mode==="count")$("se-count").disabled=false;
      if(mode==="until")$("se-until").disabled=false;
    }));
    syncWeekToggle();
    form.addEventListener("submit",event=>{event.preventDefault();saveEditor(form);});
  }

  function syncWeekToggle(){
    const weekly=$("se-freq").value==="weekly";
    $("se-week").querySelectorAll("input").forEach(box=>{box.disabled=!weekly;});
    $("se-week").setAttribute("aria-hidden",weekly?"false":"true");
  }

  function exceptionsMarkup(series){
    const list=series.exceptions||[];
    if(!list.length)return "";
    return `<section class="pj-section"><p class="pj-section-title">单次例外 · ${list.length}</p>${list.map(e=>`
      <div class="pj-card"><div><strong>${esc(e.title||"已取消的这一次")}</strong><small>${esc(e.occurrence_key)} · ${e.cancelled?"已取消":"单独修改"} · 例外修订 ${e.revision}</small></div>
      <span class="brief-actions"><button class="text-button" type="button" data-series-reset="${series.id}" data-series-key="${esc(e.occurrence_key)}">恢复原规则</button></span></div>`).join("")}
      <p class="pj-note">修改整个系列会保留这些例外；新规则不再包含其原定日期时会拒绝保存。</p></section>`;
  }

  function editorDraft(){
    const timezone=$("se-tz").value.trim()||deviceTz();
    try{new Intl.DateTimeFormat("en-US",{timeZone:timezone});}catch{throw new Error("请填写有效的 IANA 时区。");}
    const allDay=$("se-all-day").checked;
    const startInput=$("se-start").value,endInput=$("se-end").value;
    if(!startInput||!endInput)throw new Error("请先填好开始和结束时间。");
    const template={title:$("se-title").value.trim(),content:$("se-content").value.trim(),timezone,all_day:allDay,
      start_local:allDay?startInput.slice(0,10):startInput,end_local:allDay?endInput.slice(0,10):endInput};
    if(!(template.start_local<template.end_local))throw new Error("结束须晚于开始，单次最长 31 天。");
    if(!template.title)throw new Error("先给这个重复日程一个标题。");
    const interval=Number($("se-interval").value);
    if(!Number.isInteger(interval)||interval<1||interval>365)throw new Error("重复间隔须为 1–365。");
    const rule={frequency:$("se-freq").value,interval,
      weekdays:ruleFrequencyWeekly()? [...$("se-week").querySelectorAll("input:checked")].map(n=>Number(n.value)).sort((a,b)=>a-b):[]};
    if(ruleFrequencyWeekly()&&rule.weekdays.length){
      const firstDay=(new Date(template.start_local.slice(0,10)+"T00:00").getDay()+6)%7;
      if(!rule.weekdays.includes(firstDay))throw new Error(`首次日期是周${weekLabels[firstDay]}，请把这一天选进重复星期，或清空星期沿用首次日期。`);
    }
    const mode=document.querySelector('input[name="se-end-mode"]:checked').value;
    if(mode==="count"){const count=Number($("se-count").value);if(!Number.isInteger(count)||count<1||count>1000)throw new Error("次数须为 1–1000。");rule.count=count;}
    else if(mode==="until"){const until=$("se-until").value;if(!until)throw new Error("请选择重复截止日期。");rule.until=until;if(until<template.start_local.slice(0,10))throw new Error("截止日期不能早于首次日期。");}
    return {template,rule};
  }
  function ruleFrequencyWeekly(){return $("se-freq").value==="weekly";}

  async function saveEditor(form){
    const note=form.querySelector(".inline-feedback");
    let draft;
    try{draft=editorDraft();}catch(error){note.textContent=error.message;return;}
    const isUpdate=Boolean(panel.series&&panel.series.id);
    const command=isUpdate
      ?{action:"update",series_id:panel.series.id,revision:panel.series.revision,request_key:newKey(),draft}
      :{action:"create",request_key:newKey(),draft};
    busy(form.querySelector(".msg-submit"),async()=>{
      try{
        const saved=await mutate(command,{expectSeriesId:isUpdate?panel.series.id:null});
        panel.series=saved;panel.mode="editor";
        renderEditor();
        setNote(isUpdate?"整个系列已保存，已重新读取最新版本。":"重复日程已创建，之后可以在日历里看到每一次。");
        refreshCalendar();await renderManager();
      }catch(error){
        if(error.status===409){note.textContent=(error.message||"系列已有新修改。")+" 你的输入仍保留，可先读取最新版本再核对。";showReloadLatest(form,note);return;}
        throw error;
      }
    },note);
  }

  function showReloadLatest(form,note){
    if(document.getElementById("se-latest"))return;
    const bar=document.createElement("div");bar.id="se-latest";bar.className="life-latest";
    const read=document.createElement("button");read.type="button";read.className="secondary";read.textContent="读取最新版本";
    read.addEventListener("click",()=>busy(read,async()=>{
      const latest=await post({action:"get",series_id:panel.series.id});
      panel.latest=latest;
      bar.replaceChildren(document.createTextNode(`最新版本：${latest.body.template.title} · 修订 ${latest.revision}${latest.deleted_at?"（已移除）":""}`));
      const keep=document.createElement("button");keep.type="button";keep.className="secondary";keep.textContent="保留我的输入";
      keep.addEventListener("click",()=>{panel.series=latest;bar.remove();note.textContent="已保留你的输入并换用最新修订号，核对后再保存。";});
      const adopt=document.createElement("button");adopt.type="button";adopt.className="secondary";adopt.textContent="采用最新内容";
      adopt.addEventListener("click",()=>{panel.series=latest;renderEditor();});
      bar.append(keep,adopt);
    }));
    bar.append(read);form.append(bar);
  }

  /* ---------- 单次实例（仅这一次 / 整个系列） ---------- */
  async function openInstance(instanceId){
    const match=/^recurrence_([a-f0-9]{32})_(\d{8})$/.exec(instanceId);
    if(!match){notice("这一次的重复日程暂时打不开。",true);return;}
    const key=`${match[2].slice(0,4)}-${match[2].slice(4,6)}-${match[2].slice(6,8)}`;
    const identity=state.identityId;
    await resumePending([`override:${"series_"+match[1]}:${key}`,`cancel:${"series_"+match[1]}:${key}`,`reset:${"series_"+match[1]}:${key}`]);
    let series;
    try{series=await post({action:"get",series_id:"series_"+match[1],occurrence_key:key});}
    catch(error){notice(error.message||"这一次的重复日程暂时打不开。",true);return;}
    if(identity!==state.identityId)return;
    panel.mode="occurrence";panel.series=series;panel.occurrence={key,selected:series.selected||null};
    renderOccurrence();
    openPanel("series-panel");
  }

  async function refreshOccurrence(){
    const series=await post({action:"get",series_id:panel.series.id,occurrence_key:panel.occurrence.key});
    panel.series=series;panel.occurrence={key:panel.occurrence.key,selected:series.selected||null};
    renderOccurrence();
  }

  function renderOccurrence(){
    const s=panel.series,o=panel.occurrence;
    $("series-title").textContent="这一次的日程";
    const exception=(s.exceptions||[]).find(e=>e.occurrence_key===o.key);
    if(s.deleted_at){
      $("series-body").innerHTML=`<p class="pj-note">这个系列已移除；规则与例外都保留着。</p>
        <div class="brief-actions"><button class="secondary" type="button" data-series-restore="${s.id}" data-series-revision="${s.revision}">恢复整个系列</button>
        <button class="text-button" type="button" data-series-back="1">返回列表</button></div>`;
      return;
    }
    if(!o.selected){
      $("series-body").innerHTML=`<p class="pj-note">${exception&&exception.cancelled?`这一次（${esc(o.key)}）已单独取消。`:`这一天（${esc(o.key)}）不再属于当前重复规则。`}</p>
        <div class="brief-actions">${exception?'<button class="secondary" type="button" data-series-reset="'+s.id+'" data-series-key="'+esc(o.key)+'">恢复这一次的原规则</button>':""}
        <button class="text-button" type="button" data-series-edit="${s.id}">查看整个系列</button></div>`;
      return;
    }
    const item=o.selected;
    $("series-body").innerHTML=`<article class="pj-card"><div><strong>${esc(item.title)}</strong>
      <small>${esc(occurrenceWhen(item))}</small>
      ${item.content?`<p class="pj-note">${esc(item.content)}</p>`:""}
      <small>来自重复系列 · 系列修订 ${item.recurrence.series_revision}${item.recurrence.exception_revision?` · 例外修订 ${item.recurrence.exception_revision}`:""}</small></div></article>
      <div class="brief-actions">
        <button class="secondary" type="button" data-series-override="1">修改仅这一次</button>
        <button class="text-button" type="button" data-series-cancel-occ="1">取消这一次</button>
        ${item.recurrence.exception_revision?`<button class="text-button" type="button" data-series-reset="${s.id}" data-series-key="${esc(o.key)}">恢复原规则</button>`:""}
        <button class="text-button" type="button" data-series-edit="${s.id}">查看整个系列</button>
      </div>
      ${overrideMarkup(item)}
      <section class="pj-section"><p class="pj-section-title">这一次的提醒</p><div id="se-reminder"></div></section>`;
    window.WearingReminders?.render($("se-reminder"),item.id,s.revision,{anchor:item.start_at,all_day:item.all_day,completed:false,deleted:false,label:"开始时间"});
  }

  function overrideMarkup(item){
    return `<form id="se-override" class="pj-panel" hidden>
      <p class="field-help">只修改这一次（${esc(panel.occurrence.key)}）；系列其余各次保持不变。</p>
      <label class="field-help" for="ov-title">标题</label><input id="ov-title" class="ov-title" maxlength="200" required value="${esc(item.title)}">
      <label class="life-check-label"><input type="checkbox" class="ov-all-day" ${item.all_day?"checked":""}>全天</label>
      <div class="life-fields"><label>开始<input class="ov-start" type="${item.all_day?"date":"datetime-local"}" required value="${esc(item.all_day?item.start_at:utcToWall(item.start_at,item.timezone||deviceTz()))}"></label><label>结束<input class="ov-end" type="${item.all_day?"date":"datetime-local"}" required value="${esc(item.all_day?item.end_at:utcToWall(item.end_at,item.timezone||deviceTz()))}"></label></div>
      <label class="field-help" for="ov-content">补充几句</label><textarea class="ov-content" rows="3" maxlength="12000">${esc(item.content)}</textarea>
      <p class="inline-feedback" role="status"></p>
      <div class="brief-actions"><button class="secondary msg-submit" type="submit">保存仅这一次</button></div></form>`;
  }

  async function saveOverride(form){
    const note=form.querySelector(".inline-feedback");
    const item=panel.occurrence.selected;
    if(!item)return;
    const allDay=form.querySelector(".ov-all-day").checked;
    const startInput=form.querySelector(".ov-start").value,endInput=form.querySelector(".ov-end").value;
    if(!startInput||!endInput){note.textContent="请先填好开始和结束时间。";return;}
    const timezone=item.timezone||panel.series.body.template.timezone;
    const template={title:form.querySelector(".ov-title").value.trim(),content:form.querySelector(".ov-content").value.trim(),timezone,all_day:allDay,
      start_local:allDay?startInput.slice(0,10):startInput,end_local:allDay?endInput.slice(0,10):endInput};
    if(!template.title){note.textContent="先给这一次一个标题。";return;}
    if(!(template.start_local<template.end_local)){note.textContent="结束须晚于开始。";return;}
    const command={action:"override",series_id:panel.series.id,revision:panel.series.revision,request_key:newKey(),occurrence_key:panel.occurrence.key,template};
    busy(form.querySelector(".msg-submit"),async()=>{
      let saved=false;
      try{
        await mutate(command,{expectSeriesId:panel.series.id});saved=true;
        await refreshOccurrence();refreshCalendar();
        setNote("仅这一次已保存，并已重新读取。");
      }catch(error){
        if(saved){
          setNote("修改已保存，但回读失败；内容不会丢，可稍后重新读取。");
          const retry=document.createElement("button");retry.type="button";retry.className="secondary";retry.textContent="重新读取";
          retry.addEventListener("click",()=>busy(retry,refreshOccurrence));
          setNoteAfter(retry);return;
        }
        if(error.status===409){note.textContent=(error.message||"系列已有新修改。")+" 已为你重新读取，请核对后再保存。";await refreshOccurrence().catch(()=>{});return;}
        throw error;
      }
    },note);
  }
  function setNoteAfter(button){const note=$("series-note");if(note)note.after(button);}

  /* ---------- 日历合并展示（只读投影，不写入普通记录缓存） ---------- */
  async function decorate(start,end){
    if(typeof start!=="string"||typeof end!=="string")return;
    const identity=state.identityId;
    panel.window={start,end};
    const gen=++panel.decorateGen;
    try{
      const result=await post({action:"query",start,end,timezone:deviceTz()});
      if(gen!==panel.decorateGen||identity!==state.identityId)return;
      panel.occurrences=result.items||[];panel.truncated=Boolean(result.truncated);
    }catch{if(gen===panel.decorateGen)panel.occurrences=[];}
    if(gen===panel.decorateGen)paintCalendar();
  }

  function paintCalendar(){
    const cal=window.WearingLife?.calendar?.();
    if(cal){
      for(const event of panel.calEvents)event.remove();
      panel.calEvents=(panel.occurrences||[]).map(item=>cal.addEvent({id:item.id,title:item.title,start:item.start_at,end:item.end_at,allDay:item.all_day,color:"#6546A2",textColor:"#fff",editable:false}));
    }
    const stale=document.getElementById("series-agenda-section");
    if(stale)stale.remove();
    if(cal||!(panel.occurrences||[]).length)return;
    const mount=document.querySelector("#life-content .life-calendar");
    if(!mount)return;
    const section=document.createElement("section");
    section.id="series-agenda-section";section.className="life-task-group";
    section.setAttribute("aria-label","重复日程");
    section.innerHTML=`<h2>重复日程</h2>${panel.occurrences.map(item=>`
      <div class="life-row"><span class="life-time">${item.all_day?"全天":esc(utcToWall(item.start_at,item.timezone||deviceTz()).slice(11))}</span>
      <button class="life-row-main" data-series-open="${esc(item.id)}"><strong>${esc(item.title)}</strong><small>${esc(agendaWhen(item))}</small></button></div>`).join("")}${panel.truncated?'<p class="pj-note">重复日程较多，这里最多显示 1000 条。</p>':""}`;
    const more=mount.querySelector("[data-cal-more]");
    if(more)mount.insertBefore(section,more);else mount.append(section);
  }

  function refreshCalendar(){
    if(panel.window)decorate(panel.window.start,panel.window.end);
  }

  function resetPanel(){
    panel.identity=state.identityId;panel.mode=null;panel.series=null;panel.occurrence=null;panel.manager=null;
    panel.decorateGen++;panel.calEvents=[];panel.window=null;panel.occurrences=[];panel.truncated=false;
    setNote("");
    const body=$("series-body");if(body)body.replaceChildren();
    if($("series-panel")?.open)closePanel("series-panel");
  }

  /* ---------- 面板事件 ---------- */
  $("series-body").addEventListener("click",event=>{
    const button=event.target.closest("button");
    if(!button)return;
    if(button.dataset.seriesNew!==undefined){panel.series=null;panel.mode="editor";renderEditor();return;}
    if(button.dataset.seriesEdit){openEditorFor(button.dataset.seriesEdit);return;}
    if(button.dataset.seriesBack){openManager();return;}
    if(button.dataset.seriesMore){busy(button,renderManager(button.dataset.seriesMore),$("series-note"));return;}
    if(button.dataset.seriesOverride!==undefined){const form=$("se-override");if(form)form.hidden=!form.hidden;return;}
    if(button.dataset.seriesCancelOcc!==undefined){
      if(!confirmStep(button,"取消这一次"))return;
      busy(button,async()=>{
        await mutate({action:"cancel",series_id:panel.series.id,revision:panel.series.revision,request_key:newKey(),occurrence_key:panel.occurrence.key},{expectSeriesId:panel.series.id});
        await refreshOccurrence();refreshCalendar();
        setNote("这一次已取消；需要时可以恢复这一次的原规则。");
      },$("series-note"));
      return;
    }
    if(button.dataset.seriesReset){
      const {seriesReset,seriesKey}=button.dataset;
      busy(button,async()=>{
        const series=panel.series&&panel.series.id===seriesReset?panel.series:await post({action:"get",series_id:seriesReset});
        await mutate({action:"reset",series_id:seriesReset,revision:series.revision,request_key:newKey(),occurrence_key:seriesKey},{expectSeriesId:seriesReset});
        if(panel.mode==="occurrence"&&panel.occurrence&&panel.occurrence.key===seriesKey)await refreshOccurrence();
        else if(panel.mode==="editor"&&panel.series&&panel.series.id===seriesReset){panel.series=await post({action:"get",series_id:seriesReset});renderEditor();}
        else await renderManager();
        refreshCalendar();
        setNote("这一次已恢复按系列原规则安排。");
      },$("series-note"));
      return;
    }
    if(button.dataset.seriesRestore){
      const {seriesRestore,seriesRevision}=button.dataset;
      busy(button,async()=>{
        const receipt=await mutate({action:"restore",series_id:seriesRestore,revision:Number(seriesRevision),request_key:newKey()},{expectSeriesId:seriesRestore});
        if(panel.mode==="occurrence"&&panel.series&&panel.series.id===seriesRestore){panel.series=receipt;await refreshOccurrence();}
        else await renderManager();
        refreshCalendar();
        setNote("系列已恢复；日历里的每一次也回来了。");
      },$("series-note"));
      return;
    }
    if(button.dataset.seriesArchive!==undefined){
      if(!confirmStep(button,"移除整个系列"))return;
      busy(button,async()=>{
        const receipt=await mutate({action:"archive",series_id:panel.series.id,revision:panel.series.revision,request_key:newKey()},{expectSeriesId:panel.series.id});
        panel.series=receipt;renderEditor();
        setNote("整个系列已移除；规则与例外都保留，可从已移除列表恢复。");
        refreshCalendar();await renderManager();
      },$("series-note"));
      return;
    }
    if(button.dataset.seriesUnarchive!==undefined){
      busy(button,async()=>{
        const receipt=await mutate({action:"restore",series_id:panel.series.id,revision:panel.series.revision,request_key:newKey()},{expectSeriesId:panel.series.id});
        panel.series=receipt;renderEditor();
        setNote("系列已恢复。");
        refreshCalendar();await renderManager();
      },$("series-note"));
      return;
    }
  });
  $("series-body").addEventListener("submit",event=>{
    if(event.target.id==="se-override"){event.preventDefault();saveOverride(event.target);}
  });
  // 日历里的派生实例与「重复日程」管理入口。
  document.addEventListener("click",event=>{
    const open=event.target.closest("[data-series-open]");
    if(open){openInstance(open.dataset.seriesOpen);return;}
    const manage=event.target.closest("[data-series-manage]");
    if(manage)openManager();
  });
  $("series-panel").addEventListener("close",()=>{panel.mode=null;setNote("");});

  window.WearingSeries={openManager,openInstance,decorate,refreshCalendar,reset:resetPanel};
})();
