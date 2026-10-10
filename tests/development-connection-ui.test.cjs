"use strict";
const {test}=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const app=fs.readFileSync("src/wearing/web/app.js","utf8");
const html=fs.readFileSync("src/wearing/web/index.html","utf8");
const source=app.slice(app.indexOf("let developmentConnectionEnabled="),app.indexOf('$("inspect-host").addEventListener'));
function harness(over={},hook){
  const state={deployment:"local",identityEpoch:1,...over.state};
  const location={protocol:"http:",hostname:"localhost",search:"?development=1",...over.location};
  const requests=[],reloads=[],handlers={};let form=null;
  const host={replaceChildren(){form=null;},append(node){assert.equal(node.template,true);form=makeForm();},querySelector(){return form;}};
  const elements={"development-connection-host":host,"development-connection-template":{content:{cloneNode:()=>({template:true})}},"settings-panel":{addEventListener:(name,fn)=>{handlers[name]=fn;}}};
  function makeForm(){
    const elements=Object.fromEntries(["hermes-url","hermes-key","connect-button","connection-feedback"].map(id=>["#"+id,{value:"",textContent:"",disabled:false}]));
    return {elements,querySelector:id=>elements[id],addEventListener(_name,fn){this.submit=()=>fn({preventDefault(){}});}};
  }
  class StaleIdentity extends Error{}
  const api=async(path,options)=>{requests.push({path,...options,body:JSON.parse(options.body)});return hook?.();};
  const configure=new Function("$","state","location","URLSearchParams","api","loadStatus","loadConversation","StaleIdentity",source+"return configureDevelopmentConnection;")
    (id=>elements[id],state,location,URLSearchParams,api,async()=>reloads.push("status"),async()=>reloads.push("conversation"),StaleIdentity);
  return {state,location,requests,reloads,configure,get form(){return form;},close:()=>handlers.close()};
}
test("address and key inputs only exist inside an inert development template",()=>{
  const active=html.replace(/<template\b[\s\S]*?<\/template>/g,"");
  assert.doesNotMatch(active,/id="(?:connection-form|hermes-url|hermes-key)"/);
  assert.match(html,/<template id="development-connection-template">/);
  assert.match(app,/configureDevelopmentConnection\(bootstrap\);configureDeployment\(\)/);
  const views=fs.readFileSync("src/wearing/web/views.js","utf8");
  assert.doesNotMatch(views,/切换服务地址/);assert.match(views,/row\("身份管理", "切换对话、记忆与文件所属身份"/);
});
test("cloud, unknown deployment, remote host, or absent explicit dev opt-in never mount the form",()=>{
  const cases=[{state:{deployment:"cloud"}},{state:{deployment:undefined}},{location:{hostname:"pajio.luckyloading.com"}},{location:{hostname:"localhost.attacker.invalid"}},{location:{hostname:"127.0.0.2"}},{location:{protocol:"file:"}},{location:{search:""}},{location:{search:"?development=true"}}];
  for(const over of cases){const h=harness(over);h.configure({deployment:over.state?.deployment??"local"});assert.equal(h.form,null,JSON.stringify(over));}
  const h=harness();h.configure({});assert.equal(h.form,null);h.configure({deployment:"cloud"});assert.equal(h.form,null);
});
test("all supported loopback developer pages use the actual form handler",async()=>{
  for(const hostname of ["localhost","127.0.0.1","[::1]"]){
    const h=harness({location:{hostname}});h.configure({deployment:"local",hermes_url:"http://127.0.0.1:8642"});
    const form=h.form;form.elements["#hermes-key"].value="synthetic-key";await form.submit();
    assert.deepEqual(h.requests,[{path:"/api/connection",method:"POST",body:{url:"http://127.0.0.1:8642",key:"synthetic-key"}}]);
    assert.equal(form.elements["#hermes-key"].value,"");assert.deepEqual(h.reloads,["status","conversation"]);
  }
});
test("submit rechecks live deployment, host, opt-in, and replaced form before any request",async()=>{
  for(const mutate of [h=>h.state.deployment="cloud",h=>h.location.hostname="evil.invalid",h=>h.location.search="",h=>h.configure({deployment:"cloud"})]){
    const h=harness();h.configure({deployment:"local"});const old=h.form;mutate(h);await old.submit();assert.equal(h.requests.length,0);
  }
});
test("pending submission cannot repeat and a late identity reply cannot display success",async()=>{
  let resolve;const h=harness({},()=>new Promise(r=>{resolve=r;}));h.configure({deployment:"local"});const form=h.form;
  form.elements["#hermes-key"].value="synthetic-key";const first=form.submit();await form.submit();assert.equal(h.requests.length,1);
  h.state.identityEpoch++;resolve();await first;
  assert.equal(h.reloads.length,0);assert.notEqual(form.elements["#connection-feedback"].textContent,"开发服务已连接。");assert.equal(form.elements["#hermes-key"].value,"");
});
test("failure never echoes raw diagnostic/credential and closing or replacing clears the key",async()=>{
  const h=harness({},()=>{throw Error("synthetic-key internal debug");});h.configure({deployment:"local"});const form=h.form;
  form.elements["#hermes-key"].value="synthetic-key";await form.submit();assert.equal(form.elements["#hermes-key"].value,"");
  assert.equal(form.elements["#connection-feedback"].textContent.includes("synthetic-key"),false);
  form.elements["#hermes-key"].value="synthetic-key";h.close();assert.equal(form.elements["#hermes-key"].value,"");
  form.elements["#hermes-key"].value="synthetic-key";h.configure({deployment:"cloud"});assert.equal(form.elements["#hermes-key"].value,"");assert.equal(h.form,null);
});
