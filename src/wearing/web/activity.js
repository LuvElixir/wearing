"use strict";
// A view of persisted work, never a scheduler or an implicit approval.
(() => {
  let snapshot=null,signature="",lastLoad=0,pending=null,mutation=null,generation=0,openGeneration=0;
  const $=id=>document.getElementById(id);
  const panel=document.getElementById("activity-panel");
  const summary=document.getElementById("activity-return");
  const groups={attention:"等你处理",active:"正在推进",waiting:"已排队",results:"已有结果"};
  const clock=value=>new Intl.DateTimeFormat("zh-CN",{hour:"2-digit",minute:"2-digit"}).format(new Date(value));
  function disconnected(){
    $("activity-error").textContent=snapshot?`暂时未连上，以下是 ${clock(snapshot.checked_at)} 查看时的进展。`:"暂时读不到进展，请稍后重试。";
    $("activity-updated").textContent=snapshot?`上次查看 · ${clock(snapshot.checked_at)}`:"等待连接";
    if(snapshot&&snapshot.total)$("activity-return-title").textContent="连接中断 · 保留上次进展";
  }
  function render(data){
    snapshot=data;document.body.classList.add("has-activity");
    const count=data.counts;
    summary.hidden=!data.total;
    $("activity-return-title").textContent=count.attention?`${count.attention} 件等你处理${data.unread?` · ${data.unread} 份新结果`:""}`:data.unread?`${data.unread} 份新结果，回来看看`:count.active?`${count.active} 件正在推进${count.waiting?` · ${count.waiting} 件已排队`:""}`:count.waiting?`${count.waiting} 件已排队，轮到时继续`:"最近交给我的事";
    const first=data.items.find(i=>i.bucket==="attention")||data.items.find(i=>i.unread)||data.items[0];
    $("activity-return-detail").textContent=first?first.title:"";
    $("activity-updated").textContent=`读取于 · ${clock(data.checked_at)}`;
    $("activity-error").textContent="";
    const next=JSON.stringify([data.items,data.counts,data.has_more]);
    // Do not replace focused controls on every background read.
    if(next===signature)return;
    signature=next;
    $("activity-list").innerHTML=Object.entries(groups).map(([bucket,title])=>{
      const items=data.items.filter(i=>i.bucket===bucket);
      if(!items.length)return "";
      return `<section class="activity-group"><h3>${title}<span>${count[bucket]??items.length}</span></h3>${items.map(item=>`<button class="activity-item" data-activity-task="${esc(item.task_id)}"><span class="activity-meta">${item.unread?'<i class="activity-unread" aria-label="未读"></i>':""}${esc(item.label)}</span><strong>${esc(item.title)}</strong><span class="activity-prose">${esc(item.summary)}</span><span class="activity-forward">${bucket==="attention"?"查看这一步":bucket==="waiting"?"查看排队":bucket==="active"?"查看进展":"查看结果"}<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m9 6 6 6-6 6"/></svg></span></button>`).join("")}</section>`;
    }).join("")||'<p class="activity-empty">还没有交给 Wearing 的事。说一个想法，我们从那里开始。</p>';
    $("activity-more").hidden=!data.has_more;
  }
  async function load(force=false){
    if(!state.token||(!force&&Date.now()-lastLoad<10000))return;
    if(mutation)return mutation;
    if(pending)return pending;
    const epoch=state.identityEpoch,requestGeneration=++generation;
    lastLoad=Date.now();
    const work=(async()=>{
      try{const data=await api("/api/activity");if(epoch===state.identityEpoch&&requestGeneration===generation)render(data);}
      catch(error){if(epoch!==state.identityEpoch||requestGeneration!==generation||error instanceof StaleIdentity)return;
        disconnected();
      }
    })();
    pending=work;try{await work;}finally{if(pending===work)pending=null;}
  }
  async function open(){openPanel("activity-panel");await load(true);}
  async function openTask(taskId){
    if(typeof taskId!=="string"||!/^[-a-zA-Z0-9_]{1,64}$/.test(taskId))return;
    const epoch=state.identityEpoch,openTicket=++openGeneration;
    const isCurrent=()=>epoch===state.identityEpoch&&openTicket===openGeneration;
    await load(true);
    if(!isCurrent())return;
    const item=snapshot?.items.find(i=>i.task_id===taskId);
    await loadConversation(true,isCurrent);
    if(!isCurrent())return;
    window.WearingLife?.openView("chat");
    if(panel.open)await new Promise(resolve=>{panel.addEventListener("close",resolve,{once:true});closePanel("activity-panel");});
    if(!isCurrent())return;
    const turn=document.getElementById("task-turn-"+taskId)||document.getElementById("goal-turn-"+taskId);
    if(turn){
      turn.scrollIntoView({block:"start",behavior:state.motionPaused?"instant":"smooth"});
      turn.focus({preventScroll:true});
    }else{
      openPanel("keeps-panel");
      $("keep-detail").closest("details").open=true;
      await loadKeep(taskId,isCurrent);
      if(!isCurrent())return;
      $("keep-detail").scrollIntoView({block:"start",behavior:state.motionPaused?"instant":"smooth"});
    }
    if(isCurrent()&&item?.unread&&item.bucket==="results"){
      const requestGeneration=++generation;
      const work=(async()=>{
        try{const data=await api("/api/activity/seen",{method:"POST",body:JSON.stringify({items:[{task_id:item.task_id,version:item.version}]})});if(epoch===state.identityEpoch&&requestGeneration===generation)render(data);}
        catch(error){if(epoch===state.identityEpoch&&!(error instanceof StaleIdentity))notice("结果已打开；已读状态暂未保存，不影响这件事。",true);}
      })();
      mutation=work;try{await work;}finally{if(mutation===work)mutation=null;}
    }
  }
  function reset(){generation++;openGeneration++;snapshot=null;signature="";lastLoad=0;pending=null;mutation=null;summary.hidden=true;$("activity-list").replaceChildren();$("activity-updated").textContent="正在查看…";$("activity-error").textContent="";document.body.classList.remove("has-activity");}
  $("open-activity").addEventListener("click",()=>{closePanel("review-panel");open();});
  summary.addEventListener("click",open);
  $("activity-refresh").addEventListener("click",()=>busy($("activity-refresh"),()=>load(true),$("activity-error")));
  $("activity-list").addEventListener("click",event=>{const button=event.target.closest("[data-activity-task]");if(button)busy(button,()=>openTask(button.dataset.activityTask),$("activity-error"));});
  window.WearingActivity={load,reset,open,openTask,disconnected};
})();
