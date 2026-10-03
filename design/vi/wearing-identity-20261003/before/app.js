"use strict";
const $ = id => document.getElementById(id);
const esc = text => String(text ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const state = {token:"",connected:false,messages:[],signature:"",polling:false,lastStatus:0,selectedKeep:null,keepSignature:"",sending:false,computer:null,motionPaused:matchMedia("(prefers-reduced-motion: reduce)").matches};
const labels = {draft:"留在这里",starting:"正在送出",running:"正在回应",waiting_for_approval:"有一步需要你",stopping:"正在停止",connection_lost:"连接中断",ambiguous:"等待核对",completed_unverified:"已有回应",verified:"已核对",stopped:"已停止",failed:"需要再看看",closed_by_user:"已处理"};
const active = new Set(["starting","running","waiting_for_approval","stopping","connection_lost","ambiguous"]);
async function api(path,options={}) {
  const headers={"Content-Type":"application/json",...options.headers};
  if(options.method && options.method!=="GET") headers["X-Wearing-Token"]=state.token;
  const response=await fetch(path,{...options,headers});
  const data=await response.json();
  if(!response.ok) throw new Error(typeof data.detail==="string"?data.detail:"内容没有送出，请检查后重试。");
  return data;
}
function notice(text,error=false){$("notice").textContent=text;$("notice").className="notice"+(error?" error":"");$("notice").hidden=!text;}
async function busy(button,action){const old=[...button.childNodes];button.disabled=true;try{await action();}catch(error){notice(error.message||"连接中断，请稍后再试。",true);}finally{if(button.isConnected){button.disabled=false;button.replaceChildren(...old);}}}
function nearBottom(){return window.innerHeight+window.scrollY>=document.documentElement.scrollHeight-160;}
function scrollToLatest(){window.scrollTo({top:document.documentElement.scrollHeight,behavior:state.motionPaused?"instant":"smooth"});$("newest-message").hidden=true;}
function date(value){return new Intl.DateTimeFormat("zh-CN",{month:"numeric",day:"numeric"}).format(new Date(value));}
function openPanel(id){$(id).showModal();}
function closePanel(id){$(id).close();}
function turnActions(turn){
  let html="";
  if(active.has(turn.status)){
    if(turn.run_id&&turn.status!=="stopping")html+=`<button data-action="stop" data-task="${esc(turn.id)}">先停一下</button>`;
    html+=`<button data-action="refresh" data-task="${esc(turn.id)}">重新查看</button>`;
  }
  if(turn.status==="completed_unverified")html+=`<button data-verify="${esc(turn.id)}">记下核对结果</button>`;
  return html?`<div class="turn-tools">${html}</div>`:"";
}
function turnMarkup(message){
  const turn=message.turn,id=turn.id;
  const user=`<div class="message message-user"><div class="user-bubble">${esc(message.content)}</div></div>`;
  let response="";
  if(turn.output){response=`<div class="message message-assistant"><img class="message-avatar" src="/assets/mark.svg?v=6" alt="Wearing"><div class="assistant-content"><div class="assistant-copy">${esc(turn.output)}</div>${turnActions(turn)}${turn.verification_note?`<p class="note-saved">核对记录：${esc(turn.verification_note)}</p>`:""}<div id="verify-${esc(id)}"></div></div></div>`;}
  if(turn.status==="draft")response+=`<div class="delivery-note"><p>${state.connected?"这条还没有送出。你可以从这里继续。":"这句话已保存在本机。连接 Wearing 后，才能获得真实回应。"}</p><button class="text-button" ${state.connected?`data-action="start" data-task="${esc(id)}"`:'data-open-settings'}>${state.connected?"继续这句话":"连接 Wearing"}</button></div>`;
  if(["starting","running","stopping"].includes(turn.status)&&!turn.output)response+=`<div class="message response-wait"><img src="/assets/mark.svg?v=6" alt=""><span>${turn.status==="stopping"?"正在等待本轮停止……":"Wearing 正在回应……"}</span>${turnActions(turn)}</div>`;
  if(["connection_lost","ambiguous","failed"].includes(turn.status))response+=`<div class="delivery-note error"><p>${esc(turn.error||"这次连接没有完成，原消息仍然保留。")}</p>${turnActions(turn)}${["connection_lost","ambiguous"].includes(turn.status)?`<details class="setup-guide"><summary>已在执行电脑上处理完毕</summary><p>确认原运行和设备操作已经结束后，记录处理结果。这不会替你终止远端进程。</p><form class="note-form" data-resolve="${esc(id)}"><label for="resolve-${esc(id)}">处理记录</label><textarea id="resolve-${esc(id)}" name="note" required minlength="5" maxlength="2000"></textarea><button class="secondary">记录并结束</button></form></details>`:""}</div>`;
  if(turn.status==="waiting_for_approval"){
    const a=turn.approval;
    response+=a?.request_id?`<div class="message message-assistant"><img class="message-avatar" src="/assets/mark.svg?v=6" alt=""><div class="assistant-content approval"><p>继续之前，这一步需要你决定。</p><pre>${esc(a.description||a.command||a.preview||JSON.stringify(a,null,2))}</pre><div class="button-row"><button class="primary" data-choice="once" data-task="${esc(id)}" data-request="${esc(a.request_id)}">允许这一次</button><button class="secondary" data-choice="deny" data-task="${esc(id)}" data-request="${esc(a.request_id)}">这次先不做</button></div>${turnActions(turn)}</div></div>`:`<div class="delivery-note">执行端有一步等待确认，但还没有返回完整内容。${turnActions(turn)}</div>`;
  }
  if(turn.status==="stopped"&&!turn.output)response+='<div class="delivery-note">本轮已停止，前面的对话仍然保留。</div>';
  return user+response;
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
  const result=await api("/api/status");state.lastStatus=Date.now();state.connected=result.hermes.state==="reachable";
  $("connection-label").textContent=state.connected?"已连接":"连接 Wearing";
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
  $("engine-profile").textContent=r.product?.applied?`Wearing 个人模式 · 配置 v${r.product.profile_version} · 引擎 ${r.revision}。仅启动对话与执行接口，后台调度和消息平台未启用。`:"Wearing 个人模式会在下次启动引擎时应用。";
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
  const tasks=await api("/api/tasks");const conversationIds=new Set(state.messages.map(m=>m.task_id));
  const kept=tasks.filter(t=>!conversationIds.has(t.id));
  $("keeps-list").innerHTML=kept.length?kept.map(t=>`<button class="keep-row" data-keep="${esc(t.id)}"><strong>${esc(t.title)}</strong><small>${esc(date(t.created_at))} · ${esc(labels[t.status]||t.status)}</small></button>`).join(""):'<p class="empty-keeps">这里还没有单独留下的事情。我们的对话，会一直保留在外面。</p>';
}
async function loadKeep(id){
  state.selectedKeep=id;const t=await api("/api/tasks/"+id);
  $("keep-detail").hidden=false;
  $("keep-detail").innerHTML=`<h3>${esc(t.title)}</h3><p class="prompt">${esc(t.prompt)}</p><button class="primary" id="bring-to-conversation">带回对话</button>${t.output?`<div class="assistant-copy">${esc(t.output)}</div>`:""}${turnActions(t)}<div id="verify-${esc(t.id)}"></div><ol class="keep-timeline">${t.events.map(e=>`<li>${esc(e.message)}</li>`).join("")}</ol>`;
  $("bring-to-conversation").addEventListener("click",()=>{closePanel("keeps-panel");$("message-input").value="我们接着聊这件事："+t.prompt;$("message-input").focus();});
}
$("conversation-form").addEventListener("submit",async event=>{
  event.preventDefault();const content=$("message-input").value.trim();if(!content)return;
  state.sending=true;updateCompanion();
  try{await busy($("send-message"),async()=>{const result=await api("/api/conversation",{method:"POST",body:JSON.stringify({content})});$("message-input").value="";notice("");await loadConversation(true);scrollToLatest();if(result.delivery==="saved"&&state.connected)notice(result.reason);});}finally{state.sending=false;updateCompanion();}
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
function showSettings(){openPanel("settings-panel");loadPhone();loadComputer();loadRuntime().catch(e=>{$("runtime-status").textContent=e.message;});loadModel();}
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
  $("files-list").innerHTML=result.files.map(file=>`<a class="file-row" download href="/api/workspace/file?path=${encodeURIComponent(file.path)}"><span>${esc(file.path)}</span><small>${file.size<1024?file.size+" B":(file.size/1024).toFixed(1)+" KB"} · 下载</small></a>`).join("");
}
$("open-files").addEventListener("click",()=>{openPanel("files-panel");loadFiles().catch(e=>{$("files-list-status").textContent=e.message;});});
$("refresh-files").addEventListener("click",()=>busy($("refresh-files"),loadFiles));


let phoneState=null,phoneLoading=false,lastPhoneCheck=0,phoneOptionsSignature="",phoneResourceSignature="";
async function loadPhone(){
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
async function initialize(){try{const bootstrap=await api("/api/bootstrap");state.token=bootstrap.token;$("hermes-url").value=bootstrap.hermes_url;await loadStatus();await loadConversation();await loadCharacter();loadComputer();}catch{notice("本地服务暂时没有连接上。请确认 Wearing 正在运行，再刷新页面。",true);}}
setInterval(async()=>{if(document.hidden||state.polling||!state.token)return;state.polling=true;try{if(Date.now()-state.lastStatus>15000)await loadStatus();if($("settings-panel").open){await loadRuntime();if(Date.now()-lastPhoneCheck>10000)await loadPhone();}if(Date.now()-lastComputerCheck>15000)await loadComputer();await loadConversation();}catch{state.connected=false;updateCompanion();$("connection-label").textContent="连接中断";$("connection-dot").classList.remove("online");}finally{state.polling=false;}},3000);
initialize();
