"use strict";
// Independent regression checks for the Web onboarding review, 2026-10-09.
// Run: node --test /tmp/pajio-onboarding-web-independent-review.cjs
// Optional: PAJIO_REVIEW_ROOT=/path/to/facet node --test <this file>
// Reads working-tree code only. No requests, user data, browser, or file writes.
// Harness intentionally uses real scoped-store.js and account-deletion.js.
// A DOM stub cannot replace browser/device QA; tests assert previously reproduced
// state-machine defects, not aesthetics, provider connectivity, or market value.
const {test} = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const ROOT = process.env.PAJIO_REVIEW_ROOT || "/Users/archieliew/Documents/facet";
const read = name => fs.readFileSync(path.join(ROOT, "src/wearing/web", name), "utf8");
const SOURCES = Object.fromEntries(["scoped-store.js", "account-deletion.js", "onboarding.js"].map(name => [name, read(name)]));
const empty = () => ({roles:[], apps:[], interests:[], reply_detail:null, reply_tone:null});
const plain = value => JSON.parse(JSON.stringify(value));
const snapshot = (extra={}) => ({schema:1, identity_id:"qa", revision:0, status:"draft", step:0,
  values:empty(), source:"self_selected", confirmed_at:null, updated_at:null, recommend_onboarding:true, ...extra});
