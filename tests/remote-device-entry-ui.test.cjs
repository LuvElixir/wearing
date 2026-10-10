"use strict";
// 第二十四轮终复审 P2 回归：云设备行必须同时保留独立暂停/恢复入口与（白名单内的）远程接管。
// 覆盖实际 render 与 click 分支：observe-only、files-only、legacy 输入（无 private-media 路由）、
// 正常远控设备、control_pending 禁用、恢复遵循原 /api/devices/control 流程。
const {test} = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const app = fs.readFileSync("src/wearing/web/app.js", "utf8");
const html = fs.readFileSync("src/wearing/web/index.html", "utf8");

const phoneInput = ["phone.mobile_click_on_screen_at_coordinates","phone.mobile_swipe_on_screen","phone.mobile_type_keys","phone.mobile_set_text","phone.mobile_press_button","phone.mobile_launch_app"];
const device = (kind, methods, over = {}) => ({resource_id: "dev_" + kind + "_" + methods.length, name: "设备" + methods.length, kind, methods, last_seen_at: null,
  control_generation: 3, permission_revision: 1, policy_revision: 1, online: true, connected: true, paused: false,
  control_pending: false, needs_review: false, last_seen_at: null, ...over});

function renderRows(devices) {
  const start = app.indexOf("const phoneRemoteInput=");
  const end = app.indexOf("}finally{devicesLoading=false;}");
  const fnSource = app.slice(start, end)
    .replace(/await loadDeviceReviews\(\);/g, "")
    .replace(/await loadDesktopApprovals\(\);/g, "")
    .replace(/await loadPermissionChange\(\);/g, "");
  const els = {};
  const el = id => els[id] || (els[id] = {id, innerHTML: "", textContent: ""});
  const esc = t => String(t ?? "");
  const deps = "const loadDeviceReviews=async()=>{},loadDesktopApprovals=async()=>{},loadPermissionChange=async()=>{},syncPermissionForm=()=>{};let devicesLoading=false;";
  const body = '"use strict";' + deps + fnSource + 'return $("cloud-devices").innerHTML;';
  const run = new Function("window", "esc", "deviceIcon", "state", "api", "busy", "loadDevices", "result", "$", body);
  return run({}, esc, () => "", {remoteDevices: [], pendingDeviceControl: null}, async () => ({}), async (b, f) => f(), async () => {}, {devices}, el);
}

test("all device classes keep an independent pause/restore entry", () => {
  const cases = [
    ["observe-only computer", device("computer", ["computer.status", "computer.observe"])],
    ["files-only android", device("android", ["files.read", "files.write"])],
    ["legacy input computer (no private media)", device("computer", ["computer.input", "computer.observe"])],
    ["remote-capable android", device("android", phoneInput)],
    ["remote-capable computer", device("computer", ["computer.input"])],
  ];
  for (const [label, dev] of cases) {
    const markup = renderRows([dev]);
    assert.match(markup, /data-cloud-control/, label + " has pause/restore");
    assert.ok(!/data-cloud-control="[^"]*"[^>]*disabled/.test(markup) || dev.control_pending, label + " not disabled when idle");
  }
});

test("takeover button strictly gated; files-only/observe-only excluded", () => {
  const observe = renderRows([device("computer", ["computer.status", "computer.observe"])]);
  assert.ok(!observe.includes("data-rd-open"), "observe-only: no takeover");
  const filesOnly = renderRows([device("android", ["files.read", "files.write"])]);
  assert.ok(!filesOnly.includes("data-rd-open"), "files-only: no takeover");
  const legacy = renderRows([device("computer", ["computer.input", "computer.observe"])]);
  assert.ok(legacy.includes("data-rd-open"), "legacy computer.input keeps takeover");
  const phone = renderRows([device("android", phoneInput)]);
  assert.ok(phone.includes("data-rd-open"), "phone input methods keep takeover");
});

test("control_pending disables pause/restore in markup", () => {
  const markup = renderRows([device("computer", ["computer.input"], {control_pending: true})]);
  assert.match(markup, /data-pending="true"/);
  assert.match(markup, /data-cloud-control="[^"]*"[^>]*disabled/, "pending disables button");
});

