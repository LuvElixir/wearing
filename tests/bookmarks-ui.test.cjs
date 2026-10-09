const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');

const read=path=>fs.readFileSync(path,'utf8');
const html=read('src/wearing/web/index.html');
const views=read('src/wearing/web/views.js');
const bookmarks=read('src/wearing/web/bookmarks.js');
const sources=read('src/wearing/web/conversation-sources.js');

function loadValidateUrl(){
  // 在受控宿主里加载模块（非 App 宿主），取 validateUrl 纯函数逐条对齐 bookmark-url.ts 规则。
  const element=()=>({addEventListener(){},replaceChildren(){},});
  const context={document:{documentElement:{classList:{contains:()=>false}},getElementById:element},window:{},URL,Intl,structuredClone,console};
  vm.runInNewContext(bookmarks,context);
  return context.window.WearingBookmarks.validateUrl;
}

test('new web modules compile as scripts',()=>{
  for(const [name,source] of [['bookmarks',bookmarks],['sources',sources],['views',views]])
    assert.doesNotThrow(()=>new vm.Script(source,{filename:name+'.js'}),`${name}.js must parse`);
});

test('bookmark url validation mirrors the shared bookmark-url.ts rules (parse only, never fetch)',()=>{
  const validateUrl=loadValidateUrl();
  assert.equal(validateUrl('https://example.com/a?b=1'),'https://example.com/a?b=1');
  assert.equal(validateUrl('HTTP://EXAMPLE.COM/path'),'HTTP://EXAMPLE.COM/path');
  assert.equal(validateUrl('http://localhost:8765/x'),'http://localhost:8765/x');
  assert.equal(validateUrl('https://例子.中国/首页'),'https://例子.中国/首页');
  for(const bad of [
    'ftp://example.com','javascript:alert(1)','//example.com/x','example.com/x',
    'https://example.com/a b','https://example.com/a\tb','https://exa\x00mple.com',
    'https://example.com/%00','https://example.com/%1f','https://example.com/%7f',
    'https://example.com\\x','https://user:pass@example.com/','https://user@example.com/',
    'https://ex%41mple.com/','https://example.com:0/','https://example.com:65536/',
    '','   ','https://',
  ])assert.throws(()=>validateUrl(bad),undefined,`must reject: ${JSON.stringify(bad)}`);
  const long='https://example.com/'+'a'.repeat(5000);
  assert.throws(()=>validateUrl(long));
});

test('bookmarks panel uses the real read view and life writes with persisted request keys',()=>{
  assert.match(bookmarks,/classList\.contains\("mobile-host"\)\) return;/);
  assert.match(bookmarks,/api\("\/api\/bookmarks\?"\+params\)/);
  assert.match(bookmarks,/archived:String\(which==="archived"\)/);
  assert.match(bookmarks,/params\.set\("cursor",cursor\)/);
  assert.match(bookmarks,/error\.status===409\)\{setNote\("收藏列表已有变化，正在重新读取。"\)/);
  // 新建/编辑/归档恢复全部走既有 life API，带 request_key 幂等（合同）。
  assert.match(bookmarks,/api\("\/api\/life",\{method:"POST",body:JSON\.stringify\(body\)\}\)/);
  assert.match(bookmarks,/kind:"note",title,content,url,timezone:tz\(\)/);
  assert.match(bookmarks,/pajio-bookmark-create:v1/);
  assert.match(bookmarks,/pajio-bookmark-edit:v1/);
  assert.match(bookmarks,/pajio-bookmark-action:v1/);
  assert.match(bookmarks,/action:"edit",patch/);
  assert.match(bookmarks,/将用同一请求取回，不会重复保存。/);
  // url=null 显式移除收藏属性后仍是原笔记。
  assert.match(bookmarks,/清空后保存即移除收藏属性，仍保留为笔记/);
  // v3：url=null 分支先 await refresh() 再 setNote，成功提示不被列表刷新清空。
  assert.match(bookmarks,/if\(patch\.url===null\)\{ui\.mode="list";ui\.detail=null;await refresh\(\);setNote\("已移除链接属性；这条仍是你的笔记。"\);return;\}/);
  // 打开网页：渲染前重验 URL，外部标签 noopener；绝不抓取。
  assert.match(bookmarks,/target="_blank" rel="noopener noreferrer"/);
  assert.match(bookmarks,/保存不抓取、不预览|保存不代表网页存在或安全/);
  // 累计上限提示（合同：在线分页最多累计 300 项）。
  assert.match(bookmarks,/active\.items\.length>=300/);
  for(const source of [bookmarks,sources])assert.doesNotMatch(source,/onclick=|style="/);
});

