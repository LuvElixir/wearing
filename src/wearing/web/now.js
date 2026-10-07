"use strict";
(() => {
  const panel=document.getElementById('review-panel');
  document.getElementById('open-review').addEventListener('click',()=>window.WearingLife.openReview());
  document.getElementById('open-tools').addEventListener('click',()=>openPanel('review-panel')); 
  // Close review before opening another panel, without stacking focus traps.
  panel.addEventListener('click',event=>{
    if(event.target.closest('#open-files,#open-keeps,#open-settings'))panel.close();
  },true);
  if(!window.WearingHost)return;
  const dock=document.querySelector('.composer-dock');
  const received=new Set();
  let lastReview=null;
  function appendDraft(payload){
    const input=document.getElementById('message-input');
    const key='wearing-native-draft:v1:'+encodeURIComponent(state.identityId)+':'+payload.id;
    const contextKey=JSON.stringify(composerContext());
    const storageError='草稿暂时无法可靠保存，请保留当前输入后重试。';
    let receipt;
    try{receipt=JSON.parse(localStorage.getItem(key)||'null');}
    catch{notice(storageError,true);return false;}
    if(receipt?.status==='received')return true;
    if(receipt){
      // A pending append must not migrate to another topic or overwrite later edits.
      if(receipt.status!=='pending'||receipt.contextKey!==contextKey||receipt.text!==payload.text||
        typeof receipt.before!=='string'||typeof receipt.after!=='string'||receipt.after.length>12000||
        (input.value!==receipt.before&&input.value!==receipt.after)){
        notice('草稿已经变化，请查看当前输入后再添加。',true);return false;
      }
    }else{
      const after=[input.value,payload.text].filter(Boolean).join('\n');
      if(after.length>12000){notice('输入框里的内容太长，请先处理当前草稿。',true);return false;}
      receipt={status:'pending',contextKey,text:payload.text,before:input.value,after};
      // Journal first: a WebView reload between the two writes can recover exactly once.
      try{localStorage.setItem(key,JSON.stringify(receipt));}
      catch{notice(storageError,true);return false;}
    }
    if(input.value!==receipt.after){input.value=receipt.after;input.dispatchEvent(new Event('input'));}
    dock.classList.add('native-text-open');
    try{
      if(rememberComposer()!==true){notice(storageError,true);return false;}
      localStorage.setItem(key,JSON.stringify({status:'received'}));
    }catch{notice(storageError,true);return false;}
    publishComposer();return true;
  }
  window.WearingHost.openReview=payload=>{
    const targets={files:'open-files',goals:'open-keeps',schedules:'open-keeps'};
    const activity=payload?.target==="activity"&&typeof payload.taskId==="string"&&/^[-a-zA-Z0-9_]{1,64}$/.test(payload.taskId);
    const search=payload?.target==='search';
    const draft=payload?.target==='draft'&&typeof payload.text==='string'&&Boolean(payload.text.trim())&&payload.text.length<=12000;
    if(!payload||!Number.isSafeInteger(payload.id)||(!activity&&!search&&!draft&&!Object.prototype.hasOwnProperty.call(targets,payload.target))||lastReview===payload.id)return;
    if(!composerReady){window.WearingHost.pendingReview=payload;return;}
    if(draft){if(appendDraft(payload))lastReview=payload.id;return;}
    lastReview=payload.id;
    if(search){window.WearingHost.openSearch?.();return;}
    if(activity){const epoch=state.identityEpoch;window.WearingActivity?.openTask(payload.taskId).catch(()=>{if(epoch===state.identityEpoch)notice("暂时打不开这件事，请重新查看进展。",true);});return;}
    document.getElementById(targets[payload.target]).click();
    if(payload.target==='schedules')document.getElementById('schedules-section')?.scrollIntoView({block:'start'});
  };
  document.addEventListener('wearing-composer-ready',()=>{const pending=window.WearingHost.pendingReview;if(pending){window.WearingHost.pendingReview=null;window.WearingHost.openReview(pending);}});
  window.WearingHost.showText=()=>{
    dock.classList.add('native-text-open');
    document.getElementById('message-input').focus();
  };
  window.WearingHost.receiveVoice=payload=>{
    if(!payload||payload.identity!==state.identityId||typeof payload.id!=='string'||!/^voice-[a-f0-9-]{36}$/.test(payload.id)||typeof payload.text!=='string'||!payload.text.trim()||payload.text.length>12000)return;
    // A one-way native delivery can be replayed after page recreation.
    // Persist the draft before its receipt, so a received phrase is never discarded.
    const key='wearing-voice-received:'+payload.identity+':'+payload.id;
    const input=document.getElementById('message-input');
    if(!composerReady){window.WearingHost.pendingVoice=payload;return;}
    let duplicate=received.has(key);try{duplicate=duplicate||Boolean(localStorage.getItem(key));}catch{}
    if(duplicate){if(input.value)dock.classList.add('native-text-open');notice('这段语音已经带入过，请查看输入框或之前的对话。');return;}
    if(input.value.length+payload.text.length+1>12000){notice('当前输入太长，请先发送或保存，再带入这段语音。',true);return;}
    input.value=[input.value,payload.text].filter(Boolean).join('\n');
    input.dispatchEvent(new Event('input'));rememberComposer();
    received.add(key);
    if(!draftStorageWarning){try{localStorage.setItem(key,'1');}catch{}}
    dock.classList.add('native-text-open');
    notice('语音已转成文字，可以修改后发送。');
  };
  document.addEventListener("wearing-composer-ready",()=>{const pending=window.WearingHost.pendingVoice;if(pending){window.WearingHost.pendingVoice=null;window.WearingHost.receiveVoice(pending);}});
})();