const canonical = values => ({
  roles:["employed","student","independent","business","caregiver"].filter(x => values.roles.includes(x)),
  apps:["wechat","douyin","xiaohongshu","bilibili","feishu","dingtalk","wecom","mail","calendar","github"].filter(x => values.apps.includes(x)),
  interests:["technology","career","design","reading","travel","food","fitness","culture","finance"].filter(x => values.interests.includes(x)),
  reply_detail:values.reply_detail, reply_tone:values.reply_tone,
});
const flush = () => new Promise(resolve => setTimeout(resolve, 10));
function deferred() {let resolve, reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};}
function harness(options={}) {
  const elements=new Map(), listeners=new Map(), data=new Map(), calls=[], opened=[], views=[], notices=[];
  let durable=true, serial=0;
  const eventTarget = object => Object.assign(object, {
    addEventListener(type, fn) {const key=this.id+":"+type;listeners.set(key,[...(listeners.get(key)||[]),fn]);},
    removeEventListener(type, fn) {const key=this.id+":"+type;listeners.set(key,(listeners.get(key)||[]).filter(x=>x!==fn));},
    dispatchEvent(event) {for(const fn of listeners.get(this.id+":"+event.type)||[])fn(event);return true;},
  });
  const classList=()=>({contains:()=>false,add(){},remove(){},toggle(){}});
  const element=id=>{if(!elements.has(id))elements.set(id,eventTarget({id,innerHTML:"",textContent:"",dataset:{},open:false,hidden:false,disabled:false,value:"",classList:classList(),
    setAttribute(name,value){this[name]=String(value);},getAttribute(name){return this[name]??null;},removeAttribute(name){delete this[name];},
    showModal(){this.open=true;},close(){this.open=false;this.dispatchEvent({type:"close"});},focus(){},scrollIntoView(){},replaceChildren(){},querySelector(){return null;},querySelectorAll(){return [];},
  }));return elements.get(id);};
  const document=eventTarget({id:"document",hidden:false,visibilityState:"visible",documentElement:{classList:classList()},body:{dataset:{view:"chat"},classList:classList()},
    getElementById:element,querySelector:selector=>selector==="dialog[open]"?[...elements.values()].find(el=>el.open)||null:null,querySelectorAll:()=>[],createTextNode:text=>({textContent:text}),createElement:tag=>element("created-"+tag+elements.size)});
  const localStorage={get length(){return data.size;},key:index=>[...data.keys()][index]??null,getItem:key=>data.get(key)??null,
    setItem(key,value){if(!durable)throw new Error("quota exceeded");data.set(key,String(value));},removeItem:key=>data.delete(key),clear:()=>data.clear()};
  const state={identityId:"qa",identityEpoch:1,connected:true,token:"synthetic-csrf",deployment:"cloud",polling:false,sending:false};
  const profiles=new Map([["qa",options.profile||snapshot()]]);
  const window=eventTarget({id:"window",open(){},WearingIds:{uuid:()=>"reviewkey"+(++serial).toString().padStart(24,"0")},WearingPajio:{bearMarkup:()=>""},
    WearingLife:{openView:view=>views.push(view)},WearingHost:{hidden:false}});
  class StaleIdentity extends Error {}
  const context={window,document,state,localStorage,sessionStorage:localStorage,location:{origin:"https://qa.invalid",search:"",hash:"",pathname:"/",assign(){}},
    StaleIdentity,URL,URLSearchParams,Date,JSON,Number,Array,Object,String,Boolean,Math,Error,Promise,Set,Map,Event,
    console,setTimeout:(fn,ms)=>{const timer=setTimeout(fn,ms);timer.unref?.();return timer;},clearTimeout,
    setInterval:(fn,ms)=>{const timer=setInterval(fn,ms);timer.unref?.();return timer;},clearInterval,
    notice:(text,error)=>notices.push({text,error}),openPanel:id=>{opened.push(id);element(id).showModal();},closePanel:id=>element(id).close(),
    busy:async(button,fn)=>fn(),fetch:async()=>{throw new Error("network disabled in independent review");},
  };
  window.document=document;window.location=context.location;
  context.api=async(url,init={})=>{
    const epoch=state.identityEpoch,identity=state.identityId;
    const call={url,method:init.method||"GET",body:init.body?JSON.parse(init.body):null,identity,epoch};calls.push(call);
    let result;
    if(call.method==="GET")result=options.get?await options.get(url,call,h):url.includes("feishu")?{state:"not_configured",configured:false,revocation_pending:false}:profiles.get(identity)||snapshot({identity_id:identity});
    else if(options.post)result=await options.post(url,call.body,h);
    else {
      const body=call.body,now="2026-10-09T05:00:00Z";
      result=snapshot({identity_id:identity,revision:body.revision+1,status:body.status,step:body.step,values:canonical(body.values),
        confirmed_at:body.status==="completed"?now:null,updated_at:now,recommend_onboarding:body.status==="draft",request_key:body.request_key});
      profiles.set(identity,plain(result));
    }
    // Mirror the actual app.js API fence, so tests do not invent a missing fence.
    if(epoch!==state.identityEpoch)throw new StaleIdentity();
    return plain(result);
  };
  const h={context,state,window,document,element,calls,opened,views,notices,profiles,data,
    setDurable:value=>{durable=value;},journal:name=>JSON.parse(window.WearingStore.get(name)||"null"),
    click(selector,dataset={}){element("onboarding-panel").dispatchEvent({type:"click",target:{closest:s=>s===selector?{dataset}:null}});},
  };
  vm.createContext(context);
  for(const name of ["scoped-store.js","account-deletion.js","onboarding.js"]) {
    vm.runInContext(SOURCES[name],context,{filename:name});
    if(name==="scoped-store.js")window.WearingStoreBind("cloud","a".repeat(64));
  }
  h.mod=window.WearingOnboarding;h.t=h.mod._test;
  assert.ok(h.t?.load&&h.t?.save,"Onboarding _test state-machine seam must remain available or adapt this harness, not product behavior");
  return h;
}

test("P1: arbitrary multi-select click order saves successfully against canonical backend receipt", async()=>{
  const h=harness();await h.t.load();
  h.t.choose({...empty(),roles:["student","employed"],apps:["github","wechat"],interests:["travel","technology"]});
  await h.t.save("draft",2);
  assert.equal(h.t.ui.error,"");assert.equal(h.t.ui.pending,null);
  assert.equal(h.t.ui.snapshot.revision,1);
  assert.deepEqual(plain(h.t.ui.values.roles),["employed","student"]);
});