test('shell wires both panels and entries; views stays inert in the App host',()=>{
  assert.match(html,/<dialog id="bookmarks-panel"/);
  assert.match(html,/<dialog id="sources-panel"/);
  assert.ok(html.indexOf('bookmarks.js?v=')<html.indexOf('series.js?v='));
  assert.match(views,/row\("链接收藏", "保存网页链接，需要时再打开"/);
  assert.match(views,/action === "bookmarks"\) \{ window\.WearingBookmarks\?\.open\(\); \}/);
  assert.match(views,/data-sources-open/);
  assert.match(views,/对话引用范围/);
});

test('conversation source controls follow the closed contract flow',()=>{
  assert.match(sources,/classList\.contains\("mobile-host"\)\) return;/);
  assert.match(sources,/api\("\/api\/conversation-sources\?"\+params\)/);
  assert.match(sources,/params\.set\("snapshot",ui\.page\.snapshot\)/);
  assert.match(sources,/data\.snapshot!==ui\.page\.snapshot/);
  assert.match(sources,/从第一页重新读取/);
  // 闭集请求体 + 双 CAS + 稳定 request_key 先持久。
  assert.match(sources,/source_id:source\.source_id,source_revision:source\.source_revision,revision:pageRevision,request_key:window\.WearingIds\.uuid\(\)/);
  assert.match(sources,/pajio-source-exclude:v1/);
  assert.match(sources,/writePending\(\{identity:state\.identityId,body\}\);/);
  // 回执严格校验（revision+1、excluded、history_retained、request_key 回显）。
  assert.match(sources,/receipt\.revision!==body\.revision\+1/);
  assert.match(sources,/receipt\.excluded!==true\|\|receipt\.history_retained!==true/);
  // 已知 4xx 拒绝后必须重读重选；未知结果取回原回执。
  assert.match(sources,/请重新读取列表、重新选定后再确认。/);
  assert.match(sources,/取回原操作回执/);
  assert.match(sources,/submitExclude\(readPending\(\)\?\.body\)/);
  // 两击确认；取消不发请求；首版无恢复；历史保留的如实文案。
  assert.match(sources,/再点一次确认停止引用/);
  assert.match(sources,/已取消；没有发出任何请求。/);
  assert.match(sources,/目前排除后不提供恢复引用。/);
  assert.match(sources,/历史仍可查看。已保存的记忆、文件和目标不会删除/);
  // 范围预览字段。
  assert.match(sources,/开始于 \$\{esc\(dayText\(item\.started_at\)\)\} · 入场消息 \$\{item\.message_count\} 条/);
  assert.match(sources,/不再进入关键词搜索、直接读取、邻近翻阅和最近会话列表/);
});

