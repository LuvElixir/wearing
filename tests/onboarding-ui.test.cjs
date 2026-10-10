"use strict";
// 第二十二轮：onboarding-contract Web 侧检查（含独立复核 1+4+5 项修复的行为回归）。
const {test} = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const vm = require("node:vm");

const onboarding = fs.readFileSync("src/wearing/web/onboarding.js", "utf8");
const app = fs.readFileSync("src/wearing/web/app.js", "utf8");
const html = fs.readFileSync("src/wearing/web/index.html", "utf8");

test("onboarding.js and app.js compile (syntax gate)", () => {
  new vm.Script(onboarding);
  new vm.Script(app);
});

test("contract wiring: journals, completed-edit guard, skip empty, receipt verify, late receipt", () => {
  assert.match(onboarding, /classList\.contains\("mobile-host"\)\) return;/);
  assert.match(onboarding, /onboarding-draft:v1/);
  assert.match(onboarding, /onboarding-request:v1/);
  assert.match(onboarding, /if\(status==="draft"&&ui\.snapshot\.status!=="draft"&&!retry\)\{go\(nextStep\);return;\}/);
  assert.match(onboarding, /values:canonicalValues\(status==="skipped"\?emptyValues\(\):ui\.values\)/);
  assert.match(onboarding, /receipt\.revision!==body\.revision\+1/);
  assert.match(onboarding, /raw\.request_key!==body\.request_key/);
  assert.match(onboarding, /保留本机选择，重新核对/);
  assert.match(onboarding, /使用已保存的最新偏好/);
  assert.match(onboarding, /还没读到较新的版本，请保留原选择并重试。/);
  assert.match(onboarding, /请先重试上一次保存。/);
  assert.match(onboarding, /重试同一次保存/);
  // C5：规范化持久与语义比较；旧 pending 原样保留。
  assert.match(onboarding, /const canonicalValues=/);
  assert.match(onboarding, /JSON\.stringify\(canonicalValues\(ui\.pending\.values\)\)===JSON\.stringify\(request\.values\)/);
  // B2：journal 必须持久成功才发请求。
  assert.match(onboarding, /window\.WearingStore\.set\(name,JSON\.stringify\(row\)\)===true/);
  assert.match(onboarding, /本机暂时没能保留这次保存，没有发出请求。/);
  // C9：晚回执 fresh 落后或同版不同内容不可清 pending。
  assert.match(onboarding, /fresh\.revision<receipt\.revision\|\|\(fresh\.revision===receipt\.revision&&/);
  assert.match(onboarding, /最新偏好还没有核对，请重试同一次保存。/);
  // C7：注销冻结门 + 工作门。
  assert.match(onboarding, /WearingDeletion\?\.workAllowed\?\.\(\)===false/);
  assert.match(onboarding, /registerWorkGate\?\.\(\{stop\(\)/);
  // B4：单选不受多选上限约束。
  assert.match(onboarding, /disabled\(\)\|\|limit&&!selected&&/);
  // C6：入口恢复优先。
  assert.match(onboarding, /params\.get\("view"\)\|\|params\.get\("life_record"\)\|\|params\.get\("activity_task"\)/);
});

test("sources stay honest: no App Secret form, no fake connected, revoking wins over connected", () => {
  assert.ok(!onboarding.includes("App Secret") && !onboarding.includes("app-secret"));
  assert.match(onboarding, /这个服务尚未准备好飞书授权。你可以直接继续，之后在设置中连接。/);
  assert.match(onboarding, /飞书连接已建立 · 本次未读取正文/);
  assert.match(onboarding, /点选不会登录应用，也不会读取聊天、浏览或收藏历史。/);
  assert.match(onboarding, /网页端不读取系统日历；请在手机 App 中连接。/);
  assert.match(onboarding, /officialFeishuUrl/);
  // A1：撤销中优先；成功分支必须 !revocation_pending。
  assert.match(onboarding, /s\.revocation_pending\?"原授权正在撤销，暂不可用"/);
  assert.match(onboarding, /!revoking&&s\.state==="connected"/);
  assert.match(onboarding, /!revoking&&s\.configured&&s\.state!=="connected"/);
  assert.doesNotMatch(onboarding, /onclick=|style="/);
});

test("app.js hooks fire after entry recovery; index.html wiring in place", () => {
  const loadStatusBody = app.slice(app.indexOf("async function loadStatus"), app.indexOf("async function loadRuntime"));
  assert.ok(!loadStatusBody.includes("maybeOffer"), "loadStatus must not trigger onboarding before entry recovery");
  assert.match(app, /if\(activityTask\)await window\.WearingActivity\?\.openTask\(activityTask\);window\.WearingOnboarding\?\.maybeOffer\(\);/);
  assert.match(app, /await loadComputer\(\);window\.WearingOnboarding\?\.maybeOffer\(\);/);
  assert.match(app, /window\.WearingOnboarding\?\.reset\(\);/);
  assert.match(html, /onboarding\.js\?v=7/);
  assert.match(html, /id="onboarding-panel"/);
  assert.match(html, /id="onboarding-entry"/);
  assert.match(html, /app\.js\?v=59/);
  assert.match(html, /pajio\.css\?v=22/);
  // 幽灵面板回归：作者样式不得覆盖 UA 的 dialog:not([open]) display:none。
  assert.match(fs.readFileSync("src/wearing/web/pajio.css","utf8"), /\.ob-panel\[open\]\{width:min\(640px/);
  assert.doesNotMatch(fs.readFileSync("src/wearing/web/pajio.css","utf8"), /\.ob-panel\{[^}]*display:flex/);
  assert.match(html, /id="ob-back" data-ob-back/);
});

/* ---------- 行为 harness ---------- */
function harness({get, post, failSet=false, search="", lifeMode=false, deletion=null, hangPost=false}){
  const store={};
  const elements={};
  const element=id=>elements[id]||(elements[id]={id,innerHTML:"",textContent:"",hidden:false,dataset:{},listeners:{},
    addEventListener(type,fn){(this.listeners[type]=this.listeners[type]||[]).push(fn);},
    setAttribute(){},close(){}});
  const calls=[];
  let releasePost=null;
  const api=async(path,options={})=>{
    const record={path,method:options.method||"GET",body:options.body,storePendingAtCall:store["onboarding-request:v1:qa"]||null};
    calls.push(record);
    if(options.method&&options.method!=="GET"){
      if(hangPost)return new Promise(resolve=>{releasePost=()=>resolve(post(path,options.body,record));});
      return post(path,options.body,record);
    }
    return get(path,record);
  };
  const opened=[];
  const context={
    window:{},location:{search},
    URLSearchParams,
    document:{
      documentElement:{classList:{contains:()=>false}},
      getElementById:element,querySelector:()=>null,
      addEventListener(type,fn){(element("document").listeners[type]=element("document").listeners[type]||[]).push(fn);},
      body:{classList:{contains:()=>lifeMode}},
    },
    state:{identityId:"qa",identityEpoch:1,connected:true},
    api,notice(){},
    openPanel(id){opened.push(id);const el=elements[id];if(el)el.open=true;},
    closePanel(id){opened.push("close:"+id);const el=elements[id];if(el)el.open=false;},
    setTimeout,clearTimeout,Date,JSON,Number,Array,Object,String,Boolean,Math,Error,Promise,
  };
  context.window.WearingStore={get:name=>store[name]??null,
    set:(name,v)=>{if(failSet)return false;store[name]=String(v);return true;},
    remove:name=>{delete store[name];return true;}};
  context.window.WearingIds={uuid:()=>"k0123456789abcdef0123456789abcdef"};
  context.window.WearingPajio={bearMarkup:()=>""};
  context.window.WearingLife={openView(){}};
  if(deletion)context.window.WearingDeletion=deletion;
  vm.createContext(context);
  vm.runInNewContext(onboarding,context);
  const flush=()=>new Promise(r=>setTimeout(r,5));
  const journal=name=>{try{return JSON.parse(store[name]||"null");}catch{return null;}};
  return {context,calls,store,opened,journal,element,flush,mod:context.window.WearingOnboarding,
    releasePost:()=>releasePost&&releasePost()};
}
const snap=(over={})=>({schema:1,identity_id:"qa",revision:0,status:"draft",step:0,
  values:{roles:[],apps:[],interests:[],reply_detail:null,reply_tone:null},source:"self_selected",
  confirmed_at:null,updated_at:null,recommend_onboarding:true,...over});
const empty={roles:[],apps:[],interests:[],reply_detail:null,reply_tone:null};

test("draft advance persists request before POST, verifies receipt, clears journal", async () => {
  let rev=0,latest=empty;
  const h=harness({
    get:()=>snap({revision:rev,status:"draft",step:rev,values:latest}),
    post:(path,body)=>{
      const parsed=JSON.parse(body);
      rev=1;latest=parsed.values;
      return {...snap({revision:1,status:"draft",step:1,values:latest}),request_key:parsed.request_key};
    },
  });
  h.mod.open();await h.flush();
  const t=h.mod._test;
  t.choose({...empty,roles:["employed"]});
  await t.save("draft",1);
  const post=h.calls.find(c=>c.method==="POST");
  assert.ok(post,"POST sent");
  assert.equal(post.storePendingAtCall&&JSON.parse(post.storePendingAtCall).body.request_key,JSON.parse(post.body).request_key,"journal persisted BEFORE POST");
  const body=JSON.parse(post.body);
  assert.equal(body.revision,0);assert.equal(body.status,"draft");assert.equal(body.step,1);
  assert.match(body.request_key,/^[A-Za-z0-9_-]{16,120}$/);
  assert.equal(t.ui.snapshot.revision,1);
  assert.equal(h.journal("onboarding-request:v1:qa"),null,"pending cleared after verified receipt");
  assert.equal(h.journal("onboarding-draft:v1:qa")&&h.journal("onboarding-draft:v1:qa").revision,1,"draft checkpoint kept for draft status");
});

test("C5a click-order selections are canonicalized before persisting", async () => {
  let rev=0,latest=empty;
  const h=harness({
    get:()=>snap({revision:rev,status:"draft",step:rev,values:latest}),
    post:(path,body)=>{
      const parsed=JSON.parse(body);rev=1;latest={...parsed.values,roles:["employed","student"]};
      return {...snap({revision:1,status:"draft",step:1,values:latest}),request_key:parsed.request_key};
    },
  });
  h.mod.open();await h.flush();
  const t=h.mod._test;
  t.choose({...empty,roles:["student","employed"]});
  assert.deepEqual(t.ui.values.roles,["employed","student"],"choose canonicalizes immediately");
  await t.save("draft",1);
  const body=JSON.parse(h.calls.find(c=>c.method==="POST").body);
  assert.deepEqual(body.values.roles,["employed","student"],"request body canonical");
  assert.equal(t.ui.snapshot.revision,1,"receipt accepted (no fingerprint mismatch loop)");
});

test("C5b legacy pending with click-order body retries semantically and clears", async () => {
  const legacyBody={revision:0,request_key:"legacykey0123456789abcdef",status:"draft",step:1,
    values:{roles:["student","employed"],apps:[],interests:[],reply_detail:null,reply_tone:null}};
  const canonical={roles:["employed","student"],apps:[],interests:[],reply_detail:null,reply_tone:null};
  const h=harness({
    get:()=>snap({revision:1,status:"draft",step:1,values:canonical}),
    post:(path,body)=>{
      const parsed=JSON.parse(body);
      assert.equal(parsed.request_key,"legacykey0123456789abcdef","original key/body replayed unchanged");
      return {...snap({revision:1,status:"draft",step:1,values:canonical}),request_key:parsed.request_key};
    },
  });
  h.context.window.WearingStore.set("onboarding-request:v1:qa",JSON.stringify({identity:"qa",body:legacyBody}));
  h.mod.open();await h.flush();
  const t=h.mod._test;
  assert.deepEqual(t.ui.pending.values.roles,["student","employed"],"pending body loaded from journal wrapper");
  await t.save("draft",1,true);
  assert.equal(t.ui.snapshot.revision,1,"semantic compare accepts canonical receipt for click-order body");
  assert.equal(h.journal("onboarding-request:v1:qa"),null,"pending cleared");
});

test("B1 pending journal survives reload: values/step read from body, retry available", async () => {
  let fail=true,rev=0,latest=empty;
  const h=harness({
    get:()=>snap({revision:rev,status:"draft",step:rev,values:latest}),
    post:(path,body)=>{
      const parsed=JSON.parse(body);
      if(fail)throw new Error("network down");
      rev=1;latest=parsed.values;
      return {...snap({revision:1,status:"draft",step:1,values:latest}),request_key:parsed.request_key};
    },
  });
  h.mod.open();await h.flush();
  const t=h.mod._test;
  t.choose({...empty,roles:["employed"]});
  await t.save("draft",1);
  h.mod.open();await h.flush();
  assert.deepEqual(t.ui.pending.values.roles,["employed"],"pending.body read after reload");
  assert.equal(t.ui.step,1,"step restored from pending body");
  fail=false;
  await t.save("draft",1,true);
  assert.equal(t.ui.snapshot.revision,1);
  assert.equal(h.journal("onboarding-request:v1:qa"),null);
});

test("B2 store.set failure: no POST, honest notice, no false local-keep claim", async () => {
  const h=harness({
    get:()=>snap({revision:0,status:"draft",step:0,values:empty}),
    post:()=>{throw new Error("must not be called");},
    failSet:true,
  });
  h.mod.open();await h.flush();
  const t=h.mod._test;
  t.choose({...empty,roles:["employed"]});
  await t.save("draft",1);
  assert.equal(h.calls.filter(c=>c.method==="POST").length,0,"no POST when journal persist fails");
  assert.match(t.ui.error,/本机暂时没能保留这次保存，没有发出请求。/);
  assert.equal(h.journal("onboarding-request:v1:qa"),null,"no journal claimed");
});

test("B3 conflict resolve checkpoints at fresh revision; reload does not re-conflict", async () => {
  const local={...empty,roles:["employed"]};
  const other={...empty,roles:["caregiver"]};
  let rev=0,latest=empty,latestStep=0,failedOnce=false;
  const h=harness({
    get:()=>snap({revision:rev,status:"draft",step:latestStep,values:latest}),
    post:(path,body)=>{
      if(!failedOnce){failedOnce=true;const e=new Error("偏好已在另一处更新。请读取最新版本后核对。");e.status=409;throw e;}
      const parsed=JSON.parse(body);rev=parsed.revision+1;latest=parsed.values;latestStep=parsed.step;
      return {...snap({revision:rev,status:"draft",step:latestStep,values:latest}),request_key:parsed.request_key};
    },
  });
  h.mod.open();await h.flush();
  const t=h.mod._test;
  t.choose(local);
  await t.save("draft",1);
  assert.equal(t.ui.conflict,true);
  rev=1;latest=other;latestStep=1; // 另一处已写入 rev1
  await t.resolve(false);
  const draft=h.journal("onboarding-draft:v1:qa");
  assert.equal(draft.revision,1,"checkpoint written at FRESH revision (not stale)");
  await t.save("draft",1);
  assert.equal(t.ui.snapshot.revision,2);
  h.mod.open();await h.flush();
  assert.equal(t.ui.localConflict,false,"reload after resolved conflict shows no conflict box");
  assert.equal(t.ui.conflict,false);
});

test("B4 single-select options are directly switchable; multi limit still enforced", async () => {
  const h=harness({get:()=>snap({revision:0,status:"draft",step:0,values:empty}),post(){throw new Error("unused");}});
  h.mod.open();await h.flush();
  const t=h.mod._test;
  t.go(3);
  t.choose({...empty,reply_detail:"brief",reply_tone:"warm"});
  t.paint();
  const markup=h.element("ob-body").innerHTML;
  const detailSection=markup.slice(markup.indexOf("回答长一点"));
  assert.ok(!detailSection.includes("disabled"),"single-select choices never capped");
  t.go(1);
  t.choose({...empty,roles:["employed","student","independent"]});
  t.paint();
  const roleSection=h.element("ob-body").innerHTML;
  assert.match(roleSection,/data-ob-choice="roles:caregiver"[^>]*disabled/,"4th role disabled at cap");
  assert.ok(!/data-ob-choice="roles:employed"[^>]*disabled/.test(roleSection),"selected stays enabled");
});

test("unknown result retries the exact same request; changed intent is refused", async () => {
  let fail=true,rev=0,latest=empty;
  const bodies=[];
  const h=harness({
    get:()=>snap({revision:rev,status:"draft",step:rev,values:latest}),
    post:(path,body)=>{
      bodies.push(body);
      if(fail)throw new Error("network down");
      const parsed=JSON.parse(body);
      rev=1;latest=parsed.values;
      return {...snap({revision:1,status:"draft",step:1,values:latest}),request_key:parsed.request_key};
    },
  });
  h.mod.open();await h.flush();
  const t=h.mod._test;
  t.choose({...empty,roles:["employed"]});
  await t.save("draft",1);
  assert.equal(bodies.length,1);
  assert.ok(t.ui.pending,"pending kept after unknown result");
  await t.save("draft",2);
  assert.equal(bodies.length,1,"no second POST for a different body");
  assert.match(t.ui.error,/请先重试上一次保存。/);
  fail=false;
  await t.save("draft",1,true);
  assert.equal(bodies.length,2);
  assert.equal(bodies[0],bodies[1],"exact same body replayed");
  assert.equal(t.ui.snapshot.revision,1);
  assert.equal(h.journal("onboarding-request:v1:qa"),null);
});

test("skip posts an all-empty snapshot at step 0; late receipt adopts newer state", async () => {
  let latestRev=1;
  const h=harness({
    get:()=>snap({revision:latestRev,status:latestRev>1?"skipped":"draft",step:0,values:empty}),
    post:(path,body)=>{
      const parsed=JSON.parse(body);
      assert.equal(parsed.status,"skipped");
      assert.equal(parsed.step,0);
      assert.deepEqual(parsed.values,empty);
      latestRev=3;
      return {...snap({revision:parsed.revision+1,status:"skipped",step:0,values:empty}),request_key:parsed.request_key};
    },
  });
  h.mod.open();await h.flush();
  const t=h.mod._test;
  await t.save("skipped",0);
  assert.equal(t.ui.snapshot.revision,3,"late receipt re-read adopts the newer snapshot");
  assert.ok(h.opened.includes("close:onboarding-panel"));
});

test("C9 exact: fresh below receipt refuses to clear pending", async () => {
  let receiptOnce=false,freshRev=0;
  const h=harness({
    get:()=>snap({revision:freshRev,status:"draft",step:0,values:empty}),
    post:(path,body)=>{
      const parsed=JSON.parse(body);
      if(!receiptOnce){receiptOnce=true;return {...snap({revision:1,status:"draft",step:1,values:parsed.values}),request_key:parsed.request_key};}
      return {...snap({revision:2,status:"draft",step:1,values:parsed.values}),request_key:parsed.request_key};
    },
  });
  h.mod.open();await h.flush();
  const t=h.mod._test;
  t.choose({...empty,roles:["employed"]});
  freshRev=0;
  await t.save("draft",1);
  assert.match(t.ui.error,/最新偏好还没有核对/,"stale fresh read refuses to finalize");
  assert.ok(h.journal("onboarding-request:v1:qa"),"pending retained for recovery");
});

test("completed profile editing stays local until final confirm; close event never re-writes draft", async () => {
  const savedValues={roles:["student"],apps:["feishu"],interests:["reading"],reply_detail:"brief",reply_tone:null};
  let rev=3,latest=savedValues;
  const h=harness({
    get:()=>snap({revision:rev,status:"completed",step:5,values:latest,confirmed_at:"2026-10-09T01:00:00Z",updated_at:"2026-10-09T01:00:00Z",recommend_onboarding:false}),
    post:(path,body)=>{
      const parsed=JSON.parse(body);
      rev=4;latest=parsed.values;
      return {...snap({revision:4,status:"completed",step:5,values:latest,confirmed_at:"2026-10-09T02:00:00Z",updated_at:"2026-10-09T02:00:00Z",recommend_onboarding:false}),request_key:parsed.request_key};
    },
  });
  h.mod.open();await h.flush();
  const t=h.mod._test;
  assert.equal(t.ui.step,5,"completed snapshot opens at confirm step");
  t.choose({...savedValues,roles:["employed"]});
  const postsBefore=h.calls.filter(c=>c.method==="POST").length;
  await t.save("draft",1);
  assert.equal(h.calls.filter(c=>c.method==="POST").length,postsBefore,"no POST while editing completed profile");
  t.go(5);
  await t.save("completed",5);
  const post=h.calls.find(c=>c.method==="POST");
  assert.equal(JSON.parse(post.body).revision,3);
  assert.equal(h.journal("onboarding-draft:v1:qa"),null,"completed leaves no draft checkpoint");
  assert.ok(h.opened.includes("close:onboarding-panel"));
  for(const fn of (h.element("onboarding-panel").listeners.close||[]))fn();
  assert.equal(h.journal("onboarding-draft:v1:qa"),null,"close event after a completed save must not re-write the draft");
});

test("C6 maybeOffer defers to explicit entry intent", async () => {
  const mk=opts=>harness({get:()=>snap({revision:0,status:"draft",step:0,values:empty,recommend_onboarding:true}),post(){throw new Error("unused");},...opts});
  const withView=mk({search:"?identity=qa&view=memory"});
  await withView.mod.maybeOffer();await withView.flush();
  assert.ok(!withView.opened.includes("onboarding-panel"),"?view= entry must recover first");
  const withTask=mk({search:"?identity=qa&activity_task=abc"});
  await withTask.mod.maybeOffer();await withTask.flush();
  assert.ok(!withTask.opened.includes("onboarding-panel"),"activity_task entry must recover first");
  const lifeMode=mk({lifeMode:true});
  await lifeMode.mod.maybeOffer();await lifeMode.flush();
  assert.ok(!lifeMode.opened.includes("onboarding-panel"),"non-chat view never auto-offers");
  const plain=mk({search:"?identity=qa"});
  await plain.mod.maybeOffer();await plain.flush();
  assert.ok(plain.opened.includes("onboarding-panel"),"plain chat auto-offers for recommend+draft");
});

test("C7 deletion freeze blocks writes and POST; work gate unlocks in-flight state", async () => {
  const gates=[];
  const h=harness({
    get:()=>snap({revision:0,status:"draft",step:0,values:empty}),
    post(){throw new Error("must not POST when frozen");},
    deletion:{workAllowed:()=>true,registerWorkGate(g){gates.push(g);}},
  });
  h.mod.open();await h.flush();
  assert.equal(gates.length,1,"work gate registered");
  const t=h.mod._test;
  h.context.window.WearingDeletion.workAllowed=()=>false;
  t.choose({...empty,roles:["employed"]});
  assert.equal(h.journal("onboarding-draft:v1:qa"),null,"no draft write while frozen");
  await t.save("draft",1);
  assert.equal(h.calls.filter(c=>c.method==="POST").length,0,"no POST while frozen");
  assert.match(t.ui.error,/注销申请已受理/);
  t.ui.busy=true;
  gates[0].stop();
  assert.equal(t.ui.busy,false,"gate.stop unlocks busy");
});

test("C8 reset clears busy; stale in-flight save never touches the new session UI", async () => {
  const h=harness({
    get:()=>snap({revision:0,status:"draft",step:0,values:empty}),
    post:(path,body)=>{
      const parsed=JSON.parse(body);
      return {...snap({revision:1,status:"draft",step:1,values:parsed.values}),request_key:parsed.request_key};
    },
    hangPost:true,
  });
  h.mod.open();await h.flush();
  const t=h.mod._test;
  t.choose({...empty,roles:["employed"]});
  const saving=t.save("draft",1);
  await h.flush();
  assert.equal(t.ui.busy,true,"save in flight");
  h.mod.reset();
  assert.equal(t.ui.busy,false,"reset clears busy");
  assert.equal(t.ui.feishuBusy,false,"reset clears feishuBusy");
  h.releasePost();
  await saving;
  await h.flush();
  assert.equal(t.ui.error,"","stale save wrote no error into the new session");
  assert.equal(t.ui.snapshot,null,"stale save did not adopt old snapshot");
});

test("A1 revoking wins over connected in feishu branch and summary", async () => {
  const h=harness({get:()=>snap({revision:0,status:"draft",step:0,values:empty}),post(){throw new Error("unused");}});
  h.mod.open();await h.flush();
  const t=h.mod._test;
  t.ui.feishu={state:"connected",revocation_pending:true,configured:true,revision:2};
  t.ui.branch="feishu";
  t.paint();
  const markup=h.element("ob-body").innerHTML;
  assert.ok(markup.includes("原授权正在撤销"),"revoking copy shown");
  assert.ok(!markup.includes("飞书连接已建立"),"no connected-ok line while revoking");
  assert.ok(!markup.includes("已授权。"),"no authorized claim while revoking");
  assert.ok(!markup.includes("前往飞书授权"),"no new authorization entry while revoking");
  assert.equal(t.feishuSummaryText(),"原授权正在撤销，暂不可用");
  t.ui.feishu={state:"connected",revocation_pending:false,configured:true,revision:2};
  t.paint();
  const okMarkup=h.element("ob-body").innerHTML;
  assert.ok(okMarkup.includes("飞书连接已建立"),"connected without pending shows established line");
  assert.equal(t.feishuSummaryText(),"已授权，本次未读取正文");
});

test("epoch fence: stale responses never update the UI after identity switch", async () => {
  const h=harness({
    get:()=>snap({revision:0,status:"draft",step:0,values:empty}),
    post:()=>{
      h.context.state.identityEpoch=2;
      throw new Error("dropped");
    },
  });
  h.mod.open();await h.flush();
  const t=h.mod._test;
  t.choose({...empty,roles:["employed"]});
  await t.save("draft",1);
  assert.equal(t.ui.error,"","stale error never written to the new session UI");
});

test("pure helpers: limits, sample copy, label fallback, canonicalization", () => {
  const h=harness({get:()=>snap(),post(){throw new Error("unused");}});
  const w=h.mod._test;
  assert.deepEqual(w.toggle(["a"],"a",3),[]);
  assert.deepEqual(w.toggle([],"b",1),["b"]);
  assert.deepEqual(w.toggle(["a"],"b",1),["a"],"limit holds");
  assert.equal(w.sample({reply_tone:"warm",reply_detail:"brief"}).startsWith("我们可以一起"),true);
  assert.equal(w.sample({reply_detail:"detailed"}).includes("两组"),true);
  assert.equal(w.labelFor([["employed","在职工作"]],[]),"暂时跳过");
  assert.deepEqual(w.canonicalValues({roles:["student","employed"],apps:[],interests:[],reply_detail:null,reply_tone:null}).roles,["employed","student"],"canonical order by enum");
});

test("ticket separation: read-only feishu load and reopen never strand a save's busy state", async () => {
  // 场景一：保存途中确认页自动 loadFeishu（只读）不得作废 save 票据。
  let rev=0,latest=empty;
  const h=harness({
    get:path=>path.includes("cloud-apps")?{state:"not_configured",configured:false,revocation_pending:false}:snap({revision:rev,status:"draft",step:rev,values:latest}),
    post:(path,body)=>{
      const parsed=JSON.parse(body);
      rev=1;latest=parsed.values;
      return {...snap({revision:1,status:"draft",step:1,values:latest}),request_key:parsed.request_key};
    },
    hangPost:true,
  });
  h.mod.open();await h.flush();
  const t=h.mod._test;
  t.choose({...empty,roles:["employed"]});
  const saving=t.save("draft",1);
  await h.flush();
  assert.equal(t.ui.busy,true);
  // 只读来源查询与面板重读（重开）在保存途中发生
  t.loadFeishu();
  await h.flush();
  h.releasePost();
  await saving;await h.flush();
  assert.equal(t.ui.busy,false,"read-only query must not invalidate the save ticket");
  assert.equal(t.ui.snapshot?.revision,1);
  assert.equal(t.ui.feishuBusy,false);
  // 场景二：保存挂起时关闭再打开（load 重读）→ 迟到回执后 busy 必须可清、恢复可操作。
  const h2=harness({
    get:()=>snap({revision:0,status:"draft",step:0,values:empty}),
    post:()=>new Promise(r=>setTimeout(()=>r({schema:1,identity_id:"qa",revision:1,status:"draft",step:1,values:{...empty,roles:["employed"]},source:"self_selected",confirmed_at:null,updated_at:null,recommend_onboarding:true}),10)),
    hangPost:true,
  });
  h2.mod.open();await h2.flush();
  const t2=h2.mod._test;
  t2.choose({...empty,roles:["employed"]});
  const saving2=t2.save("draft",1);
  await h2.flush();
  t2.close();
  h2.mod.open();await h2.flush();
  h2.releasePost();
  await saving2;await h2.flush();
  assert.equal(t2.ui.busy===false && t2.ui.loading===false,true,"reopen during save keeps recovery operable");
  assert.ok(t2.ui.pending||t2.ui.snapshot,"state coherent after late receipt");
});

test("deletion cache cleanup covers onboarding journals (cross-file)", () => {
  const deletion=fs.readFileSync("src/wearing/web/account-deletion.js","utf8");
  assert.match(deletion, /onboarding-draft:v1/);
  assert.match(deletion, /onboarding-request:v1/);
});

test("panel handoff: settings entry closes the parent settings dialog; completion/exit land clean", async () => {
  const views=[];
  let rev=3;
  const baseline={roles:["employed","business"],apps:["wechat","feishu"],interests:["design","reading"],reply_detail:"brief",reply_tone:"warm"};
  const h=harness({
    get:()=>snap({revision:rev,status:"completed",step:5,values:baseline,confirmed_at:"2026-10-09T01:00:00Z",updated_at:"2026-10-09T01:00:00Z",recommend_onboarding:false}),
    post:(path,body)=>{
      const parsed=JSON.parse(body);rev=4;
      return {...snap({revision:4,status:"completed",step:5,values:parsed.values,confirmed_at:"2026-10-09T02:00:00Z",updated_at:"2026-10-09T02:00:00Z",recommend_onboarding:false}),request_key:parsed.request_key};
    },
  });
  h.context.window.WearingLife={openView(v){views.push(v);}};
  // 模拟：设置面板打开着，用户点「打开初始偏好」。
  h.element("settings-panel").open=true;
  for(const fn of (h.element("document").listeners.click||[]))
    fn({target:{closest:sel=>sel==="#onboarding-entry"?{}:null}});
  await h.flush();
  assert.ok(h.opened.includes("close:settings-panel"),"parent settings dialog closed on entry");
  assert.ok(h.opened.includes("onboarding-panel"),"onboarding opened");
  // 完成：引导面板关闭并进入「今天」，设置面板不再回弹。
  await h.mod._test.save("completed",5);
  await h.flush();
  assert.ok(h.opened.includes("close:onboarding-panel"));
  assert.deepEqual(views,["today"],"completion lands on today");
  assert.equal(h.opened.filter(x=>x==="onboarding-panel").length,1,"onboarding opened once; no re-stacked modal after completion");
  assert.notEqual(h.element("settings-panel").open,true,"settings stays closed after completion");
  // 退出路径：重开引导（设置已关）→ 稍后继续 → 页面无叠加模态。
  for(const fn of (h.element("document").listeners.click||[]))
    fn({target:{closest:sel=>sel==="#onboarding-entry"?{}:null}});
  await h.flush();
  await h.mod._test.close();
  assert.ok(h.opened[h.opened.length-1]==="close:onboarding-panel");
  assert.ok(!h.opened.includes("settings-panel"),"exit does not reopen settings on top");
});
