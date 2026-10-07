"use strict";
(() => {
  const el=id=>document.getElementById(id);
  const capture={identity:null,files:[],recording:null,busy:false,caps:null};
  const sourceUrl=id=>`/api/life/assets/${encodeURIComponent(id)}?identity=${encodeURIComponent(state.identityId)}`;
  const disclosureIcon='<svg class="capture-disclosure" viewBox="0 0 24 24" aria-hidden="true"><path d="m9 6 6 6-6 6"/></svg>';
  const stages={queued:"原件已保存，等 Wearing 来整理。",extracting:"原件已保存，Wearing 正在读图片或听录音。",organizing:"Wearing 正在整理这条记录。",done:"Wearing 已整理好，原话与原件仍在这里。",saved:"原话与原件已保存。",failed:"这次没整理好，原话与原件已经保存。",paused:"整理中断了，原话与原件已经保存。",conflict:"你刚刚编辑过，Wearing 把整理结果留在下面，保留了你的修改。"};
  function status(text,error=false){el("capture-input-status").textContent=text;el("capture-input-status").classList.toggle("is-error",error);}
  function remember(){if(!capture.identity)return;try{sessionStorage.setItem("wearing-media-"+capture.identity,JSON.stringify({files:capture.files.filter(f=>f.asset).map(f=>({asset:f.asset,key:f.key})),organize:el("capture-organize").checked}));}catch{}}
  function release(file){if(file.url)URL.revokeObjectURL(file.url);}
  function render(){
    const host=el("capture-files");host.hidden=!capture.files.length;
    host.innerHTML=capture.files.map((file,index)=>{const asset=file.asset,mime=asset?.mime||file.file?.type||"",name=asset?.name||file.file?.name||"原件",url=asset?sourceUrl(asset.id):file.url;
      return `<div class="capture-file">${mime.startsWith("image/")?`<img src="${esc(url)}" alt="${esc(name)}">`:""}<div class="capture-file-copy">${esc(name)}<small>${asset?"原件已保存":file.error?esc(file.error):"正在保存原件…"}</small>${mime.startsWith("audio/")&&url?`<audio controls preload="metadata" src="${esc(url)}"></audio>`:""}</div>${file.error?`<button type="button" class="text-button" data-capture-retry="${index}">重试</button>`:""}<button type="button" class="icon-button" data-capture-remove="${index}" aria-label="移除这份待提交原件：${esc(name)}"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m7 7 10 10M17 7 7 17"/></svg></button></div>`;
    }).join("");
    el("life-capture-text").required=!capture.files.length&&!capture.recording;
    el("capture-organize-label").hidden=!capture.files.length;
    remember();
  }
  function identityChanged(){
    if(capture.identity===state.identityId)return;
    if(capture.recording){capture.recording.discard=true;capture.recording.recorder.stop();}
    remember();capture.files.forEach(release);capture.files=[];capture.identity=state.identityId;
    el("capture-organize").checked=true;
    try{const saved=JSON.parse(sessionStorage.getItem("wearing-media-"+capture.identity)||"[]");capture.files=Array.isArray(saved)?saved:saved.files||[];if(saved.organize===false)el("capture-organize").checked=false;}catch{}
    capture.busy=false;status("");render();
    api("/api/capture/capabilities").then(caps=>capture.caps=caps).catch(()=>{});
  }
  async function upload(file){
    const identity=capture.identity;file.error=null;render();
    try{
      const query=new URLSearchParams({name:file.file.name,request_key:file.key});
      const asset=await api("/api/life/assets?"+query,{method:"POST",headers:{"Content-Type":file.file.type||"application/octet-stream"},body:file.file});
      if(identity!==capture.identity)return;
      file.asset=asset;release(file);file.url=null;file.file=null;status("原件已保存，可以补一句，也可以直接记下。");
    }catch(error){if(!(error instanceof StaleIdentity)&&identity===capture.identity){file.error=error.message;status("原件还没保存成功，文件仍在这里。可以重试。",true);}}
    finally{if(identity===capture.identity)render();}
  }
  function addFiles(files){
    identityChanged();
    for(const file of files){
      if(capture.files.length>=4){status("一次最多放四份原件。",true);break;}
      if(file.size>15*1024*1024){status("这份文件超过 15 MB，请选一份小一点的。",true);continue;}
      const item={file,key:window.WearingIds.uuid(),url:URL.createObjectURL(file),asset:null,error:null};
      capture.files.push(item);item.pending=upload(item);
    }
    render();
  }
  async function prepare(){
    if(capture.recording){const session=capture.recording;session.recorder.stop();await session.stopped;}
    await Promise.all(capture.files.map(file=>file.pending));
  }
  async function submit(record,key){
    if(capture.files.some(file=>!file.asset))throw new Error("原件还没保存完成，请稍等，或重试没有成功的那一份。");
    const result=await api("/api/captures",{method:"POST",body:JSON.stringify({record,asset_ids:capture.files.map(file=>file.asset.id),organize:el("capture-organize").checked,request_key:key})});
    capture.files.forEach(release);capture.files=[];render();status("原件与这条记录已经保存。");
    return result.record;
  }
  async function recordVoice(){
    if(capture.recording){capture.recording.recorder.stop();return;}
    identityChanged();
    if(capture.files.length>=4){status("这一条已有四份原件，可以先记下。",true);return;}
    if(!navigator.mediaDevices?.getUserMedia||!window.MediaRecorder){status("这个浏览器暂不支持录音，可以添加已有录音文件。",true);return;}
    const identity=capture.identity;const button=el("capture-record");button.disabled=true;let stream=null;
    try{
      stream=await navigator.mediaDevices.getUserMedia({audio:true});
      if(identity!==capture.identity){stream.getTracks().forEach(t=>t.stop());return;}
      const mime=["audio/webm;codecs=opus","audio/mp4","audio/ogg;codecs=opus"].find(type=>MediaRecorder.isTypeSupported(type));
      const recorder=new MediaRecorder(stream,mime?{mimeType:mime,audioBitsPerSecond:64000}:undefined);
      const session={recorder,stream,chunks:[],identity,discard:false,started:Date.now()};capture.recording=session;
      session.stopped=new Promise(resolve=>session.resolveStopped=resolve);render();
      const tick=()=>{const seconds=Math.floor((Date.now()-session.started)/1000);status(`正在听你说 · ${Math.floor(seconds/60)}:${String(seconds%60).padStart(2,"0")} · 点“说完了”结束`);};
      session.timer=setInterval(tick,1000);session.limit=setTimeout(()=>recorder.stop(),180000);
      recorder.ondataavailable=event=>{if(event.data.size)session.chunks.push(event.data);};
      recorder.onerror=()=>{session.discard=true;status("录音没有完成，请重新试一次，或添加录音文件。",true);};
      recorder.onstop=()=>{
        clearInterval(session.timer);clearTimeout(session.limit);stream.getTracks().forEach(t=>t.stop());
        if(capture.recording===session)capture.recording=null;
        button.classList.remove("is-recording");el("capture-record-label").textContent="说一句";
        if(session.discard||identity!==capture.identity){render();session.resolveStopped();return;}
        const type=recorder.mimeType.split(";",1)[0],suffix=type.includes("mp4")?"m4a":type.includes("ogg")?"ogg":"webm";
        const blob=new Blob(session.chunks,{type});if(!blob.size){status("没有录到声音，请再试一次。",true);render();session.resolveStopped();return;}
        addFiles([new File([blob],"随口说的-"+new Date().toISOString().slice(0,19).replaceAll(":","-")+"."+suffix,{type})]);
        session.resolveStopped();
      };
      recorder.start(500);button.classList.add("is-recording");el("capture-record-label").textContent="说完了";tick();
    }catch(error){
      stream?.getTracks().forEach(track=>track.stop());
      const session=capture.recording;
      if(session?.stream===stream){clearInterval(session.timer);clearTimeout(session.limit);session.discard=true;capture.recording=null;session.resolveStopped();button.classList.remove("is-recording");el("capture-record-label").textContent="说一句";render();}
      status(error.name==="NotAllowedError"?"没有获得麦克风权限。可以在浏览器中允许，或直接添加录音文件。":"麦克风暂时无法使用，可以添加录音文件。",true);
    }
    finally{button.disabled=false;}
  }
  function renderOriginals(record){
    const host=el("life-originals"),info=record?.capture;host.hidden=!info;if(!info){host.replaceChildren();delete host.dataset.signature;return;}
    const signature=JSON.stringify([record.id,info]);if(host.dataset.signature===signature)return;
    const sameRecord=host.dataset.recordId===record.id,openDetails=sameRecord?[...host.querySelectorAll("details")].map(detail=>detail.open):[];
    host.dataset.signature=signature;host.dataset.recordId=record.id;
    const assets=info.assets.map(asset=>{const url=sourceUrl(asset.id);return `${asset.mime.startsWith("image/")?`<a href="${esc(url)}" target="_blank" rel="noopener"><img class="capture-original-image" src="${esc(url)}" alt="${esc(asset.name)}"></a>`:`<audio class="capture-original-audio" controls preload="metadata" src="${esc(url)}"></audio>`}<a class="capture-original-link" href="${esc(url)}" target="_blank" rel="noopener">${esc(asset.name)}</a>`;}).join("");
    const extracted=info.extracted.map(part=>`<p>${esc(part.kind==="transcript"?"录音转写 · 可对照原录音":"图片文字")}\n${esc(part.text)}</p>`).join("");
    host.innerHTML=`<p class="capture-state ${["failed","paused"].includes(info.state)?"is-error":""}">${esc(stages[info.state]||"原件已保存。")}</p>${info.error?`<p class="life-help">${esc(info.error)}</p>`:""}${["failed","paused"].includes(info.state)?`<button type="button" class="text-button" data-capture-job-retry="${esc(info.id)}">再整理一次</button>`:""}<details><summary>${disclosureIcon}<span>原话与原件</span></summary>${info.original_text?`<p>${esc(info.original_text)}</p>`:""}${assets}${extracted}</details>${info.state==="conflict"&&info.proposal?`<details class="capture-proposal"><summary>${disclosureIcon}<span>看看 Wearing 的整理</span></summary><p><strong>${esc(info.proposal.title)}</strong>\n${esc(info.proposal.content)}</p></details>`:""}`;
    host.querySelectorAll("details").forEach((detail,index)=>detail.open=Boolean(openDetails[index]));
  }
  el("capture-image").addEventListener("click",()=>el("capture-image-file").click());
  el("capture-audio").addEventListener("click",()=>el("capture-audio-file").click());
  for(const id of ["capture-image-file","capture-audio-file"])el(id).addEventListener("change",event=>{addFiles(event.target.files);event.target.value="";});
  el("capture-record").addEventListener("click",recordVoice);
  el("capture-organize").addEventListener("change",remember);
  el("life-capture-text").addEventListener("paste",event=>{const files=[...event.clipboardData.files];if(files.length){event.preventDefault();addFiles(files);}});
  el("capture-files").addEventListener("click",event=>{
    const retry=event.target.closest("[data-capture-retry]");if(retry){const file=capture.files[Number(retry.dataset.captureRetry)];file.pending=upload(file);return;}
    const remove=event.target.closest("[data-capture-remove]");if(remove){release(capture.files.splice(Number(remove.dataset.captureRemove),1)[0]);render();}
  });
  el("life-originals").addEventListener("click",async event=>{
    const button=event.target.closest("[data-capture-job-retry]");if(!button)return;
    button.disabled=true;try{await api("/api/captures/"+button.dataset.captureJobRetry+"/retry",{method:"POST",body:"{}"});window.WearingLife.refresh();}catch(error){if(!(error instanceof StaleIdentity))button.textContent=error.message;}finally{button.disabled=false;}
  });
  window.addEventListener("wearing:window-hidden",()=>{
    if(capture.recording?.recorder.state==="recording")capture.recording.recorder.stop();
  });
  window.WearingCapture={identityChanged,prepare,hasFiles:()=>capture.files.length>0,submit,renderOriginals,stages,viewChanged:view=>{if(view!=="capture"&&capture.recording)capture.recording.recorder.stop();}};
  setInterval(()=>{if(state.token&&capture.identity!==state.identityId)identityChanged();},800);
  window.addEventListener("beforeunload",event=>{if(capture.recording||capture.files.some(file=>!file.asset)){event.preventDefault();event.returnValue="";}});
})();