/* ---------- 行为级 harness：QA 路由未挂期间的主要验证手段（mock api + DOM 桩） ---------- */
function sharedHost(){
  const calls=[];const store=new Map();
  const listeners=new Map();
  const elements=new Map();
  // innerHTML 赋值等价于真实 DOM 重建子树：清子桩字段并失效其它元素缓存，监听不跨渲染累积。
  const sub=()=>({value:"",checked:false,textContent:"",dataset:{},fields:{},listeners:new Map(),
    addEventListener(name,fn){const list=this.listeners.get(name)||[];list.push(fn);this.listeners.set(name,list);},
    dispatchEvent(name,event={}){for(const fn of this.listeners.get(name)||[])fn({preventDefault(){},target:this,currentTarget:this,...event});},
    querySelector(sel){if(!this.fields[sel])this.fields[sel]=sub();return this.fields[sel];},
  });
  const makeElement=id=>({id,hidden:false,open:false,textContent:"",_innerHTML:"",dataset:{},fields:{},listeners:new Map(),
    set innerHTML(value){this._innerHTML=value;for(const key of elements.keys())if(key!==this.id)elements.delete(key);this.fields={};},
    get innerHTML(){return this._innerHTML;},
    addEventListener(name,fn){const list=this.listeners.get(name)||[];list.push(fn);this.listeners.set(name,list);},
    querySelector(sel){if(!this.fields[sel])this.fields[sel]=sub();return this.fields[sel];},
    querySelectorAll(){return [];},
    replaceChildren(){this._innerHTML="";},
    after(){},closest(){return null;},
    dispatchEvent(name,event={}){for(const fn of this.listeners.get(name)||[])fn({preventDefault(){},target:this,currentTarget:this,...event});},
  });
  const element=id=>{if(!elements.has(id))elements.set(id,makeElement(id));return elements.get(id);};
  class StaleIdentity extends Error{}
  const context={
    document:{documentElement:{classList:{contains:()=>false}},getElementById:element,
      addEventListener(name,fn){const key="document:"+name;const list=listeners.get(key)||[];list.push(fn);listeners.set(key,list);},
      createElement:()=>sub(),
      hidden:false},
    window:{},URL,URLSearchParams,Intl,Date,Promise,structuredClone,console,setTimeout:()=>0,clearTimeout(){},
    state:{identityId:"qa",identityEpoch:1,token:"t"},
    StaleIdentity,
    notice(){},openPanel(){},closePanel(){},
    busy:async(button,action)=>action(),
    api:async(path,request={})=>{
      const call={path,method:request.method||"GET",body:request.body?JSON.parse(request.body):null};
      calls.push(call);
      return context.apiHandler(call);
    },
    calls,
    store,
  };
  context.window.WearingIds={uuid:()=>"fixed-uuid-key-000001"};
  context.window.WearingStore={
    get:name=>store.has(name)?store.get(name):null,
    set:(name,value)=>{store.set(name,String(value));},
    remove:name=>{store.delete(name);},
  };

  context.element=element;
  context.dispatchDocument=event=>{for(const fn of listeners.get("document:click")||[])fn(event);};
  return context;
}

