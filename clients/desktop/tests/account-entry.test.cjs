"use strict";
const {test}=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const vm=require("node:vm");
const script=fs.readFileSync(path.join(__dirname,"../frontend/connection.js"),"utf8");
const html=fs.readFileSync(path.join(__dirname,"../frontend/index.html"),"utf8");
const flush=()=>new Promise(resolve=>setImmediate(resolve));
function harness(settings={},invokeHook){
  const elements={},calls=[];
  function element(id){return elements[id]={id,value:"",textContent:"",disabled:["join","login"].includes(id),handlers:{},
    classList:{add(){},remove(){}},addEventListener(type,fn){this.handlers[type]=fn;}};}
  for(const id of ["status","join","login","shortcut","development-host","development-template"])element(id);
  elements["development-template"].content={cloneNode:()=>({template:true})};
  elements["development-host"].append=node=>{
    assert.equal(node.template,true);
    for(const id of ["server","connect","connection-form"])element(id);
  };
  const invoke=async(command,args)=>{
    calls.push({command,args:args===undefined?undefined:JSON.parse(JSON.stringify(args))});
    if(command==="connection_info")return {url:"https://old-service.invalid/",shortcut_ready:true,shortcut_label:"test",...settings};
    return invokeHook?.(command,args);
  };
  const context=vm.createContext({window:{__TAURI__:settings.noInvoke?undefined:{core:{invoke}}},document:{getElementById:id=>elements[id]||null}});
  vm.runInContext(script,context);
  return {elements,calls,context,click:id=>elements[id].handlers.click?.(),submit:()=>elements["connection-form"].handlers.submit({preventDefault(){}})};
}
test("default HTML has two account actions and no active URL or credential form",()=>{
  const active=html.replace(/<template\b[\s\S]*?<\/template>/g,"");
  assert.match(active,/id="join"[^>]*disabled/);assert.match(active,/id="login"[^>]*disabled/);
  assert.doesNotMatch(active,/<input|<form/);assert.doesNotMatch(active,/type="password"/);
});
test("production invokes fixed intents even when a saved custom URL is returned",async()=>{
  const h=harness();await flush();assert.equal(h.elements.server,undefined);
  await h.click("join");await h.click("login");
  assert.deepEqual(h.calls.slice(1),[{command:"open_account",args:{intent:"join"}},{command:"open_account",args:{intent:"login"}}]);
  assert.equal(JSON.stringify(h.calls).includes("old-service"),false);
  vm.runInContext('connect("development")',h.context);await flush();assert.equal(h.calls.length,3);
});
test("returning official user continues without sending any persisted URL",async()=>{
  const h=harness({auto_connect:true});await flush();
  assert.deepEqual(h.calls[1],{command:"open_account",args:{intent:"continue"}});
});
test("migration warning requires explicit account action and never auto-connects",async()=>{
  const h=harness({warning:"请重新登录",auto_connect:true});await flush();
  assert.equal(h.calls.length,1);assert.equal(h.elements.status.textContent,"请重新登录");
  await h.click("login");assert.equal(h.calls.length,2);
});
test("only literal development capability mounts the developer form",async()=>{
  for(const flag of [undefined,false,1,"true"]){const h=harness({development_endpoints:flag});await flush();assert.equal(h.elements.server,undefined);}
  const h=harness({development_endpoints:true,url:"http://127.0.0.1:8765/"});await flush();
  assert.equal(h.elements.server.value,"http://127.0.0.1:8765/");h.submit();await flush();
  assert.deepEqual(h.calls[1],{command:"connect_server",args:{value:"http://127.0.0.1:8765/",persist:true}});
});
test("a pending native request prevents repeated account actions; failure restores controls",async()=>{
  let reject;const h=harness({},()=>new Promise((_,r)=>{reject=r;}));await flush();
  const first=h.click("join");await h.click("login");assert.equal(h.calls.length,2);
  assert.equal(h.elements.join.disabled,true);reject(new Error("synthetic diagnostic"));await first;
  assert.equal(h.elements.join.disabled,false);assert.equal(h.elements.login.disabled,false);
  assert.equal(h.elements.status.textContent.includes("synthetic diagnostic"),false);
});
test("outside the native shell the actions stay disabled and invoke nothing",async()=>{
  const h=harness({noInvoke:true});await flush();await h.click("join");assert.equal(h.calls.length,0);assert.equal(h.elements.join.disabled,true);
});