test("P1: unknown save restored from pending.body retains values/step and can render", async()=>{
  const h=harness({post:()=>{throw new Error("response lost");}});await h.t.load();
  h.t.choose({...empty(),roles:["employed"]});await h.t.save("draft",1);
  const before=plain(h.journal(h.t.pendingKey()));assert.ok(before);
  await h.t.load();
  assert.deepEqual(plain(h.t.ui.values.roles),["employed"]);assert.equal(h.t.ui.step,1);
  assert.deepEqual(plain(h.journal(h.t.pendingKey())),before,"reload must not rewrite an unknown exact request");
  h.t.ui.open=true;await h.t.load(); // previous implementation threw during paint
});

test("P1: failed durable pending write never sends POST or claims the choice is safely stored", async()=>{
  const h=harness({post:()=>{throw new Error("response lost");}});await h.t.load();
  h.t.choose({...empty(),roles:["student"]});h.setDurable(false);await h.t.save("draft",1);
  assert.equal(h.calls.filter(c=>c.method==="POST").length,0);
  assert.ok(h.t.ui.error,"storage failure needs an actionable visible error");
  assert.doesNotMatch(h.t.ui.error,/选择已留在本机|你的选择已保留/);
});

test("P2: resolving conflict persists the fresh revision before page reload", async()=>{
  const h=harness({post:()=>{throw Object.assign(new Error("conflict"),{status:409});}});await h.t.load();
  h.t.choose({...empty(),roles:["employed"]});await h.t.save("draft",1);
  h.profiles.set("qa",snapshot({revision:1,values:{...empty(),roles:["caregiver"]}}));
  await h.t.resolve(false);
  assert.equal(h.t.ui.snapshot.revision,1);assert.equal(h.journal(h.t.draftKey()).revision,1);
  await h.t.load();assert.equal(h.t.ui.localConflict,false);assert.deepEqual(plain(h.t.ui.values.roles),["employed"]);
});

for(const mode of ["older","same-revision-conflicting"])test("P1: post-save GET "+mode+" keeps the exact request pending",async()=>{
  let gotReceipt=false;
  const h=harness({get:()=>!gotReceipt?snapshot():mode==="older"?snapshot():snapshot({revision:1,step:1,values:{...empty(),roles:["caregiver"]}}),
    post:(_,body)=>{gotReceipt=true;return snapshot({revision:1,status:body.status,step:body.step,values:body.values,request_key:body.request_key});}});
  await h.t.load();h.t.choose({...empty(),roles:["employed"]});await h.t.save("draft",1);
  assert.ok(h.journal(h.t.pendingKey()),"unverified latest state must not clear durable exact retry request");
  assert.ok(h.t.ui.pending);assert.ok(h.t.ui.error);
});

test("P2: reply detail/tone can switch directly without clearing the selected option first",async()=>{
  const h=harness();h.mod.open();await flush();h.t.go(3);h.t.choose({...empty(),reply_detail:"brief",reply_tone:"direct"});
  const html=h.element("ob-body").innerHTML;
  for(const value of ["reply_detail:balanced","reply_detail:detailed","reply_tone:natural","reply_tone:warm"]) {
    const button=html.match(new RegExp('<button[^>]*data-ob-choice="'+value+'"[^>]*>'))?.[0];
    assert.ok(button,value+" exists");assert.doesNotMatch(button,/\sdisabled(?:[\s=>]|$)/,value+" can be selected directly");
  }
});

test("P2: auto-offer does not intercept a non-chat destination",async()=>{
  const h=harness();h.document.body.dataset.view="memory";h.context.location.search="?view=memory";
  await h.mod.maybeOffer();await flush();assert.equal(h.opened.includes("onboarding-panel"),false);
});

test("P2: revocation pending never claims Feishu is connected",async()=>{
  const h=harness({get:url=>url.includes("feishu")?{state:"connected",configured:true,revocation_pending:true,revision:"r1"}:snapshot({step:4,values:{...empty(),apps:["feishu"]}})});
  h.mod.open();await flush();h.click("[data-ob-branch]",{obBranch:"feishu"});await flush();
  const html=h.element("ob-body").innerHTML;
  assert.match(html,/撤销/);assert.doesNotMatch(html,/飞书连接已建立|已授权。可访问/);
});