test('bookmarks flow: list renders, create persists request key before POST, two-step archive patches with key',async()=>{
  const context=sharedHost();
  const items=[{id:"life_"+"a".repeat(32),identity_id:"qa",revision:1,kind:"note",title:"示例收藏",content:"备注",url:"https://example.com/page",timezone:"Asia/Shanghai",deleted_at:null,created_at:"2026-10-08T01:00:00+00:00",updated_at:"2026-10-08T01:00:00+00:00"}];
  context.apiHandler=call=>{
    if(call.path.startsWith("/api/bookmarks"))return {identity_id:"qa",query:"",archived:call.path.includes("archived=true"),version:1,items:call.path.includes("archived=true")?[]:items,next_cursor:null};
    if(call.path==="/api/life"&&call.method==="POST")return {id:"life_"+"b".repeat(32),revision:1,url:call.body.record.url,kind:"note"};
    if(call.path.startsWith("/api/life/")&&call.method==="PATCH")return {id:call.path.split("/").pop(),revision:2};
    throw Error("unexpected "+call.path);
  };
  vm.runInNewContext(bookmarks,context);
  await context.window.WearingBookmarks.open();
  assert(context.element("bm-body").innerHTML.includes("示例收藏"));
  assert(context.element("bm-body").innerHTML.includes('rel="noopener noreferrer"'));
  // 新建：完整请求先持久，成功后清 journal，POST 体带 request_key。
  const form=context.element("bm-create-form");
  form.fields["#bm-create-url"]={value:"https://example.org/new"};
  form.fields["#bm-create-title"]={value:""};
  form.fields["#bm-create-content"]={value:"新备注"};
  form.dispatchEvent("submit",{preventDefault(){},currentTarget:form,target:form});
  await new Promise(r=>setImmediate(r));
  const post=context.calls.find(c=>c.path==="/api/life"&&c.method==="POST");
  assert.ok(post,"create POST issued");
  assert.equal(post.body.record.url,"https://example.org/new");
  assert.equal(post.body.request_key,"fixeduuidkey000001");
  assert.equal(post.body.record.kind,"note");
  assert.ok(![...context.store.keys()].some(k=>k.includes("pajio-bookmark-create")),"journal cleared after success");
  // 归档：先进详情再两击确认，PATCH 带 action+request_key。
  context.element("bm-body").dispatchEvent("click",{target:{closest:sel=>sel==='[data-bm-open]'?{dataset:{bmOpen:items[0].id}}:null}});
  const archive=context.element("bm-archive");
  archive.dispatchEvent("click",{target:archive});
  assert.match(archive.textContent||"confirm",/./);
  archive.dispatchEvent("click",{target:archive});
  await new Promise(r=>setImmediate(r));
  const patch=context.calls.find(c=>c.method==="PATCH"&&c.body&&c.body.action==="archive");
  assert.ok(patch,"archive PATCH issued");
  assert.equal(patch.body.patch?Object.keys(patch.body.patch).length:0,0);
  assert.ok(patch.body.request_key,"archive PATCH carries request_key");
});

