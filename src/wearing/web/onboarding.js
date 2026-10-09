"use strict";
/* Pajio 初始偏好（Web/Desktop）：六步点选式首次认识流程。
   对齐 docs/evidence/pajio-core-20261007/onboarding-contract.md 与 App onboarding-model/onboarding-client：
   - 只存点选枚举（roles≤3/apps≤10/interests≤5 + reply_detail/reply_tone 单选可空），无自由文本；
     values 按枚举顺序规范化持久/比较（点击顺序不影响指纹，旧 pending 保留原 key/正文按语义比较）。
   - 草稿（本地 WearingStore）与确认（POST completed）分离；completed 账户重开编辑只存本地。
   - request_key + 精确请求正文必须持久成功后才 POST（set 返回 false 即失败，如实提示，不发请求）；
     未知结果重试原请求；同 key 改意图拒绝双发。
   - 回执严格校验；晚回执必须重读 GET：fresh 低于回执或同版不同内容时不可清 pending（与 App 一致）。
   - 409 保留本机输入，读最新后双选择；以 fresh revision 落新检查点（刷新后不再误报冲突）。
   - 来源只呈现真实现有能力：日历说明在手机 App 连接；飞书按真实状态（撤销中优先于已连接，
     成功分支须 !revocation_pending）；无开发者凭据表单、无假连接、不声称已读取、授权结果手动检查。
   - 注销冻结（WearingDeletion workAllowed/registerWorkGate）期间不写草稿/journal、不 POST；
     账号围栏沿用 WearingStore 作用域前缀清理。epoch+generation 双围栏贯穿所有异步。 */
