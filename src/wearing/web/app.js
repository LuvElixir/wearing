"use strict";
const $ = id => document.getElementById(id);
const esc = text => String(text ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const state = {identityId:"daily",identities:[],identityEpoch:0,drafts:{},editingIdentity:null,token:"",connected:false,messages:[],signature:"",polling:false,lastStatus:0,selectedKeep:null,keepSignature:"",sending:false,computer:null,goalFocus:null,goalSource:null,motionPaused:matchMedia("(prefers-reduced-motion: reduce)").matches};
const labels = {draft:"留在这里",starting:"正在送出",running:"正在回应",waiting_for_approval:"有一步需要你",stopping:"正在停止",connection_lost:"连接中断",ambiguous:"等待核对",completed_unverified:"已有回应",verified:"已核对",stopped:"已停止",failed:"需要再看看",closed_by_user:"已处理"};
const active = new Set(["starting","running","waiting_for_approval","stopping","connection_lost","ambiguous"]);
class StaleIdentity extends Error {}
async function api(path,options={}) {
  const epoch=state.identityEpoch;
  const headers={"Content-Type":"application/json","X-Wearing-Identity":state.identityId,...options.headers};
  if(options.method && options.method!=="GET") headers["X-Wearing-Token"]=state.token;
  const response=await fetch(path,{...options,headers});
  const data=await response.json();
  if(epoch!==state.identityEpoch)throw new StaleIdentity();
  if(!response.ok) throw new Error(typeof data.detail==="string"?data.detail:"内容没有送出，请检查后重试。");
  return data;
}
function notice(text,error=false){$("notice").textContent=text;$("notice").className="notice"+(error?" error":"");$("notice").hidden=!text;}
async function busy(button,action,feedback=null){const old=[...button.childNodes];button.disabled=true;try{await action();}catch(error){if(error instanceof StaleIdentity)return;if(feedback){feedback.textContent=error.message||"连接中断，请稍后再试。";feedback.scrollIntoView({block:"nearest"});}else notice(error.message||"连接中断，请稍后再试。",true);}finally{if(button.isConnected){button.disabled=false;button.replaceChildren(...old);}}}
function nearBottom(){return window.innerHeight+window.scrollY>=document.documentElement.scrollHeight-160;}
function scrollToLatest(){window.scrollTo({top:document.documentElement.scrollHeight,behavior:state.motionPaused?"instant":"smooth"});$("newest-message").hidden=true;}
function date(value){return new Intl.DateTimeFormat("zh-CN",{month:"numeric",day:"numeric"}).format(new Date(value));}
function openPanel(id){$(id).showModal();}
function closePanel(id){$(id).close();}
function turnActions(turn,source=null){
  let html="";
  if(active.has(turn.status)){
    if(turn.run_id&&turn.status!=="stopping")html+=`<button data-action="stop" data-task="${esc(turn.id)}">先停一下</button>`;
    html+=`<button data-action="refresh" data-task="${esc(turn.id)}">重新查看</button>`;
  }
  if(turn.status==="completed_unverified")html+=`<button data-verify="${esc(turn.id)}">记下核对结果</button>`;
  if(source&&["completed_unverified","verified"].includes(turn.status))html+=`<button data-goal-source="${esc(source)}">把这件事记成目标</button>`;
  return html?`<div class="turn-tools">${html}</div>`:"";
}
function turnMarkup(message){
  const turn=message.turn,id=turn.id,isGoal=message.kind==="goal_step";
  const goalContext=message.goal_id&&!isGoal?`<div class="goal-conversation-label"><button class="text-button" data-goal="${esc(message.goal_id)}">${message.goal_mode==="note"?"补充新情况":"聊聊这件事"} · ${esc(message.goal_title)}</button></div>`:"";
  const user=message.kind==="goal_step"?`<div class="goal-conversation-label"><button class="text-button" data-goal="${esc(message.goal_id)}">一起记着：${esc(message.content)}</button></div>`:goalContext+`<div class="message message-user"><div class="user-bubble">${esc(message.content)}</div></div>`;
  let response="";
  if(turn.output){response=`<div class="message message-assistant"><img class="message-avatar" src="/assets/avatar.png?v=1" alt="Wearing"><div class="assistant-content"><div class="assistant-copy">${esc(turn.output)}</div>${turnActions(turn,isGoal||message.goal_id?null:id)}${turn.verification_note?`<p class="note-saved">核对记录：${esc(turn.verification_note)}</p>`:""}<div id="verify-${esc(id)}"></div></div></div>`;}
  if(turn.status==="draft"&&isGoal)response+=`<div class="delivery-note"><p>${state.connected?"这一步已安排，轮到时会自动推进。":"这一步等待连接恢复。目标与约定仍然保留。"}</p><button class="text-button" data-goal="${esc(message.goal_id)}">查看目标与进展</button></div>`;
  if(turn.status==="draft"&&message.queued)response+=`<div class="delivery-note"><p>这条已经收下，等前面的对话处理后回应。</p><button class="text-button" data-action="cancel-message" data-task="${esc(id)}">这条先不发</button></div>`;
  if(turn.status==="draft"&&!isGoal&&!message.queued)response+=`<div class="delivery-note"><p>${state.connected?"这条还没有送出。你可以从这里继续。":"这句话已保存在本机。连接 Wearing 后，才能获得真实回应。"}</p><button class="text-button" ${state.connected?`data-action="start" data-task="${esc(id)}"`:'data-open-settings'}>${state.connected?"继续这句话":"连接 Wearing"}</button></div>`;
  if(["starting","running","stopping"].includes(turn.status)&&!turn.output)response+=`<div class="message response-wait"><img src="/assets/avatar.png?v=1" alt=""><span>${turn.status==="stopping"?"正在等待本轮停止……":"Wearing 正在回应……"}</span>${turnActions(turn)}</div>`;
  if(["connection_lost","ambiguous","failed"].includes(turn.status))response+=`<div class="delivery-note error"><p>${esc(turn.error||"这次连接没有完成，原消息仍然保留。")}</p>${turnActions(turn)}${["connection_lost","ambiguous"].includes(turn.status)?`<details class="setup-guide"><summary>已在执行电脑上处理完毕</summary><p>确认原运行和设备操作已经结束后，记录处理结果。这不会替你终止远端进程。</p><form class="note-form" data-resolve="${esc(id)}"><label for="resolve-${esc(id)}">处理记录</label><textarea id="resolve-${esc(id)}" name="note" required minlength="5" maxlength="2000"></textarea><button class="secondary">记录并结束</button></form></details>`:""}</div>`;
  if(turn.status==="waiting_for_approval"){
    const a=turn.approval;
    response+=a?.request_id?`<div class="message message-assistant"><img class="message-avatar" src="/assets/avatar.png?v=1" alt=""><div class="assistant-content approval"><p>继续之前，这一步需要你决定。</p><pre>${esc(a.description||a.command||a.preview||JSON.stringify(a,null,2))}</pre><div class="button-row"><button class="primary" data-choice="once" data-task="${esc(id)}" data-request="${esc(a.request_id)}">允许这一次</button><button class="secondary" data-choice="deny" data-task="${esc(id)}" data-request="${esc(a.request_id)}">这次先不做</button></div>${turnActions(turn)}</div></div>`:`<div class="delivery-note">执行端有一步等待确认，但还没有返回完整内容。${turnActions(turn)}</div>`;
  }
  if(turn.status==="stopped"&&!turn.output)response+='<div class="delivery-note">本轮已停止，前面的对话仍然保留。</div>';
  return message.kind==="goal_step"?`<section id="goal-turn-${esc(id)}">${user+response}</section>`:user+response;
}
async function loadConversation(force=false){
  const messages=await api("/api/conversation");state.messages=messages;
  const signature=JSON.stringify([state.connected,messages]);
  if(signature===state.signature&&!force)return;
  if(!force&&$("messages").contains(document.activeElement))return;
  const stick=nearBottom();state.signature=signature;
  $("welcome").hidden=messages.length>0;$("conversation").hidden=!messages.length;
  $("messages").innerHTML=messages.map(turnMarkup).join("");
  const focused=messages.find(m=>active.has(m.turn.status));
  $("composer-footnote").firstChild.textContent=focused?"继续说也可以，消息会保留在这段对话里。":"想到哪儿，聊到哪儿。";
  if(stick&&messages.length)scrollToLatest();else if(messages.length)$("newest-message").hidden=false;
  updateCompanion();
  syncMotion();
}
async function loadStatus(){
  const result=await api("/api/status");state.lastStatus=Date.now();state.connected=["reachable","ready"].includes(result.hermes.state);
  const other=result.other_active?.[0];$("identity-running").hidden=!other;$("identity-running").textContent=other?`${other.name}里还有一件事${["connection_lost","ambiguous"].includes(other.status)?"等待核对":"正在处理"} · 点此查看`:"";$("identity-running").dataset.identity=other?.identity_id||"";
  $("connection-label").textContent=result.hermes.state==="ready"?"身份已就绪":state.connected?"已连接":"连接 Wearing";
  $("connection-dot").classList.toggle("online",state.connected);
  updateCompanion();
  renderReport($("device-report"),result.device_report,"你的设备报告");
}
async function loadRuntime(){
  const r=await api("/api/runtime");
  const pending=["downloading","installing","starting"].includes(r.phase);
  const copy={downloading:"正在准备 Wearing 的执行引擎……",installing:"正在准备运行环境，首次安装需要几分钟。",starting:"正在启动本地引擎……",running:"Wearing 已在这台电脑运行。"};
  $("runtime-status").textContent=r.error||copy[r.phase]||(r.installed?(r.model?.state==="configured"?"模型已配置，可以启动。首次回应后再验证实际可用性。":"引擎已安装。请先展开模型设置，选择服务并登录。"):"准备 Wearing，再连接你使用的模型。原对话会一直保留。");
  $("runtime-status").className="inline-feedback"+(r.error?" error":"");
  $("runtime-install").hidden=r.installed||r.running;
  $("runtime-install").disabled=pending;
  $("runtime-start").hidden=!r.installed||r.running;
  $("runtime-start").disabled=pending;
  $("runtime-stop").hidden=!r.running;
  $("model-command").textContent=r.model_setup_command;
  const files=r.files||{};
  $("files-status").textContent=files.error||(files.phase==="installing"?"正在准备文件能力，首次安装需要几分钟……":files.active?"已接通，可以让 Wearing 帮你写文件。":files.installed?"文件能力已准备，启动本地引擎后可用。":"启用后，可以让 Wearing 把内容整理成文件。");
  $("files-enable").hidden=files.installed&&files.phase!=="failed";
  $("files-enable").disabled=!r.installed||files.phase==="installing"||pending;
  $("engine-profile").textContent=r.product?.applied?`Wearing 个人模式 · 配置 v${r.product.profile_version} · 引擎 ${r.revision}。Hermes 原生调度和消息平台未启用；目标跟进由 Wearing 本地服务负责。`:"Wearing 个人模式会在下次启动引擎时应用。";
  if(r.installed&&!modelSettings&&!modelLoading)await loadModel();
}
for(const action of ["install","start","stop"]){
  $("runtime-"+action).addEventListener("click",async()=>{
    const button=$("runtime-"+action);button.disabled=true;
    $("runtime-status").textContent=action==="start"?"正在启动本地引擎……":action==="stop"?"正在关闭本地引擎……":"正在准备安装……";
    try{await api("/api/runtime/"+action,{method:"POST",body:"{}"});await loadRuntime();await loadStatus();await loadConversation(true);}
    catch(error){$("runtime-status").textContent=error.message;$("runtime-status").className="inline-feedback error";}
    finally{button.disabled=false;}
  });
}
function renderReport(container,report,title){
  if(!report){container.replaceChildren();return;}
  const system={Darwin:"macOS",Windows:"Windows",Linux:"Linux"}[report.system]||"未知系统";
  container.innerHTML=`<div class="report-block"><strong>${esc(title)}</strong><p>${esc(system)} · ${esc(report.architecture)}</p><p>Hermes ${report.commands?.hermes?"已发现":"未发现"} · ADB ${report.commands?.adb?"已发现":"未发现"}</p><p>${report.phones?.length?report.phones.map(p=>`${esc(p.model)} · ${esc(p.android_version||"")} · ${esc(p.state)}`).join("<br>"):"尚未识别到手机"}</p><p>检测于 ${esc(date(report.observed_at))}；操作能力仍需验证。</p></div>`;
}
async function loadKeeps(){
  await loadGoals();
  const tasks=await api("/api/tasks");const conversationIds=new Set(state.messages.map(m=>m.task_id));
  const kept=tasks.filter(t=>!conversationIds.has(t.id));
  $("keeps-list").innerHTML=kept.length?kept.map(t=>`<button class="keep-row" data-keep="${esc(t.id)}"><strong>${esc(t.title)}</strong><small>${esc(date(t.created_at))} · ${esc(labels[t.status]||t.status)}</small></button>`).join(""):'<p class="empty-keeps">这里还没有单独留下的事情。我们的对话，会一直保留在外面。</p>';
}
let memoryEntries=[];
async function loadMemory(){
  const epoch=state.identityEpoch;
  $("memory-feedback").textContent="正在找回记着的事情……";
  try{
    const data=await api("/api/memory");
    memoryEntries=[];$("memory-list").replaceChildren();
    if(!data.available){$("memory-feedback").textContent=data.message;return;}
    $("memory-list").innerHTML=["user","memory"].map(target=>{
      const group=data.targets[target],title=target==="user"?"关于你":"一起积累的经验";
      const rows=group.entries.map(entry=>{const index=memoryEntries.push(entry)-1;return `<div class="memory-entry"><p>${esc(entry)}</p><button class="text-button" data-correct-memory="${index}" aria-label="纠正第 ${index+1} 条记忆">这条需要纠正</button></div>`;}).join("");
      return `<section class="memory-group"><h3>${title}</h3>${!group.enabled?'<p class="field-help">这部分记忆已关闭；原记录仍保留。</p>':""}${rows||`<p class="field-help">${group.enabled?"还没有记下内容。":""}</p>`}</section>`;
    }).join("");
    $("memory-feedback").textContent="从当前身份的记忆中读取。纠正后可以重新查看。";
  }catch(error){if(!(error instanceof StaleIdentity)&&epoch===state.identityEpoch){memoryEntries=[];$("memory-list").replaceChildren();$("memory-feedback").textContent="暂时读不到记忆，原记录仍保留。";}}
}
function composeMemory(text){
  const input=$("message-input");
  if(input.value.trim()){ $("memory-feedback").textContent="输入框里还有未发送的内容，先处理它，再来补充记忆。";return; }
  state.goalFocus=null;renderGoalContext();closePanel("keeps-panel");input.value=text;input.dispatchEvent(new Event("input"));input.focus();
}
$("memory-section").addEventListener("toggle",()=>{if($("memory-section").open)loadMemory();});
$("refresh-memory").addEventListener("click",()=>busy($("refresh-memory"),loadMemory,$("memory-feedback")));
$("remember-something").addEventListener("click",()=>composeMemory("帮我记住："));
$("memory-list").addEventListener("click",event=>{const button=event.target.closest("[data-correct-memory]");if(button){const entry=memoryEntries[Number(button.dataset.correctMemory)];if(entry!==undefined)composeMemory(`这条记忆需要纠正：${entry}\n正确的是：`);}});
async function loadKeep(id){
  state.selectedKeep=id;const t=await api("/api/tasks/"+id);
  $("keep-detail").hidden=false;
  $("keep-detail").innerHTML=`<h3>${esc(t.title)}</h3><p class="prompt">${esc(t.prompt)}</p><button class="primary" id="bring-to-conversation">带回对话</button>${t.output?`<div class="assistant-copy">${esc(t.output)}</div>`:""}${turnActions(t)}<div id="verify-${esc(t.id)}"></div><ol class="keep-timeline">${t.events.map(e=>`<li>${esc(e.message)}</li>`).join("")}</ol>`;
  $("bring-to-conversation").addEventListener("click",()=>{closePanel("keeps-panel");$("message-input").value="我们接着聊这件事："+t.prompt;$("message-input").focus();});
}
$("conversation-form").addEventListener("submit",async event=>{
  event.preventDefault();const content=$("message-input").value.trim();if(!content)return;
  state.sending=true;$("open-identities").disabled=true;updateCompanion();
  try{await busy($("send-message"),async()=>{const result=await api("/api/conversation",{method:"POST",body:JSON.stringify({content,...(state.goalFocus?{goal_id:state.goalFocus.id,goal_mode:state.goalFocus.mode,...(state.goalFocus.mode==="note"?{goal_revision:state.goalFocus.revision}:{})}:{})})});if(result.goal&&state.goalFocus?.id===result.goal.id){state.goalFocus.revision=result.goal.revision;if(state.goalFocus.mode==="note")state.goalFocus.mode="discuss";renderGoalContext();}$("message-input").value="";notice("");await loadConversation(true);scrollToLatest();if(result.delivery==="saved"&&state.connected)notice(result.reason);});}finally{state.sending=false;$("open-identities").disabled=false;updateCompanion();}
});
$("message-input").addEventListener("keydown",event=>{if(event.key==="Enter"&&!event.shiftKey&&!event.isComposing){event.preventDefault();if(!$("send-message").disabled)$("conversation-form").requestSubmit();}});
$("open-settings").addEventListener("click",showSettings);
$("open-keeps").addEventListener("click",async()=>{openPanel("keeps-panel");await loadKeeps().catch(e=>notice(e.message,true));});
$("newest-message").addEventListener("click",scrollToLatest);
window.addEventListener("scroll",()=>{if(nearBottom())$("newest-message").hidden=true;},{passive:true});
document.addEventListener("click",async event=>{
  const close=event.target.closest("[data-close]");if(close){closePanel(close.dataset.close);return;}
  if(event.target.closest("[data-open-settings]")){showSettings();return;}
  const suggestion=event.target.closest("[data-suggestion]");if(suggestion){$("message-input").value=suggestion.dataset.suggestion;$("message-input").focus();return;}
  const keep=event.target.closest("[data-keep]");if(keep){await loadKeep(keep.dataset.keep).catch(e=>notice(e.message,true));return;}
  const source=event.target.closest("[data-goal-source]");if(source){const message=state.messages.find(m=>m.task_id===source.dataset.goalSource);if(message){if(!$("keeps-panel").open)openPanel("keeps-panel");await loadGoals();showGoalForm(message.content,source.dataset.goalSource);}return;}
  const goal=event.target.closest("[data-goal]");if(goal){if(!$("keeps-panel").open)openPanel("keeps-panel");await loadGoals();await loadGoal(goal.dataset.goal).catch(e=>{$("goal-feedback").textContent=e.message;});return;}
  const goalTurn=event.target.closest("[data-goal-turn]");if(goalTurn){closePanel("keeps-panel");await loadConversation(true);$("goal-turn-"+goalTurn.dataset.goalTurn)?.scrollIntoView({block:"center",behavior:state.motionPaused?"instant":"smooth"});return;}
  const action=event.target.closest("[data-action]");if(action){await busy(action,async()=>{await api(`/api/tasks/${action.dataset.task}/${action.dataset.action}`,{method:"POST",body:"{}"});await loadConversation(true);if(state.selectedKeep===action.dataset.task)await loadKeep(state.selectedKeep);});return;}
  const choice=event.target.closest("[data-choice]");if(choice){await busy(choice,async()=>{await api(`/api/tasks/${choice.dataset.task}/approval`,{method:"POST",body:JSON.stringify({request_id:choice.dataset.request,choice:choice.dataset.choice})});await loadConversation(true);});return;}
  const verify=event.target.closest("[data-verify]");if(verify){const id=verify.dataset.verify;$("verify-"+id).innerHTML=`<form class="note-form" data-verify-form="${esc(id)}"><label for="note-${esc(id)}">你核对了什么？</label><textarea id="note-${esc(id)}" name="note" required minlength="3" maxlength="2000" placeholder="留下实际核对的结果。"></textarea><button class="secondary">保存记录</button></form>`;$("note-"+id).focus();}
});
document.addEventListener("submit",async event=>{
  const form=event.target;if(!form.dataset.verifyForm&&!form.dataset.resolve)return;
  event.preventDefault();const id=form.dataset.verifyForm||form.dataset.resolve;
  await busy(form.querySelector("button"),async()=>{await api(`/api/tasks/${id}/${form.dataset.resolve?"resolve":"verify"}`,{method:"POST",body:JSON.stringify({note:form.elements.note.value})});await loadConversation(true);if(state.selectedKeep===id)await loadKeep(id);});
});
$("connection-form").addEventListener("submit",async event=>{
  event.preventDefault();const button=$("connect-button");button.disabled=true;$("connection-feedback").textContent="正在连接……";
  try{const result=await api("/api/connection",{method:"POST",body:JSON.stringify({url:$("hermes-url").value,key:$("hermes-key").value})});$("hermes-key").value="";$("connection-feedback").className="inline-feedback";$("connection-feedback").textContent=result.message;await loadStatus();await loadConversation(true);}catch(error){$("connection-feedback").className="inline-feedback error";$("connection-feedback").textContent=error.message;}finally{button.disabled=false;}
});
$("inspect-host").addEventListener("click",()=>busy($("inspect-host"),async()=>renderReport($("host-report"),await api("/api/doctor"),"当前这台电脑")));
$("import-report").addEventListener("click",()=>$("report-file").click());
$("report-file").addEventListener("change",async()=>{const file=$("report-file").files[0];if(!file)return;await busy($("import-report"),async()=>{if(file.size>32000)throw new Error("请选择检测脚本生成的 JSON 小文件。");await api("/api/device-report",{method:"POST",body:await file.text()});await loadStatus();});$("report-file").value="";});

let modelSettings=null,modelLoading=false;
function keyHelp(){
  const provider=modelSettings?.providers.find(p=>p.id===$("model-provider").value);
  $("model-key").required=!provider?.configured;
  $("model-key").placeholder=provider?.configured?"已保存，留空保留原密钥":"填写这个服务商的 API Key";
  $("model-key-help").textContent=provider?.configured?"已有密钥保存在本机。留空即可继续使用；填写新值会替换它。":"密钥仅保存在本机，不会显示在对话或配置响应中。";
}
async function loadModel(){
  if(modelLoading)return;
  modelLoading=true;
  $("model-save").disabled=true;
  try{
    modelSettings=await api("/api/model");
    $("model-provider").innerHTML=modelSettings.providers.map(p=>`<option value="${esc(p.id)}">${esc(p.name)}</option>`).join("");
    if(modelSettings.providers.some(p=>p.id===modelSettings.provider))$("model-provider").value=modelSettings.provider;
    else $("model-provider").value="";
    $("model-id").value=modelSettings.model;$("model-key").value="";
    $("model-feedback").textContent=$("model-provider").value?"":"当前服务请使用下面的本地向导管理，也可以在这里选择新服务。";
    keyHelp();$("model-save").disabled=false;
  }catch(e){$("model-feedback").textContent=e.message;}finally{modelLoading=false;}
}
function showSettings(){if(state.identityId!=="daily"){showIdentities();return;}openPanel("settings-panel");loadPhone();loadComputer();loadRuntime().catch(e=>{$("runtime-status").textContent=e.message;});loadModel();}
$("model-provider").addEventListener("change",()=>{$("model-key").value="";$("model-id").value=$("model-provider").value===modelSettings?.provider?modelSettings.model:"";keyHelp();});
$("model-form").addEventListener("submit",async event=>{
  event.preventDefault();$("model-save").disabled=true;$("model-feedback").className="inline-feedback";$("model-feedback").textContent="正在校验并应用模型设置……";
  try{
    const result=await api("/api/model",{method:"POST",body:JSON.stringify({provider:$("model-provider").value,model:$("model-id").value,key:$("model-key").value})});
    $("model-key").value="";await loadModel();$("model-feedback").textContent=result.message;await loadRuntime();await loadStatus();
  }catch(e){$("model-feedback").className="inline-feedback error";$("model-feedback").textContent=e.message;}finally{$("model-save").disabled=false;}
});
$("files-enable").addEventListener("click",async()=>{
  $("files-enable").disabled=true;$("files-feedback").textContent="";
  try{await api("/api/workspace/enable",{method:"POST",body:"{}"});await loadRuntime();}catch(e){$("files-feedback").textContent=e.message;$("files-enable").disabled=false;}
});
async function loadFiles(){
  const result=await api("/api/workspace");$("files-path").textContent=result.capability.path;
  $("files-list-status").textContent=result.truncated?"目录内容较多，暂时显示前 200 个文件。":result.files.length?`${result.files.length} 个文件`:"还没有文件。让 Wearing 帮你把一个想法写下来试试。";
  $("files-list").innerHTML=result.files.map(file=>`<a class="file-row" download href="/api/workspace/file?identity=${encodeURIComponent(state.identityId)}&path=${encodeURIComponent(file.path)}"><span>${esc(file.path)}</span><small>${file.size<1024?file.size+" B":(file.size/1024).toFixed(1)+" KB"} · 下载</small></a>`).join("");
}
$("open-files").addEventListener("click",()=>{openPanel("files-panel");loadFiles().catch(e=>{$("files-list-status").textContent=e.message;});});
$("refresh-files").addEventListener("click",()=>busy($("refresh-files"),loadFiles));


let phoneState=null,phoneLoading=false,lastPhoneCheck=0,phoneOptionsSignature="",phoneResourceSignature="";
async function loadPhone(){
  if(state.identityId!=="daily")return;
  if(phoneLoading)return;phoneLoading=true;
  try{
    const r=await api("/api/phone");phoneState=r;lastPhoneCheck=Date.now();
    const connector=r.connector,phones=r.devices,resources=r.resources||[];
    const installing=connector.phase==="installing";
    const enrolled=new Set(resources.map(p=>p.serial));
    const candidates=phones.filter(p=>!enrolled.has(p.serial));
    const available=candidates.filter(p=>p.state==="device");
    let copy="连接 Android 手机，解锁屏幕后允许 USB 调试。";
    if(r.state==="adb_missing")copy="先准备手机连接器，Wearing 会安装官方 Android 连接工具。";
    else if(r.state==="adb_failed")copy="暂时无法读取手机连接状态，请重新检测。";
    else if(resources.length)copy=`已接入 ${resources.length} 部手机，${resources.filter(p=>p.online).length} 部在线。${!resources.some(p=>p.enabled)?"手机操作已全部暂停。":!resources.some(p=>p.online&&p.enabled)?"等待已启用的手机连接。":connector.active?"可以直接在对话里请 Wearing 操作。":"启动本地引擎后即可使用。"}`;
    else if(phones.some(p=>p.state==="unauthorized"))copy="已发现手机，请在手机上点“允许 USB 调试”。";
    else if(phones.some(p=>p.state==="offline"))copy="手机暂时离线，请解锁并重新连接数据线。";
    else if(available.length)copy=`发现 ${available.length} 部已授权手机，选择接入即可。`;
    $("phone-status").textContent=connector.error||(installing?"正在准备手机连接器……":copy);
    $("phone-prepare").hidden=connector.installed&&connector.native_input_installed;$("phone-prepare").disabled=installing;
    $("phone-prepare").textContent=connector.installed?"准备中文输入组件":"准备手机连接器";
    const resourceSignature=JSON.stringify(resources);
    if(resourceSignature!==phoneResourceSignature){
      phoneResourceSignature=resourceSignature;
      $("phone-resources").innerHTML=resources.map(p=>`<article class="phone-resource"><div><strong>${esc(p.name)} <span class="phone-suffix">${esc(p.serial.slice(-4))}</span></strong><p>Android ${esc(p.android_version||"未知")} · ${p.online?"在线":p.connection_state==="unauthorized"?"等待调试授权":"未连接"} · ${p.enabled?"已启用":"已暂停"}</p><p>${p.capabilities?.native_text_readback?"原生输入框填写 · 已在这部手机读回验证":"点击、滑动与输入能力将在使用中确认"}</p></div><button type="button" class="secondary" data-phone-action="${p.enabled?"pause":"resume"}" data-resource-id="${esc(p.resource_id)}" aria-label="${p.enabled?"暂停":"恢复"} ${esc(p.name)} ${esc(p.serial.slice(-4))}">${p.enabled?"暂停":"恢复"}</button></article>`).join("");
    }
    $("phone-form").hidden=!connector.installed||!candidates.length;
    const signature=JSON.stringify(candidates);
    if(signature!==phoneOptionsSignature){
      const previous=$("phone-device").value;phoneOptionsSignature=signature;
      $("phone-device").innerHTML=candidates.map(p=>`<option value="${esc(p.serial)}" ${p.state==="device"?"":"disabled"}>${esc(p.model)} · ${esc(p.serial.slice(-4))} · ${p.state==="device"?"已授权":p.state==="unauthorized"?"待授权":"离线"}</option>`).join("");
      const selected=[previous,available[0]?.serial].find(v=>available.some(p=>p.serial===v));if(selected)$("phone-device").value=selected;
    }
    $("phone-bind").disabled=!available.length||installing;
  }catch(e){$("phone-status").textContent=e.message;}finally{phoneLoading=false;}
}
$("phone-refresh").addEventListener("click",()=>busy($("phone-refresh"),loadPhone));
$("phone-prepare").addEventListener("click",()=>busy($("phone-prepare"),async()=>{await api("/api/phone/prepare",{method:"POST",body:"{}"});await loadPhone();}));
$("phone-form").addEventListener("submit",async event=>{
  event.preventDefault();$("phone-bind").disabled=true;$("phone-feedback").textContent="正在接入手机……";
  try{await api("/api/phone/bind",{method:"POST",body:JSON.stringify({serial:$("phone-device").value})});$("phone-feedback").textContent="手机已接入。可以从一个简单操作开始。";await loadPhone();await loadRuntime();await loadStatus();}catch(e){$("phone-feedback").textContent=e.message;}finally{$("phone-bind").disabled=false;}
});
$("phone-resources").addEventListener("click",event=>{
  const button=event.target.closest("[data-phone-action]");if(!button)return;
  busy(button,async()=>{const action=button.dataset.phoneAction;await api(`/api/phone/${action}`,{method:"POST",body:JSON.stringify({resource_id:button.dataset.resourceId})});$("phone-feedback").textContent=action==="pause"?"已暂停这部手机的新操作；已经发出的动作可能仍需片刻返回。":"这部手机已恢复使用。";await loadPhone();});
});

// One physical character moves from the welcome scene to the conversation.
// Reparenting keeps the same decoded video and its current frame.
let companionMode="idle",presencePlayer=null;
const reduceMotion=matchMedia("(prefers-reduced-motion: reduce)");
function motionStopped(){return reduceMotion.matches;}
function updateCompanion(){
  const chatting=state.messages.length>0;
  const seat=chatting?$("companion-seat"):$("welcome");
  if($("presence").parentElement!==seat){
    if(chatting)seat.append($("presence"));else seat.prepend($("presence"));
  }
  $("companion-bar").hidden=!chatting;
  const turn=state.messages.find(m=>active.has(m.turn.status))?.turn;
  let mode="idle",line="我在，接着说。",detail="下一件事，我们一起往前推。";
  if(!state.connected){mode="offline";line="先把想法留在这里。";detail="连接恢复后，就能接着聊。";}
  else if(state.sending){mode="working";line="收到，正在送出。";detail="你的话会留在这段对话里。";}
  else if(turn){
    if(turn.status==="waiting_for_approval"){mode="handoff";line="这一步，等你决定。";detail="确认内容在上面的对话里。";}
    else if(["connection_lost","ambiguous"].includes(turn.status)){mode="handoff";line="连接中断，先核对一下。";detail="原消息还在，操作结果需要确认。";}
    else if(turn.status==="stopping"){mode="handoff";line="好，正在停下来。";detail="等已发出的操作返回。";}
    else{mode="working";line="我在处理这件事。";detail="有进展会放回对话里，随时可以叫停。";}
  }else if($("message-input").value.trim()){mode="listening";line="我在，慢慢说。";detail="写好了再发给我。";}
  const computer=state.computer;
  if(computer?.connector?.enrolled&&computer.control?.holder==="human"){
    mode="handoff";line="电脑交给你，我先等一等。";detail="接管期间，电脑读取和操作都已暂停。";
  }
  $("companion-line").textContent=line;$("companion-detail").textContent=detail;
  $("presence").dataset.mood=mode;$("companion-bar").dataset.mood=mode;
  $("companion-stop").hidden=!turn?.run_id||turn.status==="stopping";
  $("companion-stop").dataset.task=turn?.id||"";
  $("computer-takeover").hidden=!computer?.connector?.enrolled;
  $("computer-takeover").textContent=computer?.control?.holder==="human"?"交回 Wearing":"我来接管";
  companionMode=mode;
  presencePlayer?.setState(mode==="offline"?"idle":mode==="handoff"?"waiting":mode==="working"?(state.sending||turn?.status==="starting"?"working":"thinking"):mode);
  syncMotion();
}
function syncMotion(){presencePlayer?.sync();}
async function loadCharacter(){
  presencePlayer=new WearingPresence({stage:$("presence"),poster:$("character-poster"),
    videos:[$("character-video"),$("character-video-next")],preference:reduceMotion,
    onReduced:reduced=>{state.motionPaused=reduced;document.body.classList.toggle("motion-paused",reduced);}});
  try{presencePlayer.configure(await api("/assets/character.json"));}catch{/* The independent poster remains. */}
  updateCompanion();
}
$("character-stage").addEventListener("click",()=>{
  if(reduceMotion.matches){$("message-input").focus();return;}
  presencePlayer?.attention();
});
$("message-input").addEventListener("input",updateCompanion);
$("companion-stop").addEventListener("click",()=>busy($("companion-stop"),async()=>{await api(`/api/tasks/${$("companion-stop").dataset.task}/stop`,{method:"POST",body:"{}"});await loadConversation(true);}));
let computerLoading=false,lastComputerCheck=0;
async function loadComputer(force=false){
  if(state.identityId!=="daily"){state.computer=null;updateCompanion();return;}
  if(computerLoading)return;computerLoading=true;
  try{
    const r=await api(force?"/api/computer/refresh":"/api/computer",force?{method:"POST",body:"{}"}:{});
    state.computer=r;lastComputerCheck=Date.now();
    const c=r.connector,held=r.control?.holder==="human",installing=c.phase==="installing";
    const missing=[];
    if(r.accessibility!==true)missing.push("辅助功能");
    if(r.screen_recording!==true)missing.push("屏幕录制");
    const permissionText=r.can_grant?`还差系统授权：请为 CuaDriver 开启${missing.join("与")}。`:"电脑驱动还未就绪，请重新检测。";
    $("computer-permission-help").hidden=!r.can_grant||r.ready||!r.permission_app_path;
    $("computer-app-path").textContent=r.permission_app_path||"";
    let text=!r.installed?"准备连接器后，就能在这台电脑里帮你动手。":!r.ready?permissionText:!c.enrolled?"权限已就绪。接入后，可以在对话里交代电脑上的事情。":held?"你正在接管。Wearing 已暂停电脑读取和操作。":c.active?"这台电脑已连接，可以在对话里请 Wearing 操作。":"已接入，启动本地引擎后可以使用。";
    $("computer-status").textContent=c.error||r.error||(installing?"正在准备电脑连接器……":text);
    $("computer-prepare").hidden=!!r.installed;$("computer-prepare").disabled=installing;
    $("computer-permissions").hidden=!r.installed||r.ready||!r.can_grant;
    $("computer-bind").hidden=!r.ready||c.enrolled;
    $("computer-control").hidden=!c.enrolled;$("computer-control").textContent=held?"交回 Wearing":"我来接管";
    updateCompanion();
  }catch(e){$("computer-status").textContent=e.message;}finally{computerLoading=false;}
}
async function toggleComputer(){
  const action=state.computer?.control?.holder==="human"?"resume":"pause";
  const control=await api(`/api/computer/${action}`,{method:"POST",body:"{}"});
  if(state.computer)state.computer.control=control;
  updateCompanion();await loadComputer();
}
$("computer-refresh").addEventListener("click",()=>busy($("computer-refresh"),()=>loadComputer(true)));
$("computer-prepare").addEventListener("click",()=>busy($("computer-prepare"),async()=>{await api("/api/computer/prepare",{method:"POST",body:"{}"});await loadComputer(true);}));
$("computer-bind").addEventListener("click",()=>busy($("computer-bind"),async()=>{await api("/api/computer/bind",{method:"POST",body:"{}"});await loadComputer(true);await loadStatus();}));
$("computer-permissions").addEventListener("click",()=>busy($("computer-permissions"),async()=>{$("computer-feedback").textContent="请在 macOS 系统提示中完成授权，然后点重新检测。";await api("/api/computer/permissions",{method:"POST",body:"{}"});await loadComputer(true);}));
$("computer-control").addEventListener("click",()=>busy($("computer-control"),toggleComputer));
$("computer-takeover").addEventListener("click",()=>busy($("computer-takeover"),toggleComputer));
async function initialize(){try{const bootstrap=await api("/api/bootstrap");state.token=bootstrap.token;state.identities=bootstrap.identities;let remembered;try{remembered=sessionStorage.getItem("wearing-identity");}catch{}state.identityId=state.identities.some(i=>i.id===remembered)?remembered:bootstrap.default_identity_id;renderIdentityContext();$("open-identities").disabled=false;$("hermes-url").value=bootstrap.hermes_url;await loadStatus();await loadConversation();await loadCharacter();loadComputer();}catch{notice("本地服务暂时没有连接上。请确认 Wearing 正在运行，再刷新页面。",true);}}
setInterval(async()=>{if(document.hidden||state.polling||!state.token)return;state.polling=true;try{if(Date.now()-state.lastStatus>15000)await loadStatus();if($("settings-panel").open){await loadRuntime();if(Date.now()-lastPhoneCheck>10000)await loadPhone();}if(Date.now()-lastComputerCheck>15000)await loadComputer();await loadConversation();if($("keeps-panel").open&&$("goal-form").hidden){await loadGoals();if(selectedGoal)await loadGoal(selectedGoal.id,true);}}catch(error){if(error instanceof StaleIdentity)return;state.connected=false;updateCompanion();$("connection-label").textContent="连接中断";$("connection-dot").classList.remove("online");}finally{state.polling=false;}},3000);

const identityRegions={CN:"国内生活",international:"海外事务",custom:"按用途区分"};
function renderIdentityContext(){
  const current=state.identities.find(i=>i.id===state.identityId);if(!current)return;
  $("identity-name").textContent=current.name;$("open-identities").setAttribute("aria-label",`当前身份：${current.name}，切换身份`);
  $("identity-context").textContent=`${current.name} · ${current.description||identityRegions[current.region]}`;
  $("message-input").placeholder=`用「${current.name}」，想做些什么？`;
  document.title=`${current.name} · Wearing`;
}
function renderIdentityList(){
  $("identity-list").innerHTML=state.identities.map(i=>`<div class="identity-row ${i.id===state.identityId?"current":""}"><button class="identity-select" data-identity="${esc(i.id)}" aria-current="${i.id===state.identityId?"true":"false"}"><span class="identity-monogram" aria-hidden="true">${esc([...i.name][0])}</span><span class="identity-text"><strong>${esc(i.name)}${i.id===state.identityId?" · 当前":""}</strong><small>${esc(i.description||identityRegions[i.region])}</small></span></button><button class="identity-edit" data-edit-identity="${esc(i.id)}" aria-label="编辑${esc(i.name)}">编辑</button></div>`).join("");
}
async function loadIdentityDetail(){
  const d=await api("/api/identity");
  const row=(name,value)=>`<div class="identity-resource"><span>${name}</span><span>${esc(value)}</span></div>`;
  $("identity-detail-title").textContent=`${d.name}的随身配置`;
  $("identity-resources").innerHTML=row("对话与文件","独立保存")+row("电脑与手机",d.devices.map(x=>x.name).join("、")||"尚未分配")+row("电话与邮箱","待接入")+row("支付与收款","待接入")+row("模型服务","各身份共用 API 配置")+(d.id==="daily"?'<button class="identity-resource-link" id="identity-connections">管理这个身份的设备连接 →</button>':'<p class="field-help identity-pending">现在可以独立对话和整理文件。设备及其账号环境，将单独接入这个身份。</p>');
  $("identity-connections")?.addEventListener("click",()=>{closePanel("identity-panel");showSettings();});
}
async function showIdentities(){
  if(!$("identity-panel").open)openPanel("identity-panel");
  $("identity-feedback").textContent="";$("identity-form").hidden=true;$("identity-detail").hidden=false;
  try{state.identities=await api("/api/identities");renderIdentityList();renderIdentityContext();await loadIdentityDetail();}catch(e){if(!(e instanceof StaleIdentity))$("identity-feedback").textContent=e.message;}
}
async function switchIdentity(id){
  if(state.sending)return;
  if(!state.identities.some(i=>i.id===id))return;
  if(id===state.identityId){closePanel("identity-panel");return;}
  state.drafts[state.identityId]=$("message-input").value;
  state.identityId=id;state.identityEpoch++;state.messages=[];state.signature="";state.selectedKeep=null;state.computer=null;state.lastStatus=0;state.connected=false;
  memoryEntries=[];$("memory-section").open=false;$("memory-list").replaceChildren();$("memory-feedback").textContent="";
  state.goalFocus=null;state.goalSource=null;renderGoalContext();selectedGoal=null;goalsSignature="";$("goals-list").replaceChildren();$("goals-list").hidden=false;$("goal-detail").replaceChildren();$("goal-detail").hidden=true;$("goal-form").hidden=true;$("goal-feedback").textContent="";
  try{sessionStorage.setItem("wearing-identity",id);}catch{}
  $("message-input").value=state.drafts[id]||"";$("messages").replaceChildren();$("keep-detail").replaceChildren();$("keep-detail").hidden=true;$("keeps-list").replaceChildren();$("files-list").replaceChildren();$("conversation").hidden=true;$("welcome").hidden=false;$("newest-message").hidden=true;$("identity-running").hidden=true;
  document.querySelectorAll("dialog[open]").forEach(d=>d.close());notice("");renderIdentityContext();updateCompanion();
  $("connection-label").textContent="连接中……";$("connection-dot").classList.remove("online");
  try{await loadStatus();await loadConversation(true);await loadComputer();}catch(e){if(!(e instanceof StaleIdentity))notice(e.message,true);}
}
function editIdentity(id=null){
  state.editingIdentity=id;const current=state.identities.find(i=>i.id===id);
  $("identity-form").hidden=false;$("identity-detail").hidden=true;$("identity-feedback").textContent="";
  $("identity-form-title").textContent=id?"让这个身份更像你":"给这个身份起个名字";$("save-identity").textContent=id?"保存修改":"创建并切换";
  $("identity-edit-name").value=current?.name||"";$("identity-region").value=current?.region||"international";$("identity-description").value=current?.description||"";$("identity-edit-name").focus();
}
$("open-identities").addEventListener("click",showIdentities);
$("new-identity").addEventListener("click",()=>editIdentity());
$("cancel-identity").addEventListener("click",()=>{$("identity-form").hidden=true;$("identity-detail").hidden=false;});
$("identity-list").addEventListener("click",e=>{const edit=e.target.closest("[data-edit-identity]");if(edit){editIdentity(edit.dataset.editIdentity);return;}const button=e.target.closest("[data-identity]");if(button)switchIdentity(button.dataset.identity);});
$("identity-running").addEventListener("click",()=>switchIdentity($("identity-running").dataset.identity));
$("identity-form").addEventListener("submit",async event=>{
  event.preventDefault();const id=state.editingIdentity;$("save-identity").disabled=true;$("identity-feedback").textContent="正在保存……";
  try{
    const result=await api(id?`/api/identities/${id}`:"/api/identities",{method:id?"PATCH":"POST",body:JSON.stringify({name:$("identity-edit-name").value,description:$("identity-description").value,region:$("identity-region").value})});
    state.identities=await api("/api/identities");renderIdentityContext();renderIdentityList();$("identity-form").hidden=true;$("identity-detail").hidden=false;
    if(!id){await switchIdentity(result.id);notice(`「${result.name}」准备好了。从这里开始一段新的对话。`);}else{$("identity-feedback").textContent="已保存。";await loadIdentityDetail();}
  }catch(e){if(!(e instanceof StaleIdentity))$("identity-feedback").textContent=e.message;}finally{$("save-identity").disabled=false;}
});
const goalLabels={paused:"先记着",active:"正在推进",waiting:"等合适的时候",needs_user:"有件事需要你",needs_review:"等你核对结果",limited:"这几轮先到这里",completed:"已经做到了",cancelled:"已结束委托"};
let selectedGoal=null, goalsSignature="";
function renderGoalContext(){
  const goal=state.goalFocus;$("goal-compose-context").hidden=!goal;
  $("message-input").maxLength=goal?.mode==="note"?2000:12000;
  $("message-input").minLength=goal?.mode==="note"?3:1;
  if(!goal){$("message-input").placeholder=`用「${state.identities.find(i=>i.id===state.identityId)?.name||"日常"}」，想做些什么？`;return;}
  $("goal-compose-title").textContent=(goal.mode==="note"?"补充 · ":"聊聊 · ")+goal.objective;
  $("goal-compose-title").dataset.goal=goal.id;
  $("goal-compose-help").textContent=goal.mode==="note"?"发送后记为新的情况，让旧计划按你的补充调整。":"先一起讨论，原来的约定照常保留。";
  $("message-input").placeholder=goal.mode==="note"?"有什么新情况，直接跟我说。":"关于这件事，我们接着聊。";
}
$("clear-goal-context").addEventListener("click",()=>{state.goalFocus=null;renderGoalContext();$("message-input").focus();});
function showGoalForm(content="",source=null){
  state.goalSource=source;$("goal-form").reset();$("goal-form").hidden=false;$("goals-list").hidden=true;$("goal-detail").hidden=true;
  $("goal-feedback").textContent=source?"原话保留在对话里，可以把目标写得简短些。":"";
  $("goal-objective").value=content.slice(0,2000);$("goal-objective").focus();
}
async function loadGoals(){
  const goals=await api("/api/goals");
  const signature=JSON.stringify(goals);if(signature===goalsSignature)return;goalsSignature=signature;
  $("goals-list").innerHTML=goals.length?goals.map(g=>`<button class="keep-row goal-row" data-goal="${esc(g.id)}"><strong>${esc(g.objective)}</strong><small>${esc(goalLabels[g.status])} · 已安排 ${g.used_steps}/${g.max_steps} 轮</small></button>`).join(""):'<p class="empty-keeps">想做的事，不必一次想明白。交代一个目标，我们从值得验证的下一步开始。</p>';
}
async function loadGoal(id,refresh=false){
  const goal=await api("/api/goals/"+id);
  if(refresh&&(selectedGoal?.id!==id||$("goal-note")?.value.trim()||$("goal-detail").contains(document.activeElement)))return;
  if(refresh&&JSON.stringify(goal)===JSON.stringify(selectedGoal))return;
  selectedGoal=goal;
  const ended=["completed","cancelled"].includes(goal.status);
  const running=goal.steps.some(s=>active.has(s.task_status));
  const stepMarkup=s=>{
    const report=s.report;
    return `<li><p class="goal-step-status">${esc(labels[s.task_status]||s.task_status)}${s.verified_at?" · 你已核对":" · 尚未核验业务结果"}</p><p class="goal-prose">${esc(report?.summary||s.error||(s.task_status==="draft"?"这一步已安排，等待派发。":["starting","running","stopping"].includes(s.task_status)?"这一轮正在准备或执行。":s.output||(s.task_status==="stopped"?"这一轮已停止。":"等待原运行结果。")))}</p>${report?.evidence?.length?`<details class="setup-guide"><summary>这次依据了什么</summary>${report.evidence.map(e=>`<p>${esc(e.observation)}<br><span class="field-help">${esc(e.source)}</span></p>`).join("")}<p class="field-help">以上来源由模型报告；核对记录另行保存。</p></details>`:""}${report?.unknowns?.length?`<p class="field-help">仍未确定：${esc(report.unknowns.join("；"))}</p>`:""}<button class="text-button" data-goal-turn="${esc(s.task_id)}">到对话查看与核对</button></li>`;
  };
  $("goal-detail").hidden=false;$("goal-form").hidden=true;$("goals-list").hidden=false;
  $("goal-detail").innerHTML=`<h3>${esc(goal.objective)}</h3><p class="goal-status-line">${esc(goalLabels[goal.status])} · 已安排 ${goal.used_steps}/${goal.max_steps} 轮</p><p class="goal-prose">${esc(goal.reason||"这件事已记下，等你决定什么时候开始。")}</p>${goal.next_wake?`<p class="field-help">下次检查：${esc(new Date(goal.next_wake).toLocaleString("zh-CN"))}，本地服务需保持运行。</p>`:""}${goal.next_step?`<p class="goal-prose"><strong>下一步</strong><br>${esc(goal.next_step)}</p>`:""}<details class="setup-guide"><summary>我们的约定</summary><p class="goal-prose">${esc(goal.boundaries)}</p><p class="goal-prose">阶段结果：${esc(goal.success_criteria)}</p></details>
    ${!ended?`<div class="button-row goal-controls">${["active","waiting"].includes(goal.status)?'<button class="secondary" data-goal-action="pause">先停一下</button>':`<button class="primary" data-goal-action="resume" ${running?"disabled":""}>${goal.used_steps>=goal.max_steps?"再安排 1 轮":"继续推进"}</button>`}<button class="text-button" data-goal-action="cancel">结束委托</button><button class="text-button" data-goal-note-mode="complete" ${running?"disabled":""}>我已核对，目标达成</button></div><p class="field-help">暂停会阻止后续步骤，并请求停止当前运行；实际停止状态见下方。</p><form id="goal-note-form" class="note-form"><label for="goal-note">补充新的情况，或纠正之前的理解</label><textarea id="goal-note" required minlength="3" maxlength="2000" rows="2" placeholder="比如：先不考虑实体商品，沿数字服务方向继续。"></textarea><button class="secondary">记住这次补充</button></form><p id="goal-detail-feedback" class="inline-feedback" role="status"></p>`:""}
    ${goal.notes.length?`<details class="setup-guide"><summary>你补充过的情况</summary>${goal.notes.map(n=>`<p class="goal-prose">${esc(n.content)}<br><span class="field-help">${esc(date(n.created_at))} · ${n.kind==="verified_by_user"?"你的核对":"你的原话"}</span></p>`).join("")}</details>`:""}
    <div class="goal-chat-tools"><button class="text-button" data-goal-chat="discuss">一起聊聊</button>${!ended?'<button class="text-button" data-goal-chat="note">在对话里补充</button>':""}</div><h4>这件事的进展</h4>${goal.steps.length?`<ol class="goal-history">${goal.steps.map(stepMarkup).join("")}</ol>`:'<p class="field-help">还没有开始执行。启动后，每一轮的结果会回到对话里。</p>'}<button class="text-button" id="refresh-goal">更新进展</button>`;
  $("refresh-goal").addEventListener("click",()=>busy($("refresh-goal"),()=>loadGoal(id),$("goal-feedback")));
  $("goal-note-form")?.addEventListener("submit",async e=>{
    e.preventDefault();const form=e.currentTarget, action=form.dataset.mode||"note";
    await busy(form.querySelector("button"),async()=>{await api(`/api/goals/${id}/control`,{method:"POST",body:JSON.stringify({revision:selectedGoal.revision,action,note:$("goal-note").value})});await loadGoals();await loadGoal(id);($("goal-detail-feedback")||$("goal-feedback")).textContent=action==="complete"?"已保存你的核对结论。":"补充已保存，旧步骤不会继续沿用原来的方向。";},$("goal-detail-feedback"));
  });
}
$("new-goal").addEventListener("click",()=>{$("goal-form").hidden?showGoalForm($("message-input").value):$("goal-objective").focus();});
$("cancel-goal-form").addEventListener("click",()=>{$("goal-form").hidden=true;$("goals-list").hidden=false;});
$("goal-form").addEventListener("submit",async e=>{
  e.preventDefault();const start=e.submitter?.value==="start", buttons=[...$("goal-form").querySelectorAll("button")];buttons.forEach(b=>b.disabled=true);$("goal-feedback").textContent="正在记下……";
  try{const g=await api("/api/goals",{method:"POST",body:JSON.stringify({objective:$("goal-objective").value,boundaries:$("goal-boundaries").value,success_criteria:$("goal-criteria").value,max_steps:Number($("goal-rounds").value),source_task_id:state.goalSource})});
    await loadGoals();await loadGoal(g.id);
    if(start){try{await api(`/api/goals/${g.id}/control`,{method:"POST",body:JSON.stringify({revision:g.revision,action:"resume"})});}catch(error){if(error instanceof StaleIdentity)throw error;$("goal-feedback").textContent="目标已保存，启动尚未确认。更新进展后查看原状态："+error.message;return;}}
    await loadGoals();await loadGoal(g.id);$("goal-feedback").textContent=start?"记住了。服务会在有空时安排下一步，进展会回到对话里。":"先替你记着。想开始时，再交给我推进。";
  }catch(error){if(!(error instanceof StaleIdentity))$("goal-feedback").textContent=error.message;}finally{buttons.forEach(b=>b.disabled=false);}
});
$("goal-detail").addEventListener("click",async e=>{
  const chat=e.target.closest("[data-goal-chat]");if(chat&&selectedGoal){state.goalFocus={id:selectedGoal.id,objective:selectedGoal.objective,revision:selectedGoal.revision,mode:chat.dataset.goalChat};renderGoalContext();closePanel("keeps-panel");$("message-input").focus();return;}
  const mode=e.target.closest("[data-goal-note-mode]");if(mode){const form=$("goal-note-form");form.dataset.mode="complete";form.querySelector("label").textContent="你核对了什么，确认目标已经达成？";form.querySelector("button").textContent="保存核对并完成目标";$("goal-note").focus();return;}
  const button=e.target.closest("[data-goal-action]");if(!button||!selectedGoal)return;
  const g=selectedGoal, action=button.dataset.goalAction;
  await busy(button,async()=>{await api(`/api/goals/${g.id}/control`,{method:"POST",body:JSON.stringify({revision:g.revision,action,add_steps:action==="resume"&&g.used_steps>=g.max_steps?1:0})});$("goal-feedback").textContent="";await loadGoals();await loadGoal(g.id);await loadConversation(true);},$("goal-detail-feedback"));
});
initialize();