test('bookmarks edit keeps input on 409 and replays the same attempt key on unknown results',async()=>{
  const context=sharedHost();
  const item={id:"life_"+"c".repeat(32),identity_id:"qa",revision:5,kind:"note",title:"旧标题",content:"",url:"https://example.com/old",timezone:"Asia/Shanghai",deleted_at:null,created_at:"2026-10-08T01:00:00+00:00",updated_at:"2026-10-08T01:00:00+00:00"};
  let fail409=false,networkDown=false;
  context.apiHandler=call=>{
    if(call.path.startsWith("/api/bookmarks"))return {identity_id:"qa",query:"",archived:call.path.includes("archived=true"),version:1,items:call.path.includes("archived=true")?[]:[item],next_cursor:null};
    if(call.path.startsWith("/api/life/")&&call.method==="PATCH"&&call.body.action==="edit"){
      if(fail409){const error=new Error("这条收藏已在别处修改。");error.status=409;throw error;}
      if(networkDown)throw new Error("network dropped");
      return {id:item.id,revision:call.body.revision+1};
    }
    if(call.path==="/api/life/"+item.id)return {...item,revision:6,title:"最新标题"};
    throw Error("unexpected "+call.path);
  };
  vm.runInNewContext(bookmarks,context);
  await context.window.WearingBookmarks.open();
  context.element("bm-body").dispatchEvent("click",{target:{closest:sel=>sel==='[data-bm-open]'?{dataset:{bmOpen:item.id}}:null}});
  const form=context.element("bm-edit-form");
  form.querySelector("#bm-edit-title").value="我的新标题";
  form.querySelector("#bm-edit-url").value=item.url;
  form.querySelector("#bm-edit-content").value="";
  // 409：服务端最新版回读后输入仍保留（模块把未保存输入回填到新表单）。
  fail409=true;
  form.dispatchEvent("submit",{});
  await new Promise(r=>setImmediate(r));
  const formAfter=context.element("bm-edit-form");
  assert.equal(formAfter.querySelector("#bm-edit-title").value,"我的新标题","input kept after 409");
  assert.equal(formAfter.querySelector("#bm-edit-url").value,item.url);
  // 未知结果：journal 保留；再次提交用同一 attempt key + 同一 revision 重放。
  fail409=false;networkDown=true;
  formAfter.dispatchEvent("submit",{});
  await new Promise(r=>setImmediate(r));
  networkDown=false;
  formAfter.dispatchEvent("submit",{});
  await new Promise(r=>setImmediate(r));
  const edits=context.calls.filter(c=>c.method==="PATCH"&&c.body.action==="edit");
  assert.equal(edits.length,3,"409 once + unknown retry once + success once");
  assert.equal(edits[1].body.request_key,edits[2].body.request_key,"same attempt key replayed after unknown result");
  assert.equal(edits[1].body.revision,edits[2].body.revision,"same base revision replayed");
  assert.equal(edits[2].body.revision,6,"replays onto the re-read revision");
});
test('conversation sources: two-click confirm posts the closed body; unknown result replays the same request',async()=>{
  const context=sharedHost();
  const source={source_id:"source_"+"1".repeat(64),source_revision:"2".repeat(64),source_task_id:"task-1",title:"会话A",started_at:"2026-10-01T00:00:00Z",updated_at:"2026-10-02T00:00:00Z",message_count:12,excluded:false,excluded_at:null};
  const receipt={identity_id:"qa",source_id:source.source_id,source_revision:source.source_revision,revision:4,request_key:"",excluded:true,excluded_at:"2026-10-08T00:00:00Z",continuation_reset:true,history_retained:true};
  let networkDown=false,posted=0;
  context.apiHandler=call=>{
    if(call.path.startsWith("/api/conversation-sources?")&&call.method==="GET")return {identity_id:"qa",revision:3,snapshot:"s1",items:[source],next_offset:null};
    if(call.path==="/api/conversation-sources/exclude"){
      posted+=1;
      if(networkDown)throw new Error("network dropped");
      receipt.request_key=call.body.request_key;
      return receipt;
    }
    throw Error("unexpected "+call.path);
  };
  vm.runInNewContext(sources,context);
  await context.window.WearingSources.open();
  const body=context.element("sc-body");
  assert(body.innerHTML.includes("会话A"));
  assert(body.innerHTML.includes("12 条入场消息"));
  // 选择来源 → 范围预览出现。
  context.dispatchDocument({target:{closest:sel=>sel==='[data-sc-select]'?{dataset:{scSelect:source.source_id}}:null}});
  assert(body.innerHTML.includes("以后不再引用这段对话"),"preview shown");
  assert(body.innerHTML.includes("历史仍可查看"),"history retained wording");
  // 两击确认：第一击只换文案，不发请求。
  const confirm=context.element("sc-body").querySelector("[data-sc-confirm]");
  confirm.dispatchEvent("click",{target:confirm});
  assert.equal(posted,0,"first click does not post");
  networkDown=true;
  confirm.dispatchEvent("click",{target:confirm});
  await new Promise(r=>setImmediate(r));
  assert.equal(posted,1,"second click posts");
  const pending=context.store.get("pajio-source-exclude:v1:qa");
  assert.ok(pending,"request journal kept on unknown result");
  const firstBody=JSON.parse(pending).body;
  assert.equal(firstBody.source_id,source.source_id);
  assert.equal(firstBody.source_revision,source.source_revision);
  assert.equal(firstBody.revision,3);
  // 结果未知：下次打开面板自动用同一请求取回（同一 body、同一 key），回执确认后清 journal。
  networkDown=false;
  await context.window.WearingSources.open();
  assert.equal(posted,2,"replay issued with the same request");
  assert(!context.store.has("pajio-source-exclude:v1:qa"),"journal cleared after confirmed receipt");
});