(() => {
  if (document.documentElement.classList.contains("mobile-host")) return;
  const $ = id => document.getElementById(id);
  const esc = text => String(text ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));

  /* ---------- 模型（与 App onboarding-model.ts 同枚举同上限） ---------- */
  const roleChoices = [["employed","在职工作"],["student","在校学习"],["independent","自由职业"],["business","经营自己的事业"],["caregiver","照顾家庭"]];
  const appChoices = [["wechat","微信"],["douyin","抖音"],["xiaohongshu","小红书"],["bilibili","哔哩哔哩"],["feishu","飞书"],["dingtalk","钉钉"],["wecom","企业微信"],["mail","邮箱"],["calendar","系统日历"],["github","GitHub"]];
  const interestChoices = [["technology","科技与 AI"],["career","工作与成长"],["design","设计与创作"],["reading","阅读"],["travel","旅行"],["food","美食"],["fitness","运动"],["culture","文化与娱乐"],["finance","商业与财经"]];
  const detailChoices = [["brief","简短结论"],["balanced","适量解释"],["detailed","展开说明"]];
  const toneChoices = [["natural","自然"],["warm","温和"],["direct","直接"]];
  const steps = ["见个面","你的日常","常用应用","兴趣与表达","带上资料","确认偏好"];
  const emptyValues = () => ({roles:[],apps:[],interests:[],reply_detail:null,reply_tone:null});
  function toggle(items,item,limit){return items.includes(item)?items.filter(v=>v!==item):items.length<limit?[...items,item]:items;}
  function sample(values){
    const start=values.reply_tone==="warm"?"我们可以一起":values.reply_tone==="direct"?"先":"可以先";
    return start+(values.reply_detail==="brief"?"确认时间，再整理要准备的材料。":values.reply_detail==="detailed"?"核对日程里的时间与地点，再把材料分成“已经有”和“还需要准备”两组，最后逐项检查是否遗漏。":"核对时间与地点，再整理要带的材料，最后检查是否遗漏。");
  }
  const labelFor=(choices,ids)=>choices.filter(c=>ids.includes(c[0])).map(c=>c[1]).join("、")||"暂时跳过";
  // 点选是自述：绝不显示“已授权/已导入/已了解”。idOf 同时即枚举序规范化。
  const idOf=(choices,raw)=>{const allowed=choices.map(c=>c[0]);return Array.isArray(raw)?allowed.filter(id=>raw.includes(id)):[];};
  const singleOf=(choices,raw)=>choices.some(c=>c[0]===raw)?raw:null;
  // 规范化：新请求与一切比较都按枚举序；点击顺序不影响请求指纹（对齐合同 canonical order）。
  const canonicalValues=v=>!v||typeof v!=="object"?emptyValues():{roles:idOf(roleChoices,v.roles),apps:idOf(appChoices,v.apps),interests:idOf(interestChoices,v.interests),reply_detail:singleOf(detailChoices,v.reply_detail),reply_tone:singleOf(toneChoices,v.reply_tone)};
  function validValues(raw){
    if(!raw||typeof raw!=="object"||Array.isArray(raw))throw Object.assign(new Error("偏好回执无法核对，请重新读取。"),{operational:true});
    const values=canonicalValues(raw);
    if(raw.roles&&(values.roles.length!==raw.roles.length||values.roles.length>3)||raw.apps&&(values.apps.length!==raw.apps.length||values.apps.length>10)||raw.interests&&(values.interests.length!==raw.interests.length||values.interests.length>5))throw Object.assign(new Error("偏好回执无法核对，请重新读取。"),{operational:true});
    return values;
  }
  function parseSnapshot(raw){
    const integer=(v,min,max)=>Number.isSafeInteger(v)&&v>=min&&v<=max;
    const stamp=v=>v===null||typeof v==="string"&&Number.isFinite(Date.parse(v));
    if(!raw||typeof raw!=="object"||raw.schema!==1||raw.identity_id!==state.identityId||!integer(raw.revision,0,Number.MAX_SAFE_INTEGER)
      ||!integer(raw.step,0,5)||!["draft","completed","skipped"].includes(raw.status)||raw.source!=="self_selected"
      ||typeof raw.recommend_onboarding!=="boolean"||!stamp(raw.confirmed_at)||!stamp(raw.updated_at)
      ||(raw.status==="completed"&&raw.confirmed_at===null))throw Object.assign(new Error("偏好回执无法核对，请重新读取。"),{operational:true});
    return {schema:1,identity_id:raw.identity_id,revision:raw.revision,status:raw.status,step:raw.step,values:validValues(raw.values),
      source:raw.source,confirmed_at:raw.confirmed_at,updated_at:raw.updated_at,recommend_onboarding:raw.recommend_onboarding};
  }
  const issue=error=>error&&error.status===404?"这台服务还未提供初始偏好设置，可以先进入产品。":error&&(error.status||error.operational)?error.message:"暂时没能保存。选择已留在本机，请重试。";

  /* ---------- 注销冻结门：冻结期间不写草稿/journal、不 POST ---------- */
  const deletionBlocked=()=>window.WearingDeletion?.workAllowed?.()===false;
  const DELETION_NOTICE="这个账户的注销申请已受理，初始偏好操作已停止。";

  /* ---------- 本机草稿与待核对请求（WearingStore，按账户+身份隔离） ---------- */
  const draftKey = () => `onboarding-draft:v1:${state.identityId}`;
  const pendingKey = () => `onboarding-request:v1:${state.identityId}`;
  const readJournal = name => {try{const row=JSON.parse(window.WearingStore.get(name)||"null");return row&&row.identity===state.identityId?row:null;}catch{return null;}};
  // 持久结果必须核实：set 返回 false 视为失败，调用方据此决定是否发请求。
  function writeJournal(name,row){
    try{
      if(row===null){window.WearingStore.remove(name);return true;}
      return window.WearingStore.set(name,JSON.stringify(row))===true;
    }catch{return false;}
  }

  // generation=面板会话围栏（仅 reset/注销冻结作废）；load/save/feishu 各持独立票据，
  // 只读来源查询不得作废业务保存（否则 save 的 finally 永不清 busy，确认按钮永久禁用）。
  const ui={epoch:-1,generation:0,loadTicket:0,saveTicket:0,feishuTicket:0,open:false,saved:false,snapshot:null,values:emptyValues(),step:0,loading:true,busy:false,pending:null,conflict:false,localConflict:false,error:"",branch:null,feishu:null,feishuBusy:false,feishuChecked:false};
  let offeredFor="";
  // 冻结时停掉在途工作：作废会话围栏（所有票据随之失效）并解锁。
  window.WearingDeletion?.registerWorkGate?.({stop(){ui.generation++;ui.busy=false;ui.feishuBusy=false;}});

  /* ---------- 读取：服务端快照 + 本机草稿/待核对（journal 形如 {identity,body}） ---------- */
  async function load(){
    const epoch=state.identityEpoch,generation=ui.generation,ticket=++ui.loadTicket;
    const current=()=>epoch===state.identityEpoch&&generation===ui.generation&&ticket===ui.loadTicket;
    ui.epoch=epoch;ui.loading=true;ui.error="";ui.branch=null;paint();
    try{
      const fresh=parseSnapshot(await api("/api/onboarding"));
      const pendingRow=readJournal(pendingKey()),draft=readJournal(draftKey());
      if(!current())return;
      // 待核对 journal 的正文在 body 字段：结构不符时不采用（不猜）。
      const pending=pendingRow&&pendingRow.body&&typeof pendingRow.body==="object"?pendingRow.body:null;
      ui.snapshot=fresh;ui.pending=pending;ui.conflict=false;
      const saved=pending||draft;
      ui.localConflict=!pending&&!!draft&&draft.revision!==fresh.revision;
      ui.values=saved?saved.values:fresh.values;
      ui.step=saved?saved.step:(fresh.status==="completed"?5:fresh.step);
    }catch(error){if(current())ui.error=issue(error);}
    finally{if(current()){ui.loading=false;paint();}}
  }
  function retain(nextValues,nextStep){
    if(!ui.snapshot||deletionBlocked())return;
    writeJournal(draftKey(),{identity:state.identityId,version:1,revision:ui.snapshot.revision,step:nextStep,values:canonicalValues(nextValues)});
  }
  function choose(next){if(ui.busy||ui.pending||ui.loading||ui.localConflict||deletionBlocked())return;ui.values=canonicalValues(next);ui.error="";retain(next,ui.step);paint();}
  function go(next){if(ui.busy||ui.pending||ui.loading||ui.localConflict||deletionBlocked())return;ui.step=next;ui.error="";retain(ui.values,next);paint();}

  /* ---------- 保存：CAS + 持久回执 + 晚回执重读 ---------- */
  async function save(status,nextStep,retry=false){
    if(!ui.snapshot||ui.busy)return;
    // 已确认画像的编辑保持本地：翻页不 POST，最后一次确认才提交 completed。
    if(status==="draft"&&ui.snapshot.status!=="draft"&&!retry){go(nextStep);return;}
    if(deletionBlocked()){ui.error=DELETION_NOTICE;paint();return;}
    const epoch=state.identityEpoch,generation=ui.generation,ticket=++ui.saveTicket;
    const current=()=>epoch===state.identityEpoch&&generation===ui.generation&&ticket===ui.saveTicket;
    ui.busy=true;ui.error="";ui.conflict=false;paint();
    try{
      let body;
      if(retry){
        body=ui.pending;
        if(!body)throw Object.assign(new Error("没有等待保存的选择。"),{operational:true});
      }else{
        const request={revision:ui.snapshot.revision,request_key:window.WearingIds.uuid().replaceAll("-",""),status,step:nextStep,values:canonicalValues(status==="skipped"?emptyValues():ui.values)};
        if(ui.pending){
          // 同意图按语义（规范化 values + revision/status/step）判断；旧 pending 保留原 key/正文原样重试。
          const same=ui.pending.revision===request.revision&&ui.pending.status===request.status&&ui.pending.step===request.step
            &&JSON.stringify(canonicalValues(ui.pending.values))===JSON.stringify(request.values);
          if(same)body=ui.pending;
          else throw Object.assign(new Error("请先重试上一次保存。"),{operational:true});
        }else{
          // 正文必须先持久成功再发请求；持久失败时如实说明且绝不声称“已留本机”。
          if(!writeJournal(pendingKey(),{identity:state.identityId,body:request}))
            throw Object.assign(new Error("本机暂时没能保留这次保存，没有发出请求。请稍后再试。"),{operational:true});
          body=request;
        }
      }
      const raw=await api("/api/onboarding",{method:"POST",body:JSON.stringify(body)});
      if(!current())return;
      const receipt=parseSnapshot(raw);
      if(raw.request_key!==body.request_key||receipt.revision!==body.revision+1||receipt.status!==body.status||receipt.step!==body.step
        ||JSON.stringify(receipt.values)!==JSON.stringify(canonicalValues(body.values)))throw Object.assign(new Error("保存回执还没核对，请重试同一次保存。"),{operational:true});
      // 晚回执：旧成功回执可能早于现状，重读当前；fresh 低于回执或同版不同内容时不可清 pending。
      const fresh=parseSnapshot(await api("/api/onboarding"));
      if(!current())return;
      if(fresh.revision<receipt.revision||(fresh.revision===receipt.revision&&(fresh.status!==receipt.status||fresh.step!==receipt.step||JSON.stringify(fresh.values)!==JSON.stringify(receipt.values))))
        throw Object.assign(new Error("最新偏好还没有核对，请重试同一次保存。"),{operational:true});
      const latest=fresh.revision>receipt.revision?fresh:receipt;
      ui.snapshot=latest;ui.values=latest.values;ui.step=latest.status==="completed"?5:latest.step;ui.pending=null;
      writeJournal(draftKey(),latest.status==="draft"?{identity:state.identityId,version:1,revision:latest.revision,step:latest.step,values:latest.values}:null);
      writeJournal(pendingKey(),null);
      if(latest.status==="completed"||latest.status==="skipped"){
        ui.saved=true;
        closePanel("onboarding-panel");ui.open=false;
        notice(latest.status==="completed"?"初始偏好已保存。会帮助 Pajio 理解你的日常，可随时在设置里修改。":"已先进入产品；之后可以在设置里补初始偏好。");
        window.WearingLife?.openView?.("today");
      }else paint();
    }catch(error){
      if(current()){
        if(error.status===409){ui.conflict=true;ui.error=error.message||"偏好已在另一处更新。请读取最新版本后核对。";}
        else ui.error=issue(error);
        const pendingRow=readJournal(pendingKey());
        ui.pending=pendingRow&&pendingRow.body?pendingRow.body:null;
      }
    }finally{
      if(current()){ui.busy=false;paint();}
    }
  }
  async function resolve(useSaved){
    if(ui.busy)return;
    if(deletionBlocked()){ui.error=DELETION_NOTICE;paint();return;}
    const epoch=state.identityEpoch,generation=ui.generation,ticket=++ui.saveTicket;
    const current=()=>epoch===state.identityEpoch&&generation===ui.generation&&ticket===ui.saveTicket;
    ui.busy=true;ui.error="";paint();
    try{
      const fresh=parseSnapshot(await api("/api/onboarding"));
      if(!current())return;
      if(ui.conflict){
        const pending=ui.pending;
        // 只有确定读到更新的版本才允许废弃同 key 的原请求。
        if(pending&&fresh.revision<=pending.revision)throw Object.assign(new Error("还没读到较新的版本，请保留原选择并重试。"),{operational:true});
        writeJournal(pendingKey(),null);ui.pending=null;
      }
      const next=useSaved?fresh.values:ui.values;
      const nextStep=useSaved?(fresh.status==="completed"?5:fresh.step):ui.step;
      // 先把快照换成 fresh，再以 fresh 的 revision 落草稿检查点：刷新后不会用旧 revision 再次误报冲突。
      ui.snapshot=fresh;ui.values=next;ui.step=nextStep;ui.localConflict=false;ui.conflict=false;ui.error="";
      retain(next,nextStep);
    }catch(error){if(current())ui.error=issue(error);}
    finally{if(current()){ui.busy=false;paint();}}
  }
  function close(){
    if(ui.loading){closePanel("onboarding-panel");ui.open=false;return;}
    if(ui.snapshot&&!ui.pending&&!ui.saved)retain(ui.values,ui.step);
    closePanel("onboarding-panel");ui.open=false;
  }

  /* ---------- 来源分支：只读真实状态，不模拟权限；撤销中优先于已连接 ---------- */
  const feishuStates={not_configured:"未配置",configured:"已配置应用，待授权",authorizing:"等待你在飞书完成授权",authorization_expired:"授权入口已过期",connected:"已连接",expired:"授权已过期"};
  const officialFeishuUrl=url=>/^https:\/\/([a-z0-9-]+\.)*feishu\.cn\//i.test(String(url));
  async function loadFeishu(){
    const epoch=state.identityEpoch,generation=ui.generation,ticket=++ui.feishuTicket;
    const current=()=>epoch===state.identityEpoch&&generation===ui.generation&&ticket===ui.feishuTicket;
    ui.feishuBusy=true;paint();
    try{
      const data=await api("/api/cloud-apps/feishu");
      if(!current())return;
      if(!feishuStates[data?.state]||typeof data.configured!=="boolean"||typeof data.revocation_pending!=="boolean"){ui.feishu=null;ui.error="暂时无法读取飞书连接，可以稍后再来。";}
      else ui.feishu=data;
    }catch{if(current())ui.error="暂时无法读取飞书连接，可以稍后再来。";}
    finally{if(current()){ui.feishuBusy=false;paint();}}
  }
  async function feishuAuthorize(){
    const revision=ui.feishu?.revision;
    // 撤销中（含 connected+revocation_pending）不提供新授权入口。
    if(!ui.feishu?.configured||!revision||ui.feishu.revocation_pending||ui.busy||deletionBlocked())return;
    const epoch=state.identityEpoch,generation=ui.generation,ticket=++ui.saveTicket;
    const current=()=>epoch===state.identityEpoch&&generation===ui.generation&&ticket===ui.saveTicket;
    ui.busy=true;ui.error="";paint();
    try{
      const next=await api("/api/cloud-apps/feishu/authorize",{method:"POST",body:JSON.stringify({revision})});
      if(!current())return;
      if(feishuStates[next?.state]){ui.feishu=next;if(next.authorization&&officialFeishuUrl(next.authorization.url))window.open(next.authorization.url,"_blank","noopener");}
      else ui.error="授权尚未完成，请重试或稍后设置。";
    }catch{if(current())ui.error="授权尚未完成，请重试或稍后设置。";}
    finally{if(current()){ui.busy=false;paint();}}
  }
  async function feishuPoll(){
    const id=ui.feishu?.authorization?.id;
    if(!id||ui.busy||deletionBlocked())return;
    const epoch=state.identityEpoch,generation=ui.generation,ticket=++ui.saveTicket;
    const current=()=>epoch===state.identityEpoch&&generation===ui.generation&&ticket===ui.saveTicket;
    ui.busy=true;ui.error="";paint();
    try{
      const next=await api("/api/cloud-apps/feishu/poll",{method:"POST",body:JSON.stringify({authorization_id:id})});
      if(!current())return;
      if(feishuStates[next?.state])ui.feishu=next;else ui.error="还没能确认授权结果，请重试。";
    }catch{if(current())ui.error="还没能确认授权结果，请重试。";}
    finally{if(current()){ui.busy=false;paint();}}
  }

  /* ---------- 渲染 ---------- */
  const disabled=()=>ui.busy||!!ui.pending||ui.loading||ui.localConflict;
  function feishuSummaryText(){
    const s=ui.feishu;
    return !s?"正在核对连接状态…":s.revocation_pending?"原授权正在撤销，暂不可用":s.state==="connected"?"已授权，本次未读取正文":s.authorization?"授权尚待完成":s.state==="not_configured"?"服务尚未准备好授权":"尚未连接";
  }
  function paint(){
    const panel=$("onboarding-panel");if(!panel||!ui.open)return;
    const back=$("ob-back");
    if(back){back.textContent=ui.step?"上一步":"退出初始设置";back.hidden=!ui.snapshot||ui.loading;}
    $("ob-progress").innerHTML=steps.map((_,index)=>`<i class="ob-tick${index<=ui.step?" on":""}"></i>`).join("");
    $("ob-progress").setAttribute("aria-label",`初始设置，第 ${ui.step+1} 步，共 6 步`);
    $("ob-body").innerHTML=ui.loading?'<div class="ob-loading"><p>正在读取你的设置</p></div>'
      :!ui.snapshot?`<div class="ob-card"><h3>稍后再认识，也可以。</h3><p class="ob-copy">${esc(ui.error||"暂时读不到初始偏好。")}</p><div class="brief-actions"><button class="secondary" type="button" data-ob-reload>重新读取</button><button class="text-button" type="button" data-ob-close>先进入产品</button></div></div>`
      :`${ui.branch?branchMarkup():stepMarkup()}${conflictMarkup()}${pendingMarkup()}${ui.error?`<p class="ob-error" role="alert">${esc(ui.error)}</p>`:""}`;
    $("ob-footer").innerHTML=!ui.snapshot||ui.loading||ui.branch?"":footMarkup();
    // 确认页选中飞书时核对一次真实来源状态（进入其它步骤不重复读）。
    if(ui.snapshot&&!ui.loading&&ui.step===5&&ui.values.apps.includes("feishu")&&!ui.feishuChecked&&!ui.branch){ui.feishuChecked=true;loadFeishu();}
  }
  // 单选（reply_detail/reply_tone）不受多选上限约束：可直接换选（App radio 同语义）。
  const choiceRow=([id,label],selected,limit,field,chip=false)=>`<button type="button" class="ob-choice${chip?" chip":""}${selected?" on":""}" data-ob-choice="${field}:${esc(id)}" aria-pressed="${selected?"true":"false"}"${disabled()||limit&&!selected&&(ui.values[field]?.length||0)>=limit?" disabled":""}><span>${esc(label)}</span></button>`;
  function stepMarkup(){
    const s=ui.step,v=ui.values;
    if(s===0)return `<section class="ob-step">
      <p class="ob-eyebrow">${steps[0]} · 1 / 6</p>
      <div class="ob-hero" aria-hidden="true">${window.WearingPajio?.bearMarkup?.(undefined,140)||""}</div>
      <h3 class="ob-title">你好，我是 Pajio。</h3><p class="ob-lead">点几下，让我更懂你的日常。<br>不必先想好，要交给我什么。</p>
      <div class="ob-card"><p class="ob-label">你可以这样用我</p>
        <div class="ob-example"><div class="ob-words"><p class="ob-option">把安排放在一起</p><p class="ob-copy">连接你选择的日历，在「今天」查看。</p></div></div>
        <div class="ob-example"><div class="ob-words"><p class="ob-option">读懂你交给我的资料</p><p class="ob-copy">分享链接或文件，需要时帮你整理。</p></div></div>
        <p class="ob-caption">能力示例 · 现在还没有读取你的资料</p></div></section>`;
    if(s===1)return `<section class="ob-step"><p class="ob-eyebrow">${steps[1]} · 2 / 6</p>
      <h3 class="ob-title">你的日常里，有哪些角色？</h3><p class="ob-lead">可以同时选几个，也可以暂时跳过。最多 3 项。</p>
      <div class="ob-stack">${roleChoices.map(c=>choiceRow(c,v.roles.includes(c[0]),3,"roles")).join("")}</div>
      <p class="ob-caption">这些是你当前的选择，之后随时能改。不据此推断收入、人格、作息或权限。</p></section>`;
    if(s===2)return `<section class="ob-step"><p class="ob-eyebrow">${steps[2]} · 3 / 6</p>
      <h3 class="ob-title">平时常用哪些应用？</h3><p class="ob-lead">选熟悉的就好，用来推荐合适的资料入口。</p>
      <div class="ob-grid">${appChoices.map(c=>choiceRow(c,v.apps.includes(c[0]),10,"apps",true)).join("")}</div>
      <p class="ob-caption">点选不会登录应用，也不会读取聊天、浏览或收藏历史。</p></section>`;
    if(s===3)return `<section class="ob-step"><p class="ob-eyebrow">${steps[3]} · 4 / 6</p>
      <h3 class="ob-title">什么值得多看一眼？</h3><p class="ob-lead">选几个愿意了解的话题，最多 5 项。</p>
      <div class="ob-chips">${interestChoices.map(c=>choiceRow(c,v.interests.includes(c[0]),5,"interests",true)).join("")}</div>
      <div class="ob-card"><p class="ob-label">回答长一点，还是短一点？</p>
        <div class="ob-chips">${detailChoices.map(c=>choiceRow(c,v.reply_detail===c[0],0,"reply_detail",true)).join("")}</div>
        <p class="ob-label">更喜欢怎样的语气？</p>
        <div class="ob-chips">${toneChoices.map(c=>choiceRow(c,v.reply_tone===c[0],0,"reply_tone",true)).join("")}</div>
        <p class="ob-caption">表达示例 · 未选择时使用默认</p><p class="ob-sample">${esc(sample(v))}</p></div></section>`;
    if(s===4)return `<section class="ob-step"><p class="ob-eyebrow">${steps[4]} · 5 / 6</p>
      <h3 class="ob-title">带上现成资料，少一些反复说明。</h3>
      <p class="ob-copy">有现成的安排，可以少解释一些。每一项都由你决定，暂时不连接也可以继续。</p>
      <div class="ob-card"><p class="ob-option">日历与提醒事项</p><p class="ob-copy">由你选择要同步的列表，让安排出现在「今天」。网页端不读取系统日历；请在手机 App 中连接。</p></div>
      ${v.apps.includes("feishu")?`<button type="button" class="ob-choice ob-source-row" data-ob-branch="feishu"><span><strong>飞书</strong><small>查看当前服务是否已准备好资料与日历授权。</small></span></button>`:""}
      <p class="ob-copy">微信、抖音和小红书的历史不会因为选择了应用而被读取。之后可以把需要处理的链接或截图分享给 Pajio。</p></section>`;
    return `<section class="ob-step"><p class="ob-eyebrow">${steps[5]} · 6 / 6</p>
      <h3 class="ob-title">先这样认识你。</h3><p class="ob-copy">只记下你选的内容，随时可以调整。</p>
      <div class="ob-card">
        ${summaryRow("日常角色",labelFor(roleChoices,v.roles),1)}
        ${summaryRow("常用应用",labelFor(appChoices,v.apps),2)}
        ${summaryRow("关注的话题",labelFor(interestChoices,v.interests),3)}
        ${summaryRow("回答方式",[...detailChoices.filter(c=>c[0]===v.reply_detail).map(c=>c[1]),...toneChoices.filter(c=>c[0]===v.reply_tone).map(c=>c[1])].join(" · ")||"默认长度 · 默认语气",3)}
        ${summaryRow("资料连接","查看或调整来源",4)}
        <p class="ob-copy">日历与提醒事项 · 在手机 App 中连接</p>
        ${v.apps.includes("feishu")?`<p class="ob-copy">飞书 · ${esc(feishuSummaryText())}</p>`:""}
      </div>
      <p class="ob-copy">确认后，这些初始偏好会帮助 Pajio 理解你的日常、调整回答和简报关注。选择常用应用不代表已连接，资料是否可用以授权页为准。</p>
      <p class="ob-caption">不会因为完成引导而自动执行任务或开启通知。你可以在「设置 → 初始偏好」修改。</p></section>`;
  }
  const summaryRow=(label,value,editStep)=>`<div class="ob-summary"><div><p class="ob-caption">${esc(label)}</p><p class="ob-option">${esc(value)}</p></div><button class="text-button" type="button" data-ob-goto="${editStep}"${disabled()?" disabled":""}>修改</button></div>`;
  function branchMarkup(){
    if(ui.branch!=="feishu")return "";
    const s=ui.feishu;
    // 撤销中优先：connected+revocation_pending 不显示“已授权/已建立”，也不提供新授权入口。
    const revoking=!!s?.revocation_pending;
    return `<section class="ob-step"><button class="text-button" type="button" data-ob-branch-back>← 返回资料选择</button>
      <h3 class="ob-title">飞书资料与日程</h3>
      ${ui.feishuBusy?"<p class=\"ob-copy\">正在读取连接状态…</p>":""}
      ${!s?"":`
        <p class="ob-copy">${revoking?"原授权正在撤销，请完成后再连接。你可以直接继续引导，之后在设置中处理。":s.state==="connected"?"已授权。可访问的范围以飞书权限为准，完成引导不会自动读取文档。":s.configured?"允许 Pajio 访问你授权范围内的飞书资料。请先在授权页核对权限。":"这个服务尚未准备好飞书授权。你可以直接继续，之后在设置中连接。"}</p>
        ${s.authorization&&!revoking?`<p class="ob-copy">需要时使用确认码：${esc(s.authorization.user_code)}</p>
          <div class="brief-actions">${officialFeishuUrl(s.authorization.url)?`<a class="secondary" href="${esc(s.authorization.url)}" target="_blank" rel="noopener noreferrer">打开飞书授权页</a>`:""}<button class="text-button" type="button" data-ob-feishu-poll${ui.busy?" disabled":""}>我已授权，检查结果</button></div>`
          :!revoking&&s.configured&&s.state!=="connected"?`<button class="secondary" type="button" data-ob-feishu-authorize${ui.busy?" disabled":""}>前往飞书授权</button>`:""}
        ${!revoking&&s.state==="connected"?'<p class="ob-ok">飞书连接已建立 · 本次未读取正文</p>':""}`}
    </section>`;
  }
  const conflictMarkup=()=>(ui.conflict||ui.localConflict)&&ui.snapshot?`<div class="ob-problem"><p class="ob-copy">另一处保存了更新的偏好。你的本机选择仍保留，请选择以哪份继续核对。</p>
    <div class="brief-actions"><button class="secondary" type="button" data-ob-resolve="local"${ui.busy?" disabled":""}>保留本机选择，重新核对</button><button class="secondary" type="button" data-ob-resolve="saved"${ui.busy?" disabled":""}>使用已保存的最新偏好</button></div></div>`:"";
  const pendingMarkup=()=>ui.pending&&!ui.conflict&&ui.snapshot?`<div class="ob-problem"><p class="ob-copy">上一次保存还没有确认，先取回结果再继续。你的选择已保留。</p>
    <button class="secondary" type="button" data-ob-retry${ui.busy?" disabled":""}>重试同一次保存</button></div>`:"";
  function footMarkup(){
    if(!ui.snapshot)return "";
    const emptyHere=ui.step===1?!ui.values.roles.length:ui.step===2?!ui.values.apps.length:ui.step===3?!(ui.values.interests.length||ui.values.reply_detail||ui.values.reply_tone):false;
    const primary=`<button class="primary" type="button" data-ob-primary${disabled()?" disabled":""}>${ui.step===0?"开始认识":ui.step===5?"确认并进入 Pajio":"继续"}</button>`;
    const skip=ui.step===0&&ui.snapshot.status==="draft"
      ?`<button class="text-button" type="button" data-ob-skip${disabled()?" disabled":""}>先进去看看</button>`
      :ui.step>0&&ui.step<4&&emptyHere?`<button class="text-button" type="button" data-ob-skip-step${disabled()?" disabled":""}>这一项暂时不补充</button>`
      :'<p class="ob-caption">当前身份的选择 · 可随时返回修改</p>';
    return primary+skip;
  }

  /* ---------- 事件 ---------- */
  const panel=document.getElementById("onboarding-panel");
  panel.addEventListener("click",event=>{
    const choice=event.target.closest("[data-ob-choice]");
    if(choice){
      const [field,id]=choice.dataset.obChoice.split(":");
      if(field==="reply_detail")choose({...ui.values,reply_detail:ui.values.reply_detail===id?null:id});
      else if(field==="reply_tone")choose({...ui.values,reply_tone:ui.values.reply_tone===id?null:id});
      else choose({...ui.values,[field]:toggle(ui.values[field],id,{roles:3,apps:10,interests:5}[field])});
      return;
    }
    if(event.target.closest("[data-ob-primary]")){save(ui.step===5?"completed":"draft",Math.min(5,ui.step+1));return;}
    if(event.target.closest("[data-ob-skip]")){save("skipped",0);return;}
    if(event.target.closest("[data-ob-skip-step]")){save("draft",ui.step+1);return;}
    if(event.target.closest("[data-ob-retry]")){save("draft",ui.step,true);return;}
    const resolveBtn=event.target.closest("[data-ob-resolve]");
    if(resolveBtn){resolve(resolveBtn.dataset.obResolve==="saved");return;}
    const goto=event.target.closest("[data-ob-goto]");
    if(goto){go(Number(goto.dataset.obGoto));return;}
    if(event.target.closest("[data-ob-back]")){if(ui.step>0&&!ui.pending&&!ui.localConflict)go(ui.step-1);else close();return;}
    if(event.target.closest("[data-ob-close]")||event.target.closest("[data-ob-close-btn]")){close();return;}
    if(event.target.closest("[data-ob-reload]")){load();return;}
    const branch=event.target.closest("[data-ob-branch]");
    if(branch){ui.branch=branch.dataset.obBranch;ui.error="";loadFeishu();return;}
    if(event.target.closest("[data-ob-branch-back]")){ui.branch=null;ui.error="";paint();return;}
    if(event.target.closest("[data-ob-feishu-authorize]")){feishuAuthorize();return;}
    if(event.target.closest("[data-ob-feishu-poll]")){feishuPoll();return;}
  });
  panel.addEventListener("close",()=>{ui.open=false;if(ui.snapshot&&!ui.pending&&!ui.saved)retain(ui.values,ui.step);},{once:false});
  document.addEventListener("click",event=>{
    if(event.target.closest("#onboarding-entry")){
      // 面板交接：从设置进入引导时关闭父设置面板——完成（进入今天）或退出（稍后继续）
      // 都不再叠加两个模态，落在合理页面上。
      const settings=$("settings-panel");
      if(settings?.open)closePanel("settings-panel");
      open();return;
    }
  });

  function open(){
    ui.open=true;ui.saved=false;ui.branch=null;ui.feishu=null;ui.feishuChecked=false;
    openPanel("onboarding-panel");
    load();
  }
  /* 只在普通聊天且无明确恢复意图时按服务端 recommend_onboarding 自动展示一次：
     ?view= / life_record / activity_task 等入口先完成恢复，不被引导覆盖；
     已有面板打开、非聊天视图、读取失败均不弹（设置入口常在）。 */
  async function maybeOffer(){
    if(!state.connected)return;
    const key=state.identityId+":"+state.identityEpoch;
    if(offeredFor===key)return;offeredFor=key;
    try{
      const params=new URLSearchParams(location.search);
      if(params.get("view")||params.get("life_record")||params.get("activity_task"))return;
      if(document.body.classList.contains("life-mode"))return;
      if(document.querySelector("dialog[open]"))return;
      const epoch=state.identityEpoch;
      const snap=parseSnapshot(await api("/api/onboarding"));
      if(epoch!==state.identityEpoch||document.body.classList.contains("life-mode")||document.querySelector("dialog[open]"))return;
      if(snap.recommend_onboarding&&snap.status==="draft")open();
    }catch{/* 读不到就不推荐，设置入口仍在 */}
  }
  function reset(){ui.generation++;ui.loadTicket++;ui.saveTicket++;ui.feishuTicket++;ui.epoch=-1;ui.open=false;offeredFor="";ui.feishu=null;ui.branch=null;ui.snapshot=null;ui.loading=true;ui.values=emptyValues();ui.step=0;ui.pending=null;ui.conflict=false;ui.localConflict=false;ui.error="";ui.busy=false;ui.feishuBusy=false;ui.feishuChecked=false;ui.saved=false;}

  window.WearingOnboarding={open,maybeOffer,reset,
    // 供行为测试使用的小入口（不参与渲染）。
    _test:{choose,go,save,resolve,close,load,loadFeishu,ui,toggle,sample,labelFor,parseSnapshot,emptyValues,canonicalValues,draftKey,pendingKey,paint,feishuSummaryText,deletionBlocked}};
})();
