"use strict";
/* Pajio 对话引用范围（Web）：选择一整段连续会话，确认后不再作为后续回答来源。
   对齐 docs/evidence/pajio-core-20261007/conversation-source-controls-contract.md：
   - GET /api/conversation-sources?offset=&limit=&snapshot=：每页 20，续页附同一 snapshot；
     成员/凭证/设置变化 409 → 从第一页重读，不拼接不同快照。
   - POST /api/conversation-sources/exclude 闭集 {source_id,source_revision,revision,request_key}；
     完整请求先经 WearingStore 持久，结果未知用同一 key 取回原回执；已证明的 4xx 冲突
     清为 rejected，必须重新读取、重新选定确认，不静默换 revision。
   - 确认两击、取消不发请求；排除后不提供恢复引用（如实文案）；历史、备份与已保存
     记忆/文件/目标不删除，不声称彻底遗忘。 */
(() => {
  if (document.documentElement.classList.contains("mobile-host")) return;
  const $ = id => document.getElementById(id);
  const esc = text => String(text ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const dayText = value => new Date(value).toLocaleString("zh-CN",{year:"numeric",month:"numeric",day:"numeric",hour:"2-digit",minute:"2-digit",hour12:false});
  const ui = {identity:null, page:null, selected:null, busy:false};

  const pendingName = () => `pajio-source-exclude:v1:${state.identityId}`;
  function readPending(){try{return JSON.parse(window.WearingStore.get(pendingName())||"null");}catch{return null;}}
  function writePending(entry){try{window.WearingStore.set(pendingName(),JSON.stringify(entry));}catch{}}
  function clearPending(){try{window.WearingStore.remove(pendingName());}catch{}}
  function setNote(text){const note=$("sc-note");if(note)note.textContent=text||"";}

  async function loadPage(reset=true){
    const identity=state.identityId,epoch=state.identityEpoch;
    const offset=reset?0:(ui.page?.items.length||0);
    const params=new URLSearchParams({limit:"20",offset:String(offset)});
    if(!reset&&ui.page?.snapshot)params.set("snapshot",ui.page.snapshot);
    let data;
    try{data=await api("/api/conversation-sources?"+params);}
    catch(error){
      if(identity!==state.identityId||epoch!==state.identityEpoch||error instanceof StaleIdentity)return;
      if(error.status===409){setNote("来源列表已有变化，正在从第一页重新读取。");ui.page=null;await loadPage(true);return;}
      setNote(error.message||"来源范围暂时读不到，可稍后再试。");
      return;
    }
    if(identity!==state.identityId||epoch!==state.identityEpoch)return;
    if(reset)ui.page=data;
    else{
      if(data.snapshot!==ui.page.snapshot){setNote("来源列表已有变化，请重新读取。");return;}
      const seen=new Set(ui.page.items.map(i=>i.source_id));
      ui.page={...data,items:[...ui.page.items,...data.items.filter(i=>!seen.has(i.source_id))]};
    }
    paint();
  }

  function paint(){
    const items=ui.page?.items||[];
    $("sc-body").innerHTML=`
      <p class="pj-note">选择哪些历史对话不再作为后续回答来源。每项是一整段连续会话，包含压缩后的后续内容。</p>
      ${items.length?items.map(item=>`
        <div class="pj-card" data-sc-source="${esc(item.source_id)}">
          <div><strong>${esc(item.title||"未命名对话")}</strong>
            <small>${esc(dayText(item.started_at))} 开始 · ${item.message_count} 条入场消息</small>
            <small>${item.excluded?`已停止引用 · ${esc(dayText(item.excluded_at))}`:"可被后续对话检索和引用"}</small></div>
          <span class="brief-actions"><button class="text-button" type="button" data-sc-select="${esc(item.source_id)}">查看范围</button></span>
        </div>`).join(""):'<p class="pj-note">还没有可核对的会话来源记录。</p>'}
      ${ui.page?.next_offset!=null?`<button class="pj-load-more" type="button" id="sc-more">继续加载</button>`:""}
      ${ui.page?`<button class="text-button" type="button" id="sc-reload">重新读取来源范围</button>`:""}
      <p class="pj-note">此设置只控制对话历史检索和续接。已保存的记忆、文件、目标及其他记录仍可使用，需要在各自页面管理。历史与备份不会被删除；这不代表彻底遗忘。目前排除后不提供恢复引用。</p>
      ${ui.selected?previewMarkup(ui.selected):""}`;
    const more=$("sc-more");if(more)more.addEventListener("click",()=>busy(more,loadPage(false),$("sc-note")));
    const reload=$("sc-reload");if(reload)reload.addEventListener("click",()=>busy(reload,loadPage(true),$("sc-note")));
    const select=$("sc-body").querySelector("[data-sc-confirm]");
    if(select){
      select.addEventListener("click",()=>{
        select.dataset.confirm=String(Number(select.dataset.confirm||0)+1);
        if(select.dataset.confirm==="1"){select.textContent="再点一次确认停止引用";setTimeout(()=>{if(select.dataset.confirm==="1"){select.dataset.confirm="";select.textContent="确认停止引用";}},4000);return;}
        select.dataset.confirm="";select.textContent="确认停止引用";
        submitExclude();
      });
    }
    const cancel=$("sc-cancel");
    if(cancel)cancel.addEventListener("click",()=>{ui.selected=null;setNote("已取消；没有发出任何请求。");paint();});
  }

  function previewMarkup(item){
    return `<section class="pj-section" aria-label="范围预览"><p class="pj-section-title">以后不再引用这段对话</p>
      <div class="pj-card"><div><strong>${esc(item.title||"未命名对话")}</strong>
        <small>开始于 ${esc(dayText(item.started_at))} · 入场消息 ${item.message_count} 条</small>
        <small>${item.excluded?"当前状态：已停止引用":"当前状态：仍作为来源"}</small></div></div>
      <p class="pj-note">确认后：这段会话及其压缩后的后续内容不再进入关键词搜索、直接读取、邻近翻阅和最近会话列表；这个身份的后续聊天从全新会话上下文开始。</p>
      <p class="pj-note">历史仍可查看。已保存的记忆、文件和目标不会删除；本页暂不提供恢复引用。若这个身份仍有运行中或待核对的任务，请先结束任务后再确认。</p>
      <div class="brief-actions">
        <button class="secondary" type="button" data-sc-confirm="1">确认停止引用</button>
        <button class="text-button" type="button" id="sc-cancel">取消</button>
      </div></section>`;
  }

  async function submitExclude(replay=null){
    if(ui.busy)return;
    const source=replay?null:ui.selected;
    const pageRevision=ui.page?.revision;
    if(!replay&&(!source||pageRevision==null))return;
    const body=replay||{source_id:source.source_id,source_revision:source.source_revision,revision:pageRevision,request_key:window.WearingIds.uuid().replaceAll("-","")};
    // 完整请求先持久，结果未知沿用同一 key 取回原回执（合同）。
    writePending({identity:state.identityId,body});
    ui.busy=true;setNote("正在确认停止引用…");
    const identity=state.identityId,epoch=state.identityEpoch;
    try{
      const receipt=await api("/api/conversation-sources/exclude",{method:"POST",body:JSON.stringify(body)});
      if(identity!==state.identityId||epoch!==state.identityEpoch)return;
      if(!receipt||receipt.identity_id!==state.identityId||receipt.source_id!==body.source_id
        ||receipt.revision!==body.revision+1||receipt.request_key!==body.request_key
        ||receipt.excluded!==true||receipt.history_retained!==true)
        throw Object.assign(new Error("回执与本次操作不一致，已保留请求，可取回原回执核对。"),{replayable:true});
      clearPending();
      ui.selected=null;
      setNote("已停止引用所选对话。后续消息将从新的会话上下文开始，历史仍可查看。");
      await loadPage(true);
    }catch(error){
      if(identity!==state.identityId||epoch!==state.identityEpoch)return;
      if(error instanceof StaleIdentity)return;
      if(error&&error.status){
        clearPending();
        ui.selected=null;
        setNote(`${error.message||"这次确认没有生效。"} 请重新读取列表、重新选定后再确认。`);
        paint();
      }else{
        setNote((error.message||"结果未知。")+" 已保留原请求，可用「取回原操作回执」继续核对。");
        paintRetrieve();
      }
    }finally{ui.busy=false;}
  }

  function paintRetrieve(){
    if($("sc-retrieve"))return;
    const button=document.createElement("button");
    button.type="button";button.className="secondary";button.id="sc-retrieve";button.textContent="取回原操作回执";
    button.addEventListener("click",()=>busy(button,()=>submitExclude(readPending()?.body),$("sc-note")));
    setNoteAfter(button);
  }
  function setNoteAfter(button){const note=$("sc-note");if(note)note.after(button);}

  async function open(){
    ui.identity=state.identityId;ui.selected=null;ui.page=null;
    $("sc-body").innerHTML='<p class="life-empty">正在读取来源范围……</p>';
    openPanel("sources-panel");
    const pending=readPending();
    if(pending&&pending.identity===state.identityId){
      setNote("发现未确认的停止引用操作，可用同一请求取回。");
      await submitExclude(pending.body);
      return;
    }
    await loadPage(true);
  }

  document.addEventListener("click",event=>{
    if(event.target.closest("[data-sources-open]")){open();return;}
    const select=event.target.closest("[data-sc-select]");
    if(select){ui.selected=(ui.page?.items||[]).find(i=>i.source_id===select.dataset.scSelect)||null;setNote("");paint();}
  });
  window.WearingSources={open};
})();
