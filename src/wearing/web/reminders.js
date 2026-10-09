"use strict";
/* Pajio 记录提醒（Web）：待办截止时间 / 日程开始时间的具体提醒。
   对齐 docs/evidence/pajio-core-20261007/record-reminders-contract.md：
   - 开关与提前量需显式保存；revision（提醒设置）与 record_revision（记录/系列修订）双 CAS。
   - request_key 先经 WearingStore 持久；失败/结果未知沿用同一请求取原回执；
     已知 400/404/409/422 后重新读取最新设置，再次保存换新 key。
   - 回执 status/reason/provider_status 如实显示；不声称手机已展示。
   全天、无时间、已完成、已删除不可开提醒；改期/完成后由服务端停用，不自动重开。 */
(() => {
  if (document.documentElement.classList.contains("mobile-host")) return;
  const esc = text => String(text ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const advances = [[0,"准时"],[5,"提前 5 分钟"],[15,"提前 15 分钟"],[30,"提前 30 分钟"],[60,"提前 1 小时"],[1440,"提前 1 天"]];
  const statusLabels = {unavailable:"暂不可用", disabled:"未开启", scheduled:"已安排", due:"已到期", expired:"已过期"};
  const reasonLabels = {missing:"没有具体时间", removed:"记录已移除", completed:"记录已完成", all_day:"全天没有具体时间", no_time:"没有具体时间"};
  const clock = value => new Date(value).toLocaleString("zh-CN",{month:"numeric",day:"numeric",hour:"2-digit",minute:"2-digit",hour12:false});
  const targetPattern = /^(life_[a-f0-9]{32}|recurrence_[a-f0-9]{32}_\d{8})$/;
  const journalName = target => `pajio-reminder-request:v1:${state.identityId}:${target}`;
  function readJournal(target){try{return JSON.parse(window.WearingStore.get(journalName(target))||"null");}catch{return null;}}
  function writeJournal(target,body){try{window.WearingStore.set(journalName(target),JSON.stringify(body));}catch{}}
  function clearJournal(target){try{window.WearingStore.remove(journalName(target));}catch{}}
  function noteNode(text){const p=document.createElement("p");p.className="pj-note";p.textContent=text;return p;}

  function statusLine(view){
    if(!view)return "";
    const parts=[`当前：${statusLabels[view.status]||view.status}`];
    if(view.reason)parts.push(reasonLabels[view.reason]||view.reason);
    if(view.enabled&&view.fire_at)parts.push(`触发 ${clock(view.fire_at)}`);
    if(view.provider_status)parts.push(`服务商阶段 ${view.provider_status}（不代表手机已展示）`);
    return parts.join(" · ");
  }

  function paint(host,target,recordRevision,ctx,view,failure,preferred){
    if(ctx.completed){host.replaceChildren(noteNode("已完成的记录不再提醒；重新打开完成后可再设置。"));return;}
    if(ctx.all_day){host.replaceChildren(noteNode("全天日程没有具体开始时间，不能提醒；改为具体时段后可开启。"));return;}
    if(!ctx.anchor){host.replaceChildren(noteNode(`先保存${ctx.label||""}的具体时间，才能开启提醒。`));return;}
    if(!view){host.replaceChildren(noteNode(failure||"提醒设置暂时读不到，可稍后重试。"));return;}
    const enabled=preferred?preferred.enabled:view.enabled;
    const advance=preferred?preferred.advance_minutes:(view.advance_minutes??15);
    host.dataset.rmRevision=String(view.revision??0);
    host.dataset.rmRecordRevision=String(recordRevision);
    host.innerHTML=`<div class="reminder-box">
      <label class="life-check-label"><input class="rm-enabled" type="checkbox" ${enabled?"checked":""}>开启提醒（按${esc(ctx.label||"具体时间")}）</label>
      <label class="field-help">提前量
        <select class="rm-advance">${advances.map(([value,label])=>`<option value="${value}" ${value===advance?"selected":""}>${label}</option>`).join("")}</select></label>
      <p class="inline-feedback" role="status">${esc(statusLine(view))}</p>
      <small class="pj-note">由常驻服务按计划发送；保存成功不代表手机已展示。</small>
      <button class="secondary rm-save" type="button">保存提醒设置</button></div>`;
    host.querySelector(".rm-save").addEventListener("click",()=>save(host,target,recordRevision,ctx));
  }

  async function render(host,target,recordRevision,ctx={}){
    if(!host)return;
    if(!targetPattern.test(target)){host.replaceChildren();return;}
    const identity=state.identityId,epoch=state.identityEpoch;
    let view=null,failure="";
    try{view=await api("/api/record-reminders/"+target);}
    catch(error){failure=error.message||"提醒设置暂时读不到，可稍后重试。";}
    if(identity!==state.identityId||epoch!==state.identityEpoch)return;
    paint(host,target,recordRevision,ctx,view,failure,null);
    await resumePending(host,target,recordRevision,ctx);
  }

  async function renderKeepSelection(host,target,recordRevision,ctx,preferred){
    const identity=state.identityId;
    let view=null;try{view=await api("/api/record-reminders/"+target);}catch{}
    if(identity!==state.identityId)return;
    paint(host,target,recordRevision,ctx,view,"",preferred);
  }

  async function save(host,target,recordRevision,ctx){
    const note=host.querySelector(".inline-feedback");
    const body={revision:Number(host.dataset.rmRevision||0),record_revision:recordRevision,
      enabled:host.querySelector(".rm-enabled").checked,
      advance_minutes:Number(host.querySelector(".rm-advance").value),
      request_key:window.WearingIds.uuid().replaceAll("-","")};
    writeJournal(target,body);
    busy(host.querySelector(".rm-save"),async()=>{
      try{
        const receipt=await api("/api/record-reminders/"+target,{method:"POST",body:JSON.stringify(body)});
        if(!receipt||receipt.target_id!==target||receipt.revision!==body.revision+1||receipt.enabled!==body.enabled)
          throw new Error("回执与本次保存不一致，已保留请求，可安全重试取回。");
        clearJournal(target);
        note.textContent="提醒设置已保存，正在核实最新状态…";
        await render(host,target,receipt.record_revision,ctx);
      }catch(error){
        if(error.status===409){
          clearJournal(target);
          note.textContent=(error.message||"记录或提醒设置已有变化。")+" 已重新读取最新设置，请核对后再保存。";
          await renderKeepSelection(host,target,recordRevision,ctx,{enabled:body.enabled,advance_minutes:body.advance_minutes});
          return;
        }
        if(error.status===400||error.status===404||error.status===413||error.status===422){clearJournal(target);note.textContent=error.message||"这次保存没有成功。";return;}
        note.textContent=(error.message||"结果未知。")+" 将用同一请求取回，不会重复设置。";
      }
    },note);
  }

  async function resumePending(host,target,recordRevision,ctx){
    const pending=readJournal(target);
    if(!pending)return;
    const note=host.querySelector(".inline-feedback");
    if(note)note.textContent="发现未确认的提醒设置，正在用同一请求取回…";
    try{
      const receipt=await api("/api/record-reminders/"+target,{method:"POST",body:JSON.stringify(pending)});
      if(receipt&&receipt.target_id===target)clearJournal(target);
      await render(host,target,receipt?.record_revision||recordRevision,ctx);
    }catch(error){
      const fresh=host.querySelector(".inline-feedback");
      if(error&&error.status){clearJournal(target);if(fresh)fresh.textContent=`上一次保存没有成功：${error.message||"请核对后重试。"}`;}
      else if(fresh)fresh.textContent="上一次设置仍未确认，稍后会继续用同一请求取回。";
    }
  }

  window.WearingReminders={render};
})();