test("P1: account freeze prevents new onboarding business requests and local writes",async()=>{
  const h=harness();await h.t.load();await h.window.WearingDeletion.freezeAccountWork();
  h.t.choose({...empty(),roles:["student"]});await h.t.save("draft",1);
  assert.equal(h.calls.filter(c=>c.method==="POST").length,0);
  assert.equal(h.journal(h.t.draftKey()),null);assert.equal(h.journal(h.t.pendingKey()),null);
});

test("P1: account deletion cache cleanup includes both onboarding journals and preserves another account",()=>{
  const h=harness();const store=h.window.WearingStore;
  const draft="onboarding-draft:v1:qa",pending="onboarding-request:v1:qa";
  store.set(draft,JSON.stringify({identity:"qa",revision:0,step:1,values:empty()}));
  store.set(pending,JSON.stringify({identity:"qa",body:{revision:0,status:"draft",step:1,values:empty(),request_key:"reviewkey1234567890"}}));
  const other="pajio:"+"b".repeat(64)+":"+draft;h.context.localStorage.setItem(other,"other-account");
  h.window.WearingDeletion.clearAccountCaches({origin:h.context.location.origin,user_id:"qa-user"});
  assert.equal(store.get(draft),null);assert.equal(store.get(pending),null);
  assert.equal(h.context.localStorage.getItem(other),"other-account");
});

test("P2: identity reset releases busy state and ignores old request catch/finally",async()=>{
  const late=deferred();const h=harness({post:()=>late.promise});await h.t.load();
  const saving=h.t.save("draft",1);await flush();
  h.state.identityId="second";h.state.identityEpoch++;h.mod.reset();await h.t.load();
  const before={busy:h.t.ui.busy,error:h.t.ui.error,identity:h.t.ui.snapshot.identity_id};
  late.resolve(snapshot());await saving;
  assert.equal(before.identity,"second");assert.equal(before.busy,false,"new identity must not wait for old request");
  assert.equal(h.t.ui.error,"");assert.equal(h.t.ui.snapshot.identity_id,"second");
});

test("P1 regression: entering confirmation with Feishu selected does not strand save busy state",async()=>{
  const h=harness({profile:snapshot({step:4,values:{...empty(),apps:["feishu"]}})});
  h.mod.open();await flush();await h.t.save("draft",5);await flush();
  assert.equal(h.t.ui.step,5);assert.equal(h.t.ui.pending,null);
  assert.equal(h.t.ui.feishuBusy,false);
  assert.equal(h.t.ui.busy,false,"read-only Feishu summary load must not invalidate save cleanup");
  const button=h.element("ob-footer").innerHTML.match(/<button[^>]*data-ob-primary[^>]*>/)?.[0];
  assert.ok(button);assert.doesNotMatch(button,/\sdisabled(?:[\s=>]|$)/);
});

test("P1 regression: close/reopen during unknown save leaves recovery operable",async()=>{
  const late=deferred();const h=harness({post:()=>late.promise});h.mod.open();await flush();
  const saving=h.t.save("draft",1);await flush();h.t.close();h.mod.open();await flush();
  // The previous session's transport eventually returns. Regardless of whether
  // its receipt is ignored or verified, the newly opened recovery cannot stay busy.
  late.resolve(snapshot());await saving;await flush();
  assert.equal(h.t.ui.loading,false);assert.equal(h.t.ui.busy,false);
  assert.ok(h.t.ui.pending,"unknown exact request remains available for recovery");
});

// Read-only integration checkpoints (manual/browser QA after tests pass):
// - app.js initialize() must complete openFromLink/activity_task recovery before auto-offer.
// - Feishu return currently has a manual check button. Claim automatic return only
//   after focus/visibility/poll handling has actually been implemented and exercised.
// - Storage absent/denied, account rebind, close during save, and actual keyboard/
//   screen-reader radio semantics still need browser verification.
