"use strict";
const $ = id => document.getElementById(id);
const esc = text => String(text ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const state = {goalPolicy:{default_steps:100,max_steps:1000,extension_steps:100},deployment:"local",remoteDevices:[],identityId:"daily",identities:[],identityEpoch:0,editingIdentity:null,token:"",connected:false,messages:[],signature:"",polling:false,lastStatus:0,selectedKeep:null,keepSignature:"",sending:false,computer:null,goalFocus:null,lifeFocus:null,goalSource:null,motionPaused:matchMedia("(prefers-reduced-motion: reduce)").matches};
const labels = {draft:"留在这里",starting:"正在送出",running:"正在回应",waiting_for_approval:"有一步需要你",stopping:"正在停止",connection_lost:"连接中断",ambiguous:"等待核对",completed_unverified:"已有回应",verified:"已核对",stopped:"已停止",failed:"需要再看看",closed_by_user:"已处理"};
const active = new Set(["starting","running","waiting_for_approval","stopping","connection_lost","ambiguous"]);
const pendingDecisions=new Set();
class StaleIdentity extends Error {}
async function api(path,options={}) {
  const epoch=state.identityEpoch;
  const headers={"Content-Type":"application/json","X-Wearing-Identity":state.identityId,...options.headers};
  if(options.method && options.method!=="GET") headers["X-Wearing-Token"]=state.token;
  const response=await fetch(path,{...options,headers});
  let data;try{data=await response.json();}catch{throw new Error("服务暂时没有回应，输入仍在。请稍后重试。");}
  if(epoch!==state.identityEpoch)throw new StaleIdentity();
  if(!response.ok) {const error=new Error(typeof data.detail==="string"?data.detail:"内容没有送出，请检查后重试。");error.status=response.status;throw error;}
  return data;
}
function publishComposer(){document.dispatchEvent?.(new Event("wearing-composer-state"));}
function notice(text,error=false){$("notice").textContent=text;$("notice").className="notice"+(error?" error":"");$("notice").hidden=!text;publishComposer();}
async function busy(button,action,feedback=null){const old=[...button.childNodes];const controls=[...(button.closest(".decision-card")?.querySelectorAll("button")||[button])].map(b=>[b,b.disabled]);controls.forEach(([b])=>b.disabled=true);try{await action();}catch(error){if(error instanceof StaleIdentity)return;if(feedback){feedback.textContent=error.message||"连接中断，请稍后再试。";feedback.scrollIntoView({block:"nearest"});}else notice(error.message||"连接中断，请稍后再试。",true);}finally{controls.forEach(([b,wasDisabled])=>{if(b.isConnected)b.disabled=wasDisabled;});if(button.isConnected)button.replaceChildren(...old);}}
function nearBottom(){return window.innerHeight+window.scrollY>=document.documentElement.scrollHeight-160;}
function scrollToLatest(){if(document.body.classList.contains("life-mode"))return;window.scrollTo({top:document.documentElement.scrollHeight,behavior:state.motionPaused?"instant":"smooth"});$("newest-message").hidden=true;}
function date(value){return new Intl.DateTimeFormat("zh-CN",{month:"numeric",day:"numeric"}).format(new Date(value));}
function openPanel(id){if(window.WearingMotion)window.WearingMotion.open($(id));else $(id).showModal();}
function closePanel(id){if(window.WearingMotion)window.WearingMotion.close($(id));else $(id).close();}
let composerReady=false, composerTimer=null, draftStorageWarning=false;
// 个人持久存储在 bootstrap 完成（storage_scope 就绪）后才创建；此前仅内存占位。
const pendingDrafts=window.WearingDrafts.create(()=>window.WearingStore);
const pendingSubmissions=window.WearingSubmissions.create(()=>window.WearingStore);
let composerDrafts=pendingDrafts, conversationSubmissions=pendingSubmissions;
function bindScopedStorage(bootstrap){
  // Pass the raw value: a missing/unknown deployment is decided by the store as memory-only (fail-closed), never defaulted to local here.
  const change=window.WearingStoreBind(bootstrap.deployment,bootstrap.storage_scope);
  // 账号/租户变化：丢弃旧内存态并作废在途请求（身份纪元一并推进）。
  if(change.mode==="cloud-memory"||change.previous!==null&&change.previous!==change.current)state.identityEpoch++;
  composerDrafts=window.WearingDrafts.create(()=>window.WearingStore,()=>{
    if(!draftStorageWarning){draftStorageWarning=true;notice("草稿暂时只能留在当前页面，请先保留输入，再关闭或重新载入。",true);}
  });
  conversationSubmissions=window.WearingSubmissions.create(()=>window.WearingStore,()=>{
    if(!draftStorageWarning){draftStorageWarning=true;notice("本机暂时无法保存提交记录，请保持此页打开，核对消息状态后再重试。",true);}
  });
}
function composerContext(){return {identity:state.identityId,goal:state.goalFocus,life:state.goalFocus?null:state.lifeFocus};}
function rememberComposer(){
  clearTimeout(composerTimer);
  if(window.WearingDeletion?.workAllowed?.() === false) return false; // 注销受理后旧异步草稿不写回
  return composerReady?composerDrafts.save(composerContext(),$("message-input").value):false;
}
function activateComposer(context,seed=""){
  rememberComposer();
  const saved=composerDrafts.read(context),next=saved?.context||context;
  state.goalFocus=next.goal||null;state.lifeFocus=next.life||null;
  composerReady=true;$("message-input").value=saved?.text??seed;
  document.querySelector(".composer-dock").classList.toggle("native-text-open",Boolean($("message-input").value));
  renderGoalContext();window.WearingLife?.renderContext();
  $("message-input").dispatchEvent(new Event("input"));
  document.dispatchEvent(new Event("wearing-composer-ready"));
}
$("message-input").addEventListener("input",()=>{clearTimeout(composerTimer);composerTimer=setTimeout(rememberComposer,180);});
window.addEventListener("pagehide",rememberComposer);
window.addEventListener("beforeunload",rememberComposer);
document.addEventListener("visibilitychange",()=>{if(document.hidden)rememberComposer();});
document.addEventListener("wearing-host-visibility",()=>{if(window.WearingHost?.hidden)rememberComposer();});
function turnActions(turn,verify=false){
  let html="";
  if(active.has(turn.status)){
    if(turn.run_id&&turn.status!=="stopping")html+=`<button data-action="stop" data-task="${esc(turn.id)}">先停一下</button>`;
    html+=`<button data-action="refresh" data-task="${esc(turn.id)}">重新查看</button>`;
  }
  // 聊天回复不再逐条挂「核对结果/记成目标」；真实核对入口保留在旧任务详情里。
  if(verify&&turn.status==="completed_unverified")html+=`<button data-verify="${esc(turn.id)}"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m5 12 4 4L19 6"/></svg>核对结果</button>`;
  return html?`<div class="turn-tools">${html}</div>`:"";
}
// 公开任务不再透传 error：已知执行上限映射固定说明，未知类型用通用失败说明（recovery-presentation 合同）。
const failureText=turn=>turn.failure_code==="execution_limit"?"已达到本轮执行上限，现有结果和查看记录已保留；这件事尚未完成。":turn.status==="failed"?"这次没有完成；已返回的结果仍然保留，可以稍后重新查看。":"这次连接没有完成，原消息仍然保留。";
function turnMarkup(message){
  const turn=message.turn,id=turn.id,isGoal=message.kind==="goal_step",isSchedule=message.kind==="schedule_run";
  // 恢复请求按 kind/message_kind 识别（真实账本投影，不用提示词猜测）；
  // 能力开关只信任务回执 can_retry/can_cancel，旧服务缺字段沿用旧语义（继续这句话/排队撤回）。
  const isRecovery=message.kind==="confirmation_recovery"||turn.message_kind==="confirmation_recovery";
  const goalContext=message.goal_id&&!isGoal?`<div class="goal-conversation-label"><button class="text-button" data-goal="${esc(message.goal_id)}">${message.goal_mode==="note"?"补充新情况":"聊聊这件事"} · ${esc(message.goal_title)}</button></div>`:"";
  const user=isSchedule?`<div class="goal-conversation-label"><button class="text-button" data-open-schedule="${esc(message.schedule_id)}">${message.trigger==="life_change"?"有变化，我来看看":"到时我来"}：${esc(message.content)}</button></div>`:message.kind==="goal_step"?`<div class="goal-conversation-label"><button class="text-button" data-goal="${esc(message.goal_id)}">一起记着：${esc(message.content)}</button></div>`:goalContext+`<div class="message message-user"><div class="user-bubble">${esc(message.content)}</div></div>`;
  let response="";
  if(turn.output){response=`<div class="message message-assistant">${wearingFaceMarkup()}<div class="assistant-content"><div class="assistant-copy">${esc(turn.output)}</div>${artifactMarkup(turn.artifacts)}${researchMarkup(turn.research,turn.id)}${turnActions(turn)}${turn.verification_note?`<p class="note-saved">核对记录：${esc(turn.verification_note)}</p>`:""}<div id="verify-${esc(id)}"></div></div></div>`;}
  if(!turn.output&&turn.artifacts?.length)response+=`<div class="message message-assistant artifact-message"><div class="artifact-avatar-space" aria-hidden="true"></div><div class="assistant-content">${artifactMarkup(turn.artifacts)}</div></div>`;
  if(turn.status==="draft"&&isSchedule)response+='<div class="delivery-note"><p>这次安排正在等候执行；超过有效时间会跳过。</p></div>';
  if(turn.status==="draft"&&isGoal)response+=`<div class="delivery-note"><p>${state.connected?"这一步已安排，轮到时会自动推进。":"这一步等待连接恢复。目标与约定仍然保留。"}</p><button class="text-button" data-goal="${esc(message.goal_id)}">查看目标与进展</button></div>`;
  if(turn.status==="draft"&&message.queued)response+=`<div class="delivery-note"><p>${message.queue_state==="blocked"?"已排队，暂时还不能开始。":"已排队，轮到这条时会自动处理。"}</p>${message.queue_state==="blocked"&&message.blocked_reason?`<p class="muted">${esc(message.blocked_reason)}</p>`:""}${turn.can_cancel===false?"":`<button class="text-button" data-action="cancel-message" data-task="${esc(id)}">撤回这条</button>`}</div>`;
  if(turn.status==="draft"&&!isGoal&&!isSchedule&&!message.queued){
    const startLabel=!state.connected?"连接 Pajio":isRecovery?"重新核对":"继续这句话";
    const note=isRecovery?(state.connected?"这次重新核对还没有开始；点按钮并再确认一次后才会送出，不会直接执行原提案。":"这次重新核对已经保留。连接 Pajio 后，才能继续。"):state.connected?"这条还没有送出。你可以从这里继续。":"这句话已经保留。连接 Pajio 后，才能获得真实回应。";
    response+=`<div class="delivery-note"><p>${note}</p>${turn.blocked_reason?`<p class="muted">${esc(turn.blocked_reason)}</p>`:""}${turn.can_retry===false?"":`<button class="text-button" ${state.connected?`data-action="start" data-task="${esc(id)}"`:'data-open-settings'}>${startLabel}</button>`}${turn.can_cancel===true?`<button class="text-button" data-action="cancel-message" data-task="${esc(id)}">撤回这条</button>`:""}</div>`;
  }
  if(["starting","running","stopping"].includes(turn.status)&&!turn.output)response+=`<div class="message response-wait">${wearingFaceMarkup()}<span>${turn.status==="stopping"?"正在等待本轮停止……":"Pajio 正在回应……"}</span></div>`;
  if(["connection_lost","ambiguous","failed"].includes(turn.status))response+=`<div class="delivery-note error"><p>${esc(failureText(turn))}</p>${turnActions(turn)}${["connection_lost","ambiguous"].includes(turn.status)?`<details class="setup-guide"><summary>已在执行电脑上处理完毕</summary><p>确认原运行和设备操作已经结束后，记录处理结果。这不会替你终止远端进程。</p><form class="note-form decision-card" data-resolve="${esc(id)}"><label for="resolve-${esc(id)}">处理记录</label><textarea id="resolve-${esc(id)}" name="note" required minlength="5" maxlength="2000"></textarea><button class="secondary">记录并结束</button></form></details>`:""}</div>`;
  if(turn.status==="waiting_for_approval"){
    const a=turn.approval;
    response+=a?.kind==="desktop_input"?`<div class="delivery-note">${a.desktop_unavailable?"这一步的界面或运行已经变化，等待执行端结束确认。":"任务交托在下方，交给我后会接着处理。"}</div>`:a?.request_id?`<div class="message message-assistant">${wearingFaceMarkup()}<div class="assistant-content">${WearingConfirmations.pending(id,a,pendingDecisions.has(id+":"+a.request_id))}</div></div>`:`<div class="delivery-note">执行端有一步等待确认，但还没有返回完整内容。${turnActions(turn)}</div>`;
  }
  const decisionHistory=WearingConfirmations.history(turn.confirmations,turn.status==="waiting_for_approval"?turn.approval?.request_id:null);
  if(decisionHistory)response+=`<div class="message message-assistant"><div class="artifact-avatar-space" aria-hidden="true"></div><div class="assistant-content">${decisionHistory}</div></div>`;
  if(turn.status==="stopped"&&!turn.output)response+=`<div class="delivery-note">${message.queue_state==="cancelled"?"这条已撤回，没有开始执行。":"本轮已停止，前面的对话仍然保留。"}</div>`;
  if(!turn.output&&["failed","stopped"].includes(turn.status))response+=researchMarkup(turn.research,turn.id);
  return `<section class="conversation-turn" id="${message.kind==="goal_step"?"goal-turn":"task-turn"}-${esc(id)}" tabindex="-1">${user+response}</section>`;
}
async function loadConversation(force=false,isCurrent=()=>true){
  const messages=await api("/api/conversation");if(!isCurrent())return;state.messages=messages;
  const signature=JSON.stringify([state.connected,messages]);
  if(signature===state.signature&&!force)return;
  if(!force&&$("messages").contains(document.activeElement))return;
  const stick=nearBottom();state.signature=signature;
  $("welcome").hidden=messages.length>0;$("conversation").hidden=!messages.length;
  const opened=new Set([...$("messages").querySelectorAll("details[data-research-key][open]")].map(el=>el.dataset.researchKey));
  $("messages").innerHTML=messages.map(turnMarkup).join("");
  $("messages").querySelectorAll("details[data-research-key]").forEach(el=>{el.open=opened.has(el.dataset.researchKey);});
  const focused=messages.find(m=>active.has(m.turn.status));
  $("composer-footnote").firstChild.textContent=focused?"继续说也可以，新消息会排队，开始前可以撤回。":"说一声，我来做。";
  updateCompanion();
  syncMotion();
  // Measure the final dock height, including its companion, before scrolling.
  if(stick&&messages.length)scrollToLatest();else if(messages.length)$("newest-message").hidden=false;
}
async function loadStatus(){
  const result=await api("/api/status");state.lastStatus=Date.now();state.connected=["reachable","ready"].includes(result.hermes.state);
  const other=result.other_active?.[0];$("identity-running").hidden=!other;$("identity-running").textContent=other?`${other.name}里还有一件事${["connection_lost","ambiguous"].includes(other.status)?"等待核对":"正在处理"} · 点此查看`:"";$("identity-running").dataset.identity=other?.identity_id||"";
  $("connection-label").textContent=result.hermes.state==="ready"?"身份已就绪":state.connected?(state.deployment==="cloud"?"云端已连接":"已连接"):"连接 Pajio";
  $("connection-dot").classList.toggle("online",state.connected);
  updateCompanion();
  const webTools=result.hermes.wearing?.web_tools||[];
  $("web-capability").textContent=webTools.includes("web_search")&&webTools.includes("web_extract")?"公开搜索与网页读取已启用。实际可读性会在使用时检查。":result.hermes.state==="reachable"?"当前引擎尚未启用公开检索，升级后重新连接即可检查。":"连接后检查检索能力；已保存的来源仍可查看。";
  renderReport($("device-report"),result.device_report,"你的设备报告");
}
async function loadRuntime(){
  const r=await api("/api/runtime");
  const pending=["downloading","installing","starting"].includes(r.phase);
  const copy={downloading:"正在准备 Pajio 的执行引擎……",installing:"正在准备运行环境，首次安装需要几分钟。",starting:"正在启动本地引擎……",running:"Pajio 已在这台电脑运行。"};
  $("runtime-status").textContent=r.error||copy[r.phase]||(r.installed?(r.model?.state==="configured"?"模型已配置，可以启动。首次回应后再验证实际可用性。":"引擎已安装。请先展开模型设置，选择服务并登录。"):"准备 Pajio，再连接你使用的模型。原对话会一直保留。");
  $("runtime-status").className="inline-feedback"+(r.error?" error":"");
  $("runtime-install").hidden=r.installed||r.running;
  $("runtime-install").disabled=pending;
  $("runtime-start").hidden=!r.installed||r.running;
  $("runtime-start").disabled=pending;
  $("runtime-stop").hidden=!r.running;
  $("model-command").textContent=r.model_setup_command;
  const files=r.files||{};
  $("files-status").textContent=files.error||(files.phase==="installing"?"正在准备文件能力，首次安装需要几分钟……":files.active?"已接通，可以让 Pajio 帮你写文件。":files.installed?"文件能力已准备，启动本地引擎后可用。":"启用后，可以让 Pajio 把内容整理成文件。");
  $("files-enable").hidden=files.installed&&files.phase!=="failed";
  $("files-enable").disabled=!r.installed||files.phase==="installing"||pending;
  $("engine-profile").textContent=r.product?.applied?`Pajio 个人模式 · 配置 v${r.product.profile_version} · 引擎 ${r.revision}。Hermes 原生调度和消息平台未启用；目标跟进由 Pajio 本地服务负责。`:"Pajio 个人模式会在下次启动引擎时应用。";
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
  await loadGoalUpdates();
  await loadGoals();
  await window.WearingSchedules?.load();
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
  activateComposer({identity:state.identityId});closePanel("keeps-panel");input.value=text;input.dispatchEvent(new Event("input"));input.focus();
}
$("memory-section").addEventListener("toggle",()=>{if($("memory-section").open)loadMemory();});
$("refresh-memory").addEventListener("click",()=>busy($("refresh-memory"),loadMemory,$("memory-feedback")));
$("remember-something").addEventListener("click",()=>composeMemory("帮我记住："));
$("memory-list").addEventListener("click",event=>{const button=event.target.closest("[data-correct-memory]");if(button){const entry=memoryEntries[Number(button.dataset.correctMemory)];if(entry!==undefined)composeMemory(`这条记忆需要纠正：${entry}\n正确的是：`);}});
async function loadKeep(id,isCurrent=()=>true){
  const t=await api("/api/tasks/"+id);if(!isCurrent())return;state.selectedKeep=id;
  $("keep-detail").hidden=false;
  $("keep-detail").innerHTML=`<h3>${esc(t.title)}</h3><p class="prompt">${esc(t.prompt)}</p><button class="primary" id="bring-to-conversation">带回对话</button>${t.output?`<div class="assistant-copy">${esc(t.output)}</div>${researchMarkup(t.research,t.id)}`:""}${turnActions(t,true)}<div id="verify-${esc(t.id)}"></div><ol class="keep-timeline">${t.events.map(e=>`<li>${esc(e.message)}</li>`).join("")}</ol>`;
  $("bring-to-conversation").addEventListener("click",()=>{closePanel("keeps-panel");activateComposer({identity:state.identityId});$("message-input").value="我们接着聊这件事："+t.prompt;$("message-input").dispatchEvent(new Event("input"));$("message-input").focus();});
}
$("conversation-form").addEventListener("submit",async event=>{
  event.preventDefault();if(state.sending)return;
  if(window.WearingDeletion?.workAllowed?.() === false){notice("这个账户的注销申请已受理，业务操作已停止。",true);return;}
  const raw=$("message-input").value,content=raw.trim();if(!content)return;
  rememberComposer();const submitted=composerContext();
  const body={content,...(submitted.life?{life_record_id:submitted.life.id,life_revision:submitted.life.revision}:{}),...(submitted.goal?{goal_id:submitted.goal.id,goal_mode:submitted.goal.mode,...(submitted.goal.mode==="note"?{goal_revision:submitted.goal.revision}:{})}:{})};
  state.sending=true;$("open-identities").disabled=true;updateCompanion();publishComposer();
  try{await busy($("send-message"),async()=>{
    if(!submitted.life&&!submitted.goal)body.request_id=conversationSubmissions.prepare(submitted.identity,content);
    const result=await api("/api/conversation",{method:"POST",body:JSON.stringify(body)});
    if(!result||typeof result.task?.id!=="string"||!result.task.id||!["submitted","queued","saved"].includes(result.delivery))throw new Error("还没有收到消息保存回执，原话已保留，请核对后重试。");
    if(body.request_id)conversationSubmissions.acknowledge(submitted.identity,body.request_id);
    rememberComposer();composerDrafts.acknowledge(submitted,raw);
    const unchanged=composerDrafts.key(submitted)===composerDrafts.key(composerContext())&&$("message-input").value===raw;
    if(unchanged){
      $("message-input").value="";document.querySelector(".composer-dock").classList.remove("native-text-open");rememberComposer();
      if(result.goal&&state.goalFocus?.id===result.goal.id)activateComposer({identity:state.identityId,goal:{...state.goalFocus,revision:result.goal.revision,mode:"discuss"}});
    }
    if(!draftStorageWarning)notice(result.queue_state==="cancelled"?"这条此前已撤回，没有开始执行。":result.delivery==="saved"?(result.reason||"消息已保存，尚未开始执行。") : "");
    await loadConversation(true);window.WearingActivity?.load(true);scrollToLatest();
  });}finally{state.sending=false;$("open-identities").disabled=false;updateCompanion();publishComposer();}
});
$("message-input").addEventListener("keydown",event=>{if(event.key==="Enter"&&!event.shiftKey&&!event.isComposing){event.preventDefault();if(!$("send-message").disabled)$("conversation-form").requestSubmit();}});
async function loadUsage(){
  const host=$("usage-body");
  try{
    const data=await api("/api/usage");
    const rows=Object.entries(data.resources||{}).map(([kind,r])=>`<div class="me-row me-row-static"><div><strong>${kind==="model"?"模型调用":kind==="speech"?"语音识别":esc(kind)}</strong><small>${r.calls??0} 次 · 剩余 ${r.remaining??0}${r.limit?`/${r.limit}`:""}${r.concurrency?` · 并发 ${r.concurrency}`:""}${r.ms_remaining!==undefined?` · 音频剩余 ${Math.round((r.ms_remaining||0)/1000)}s`:""}</small></div></div>`).join("");
    const own=data.identity_usage||{};
    host.innerHTML=`<p class="field-help">${data.mode==="trial"?"试用模式 · 按次限制，未启用计费":"用量统计未启用"}${data.cost_status==="unavailable"?" · 金额未知（未接入计费，不显示为 0 元）":""} · 读取于 ${new Date((data.observed_at||0)*1000).toLocaleTimeString("zh-CN",{hour:"2-digit",minute:"2-digit"})}</p>
      <div class="me-group">${rows}</div>
      <p class="field-help">本身份累计：${own.calls??0} 次调用${own.input_tokens!=null?` · ${own.input_tokens} 输入 / ${own.output_tokens??0} 输出 tokens`:""}${own.unreported_model_calls?` · ${own.unreported_model_calls} 次未上报 token 数`:""}</p>`;
  }catch(error){host.innerHTML=`<p class="field-help">${esc(error.message||"用量暂不可用。")}</p>`;}
}
$("open-settings").addEventListener("click",showSettings);
$("open-keeps").addEventListener("click",async()=>{openPanel("keeps-panel");await loadKeeps().catch(e=>notice(e.message,true));});
$("newest-message").addEventListener("click",scrollToLatest);
window.addEventListener("scroll",()=>{if(nearBottom())$("newest-message").hidden=true;},{passive:true});
document.addEventListener("click",async event=>{
  const close=event.target.closest("[data-close]");if(close){closePanel(close.dataset.close);return;}
  if(event.target.closest("[data-open-settings]")){showSettings();return;}
  const suggestion=event.target.closest("[data-suggestion]");if(suggestion){$("message-input").value=suggestion.dataset.suggestion;$("message-input").dispatchEvent(new Event("input"));$("message-input").focus();return;}
  const keep=event.target.closest("[data-keep]");if(keep){await loadKeep(keep.dataset.keep).catch(e=>notice(e.message,true));return;}
  const goal=event.target.closest("[data-goal]");if(goal){if(!$("keeps-panel").open)openPanel("keeps-panel");await loadGoals();await loadGoal(goal.dataset.goal).catch(e=>{$("goal-feedback").textContent=e.message;});return;}
  const goalTurn=event.target.closest("[data-goal-turn]");if(goalTurn){closePanel("keeps-panel");await loadConversation(true);$("goal-turn-"+goalTurn.dataset.goalTurn)?.scrollIntoView({block:"center",behavior:state.motionPaused?"instant":"smooth"});return;}
  const action=event.target.closest("[data-action]");
  if(action){
    const name=action.dataset.action;
    // 开始与撤回都需明确确认（recovery-presentation 合同）：两击确认，4 秒未复点自动还原。
    if((name==="start"||name==="cancel-message")&&action.dataset.confirm!=="1"){action.dataset.confirm="1";const label=action.textContent;action.textContent=name==="start"?"再点一次确认开始":"再点一次确认撤回";setTimeout(()=>{if(action.dataset.confirm==="1"){action.dataset.confirm="";action.textContent=label;}},4000);return;}
    await busy(action,async()=>{
      if(name==="start"){
        // 显式重试用原任务：提交前重读回执 can_retry；读不到或不可开始就不提交，只提示重读，不自动重试。
        let task=null;
        try{task=await api("/api/tasks/"+action.dataset.task);}
        catch(error){if(error instanceof StaleIdentity)throw error;throw new Error("暂时读不到这条的最新状态，请稍后重新查看。");}
        if(task&&task.can_retry===false)throw new Error(task.blocked_reason||"这条现在不能开始；请先处理提示的原因。");
        try{await api(`/api/tasks/${action.dataset.task}/start`,{method:"POST",body:"{}"});}
        catch(error){if(!(error instanceof StaleIdentity)&&!error.status)throw new Error("开始请求的结果未知；请重新查看这条，不要重复点击。");throw error;}
      }else{
        await api(`/api/tasks/${action.dataset.task}/${name}`,{method:"POST",body:"{}"});
      }
      await loadConversation(true);await window.WearingActivity?.load(true);if(state.selectedKeep===action.dataset.task)await loadKeep(state.selectedKeep);
    });
    return;
  }
  const choice=event.target.closest("[data-choice]");if(choice){
    const key=choice.dataset.task+":"+choice.dataset.request;if(pendingDecisions.has(key))return;
    const card=choice.closest("[data-decision-card]"),epoch=state.identityEpoch;pendingDecisions.add(key);
    if(card){card.setAttribute("aria-busy","true");card.querySelectorAll("button").forEach(b=>b.disabled=true);card.querySelector(".decision-hint").hidden=false;card.querySelector(".decision-hint").textContent="正在送出…";}
    let failure=null;
    try{await api(`/api/tasks/${choice.dataset.task}/approval`,{method:"POST",body:JSON.stringify({request_id:choice.dataset.request,choice:choice.dataset.choice})});}
    catch(error){if(!(error instanceof StaleIdentity))failure=error;}
    finally{pendingDecisions.delete(key);}
    if(epoch!==state.identityEpoch)return;
    try{await loadConversation(true);}catch(error){failure=failure||error;}
    if(failure)notice(failure.message||"连接中断，请查看原运行状态。",true);
    return;
  }
  const verify=event.target.closest("[data-verify]");if(verify){const id=verify.dataset.verify;$("verify-"+id).innerHTML=`<form class="note-form decision-card" data-verify-form="${esc(id)}"><label for="note-${esc(id)}">你核对了什么？</label><textarea id="note-${esc(id)}" name="note" required minlength="3" maxlength="2000" placeholder="留下实际核对的结果。"></textarea><button class="secondary">保存记录</button></form>`;$("note-"+id).focus();}
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
function showSettings(){
  // 设置对所有身份开放：身份管理走独立入口（身份胶囊），不再把设置重定向成身份面板。
  openPanel("settings-panel");
  if(state.deployment==="cloud"){loadDevices().catch(e=>{$("cloud-devices-feedback").textContent=e.message;});}
  else{loadPhone();loadComputer();loadRuntime().catch(e=>{$("runtime-status").textContent=e.message;});loadModel();}
  window.WearingViews?.renderMessaging?.($("messaging-body"));window.WearingCloudApps?.refresh();window.WearingDecisions?.load();loadUsage();window.WearingDataExports?.load();window.WearingDiagnostics?.generate();window.WearingQuietHours?.load();window.WearingDeletion?.start();
}
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
let filesQuery="", filesCursor=null, filesScan=null, filesPhase="", filesBusy=false, filesDone=false, filesDebounce=0;
function renderFileRows(files){
  const fileUrl=path=>`/api/workspace/file?identity=${encodeURIComponent(state.identityId)}&path=${encodeURIComponent(path)}`;
  $("files-list").insertAdjacentHTML("beforeend", files.map(file=>`<div class="file-row" data-file-path="${esc(file.path)}"><a href="${fileUrl(file.path)}" target="_blank" rel="noreferrer">打开</a><a download href="${fileUrl(file.path)}"><span>${esc(file.path)}</span><small>${file.size<1024?file.size+" B":(file.size/1024).toFixed(1)+" KB"} · 下载</small></a><button class="text-button" data-files-chat="${esc(file.path)}" type="button">交给 Pajio</button><button class="text-button" data-text-edit="${esc(file.path)}" type="button">编辑</button></div>`).join(""));
}
async function loadFiles(){
  await window.WearingArtifacts.library();
  $("files-path").textContent="（按目录与搜索读取，路径见详情）";
  filesCursor=null;filesScan=null;filesPhase="";filesDone=false;
  $("files-list").innerHTML="";
  await filesLoadMore(true);
}
async function filesLoadMore(first=false){
  if(filesBusy)return;
  filesBusy=true;
  try{
    const query=new URLSearchParams({limit:"200"});
    if(filesQuery)query.set("query",filesQuery);
    if(filesCursor)query.set("cursor",filesCursor);
    const result=await api("/api/workspace/page?"+query);
    // 目录变化或游标过期：清列表重读（服务端 409 → error 路径同此处理）。
    if(filesScan&&result.scan_id&&result.scan_id!==filesScan){filesCursor=null;filesScan=null;return filesLoadMore(true);}
    filesScan=result.scan_id;filesCursor=result.next_cursor;
    filesPhase=result.phase||"";
    filesDone=result.complete===true;
    if(first)$("files-list").innerHTML="";
    renderFileRows(result.files||[]);
    const rows=$("files-list").querySelectorAll(".file-row").length;
    $("files-list-status").textContent=(filesQuery?`「${filesQuery}」`:"")+(filesDone?"已完整读取 "+rows+" 个文件":`已读取 ${rows} 个${filesPhase==="checking"?" · 正在核对目录":" · 正在扫描"}${result.scanned!==undefined?" · 已扫描 "+result.scanned+" 项":""}`);
    $("files-more").hidden=!filesCursor;
  }catch(error){
    if(error instanceof StaleIdentity)return;
    $("files-list-status").textContent=error.message||"文件列表暂时读不到。";
    $("files-more").hidden=false;
    $("files-more").textContent="重新读取";
  }finally{filesBusy=false;}
}
// 导入：raw bytes + 幂等 request_key，失败重试沿用同一编号核对同一份文件（对齐 workspace_upload 合同）。
let importAttempt=null;
async function importWorkspaceFile(file){
  if(!file.size||file.size>20*1024*1024)throw new Error("请选择非空且不超过 20 MB 的文件。");
  const normalized=file.name.normalize("NFC").trim();
  if(!importAttempt||importAttempt.name!==normalized)importAttempt={name:normalized,key:window.WearingIds.uuid().replaceAll("-","")};
  const epoch=state.identityEpoch;
  const body=await file.arrayBuffer();
  const response=await fetch(`/api/workspace/import?${new URLSearchParams({name:normalized,request_key:importAttempt.key})}`,{method:"POST",body,headers:{"Content-Type":"application/octet-stream","X-Wearing-Identity":state.identityId,"X-Wearing-Token":state.token}});
  let data;try{data=await response.json();}catch{data=null;}
  if(!response.ok)throw new Error(data?.detail||"文件暂时没有导入成功，请重试。");
  const receipt=data?.file;
  if(data?.request_key!==importAttempt.key||!/^[a-f0-9]{64}$/.test(data?.sha256||"")||!receipt||receipt.path!==`imports/${importAttempt.key}/${normalized}`||receipt.size!==file.size)throw new Error("尚未取得完整导入回执，请重试核对。");
  importAttempt=null;
  if(epoch!==state.identityEpoch)return;
  $("files-feedback").textContent=`已导入 ${normalized}，可在列表中打开或交给 Pajio。`;
  await loadFiles();
}
$("open-files").addEventListener("click",()=>{openPanel("files-panel");loadFiles().catch(e=>{$("files-list-status").textContent=e.message;});});
$("refresh-files").addEventListener("click",()=>busy($("refresh-files"),loadFiles));
$("files-more").addEventListener("click",()=>{$("files-more").textContent="继续查找";filesLoadMore().catch(()=>{});});
$("files-import").addEventListener("click",()=>$("files-import-input").click());
$("files-import-input").addEventListener("change",event=>{const file=event.target.files[0];event.target.value="";if(file)busy($("files-import"),()=>importWorkspaceFile(file),$("files-feedback"));});
$("files-search").addEventListener("input",event=>{clearTimeout(filesDebounce);filesDebounce=setTimeout(()=>{filesQuery=event.target.value.trim();if($("files-panel").open)loadFiles().catch(()=>{});},350);});
// 交给 Pajio：带着真实文件路径回聊天准备草稿（不自动发送）。
$("files-list").addEventListener("click",event=>{
  const chat=event.target.closest("[data-files-chat]");if(!chat)return;
  closePanel("files-panel");activateComposer({identity:state.identityId});
  $("message-input").value=`请读这份文件，按内容协助我：${chat.dataset.filesChat}`;
  $("message-input").dispatchEvent(new Event("input"));
  $("message-input").focus();
});


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
    if(r.state==="adb_missing")copy="先准备手机连接器，Pajio 会安装官方 Android 连接工具。";
    else if(r.state==="adb_failed")copy="暂时无法读取手机连接状态，请重新检测。";
    else if(resources.length)copy=`已接入 ${resources.length} 部手机，${resources.filter(p=>p.online).length} 部在线。${!resources.some(p=>p.enabled)?"手机操作已全部暂停。":!resources.some(p=>p.online&&p.enabled)?"等待已启用的手机连接。":connector.active?"可以直接在对话里请 Pajio 操作。":"启动本地引擎后即可使用。"}`;
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
  let mode="idle",line="说一声，我来做。",detail="交代要做的事，有进展会回到这里。";
  if(!state.connected){mode="offline";line="先把想法留在这里。";detail="连接恢复后，就能接着聊。";}
  else if(state.sending){mode="working";line="收到，正在送出。";detail="你的话会留在这段对话里。";}
  else if(turn){
    if(turn.status==="waiting_for_approval"){
      mode="handoff";
      const desktop=turn.approval?.kind==='desktop_input';
      line=desktop?(state.currentDesktopApproval?.task_eligible?'这件事，等你交给我。':state.currentDesktopApproval?'这里需要你定一下。':'收到，接着处理。'):'这里需要你定一下。';
      detail=desktop&&state.currentDesktopApproval?.task_eligible?'交给我后，普通操作会连续推进。':'具体内容在上面的对话里。';
    }
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
  $("companion-stop").hidden=!turn?.run_id||["stopping","waiting_for_approval"].includes(turn.status);
  $("companion-stop").dataset.task=turn?.id||"";
  const remote=state.remoteDevices.filter(r=>r.kind==='computer'&&r.methods.includes('computer.input'));
  const remoteComputer=remote.length===1?remote[0]:null;
  $("computer-takeover").hidden=state.deployment==='cloud'?!remoteComputer:!computer?.connector?.enrolled;
  $("computer-takeover").textContent=state.deployment==='cloud'?(remoteComputer?.control_pending?'正在交接……':remoteComputer?.paused?'交回 Pajio':'我来接管'):computer?.control?.holder==='human'?'交回 Pajio':'我来接管';
  $("computer-takeover").disabled=!!remoteComputer?.control_pending;
  companionMode=mode;
  presencePlayer?.setState(mode==="offline"?"idle":mode==="handoff"?"waiting":mode==="working"?(state.sending||turn?.status==="starting"?"working":"thinking"):mode);
  syncMotion();
}
function syncMotion(){presencePlayer?.sync();}
async function loadCharacter(){
  if(document.documentElement.classList.contains('native-composer-host')){
    // The approved iPhone shell uses the still character; input belongs to the
    // native dock, so a welcome tap must not focus the hidden web composer.
    $("character-stage").disabled=true;
    updateCompanion();return;
  }
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
  if(state.deployment==="cloud"){state.computer=null;lastComputerCheck=Date.now();updateCompanion();return;}
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
    let text=!r.installed?"准备连接器后，就能在这台电脑里帮你动手。":!r.ready?permissionText:!c.enrolled?"权限已就绪。接入后，可以在对话里交代电脑上的事情。":held?"你正在接管。Pajio 已暂停电脑读取和操作。":c.active?"这台电脑已连接，可以在对话里请 Pajio 操作。":"已接入，启动本地引擎后可以使用。";
    $("computer-status").textContent=c.error||r.error||(installing?"正在准备电脑连接器……":text);
    $("computer-prepare").hidden=!!r.installed;$("computer-prepare").disabled=installing;
    $("computer-permissions").hidden=!r.installed||r.ready||!r.can_grant;
    $("computer-bind").hidden=!r.ready||c.enrolled;
    $("computer-control").hidden=!c.enrolled;$("computer-control").textContent=held?"交回 Pajio":"我来接管";
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
$("computer-takeover").addEventListener("click",()=>busy($("computer-takeover"),async()=>{
  if(state.deployment!=='cloud')return toggleComputer();
  const remote=state.remoteDevices.filter(r=>r.kind==='computer'&&r.methods.includes('computer.input'));
  if(remote.length!==1)return showSettings();
  const r=remote[0];
  await api('/api/devices/control',{method:'POST',body:JSON.stringify({resource_id:r.resource_id,paused:!r.paused,expected_generation:r.control_generation})});
  await loadDesktopApprovals();
}));
function configureDeployment(){
  if(state.deployment!=="cloud")return;
  $("settings-title").textContent="一直连接着";
  $("connection-intro").textContent="我在你的独立云端实例里，接着记、接着做。电脑和手机随时可以交给我，也可以拿回来。";
  $("cloud-devices-section").hidden=false;
  const panel=$("settings-panel");
  for(const node of panel.querySelectorAll(":scope > .local-engine, :scope > .remote-connection, :scope > .device-section"))node.hidden=true;
  $("goal-continuity-help").textContent="目标和进展会一直保留。云端 Pajio 会按约定轮次继续推进，关掉网页也没关系；操作手机或电脑时，需要对应设备在线。";
}
let remoteDeviceSignature="",devicesLoading=false;
const deviceIcon=kind=>kind==="android"?'<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="6.5" y="2.5" width="11" height="19" rx="3"/><path d="M10 5h4m-3 13.5h2"/></svg>':'<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="4" width="18" height="12" rx="2"/><path d="M9 20h6m-3-4v4"/></svg>';
async function loadDevices(){
  if(devicesLoading)return;devicesLoading=true;
  try{
    const result=await api("/api/devices");state.remoteDevices=result.devices;
    syncPermissionForm();
    await loadDeviceReviews();
    await loadDesktopApprovals();
    await loadPermissionChange();
    if(state.pendingDeviceControl){
      const r=result.devices.find(r=>r.resource_id===state.pendingDeviceControl);
      if(r&&!r.control_pending){$("cloud-devices-feedback").textContent=r.paused?"设备已确认暂停。你可以自己使用，随时交回。":r.online?"设备已交回 Pajio，可以继续一起做事。":"云端已交回，设备在本机仍暂停或未就绪，请在设备连接器里检查。";state.pendingDeviceControl=null;}
    }
    const signature=JSON.stringify([state.identityId,...result.devices.map(({last_seen_at,...r})=>r)]);
    if(signature===remoteDeviceSignature)return;remoteDeviceSignature=signature;
    $("cloud-devices").innerHTML=result.devices.length?result.devices.map(r=>{
      const canInput=r.methods.includes('computer.input');
      const status=r.paused?(r.control_pending?"云端已暂停 · 等待设备确认":"已暂停"):
        r.control_pending?"等待设备确认恢复":r.needs_review?"有一步待核对 · 后续操作暂停":r.online?(r.kind==="computer"&&!canInput?"可以帮你观察":"可以一起做事"):r.connected?"本机已暂停或设备未就绪":"设备离线";
      const capability=r.kind==="android"?(r.methods.some(m=>!['phone.mobile_list_apps','phone.mobile_get_screen_size','phone.mobile_list_elements_on_screen','phone.mobile_take_screenshot'].includes(m))?"读取、点击与输入":"只读界面与应用"):canInput?"按任务连续操作":"已接通电脑观察";
      return `<article class="cloud-device-row"><div class="cloud-device-icon">${deviceIcon(r.kind)}</div><div class="cloud-device-copy"><strong>${esc(r.name)}</strong><p><span class="device-state-dot ${r.online?"ready":""}"></span>${status}</p><small>${capability}</small>${r.kind==='computer'?`<button class="text-button device-permission-open" data-permission-resource="${esc(r.resource_id)}">${canInput?'调整权限':'让 Pajio 动手'}</button>`:''}</div><button class="secondary" data-cloud-control="${esc(r.resource_id)}" data-generation="${r.control_generation}" data-paused="${r.paused}" aria-label="${r.paused?"交回":"暂停"} ${esc(r.name)}">${r.paused?"交回 Pajio":r.kind==="computer"?"我来接管":"暂停"}</button></article>`;
    }).join(""):'<p class="cloud-device-empty">这个身份还没有接入设备。先接入电脑连接器，再把手机交给 Pajio。</p>';
  }finally{devicesLoading=false;}
}
$("cloud-devices-refresh").addEventListener("click",()=>busy($("cloud-devices-refresh"),loadDevices,$("cloud-devices-feedback")));
$("cloud-devices").addEventListener("click",event=>{
  const button=event.target.closest("[data-cloud-control]");if(!button)return;
  busy(button,async()=>{
    const paused=button.dataset.paused!=="true";
    $("cloud-devices-feedback").textContent=paused?"正在暂停这台设备……":"正在交回这台设备……";
    await api("/api/devices/control",{method:"POST",body:JSON.stringify({resource_id:button.dataset.cloudControl,paused,expected_generation:Number(button.dataset.generation)})});
    state.pendingDeviceControl=button.dataset.cloudControl;
    $("cloud-devices-feedback").textContent=paused?"云端已停止派发新动作，正在等待设备确认。":"正在等待设备确认恢复。旧操作不会重新执行。";await loadDevices();
  },$("cloud-devices-feedback"));
});
let permissionDevice=null,permissionRequest=null;
function closePermissionChange(){permissionDevice=null;permissionRequest=null;$("device-permission-form").hidden=true;$("device-permission-next").hidden=true;$("device-permission-feedback").textContent='';}
function syncPermissionForm(){
  if(!permissionDevice)return;
  const current=state.remoteDevices.find(r=>r.resource_id===permissionDevice.resource_id);
  if(!current){closePermissionChange();return;}
  permissionDevice=current;
  const mode=current.methods.includes('computer.input')?'input':'observe';
  $("device-permission-current").textContent=mode==='input'?'现在可以按任务连续处理，你随时可以接管。':'现在可以观察屏幕与窗口。';
  $("device-permission-create").disabled=$("device-permission-mode").value===mode;
}
$("device-permission-close").addEventListener('click',closePermissionChange);
$("cloud-devices").addEventListener('click',event=>{
  const button=event.target.closest('[data-permission-resource]');if(!button)return;
  closePermissionChange();
  permissionDevice=state.remoteDevices.find(r=>r.resource_id===button.dataset.permissionResource);if(!permissionDevice)return;
  $("device-permission-title").textContent=`让${permissionDevice.name}帮到哪一步`;
  $("device-permission-current").textContent=permissionDevice.methods.includes('computer.input')?'现在可以按任务连续处理，你随时可以接管。':'现在可以观察屏幕与窗口。';
  $("device-permission-mode").value='input';
  $("device-permission-form").hidden=false;
  syncPermissionForm();
  if(!permissionDevice.methods.includes('computer.input'))$("device-permission-form").requestSubmit();
});
$("device-permission-mode").addEventListener('change',()=>{permissionRequest=null;$("device-permission-next").hidden=true;$("device-permission-feedback").textContent='';syncPermissionForm();});
$("device-permission-form").addEventListener('submit',event=>{event.preventDefault();busy($("device-permission-create"),async()=>{
  if(!permissionDevice)return;
  const mode=$("device-permission-mode").value;
  const intent={resource_id:permissionDevice.resource_id,revision:permissionDevice.permission_revision,mode,delivery:'connector'};
  const signature=JSON.stringify(intent);
  if(!permissionRequest||permissionRequest.signature!==signature)permissionRequest={id:window.WearingIds.uuid().replaceAll('-',''),signature,identity:state.identityId};
  await api('/api/devices/permissions',{method:'POST',body:JSON.stringify({...intent,request_id:permissionRequest.id})});
  $("device-permission-next").hidden=false;
  $("device-permission-feedback").textContent='正在自动连接……无需下载或运行命令。';
},$("device-permission-feedback"));});
async function loadPermissionChange(){
  if(!permissionRequest||permissionRequest.identity!==state.identityId)return;
  const result=await api(`/api/devices/permissions/${permissionRequest.id}`);
  if(result.state==='applied'){
    $("device-permission-feedback").textContent=result.connected?'权限已更新，设备已重新连接。可以继续对话了。':'权限已更新，正在自动重新连接……';
    $("device-permission-next").hidden=true;
  }else if(['expired','superseded'].includes(result.state)){
    $("device-permission-feedback").textContent=result.state==='expired'?'同步等待已超时，请确认电脑连接器在线后重试。':'设备权限又有变化，请重新查看。';
    $("device-permission-next").hidden=true;permissionRequest=null;
  }
}
let desktopApprovalSignature="";
async function loadDesktopApprovals(){
  const {approvals,computers=[]}=await api('/api/devices/input-approvals');
  state.remoteDevices=[...state.remoteDevices.filter(r=>r.kind!=='computer'),...computers];state.currentDesktopApproval=approvals.find(a=>a.state==='awaiting_user');updateCompanion();
  const signature=JSON.stringify([state.identityId,approvals]);if(signature===desktopApprovalSignature)return;desktopApprovalSignature=signature;
  const visible=approvals.filter(a=>['awaiting_user','unknown','device_error'].includes(a.state)||(!a.delegated&&['queued','executing'].includes(a.state))).slice(0,1);
  $('desktop-input-section').hidden=!visible.length;
  $('desktop-input-cards').innerHTML=visible.map(a=>{
    const p=a.action,names={click:'点击',set_value:'填写',type:'输入',key:'按键',scroll:'滚动'};
    const detail=p.action==='click'?p.element_label:p.action==='set_value'?`${p.element_label}\n${p.value}`:p.text??p.keys??`${p.direction} · ${p.amount}`;
    const status={awaiting_user:a.task_eligible?'这件事，交给我来做。':'这里需要你定一下。',queued:'你已允许，正在送到电脑。',executing:'正在电脑上做这一步。',completed:'这一步已收到电脑回执。',unknown:'这一步的结果还不确定。',device_error:'电脑没能完成这一步。',blocked:'这一步已停止，没有继续执行。',denied:'这次先不做，我停在这里。',expired:'这一帧已过期，需要重新看一眼。',cancelled:'电脑状态变化，这一步停下了。'}[a.state];
    return `<article class="desktop-input-card decision-card"><div class="desktop-input-heading"><img src="/assets/companion-portrait.png?v=1" alt="" width="36" height="36"><strong>${status}</strong></div><p>${esc(a.reason)}</p><div class="desktop-input-preview"><span>${esc(p.app)} · ${names[p.action]}</span><pre>${esc(detail)}</pre></div>${a.state==='awaiting_user'&&a.can_decide?`<p class="field-help">${a.task_eligible?`本轮在 ${esc(p.app)} 连续处理，最长 30 分钟。付款、发送内容或账号安全变更前会停下来。`:'这一步涉及关键动作，确认后我会接着处理。'}</p><div class="button-row decision-actions"><button class="primary" data-desktop-decision="${a.task_eligible?'task':'once'}" data-id="${esc(a.approval_id)}" data-revision="${esc(a.revision)}">${a.task_eligible?'交给 Pajio':'确认并继续'}</button><button class="secondary" data-desktop-decision="deny" data-id="${esc(a.approval_id)}" data-revision="${esc(a.revision)}">先停一下</button></div>`:`<p class="field-help">${a.state==='awaiting_user'?(a.run_wait?.state==='answered'?'已收到你的决定，等待执行端继续。':'正在连接本轮确认，请稍等。'):a.state==='completed'?(a.run_wait?'电脑已返回回执，我会接着核对并回应。':'回执不等于事情办成了；接下来重新观察并核对结果。'):['unknown','device_error'].includes(a.state)?'先到设备设置核对实际结果，旧动作不会重做。':'可以随时在设备设置里接管电脑。'}</p>`}</article>`;
  }).join('');
}
$('desktop-input-cards').addEventListener('click',event=>{
  const button=event.target.closest('[data-desktop-decision]');if(!button)return;
  busy(button,async()=>{await api('/api/devices/input-approvals',{method:'POST',body:JSON.stringify({approval_id:button.dataset.id,revision:button.dataset.revision,choice:button.dataset.desktopDecision})});await loadDevices();},$('desktop-input-feedback'));
});
let deviceOffer=null,pairRequest=null,deviceReviewSignature="";
const deviceActionNames={mobile_press_button:"按手机按键",mobile_launch_app:"打开应用",mobile_click_on_screen_at_coordinates:"点击屏幕",mobile_swipe_on_screen:"滑动屏幕",mobile_type_keys:"输入文字",mobile_set_text:"填写输入框",mobile_list_elements_on_screen:"读取当前界面",mobile_take_screenshot:"读取屏幕截图",mobile_list_apps:"查看应用列表",mobile_get_screen_size:"读取屏幕尺寸",status:"查看电脑状态",observe:"观察电脑"};
async function loadDeviceReviews(){
  const {reviews}=await api("/api/devices/reviews");
  const signature=JSON.stringify([state.identityId,reviews]);if(signature===deviceReviewSignature)return;deviceReviewSignature=signature;
  const notes=new Map([...$("device-reviews").querySelectorAll("form")].map(f=>[f.dataset.command,{revision:f.dataset.revision,note:f.querySelector("textarea").value,checked:f.querySelector("input").checked}]));
  $("device-reviews-section").hidden=!reviews.length;
  $("device-reviews").innerHTML=reviews.map(r=>`<form class="device-review decision-card" data-command="${esc(r.command_id)}" data-revision="${esc(r.revision)}"><strong>${esc(r.name)} · ${esc(deviceActionNames[r.method.split('.').pop()]||"设备操作")}</strong><p>${esc(new Date(r.created_at).toLocaleString())} · ${r.state==="unknown"?"结果不明":"设备未能完成"}</p><label>核对后发生了什么？<textarea required minlength="5" maxlength="2000" placeholder="例如：已查看手机，应用没有打开，旧动作已结束。" aria-label="${esc(r.name)} 核对结果"></textarea></label><label class="device-checked"><input type="checkbox" required>我已查看设备，确认旧动作已结束</label><button class="secondary" type="submit" ${r.can_review?"":"disabled"}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m5 12 4 4L19 6"/></svg>核对结果</button>${r.can_review?"":'<p class="field-help">正在等旧动作结束、设备重新在线；现在还不能解除卡点。</p>'}</form>`).join("");
  for(const f of $("device-reviews").querySelectorAll("form")){const previous=notes.get(f.dataset.command);if(previous){f.querySelector("textarea").value=previous.note;f.querySelector("input").checked=previous.checked&&previous.revision===f.dataset.revision;}}
}
$("device-reviews").addEventListener("submit",event=>{event.preventDefault();const form=event.target;busy(form.querySelector("button"),async()=>{
  await api("/api/devices/reviews",{method:"POST",body:JSON.stringify({command_id:form.dataset.command,revision:form.dataset.revision,note:form.querySelector("textarea").value.trim(),checked:form.querySelector("input").checked})});
  $("device-review-feedback").textContent="核对结果已保存。接下来可以发起新动作，旧动作不会重做。";await loadDevices();
},$("device-review-feedback"));});
$("device-offer-file").addEventListener("change",async event=>{
  const file=event.target.files[0];if(!file)return;const epoch=state.identityEpoch;
  deviceOffer=null;pairRequest=null;$("device-pair-form").hidden=true;$("device-pair-next").hidden=true;
  try{
    if(file.size>32768)throw new Error("清单过大，请使用 Pajio 连接器重新导出。");
    let offer;try{offer=JSON.parse(await file.text());}catch{throw new Error("清单格式不正确，请重新导出 JSON 文件。");}
    if(epoch!==state.identityEpoch)return;
    const result=await api("/api/devices/offer",{method:"POST",body:JSON.stringify(offer)});deviceOffer=offer;
    $("device-offer-choices").innerHTML=result.resources.map((r,i)=>`<div class="device-offer-choice"><label><input type="checkbox" data-offer-index="${i}" ${r.already_paired?"disabled":"checked"}><strong>${esc(r.name)}</strong> <small>${r.already_paired?"已经接入":r.kind==="computer"?"电脑":"Android 手机"}</small></label>${!r.already_paired?`<label class="device-scope-label">交给我的能力<select data-offer-scope="${i}"><option value="read">${r.kind==='computer'?'观察电脑':'读取界面与应用'}</option><option value="full">${r.kind==='computer'?'观察、点击与输入':'读取、点击与输入'}</option></select></label>`:""}</div>`).join("");
    $("device-pair-form").hidden=false;
    $("device-pair-create").disabled=result.resources.every(r=>r.already_paired);
    $("device-pair-feedback").textContent=result.resources.every(r=>r.already_paired)?"这份清单里的设备已经接入，无需重复配对。":"选择设备与权限后，生成一次性配对文件。";
  }catch(error){if(error instanceof StaleIdentity)return;$("device-pair-feedback").textContent=error.message;}
});
$("device-offer-choices").addEventListener("change",()=>{$("device-pair-create").disabled=!$("device-offer-choices").querySelector("[data-offer-index]:checked");$("device-pair-next").hidden=true;});
$("device-pair-form").addEventListener("submit",event=>{event.preventDefault();busy($("device-pair-create"),async()=>{
  const resources=[...$("device-offer-choices").querySelectorAll("[data-offer-index]:checked")].map(el=>{
    const i=Number(el.dataset.offerIndex),r=deviceOffer.resources[i],read=$("device-offer-choices").querySelector(`[data-offer-scope="${i}"]`)?.value==="read";
    return {...r,methods:read?r.methods.filter(m=>["computer.status","computer.observe","phone.mobile_list_apps","phone.mobile_get_screen_size","phone.mobile_list_elements_on_screen","phone.mobile_take_screenshot"].includes(m)):r.methods};
  });
  if(!resources.length)throw new Error("请选择一台尚未接入的设备。");
  const offer={schema_version:1,resources},selection=JSON.stringify([state.identityId,offer]);
  if(!pairRequest||pairRequest.selection!==selection)pairRequest={selection,id:window.WearingIds.uuid().replaceAll("-","")};
  const result=await api("/api/devices/pair",{method:"POST",body:JSON.stringify({request_id:pairRequest.id,offer})});
  $("device-pair-download").href=`/api/devices/pair/${pairRequest.id}/download?identity=${encodeURIComponent(state.identityId)}`;
  $("device-pair-feedback").textContent="配对文件已生成。请点击下载，仅交给你选择的设备所在电脑。";$("device-pair-next").hidden=false;
},$("device-pair-feedback"));});
$("device-tools-refresh").addEventListener("click",()=>busy($("device-tools-refresh"),async()=>{const result=await api("/api/devices/refresh-tools",{method:"POST",body:"{}"});$("device-pair-feedback").textContent=result.message;},$("device-pair-feedback")));
async function initialize(){try{const bootstrap=await api("/api/bootstrap");state.token=bootstrap.token;state.goalPolicy=bootstrap.goal_policy||state.goalPolicy;state.deployment=bootstrap.deployment||"local";bindScopedStorage(bootstrap);configureDeployment();window.WearingDeletion?.start();state.identities=bootstrap.identities;let remembered;try{remembered=sessionStorage.getItem("wearing-identity");}catch{}const requested=new URLSearchParams(location.search).get("identity");if(requested&&!state.identities.some(i=>i.id===requested))throw new Error("入口身份不存在");state.identityId=requested||(state.identities.some(i=>i.id===remembered)?remembered:bootstrap.default_identity_id);renderIdentityContext();window.WearingLife?.identityChanged();activateComposer(composerDrafts.last(state.identityId)||{identity:state.identityId},$("message-input").value);$("open-identities").disabled=false;$("hermes-url").value=bootstrap.hermes_url;await loadStatus();await loadConversation();await loadGoalUpdates();await window.WearingActivity?.load(true);await loadCharacter();loadComputer();await window.WearingLife?.openFromLink();const activityTask=new URLSearchParams(location.search).get("activity_task");if(activityTask)await window.WearingActivity?.openTask(activityTask);window.WearingOnboarding?.maybeOffer();}catch{notice("暂时没有连接上 Pajio。请检查入口和连接，再刷新页面。",true);}}
async function pollConversation(){
  if(window.WearingDeletion && window.WearingDeletion.workAllowed() === false) return; // 注销受理后停止本账户业务轮询

  if(document.hidden||window.WearingHost?.hidden||state.polling||!state.token)return;
  state.polling=true;const epoch=state.identityEpoch;
  try{
    // A device/settings failure must not hide a completed run or its next card.
    if(Date.now()-state.lastStatus>15000)await loadStatus();
    await loadConversation();
  }catch(error){
    if(epoch===state.identityEpoch&&!(error instanceof StaleIdentity)){state.connected=false;window.WearingActivity?.disconnected();updateCompanion();$("connection-label").textContent="连接中断";$("connection-dot").classList.remove("online");}
    state.polling=false;return;
  }
  try{
    const extras=[()=>window.WearingActivity?.load()];
    if($("settings-panel").open){
      if(state.deployment==="cloud")extras.push(()=>loadDevices());
      else{extras.push(()=>loadRuntime());if(Date.now()-lastPhoneCheck>10000)extras.push(()=>loadPhone());}
    }else if(state.deployment==="cloud")extras.push(()=>loadDesktopApprovals());
    if(Date.now()-lastComputerCheck>15000)extras.push(()=>loadComputer());
    if(Date.now()-lastGoalUpdates>10000)extras.push(()=>loadGoalUpdates());
    if($("keeps-panel").open&&$("goal-form").hidden){extras.push(()=>loadGoals(),()=>window.WearingSchedules?.load());if(selectedGoal)extras.push(()=>loadGoal(selectedGoal.id,true));}
    const results=await Promise.allSettled(extras.map(fn=>fn()));
    if(epoch===state.identityEpoch){
      const failures=results.filter(r=>r.status==="rejected"&&!(r.reason instanceof StaleIdentity));
      if(failures.length&&$("settings-panel").open)$("device-review-feedback").textContent="部分连接状态暂未更新，对话仍可继续。";
      if(failures.length&&$("keeps-panel").open)$("goal-feedback").textContent="部分进展暂未更新，已保存的内容保留。";
    }
  }finally{state.polling=false;}
}
setInterval(pollConversation,3000);

const identityRegions={CN:"国内生活",international:"海外事务",custom:"按用途区分"};
function renderIdentityContext(){
  const current=state.identities.find(i=>i.id===state.identityId);if(!current)return;
  $("identity-name").textContent=current.name;$("open-identities").setAttribute("aria-label",`当前身份：${current.name}，切换身份`);
  $("identity-context").textContent=`${current.name} · ${current.description||identityRegions[current.region]}`;
  $("message-input").placeholder=`说一声，我来做…`;
  document.title=`${current.name} · Pajio`;
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
  rememberComposer();composerReady=false;
  state.identityId=id;state.identityEpoch++;state.messages=[];state.signature="";state.selectedKeep=null;state.computer=null;state.lastStatus=0;state.connected=false;
  window.WearingArtifacts.identityChanged();
  window.WearingLife?.identityChanged();
  window.WearingSchedules?.identityChanged();
  window.WearingActivity?.reset();
  window.WearingOnboarding?.reset();
  window.WearingChatImport?.reset();
  lastGoalUpdates=0;goalUpdatesSignature="";renderGoalUpdates({unread:0,items:[]});$("goal-updates-feedback").textContent="";
  $('desktop-input-section').hidden=true;$('desktop-input-cards').innerHTML='';
  deviceOffer=null;pairRequest=null;deviceReviewSignature="";remoteDeviceSignature="";desktopApprovalSignature="";state.remoteDevices=[];state.currentDesktopApproval=null;$("desktop-input-cards").replaceChildren();$("desktop-input-section").hidden=true;
  $("device-pair-form").hidden=true;$("device-pair-next").hidden=true;$("device-offer-file").value="";$("device-pair-feedback").textContent="";$("device-review-feedback").textContent="";$("device-reviews").replaceChildren();$("device-reviews-section").hidden=true;
  closePermissionChange();
  memoryEntries=[];$("memory-section").open=false;$("memory-list").replaceChildren();$("memory-feedback").textContent="";
  state.goalFocus=null;state.goalSource=null;renderGoalContext();selectedGoal=null;goalsSignature="";$("goals-list").replaceChildren();$("goals-list").hidden=false;$("goal-detail").replaceChildren();$("goal-detail").hidden=true;$("goal-form").hidden=true;$("goal-feedback").textContent="";
  try{sessionStorage.setItem("wearing-identity",id);}catch{}
  $("message-input").value="";activateComposer(composerDrafts.last(id)||{identity:id});$("messages").replaceChildren();$("keep-detail").replaceChildren();$("keep-detail").hidden=true;$("keeps-list").replaceChildren();$("files-list").replaceChildren();$("conversation").hidden=true;$("welcome").hidden=false;$("newest-message").hidden=true;$("identity-running").hidden=true;
  document.querySelectorAll("dialog[open]").forEach(d=>d.close());notice("");renderIdentityContext();updateCompanion();
  $("connection-label").textContent="连接中……";$("connection-dot").classList.remove("online");
  try{await loadStatus();await loadConversation(true);await loadGoalUpdates();await window.WearingActivity?.load(true);await loadComputer();window.WearingOnboarding?.maybeOffer();}catch(e){if(!(e instanceof StaleIdentity))notice(e.message,true);}
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
let lastGoalUpdates=0, goalUpdatesSignature="";
function renderGoalUpdates(data){
  $("goal-updates-badge").hidden=!data.unread;
  $("goal-updates-badge").textContent=data.unread>99?"99+":String(data.unread);
  const navBadge=$("nav-goal-badge");
  if(navBadge){navBadge.hidden=!data.unread;navBadge.textContent=data.unread>99?"99+":String(data.unread);}
  document.querySelector('.app-nav [data-life-view="tasks"]')?.setAttribute("aria-label",data.unread?`任务与目标进展，${data.unread} 条新进展`:"任务与目标进展");
  $("open-keeps").setAttribute("aria-label",data.unread?`目标与定时任务，${data.unread} 条新进展`:"目标与定时任务");
  $("goal-updates-summary").hidden=!data.unread;
  $("goal-updates-greeting").textContent=data.unread===1?"有件事，有了新进展。":`有 ${data.unread} 条进展，回来跟你说。`;
  $("goal-updates-preview").textContent=data.items[0]?.objective||"";
  $("goal-updates-section").hidden=!data.items.length;
  $("goal-updates-seen").dataset.seenUpdates=data.items.map(u=>u.id).join(",");
  $("goal-updates-more").hidden=data.unread<=data.items.length;
  $("goal-updates-more").textContent="先显示最近 20 条，看过后可以接着看更早的进展。";
  $("goal-updates-list").innerHTML=data.items.map(u=>{
    const changed=u.revision!==u.current_revision||u.status!==u.current_status;
    const label=changed?`这轮的记录 · 现在${goalLabels[u.current_status]||"有新变化"}`:({active:"这轮有了进展",waiting:"等合适的时候继续",needs_user:"有件事需要你决定",needs_review:"结果等你核对",limited:"约定的几轮已跑完"}[u.status]||"这轮的记录");
    return `<article class="goal-update"><p class="goal-update-label">${esc(label)} · ${esc(date(u.created_at))}</p><h4>${esc(u.objective)}</h4><p class="goal-prose">${esc(u.summary)}</p>${u.reason!==u.summary?`<p class="field-help">${esc(u.reason)}</p>`:""}<div class="goal-update-actions"><button class="text-button" data-open-update="${u.id}" data-update-goal="${esc(u.goal_id)}">看看进展</button><button class="text-button" data-seen-updates="${u.id}">知道了</button></div></article>`;
  }).join("");
}
async function loadGoalUpdates(){
  try{
    const data=await api("/api/goal-updates");lastGoalUpdates=Date.now();
    const signature=JSON.stringify(data);if(signature!==goalUpdatesSignature){goalUpdatesSignature=signature;renderGoalUpdates(data);}
    $("goal-updates-feedback").textContent="";
  }catch(error){
    if(error instanceof StaleIdentity)throw error;
    lastGoalUpdates=Date.now();
    $("goal-updates-feedback").textContent="暂时读不到新进展，原目标和记录仍然保留。";
  }
}
async function acknowledgeGoalUpdates(ids){
  const data=await api("/api/goal-updates/seen",{method:"POST",body:JSON.stringify({ids})});
  goalUpdatesSignature=JSON.stringify(data);renderGoalUpdates(data);
}
$("open-goal-updates").addEventListener("click",async()=>{if(!$("keeps-panel").open)openPanel("keeps-panel");await loadKeeps().catch(e=>notice(e.message,true));});
$("keeps-panel").addEventListener("click",async event=>{
  const view=event.target.closest("[data-open-update]");
  if(view){await busy(view,async()=>{await loadGoal(view.dataset.updateGoal);await acknowledgeGoalUpdates([Number(view.dataset.openUpdate)]);$("goal-detail").scrollIntoView({block:"start",behavior:state.motionPaused?"instant":"smooth"});},$("goal-updates-feedback"));return;}
  const seen=event.target.closest("[data-seen-updates]");
  if(seen){const ids=seen.dataset.seenUpdates.split(",").filter(Boolean).map(Number);await busy(seen,()=>acknowledgeGoalUpdates(ids),$("goal-updates-feedback"));}
});
function renderGoalContext(){
  if(state.goalFocus){state.lifeFocus=null;window.WearingLife?.renderContext();}
  const goal=state.goalFocus;$("goal-compose-context").hidden=!goal;
  $("message-input").maxLength=goal?.mode==="note"?2000:12000;
  $("message-input").minLength=goal?.mode==="note"?3:1;
  if(!goal){$("message-input").placeholder=`说一声，我来做…`;return;}
  $("goal-compose-title").textContent=(goal.mode==="note"?"补充 · ":"聊聊 · ")+goal.objective;
  $("goal-compose-title").dataset.goal=goal.id;
  $("goal-compose-help").textContent=goal.mode==="note"?"发送后记为新的情况，让旧计划按你的补充调整。":"先一起讨论，原来的约定照常保留。";
  $("message-input").placeholder=goal.mode==="note"?"有什么新情况，直接跟我说。":"关于这件事，我们接着聊。";
}
$("clear-goal-context").addEventListener("click",()=>{activateComposer({identity:state.identityId});$("message-input").focus();});
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
  const extension=Math.min(state.goalPolicy.extension_steps,Math.max(0,state.goalPolicy.max_steps-goal.max_steps));
  const exhausted=goal.used_steps>=goal.max_steps;
  const running=goal.steps.some(s=>active.has(s.task_status));
  const stepMarkup=s=>{
    const report=s.report;
    return `<li><p class="goal-step-status">${esc(labels[s.task_status]||s.task_status)}${s.verified_at?" · 你已核对":" · 尚未核验业务结果"}</p><p class="goal-prose">${esc(report?.summary||s.error||(s.task_status==="draft"?"这一步已安排，等待派发。":["starting","running","stopping"].includes(s.task_status)?"这一轮正在准备或执行。":s.output||(s.task_status==="stopped"?"这一轮已停止。":"等待原运行结果。")))}</p>${report?.evidence?.length?`<details class="setup-guide"><summary>这次依据了什么</summary>${report.evidence.map(e=>`<p>${esc(e.observation)}<br><span class="field-help">${esc(e.source)}</span></p>`).join("")}<p class="field-help">以上来源由模型报告；核对记录另行保存。</p></details>`:""}${report?.unknowns?.length?`<p class="field-help">仍未确定：${esc(report.unknowns.join("；"))}</p>`:""}<button class="text-button" data-goal-turn="${esc(s.task_id)}">到对话查看与核对</button></li>`;
  };
  $("goal-detail").hidden=false;$("goal-form").hidden=true;$("goals-list").hidden=false;
  $("goal-detail").innerHTML=`<h3>${esc(goal.objective)}</h3><p class="goal-status-line">${esc(goalLabels[goal.status])} · 已安排 ${goal.used_steps}/${goal.max_steps} 轮</p><p class="goal-prose">${esc(goal.reason||"这件事已记下，等你决定什么时候开始。")}</p>${goal.next_wake?`<p class="field-help">下次检查：${esc(new Date(goal.next_wake).toLocaleString("zh-CN"))}${state.deployment==="cloud"?"，由云端 Pajio 继续推进。":"，本地服务需保持运行。"}</p>`:""}${goal.next_step?`<p class="goal-prose"><strong>下一步</strong><br>${esc(goal.next_step)}</p>`:""}<details class="setup-guide"><summary>我们的约定</summary><p class="goal-prose">${esc(goal.boundaries)}</p><p class="goal-prose">阶段结果：${esc(goal.success_criteria)}</p></details>
    ${!ended?`<div class="button-row goal-controls">${["active","waiting"].includes(goal.status)?'<button class="secondary" data-goal-action="pause">先停一下</button>':`<button class="primary" data-goal-action="resume" ${running||(exhausted&&!extension)?"disabled":""}>${exhausted?(extension?`继续推进 · 增加 ${extension} 轮`:"请先复盘这个目标"):"继续推进"}</button>`}<button class="text-button" data-goal-action="cancel">结束委托</button><button class="text-button" data-goal-note-mode="complete" ${running?"disabled":""}>我已核对，目标达成</button></div><p class="field-help">暂停会阻止后续步骤，并请求停止当前运行；实际停止状态见下方。</p><form id="goal-note-form" class="note-form decision-card"><label for="goal-note">补充新的情况，或纠正之前的理解</label><textarea id="goal-note" required minlength="3" maxlength="2000" rows="2" placeholder="比如：先不考虑实体商品，沿数字服务方向继续。"></textarea><button class="secondary">记住这次补充</button></form><p id="goal-detail-feedback" class="inline-feedback" role="status"></p>`:""}
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
// 目标创建幂等：同一份表单内容失败后重试沿用同一 request_key，
// 服务端对同 spec 重放回原目标；改了内容才换新 key（对齐 GoalBook.create 合同）。
let goalCreateState=null;
function goalCreateKey(spec){if(!goalCreateState||goalCreateState.spec!==spec)goalCreateState={spec,key:window.WearingIds.uuid().replaceAll("-","")};return goalCreateState.key;}
function goalCreateReset(){goalCreateState=null;}
$("goal-form").addEventListener("submit",async e=>{
  e.preventDefault();const start=e.submitter?.value==="start", buttons=[...$("goal-form").querySelectorAll("button")];buttons.forEach(b=>b.disabled=true);$("goal-feedback").textContent="正在记下……";
  try{const objective=$("goal-objective").value,boundaries=$("goal-boundaries").value,success_criteria=$("goal-criteria").value,max_steps=Number($("goal-rounds").value);
    const spec=[objective,boundaries,success_criteria,max_steps,state.goalSource??""].join("\u0001");
    const retried=Boolean(goalCreateState);
    const g=await api("/api/goals",{method:"POST",body:JSON.stringify({objective,boundaries,success_criteria,max_steps,...(state.goalSource?{source_task_id:state.goalSource}:{}),request_key:goalCreateKey(spec)})});
    goalCreateReset();
    await loadGoals();await loadGoal(g.id);
    if(start){try{await api(`/api/goals/${g.id}/control`,{method:"POST",body:JSON.stringify({revision:g.revision,action:"resume"})});}catch(error){if(error instanceof StaleIdentity)throw error;$("goal-feedback").textContent="目标已保存，启动尚未确认。更新进展后查看原状态："+error.message;return;}}
    await loadGoals();await loadGoal(g.id);$("goal-feedback").textContent=(retried?"同一创建请求已接回原目标，未重复建。":"")+(start?"记住了。服务会在有空时安排下一步，进展会回到对话里。":"先替你记着。想开始时，再交给我推进。");
  }catch(error){if(!(error instanceof StaleIdentity))$("goal-feedback").textContent=error.message;}finally{buttons.forEach(b=>b.disabled=false);}
});
$("goal-detail").addEventListener("click",async e=>{
  const chat=e.target.closest("[data-goal-chat]");if(chat&&selectedGoal){activateComposer({identity:state.identityId,goal:{id:selectedGoal.id,objective:selectedGoal.objective,revision:selectedGoal.revision,mode:chat.dataset.goalChat}});closePanel("keeps-panel");$("message-input").focus();return;}
  const mode=e.target.closest("[data-goal-note-mode]");if(mode){const form=$("goal-note-form");form.dataset.mode="complete";form.querySelector("label").textContent="你核对了什么，确认目标已经达成？";form.querySelector("button").textContent="保存核对并完成目标";$("goal-note").focus();return;}
  const button=e.target.closest("[data-goal-action]");if(!button||!selectedGoal)return;
  const g=selectedGoal, action=button.dataset.goalAction;
  await busy(button,async()=>{await api(`/api/goals/${g.id}/control`,{method:"POST",body:JSON.stringify({revision:g.revision,action,add_steps:action==="resume"&&g.used_steps>=g.max_steps?Math.min(state.goalPolicy.extension_steps,Math.max(0,state.goalPolicy.max_steps-g.max_steps)):0})});$("goal-feedback").textContent="";await loadGoals();await loadGoal(g.id);await loadConversation(true);},$("goal-detail-feedback"));
});
initialize();