test("click branch: pending guard and original control flow", () => {
  // 提取 [data-cloud-control] click 分支源码并行为验证关键语义。
  const start = app.indexOf('$("cloud-devices").addEventListener("click",event=>{');
  const segment = app.slice(app.indexOf("function captureControlSnapshot"), app.indexOf("let permissionDevice"));
  assert.match(segment, /dataset\.pending==="true"/, "pending guard present");
  assert.match(segment, /\/api\/devices\/control/, "original control endpoint preserved");
  assert.match(segment, /expected_generation/, "generation CAS preserved");
  assert.match(segment, /pendingDeviceControl/, "pending tracking preserved");
});

test("version bumped; no regression in wiring", () => {
  assert.match(html, /app\.js\?v=59/);
  assert.match(html, /pajio\.css\?v=22/);
  assert.match(app, /data-rd-open data-rd-resource/);
});


// Register the actual production handlers. No hand-written copy of dispatch logic.
function harness(devices, accessHook) {
  const state={identityEpoch:1,identityId:"qa",deployment:"cloud",remoteDevices:devices,pendingDeviceControl:null};
  const handlers={},els={},pending=[],requests=[],opens=[];
  const el=id=>els[id]||(els[id]={textContent:"",addEventListener:(_event,fn)=>{handlers[id]=fn;}});
  const api=async(path,options={})=>{
    requests.push({path,...options,body:options.body?JSON.parse(options.body):undefined});
    if(path.startsWith("/api/devices/access/"))return accessHook(path,state);
    return {};
  };
  const busy=(_button,fn)=>{const promise=fn();pending.push(promise);return promise;};
  const source=app.slice(app.indexOf("function captureControlSnapshot"),app.indexOf("let permissionDevice"));
  const chat=app.slice(app.indexOf('$("computer-takeover").addEventListener'),app.indexOf("function configureDeployment"));
  new Function("api","state","busy","$","window","loadDevices","toggleComputer","showSettings",source+chat)
    (api,state,busy,el,{WearingRemoteDevice:{open:(...args)=>opens.push(args)}},async()=>{},()=>{},()=>{});
  async function click(device,mutate){
    const markup=renderRows([device]);
    const tag=markup.match(/<button[^>]*data-cloud-control=[\s\S]*?<\/button>/)[0];
    const attr=name=>tag.match(new RegExp('data-'+name+'="([^"]*)"'))?.[1];
    const button={disabled:/ disabled/.test(tag),dataset:{cloudControl:attr("cloud-control"),generation:attr("generation"),paused:attr("paused"),pending:attr("pending")}};
    handlers["cloud-devices"]({target:{closest:()=>button}});
    mutate?.(button);
    await Promise.all(pending.splice(0));
  }
  async function chatClick(mutate){handlers["computer-takeover"]();mutate?.();await Promise.all(pending.splice(0));}
  return {state,requests,opens,click,chatClick,els};
}
const controlDevice=(kind="computer",over={})=>device(kind,[kind==="computer"?"computer.input":phoneInput[0]],{resource_id:"dev_a",control_generation:7,paused:true,control_pending:false,...over});
const privateAccess={resource_id:"dev_a",supported:true,state:"paused",control_generation:7};
const posts=h=>h.requests.filter(r=>r.path==="/api/devices/control");

test("actual rendered click: unpaused device pauses without an access request",async()=>{
  const dev=controlDevice("android",{paused:false});const h=harness([dev],()=>{throw Error("unexpected access");});
  await h.click(dev);
  assert.deepEqual(posts(h).map(r=>r.body),[{resource_id:"dev_a",paused:true,expected_generation:7}]);
  assert.equal(h.requests.length,1);assert.equal(h.opens.length,0);
});
test("actual rendered click: paused Linux and Android open their own private return panel",async()=>{
  for(const kind of ["computer","android"]){const dev=controlDevice(kind);const h=harness([dev],()=>privateAccess);
    await h.click(dev);assert.deepEqual(h.opens,[[dev.resource_id,dev.name,kind]]);assert.equal(posts(h).length,0);
  }
});
test("actual rendered click: explicit unsupported legacy device resumes normally",async()=>{
  const dev=controlDevice();const h=harness([dev],()=>({resource_id:"dev_a",supported:false}));
  await h.click(dev);assert.deepEqual(posts(h).map(r=>r.body),[{resource_id:"dev_a",paused:false,expected_generation:7}]);assert.equal(h.opens.length,0);
});
test("actual rendered pending button sends no request",async()=>{
  const dev=controlDevice("android",{control_pending:true});const h=harness([dev],()=>privateAccess);
  await h.click(dev);assert.equal(h.requests.length,0);assert.equal(h.opens.length,0);
});
test("actual click rejects unknown access, invalid generation and transient states",async()=>{
  const cases=[null,{},... [undefined,null,"true","false",0,1].map(supported=>({...privateAccess,supported})),
    ...[undefined,null,"7",7.5,8].map(control_generation=>({...privateAccess,control_generation})),
    {...privateAccess,resource_id:"dev_b"},... ["unknown","handoff_pending","return_pending"].map(state=>({...privateAccess,state}))];
  for(const access of cases){const dev=controlDevice();const h=harness([dev],()=>access);
    await h.click(dev);assert.equal(posts(h).length,0,JSON.stringify(access));assert.equal(h.opens.length,0,JSON.stringify(access));
  }
});
test("actual click rechecks identity and device ownership after access resolves",async()=>{
  const changes=[s=>s.identityEpoch++,s=>s.identityId="other",s=>s.remoteDevices[0].control_generation++,s=>s.remoteDevices=[],
    s=>s.remoteDevices[0].paused=false,s=>s.remoteDevices[0].control_pending=true,s=>s.remoteDevices[0].kind="android"];
  for(const change of changes){const dev=controlDevice();let resolve;const gate=new Promise(r=>resolve=r);const h=harness([dev],()=>gate);
    const done=h.click(dev);change(h.state);resolve(privateAccess);await done;
    assert.equal(posts(h).length,0);assert.equal(h.opens.length,0);
  }
});
test("actual click freezes target and generation before mutable button data changes",async()=>{
  for(const legacy of [false,true]){const dev=controlDevice("android");let resolve;const gate=new Promise(r=>resolve=r);const h=harness([dev],()=>gate);
    const done=h.click(dev,button=>{button.dataset.cloudControl="dev_b";button.dataset.generation="99";button.dataset.paused="false";});
    resolve(legacy?{resource_id:"dev_a",supported:false}:privateAccess);await done;
    if(legacy)assert.deepEqual(posts(h).map(r=>r.body),[{resource_id:"dev_a",paused:false,expected_generation:7}]);
    else assert.deepEqual(h.opens,[["dev_a",dev.name,"android"]]);
  }
});
test("direct pause also cancels if identity changes in its await continuation",async()=>{
  const dev=controlDevice("computer",{paused:false});const h=harness([dev],()=>privateAccess);
  await h.click(dev,()=>h.state.identityEpoch++);assert.equal(posts(h).length,0);assert.equal(h.opens.length,0);
});
test("actual chat control shares explicit return and identity guards",async()=>{
  const dev=controlDevice();const h=harness([dev],()=>privateAccess);await h.chatClick();
  assert.deepEqual(h.opens,[["dev_a",dev.name,"computer"]]);assert.equal(posts(h).length,0);
  const dev2=controlDevice();let resolve;const gate=new Promise(r=>resolve=r);const race=harness([dev2],()=>gate);
  const done=race.chatClick(()=>race.state.identityEpoch++);resolve(privateAccess);await done;
  assert.equal(posts(race).length,0);assert.equal(race.opens.length,0);
});
test("paused device label and accessible name agree for both platforms",()=>{
  for(const kind of ["computer","android"]){const markup=renderRows([controlDevice(kind)]);
    assert.match(markup,/aria-label="查看并交还 /);assert.match(markup,/>查看并交还<\/button>/);
  }
});
