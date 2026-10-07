const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const window={};
vm.runInNewContext(fs.readFileSync('src/wearing/web/conversation-submissions.js','utf8'),{window});
const create=window.WearingSubmissions.create;
function fixture(){const values=new Map();let n=0;const storage={getItem:k=>values.get(k)||null,setItem:(k,v)=>values.set(k,v),removeItem:k=>values.delete(k)};return {storage,make:()=>create(()=>storage,()=>{},()=>`request-${String(++n).padStart(16,'0')}`)};}
test('lost response retries with the same key after page recreation',()=>{
  const h=fixture(),id=h.make().prepare('daily','帮我整理周末计划');
  assert.equal(h.make().prepare('daily','帮我整理周末计划'),id);
});
test('identity and changed content cannot reuse the previous submission',()=>{
  const h=fixture(),s=h.make(),id=s.prepare('daily','同一句话');
  assert.notEqual(s.prepare('overseas','同一句话'),id);
  assert.notEqual(s.prepare('daily','改过的一句话'),id);
});
test('a late acknowledgement cannot clear a newer request',()=>{
  const h=fixture(),s=h.make(),first=s.prepare('daily','第一件'),second=s.prepare('daily','第二件');
  assert.equal(s.acknowledge('daily',first),false);
  assert.equal(h.make().prepare('daily','第二件'),second);
});
test('an acknowledged message can intentionally be sent again with a new key',()=>{
  const h=fixture(),s=h.make(),first=s.prepare('daily','再帮我查一次');
  assert.equal(s.acknowledge('daily',first),true);
  assert.notEqual(h.make().prepare('daily','再帮我查一次'),first);
});
test('storage failure keeps a stable in-page key and reports persistence limits',()=>{
  let warnings=0,counter=0;
  const s=create(()=>{throw Error('storage denied');},()=>warnings++,()=>`request-${String(++counter).padStart(16,'0')}`);
  const id=s.prepare('daily','离线想法');assert.equal(s.prepare('daily','离线想法'),id);assert(warnings>0);
});
test('empty and oversized input fails before storage',()=>{
  const s=create(()=>{throw Error('should not access');});
  assert.throws(()=>s.prepare('','test'));assert.throws(()=>s.prepare('daily',' '));assert.throws(()=>s.prepare('daily','x'.repeat(12001)));
});

test('an acknowledgement in another page cannot erase the newer persisted nonce',()=>{
  const h=fixture(),firstPage=h.make(),secondPage=h.make();
  const first=firstPage.prepare('daily','第一件事');
  const second=secondPage.prepare('daily','第二件事');
  firstPage.acknowledge('daily',first);
  assert.equal(h.make().prepare('daily','第二件事'),second);
});

// Execute the production submit listener and its real API/draft/journal helpers.
// The DOM and fetch boundary are isolated; no backend, real account or task is touched.
function composerHarness(storage=fixture().storage, cryptoSource){
  const elements=new Map(),requests=[],timers=new Map();let id=0,timerId=0,loads=0,scrolls=0;
  function element(name){
    if(elements.has(name))return elements.get(name);
    const listeners=new Map(),classes=new Set();
    const node={value:'',disabled:false,childNodes:[],isConnected:true,hidden:false,textContent:'',className:'',
      classList:{add:name=>classes.add(name),remove:name=>classes.delete(name),toggle:(name,on)=>on?classes.add(name):classes.delete(name)},
      addEventListener:(type,fn)=>{const handlers=listeners.get(type)||[];handlers.push(fn);listeners.set(type,handlers);},
      dispatchEvent:event=>{for(const fn of listeners.get(event.type)||[])fn(event);},
      closest:()=>null,replaceChildren(){},focus(){},scrollIntoView(){},listeners};
    elements.set(name,node);return node;
  }
  const window={addEventListener(){},WearingLife:{renderContext(){}},WearingActivity:{load(){}}};
  const context={window,localStorage:storage,Event,
    document:{getElementById:element,querySelector:()=>element('dock'),addEventListener(){},dispatchEvent(){}},
    matchMedia:()=>({matches:false}),
    crypto:cryptoSource ?? {randomUUID:()=>`request-${String(++id).padStart(16,'0')}`},
    setTimeout:fn=>{timers.set(++timerId,fn);return timerId;},clearTimeout:key=>timers.delete(key),
    updateCompanion(){},renderGoalContext(){},loadConversation:async()=>{loads++;},scrollToLatest:()=>{scrolls++;},
    fetch:(path,options)=>new Promise((resolve,reject)=>requests.push({path,options,resolve,reject})),
  };
  vm.createContext(context);
  for(const file of ['request-id.js','conversation-drafts.js','conversation-submissions.js'])vm.runInContext(fs.readFileSync('src/wearing/web/'+file,'utf8'),context);
  const app=fs.readFileSync('src/wearing/web/app.js','utf8');
  const helpers=app.slice(0,app.indexOf('function nearBottom()'));
  const drafts=app.slice(app.indexOf('let composerReady=false'),app.indexOf('function turnActions('));
  const handler=app.slice(app.indexOf('$("conversation-form").addEventListener("submit"'),app.indexOf('$("message-input").addEventListener("keydown"'));
  assert(helpers&&drafts&&handler,'submit production seams must be available');
  vm.runInContext(helpers+'\n'+drafts+'\n'+handler+'\nglobalThis.h={state,activateComposer,composerDrafts,conversationSubmissions};',context);
  const h=context.h,input=element('message-input');h.activateComposer({identity:'daily'});
  return {h,input,requests,storage,element,get loads(){return loads;},get scrolls(){return scrolls;},
    write(value){input.value=value;input.dispatchEvent(new Event('input'));},
    submit:()=>element('conversation-form').listeners.get('submit')[0]({preventDefault(){}}),
    reply(index,data={delivery:'queued',task:{id:'synthetic-task'}},status=200){requests[index].resolve({ok:status>=200&&status<300,status,json:async()=>data});},
    persisted(c={identity:'daily'}){return window.WearingDrafts.create(()=>storage).read(c);},
    nonce(content,identity='daily'){return window.WearingSubmissions.create(()=>storage,()=>{},()=>`request-${String(++id).padStart(16,'0')}`).prepare(identity,content);},
  };
}

test('LAN WebView without randomUUID sends successfully and preserves idempotency on retry',async()=>{
  const h=composerHarness(undefined,{getRandomValues:bytes=>require('node:crypto').randomFillSync(bytes)});
  h.write('你好，做个自我介绍。');const pending=h.submit();
  assert.equal(h.requests.length,1);
  const request=JSON.parse(h.requests[0].options.body);
  assert.match(request.request_id,/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
  h.requests[0].reject(Error('response lost'));await pending;
  assert.equal(h.input.value,'你好，做个自我介绍。');
  const retry=h.submit();assert.equal(JSON.parse(h.requests[1].options.body).request_id,request.request_id);
  h.reply(1);await retry;assert.equal(h.input.value,'');
});

test('missing Web Crypto preserves the draft without issuing a request',async()=>{
  const h=composerHarness(undefined,{});h.write('保留这段输入');await h.submit();
  assert.equal(h.requests.length,0);assert.equal(h.input.value,'保留这段输入');
  assert.equal(h.persisted().text,'保留这段输入');assert.match(h.element('notice').textContent,/输入仍然保留/);
});

test('HTTP errors preserve exact input, saved draft, and request identity for retry',async()=>{
  for(const status of [400,409,422,500,503]){
    const h=composerHarness();h.write('  帮我整理周末计划\n');
    const first=h.submit(),request=JSON.parse(h.requests[0].options.body);
    assert.equal(request.content,'帮我整理周末计划');assert.ok(request.request_id);
    h.reply(0,{detail:'尚未接受这条消息'},status);await first;
    assert.equal(h.input.value,'  帮我整理周末计划\n');
    assert.equal(h.persisted().text,h.input.value);assert.equal(h.h.state.sending,false);
    assert.equal(h.element('send-message').disabled,false);assert.equal(h.element('open-identities').disabled,false);
    assert.equal(h.loads,0);
    const retry=h.submit();assert.equal(JSON.parse(h.requests[1].options.body).request_id,request.request_id);
    h.reply(1);await retry;assert.equal(h.input.value,'');assert.equal(h.persisted(),null);
  }
});

test('lost and non-JSON responses keep the nonce available after page recreation',async()=>{
  for(const failure of ['lost','non-json']){
    const h=composerHarness();h.write('不要丢掉这句话');const pending=h.submit();
    const nonce=JSON.parse(h.requests[0].options.body).request_id;
    if(failure==='lost')h.requests[0].reject(Error('response lost'));
    else h.requests[0].resolve({ok:true,status:200,json:async()=>{throw Error('not JSON');}});
    await pending;
    assert.equal(h.input.value,'不要丢掉这句话');assert.equal(h.persisted().text,h.input.value);
    assert.equal(h.nonce(h.input.value),nonce);
  }
});

test('an empty successful HTTP envelope cannot acknowledge a message or discard its input',async()=>{
  for(const body of [null,{},[]]){
    const h=composerHarness();h.write('还没有拿到保存回执');const pending=h.submit();
    const nonce=JSON.parse(h.requests[0].options.body).request_id;
    h.reply(0,body);await pending;
    assert.equal(h.input.value,'还没有拿到保存回执');assert.equal(h.persisted().text,h.input.value);
    assert.equal(h.nonce(h.input.value),nonce);assert.equal(h.loads,0);
  }
});

test('two concurrent submit events issue one POST and one successful draft acknowledgement',async()=>{
  const h=composerHarness();h.write('只提交一次');const first=h.submit();
  await h.submit();assert.equal(h.requests.length,1);assert.equal(h.h.state.sending,true);
  assert.equal(h.element('open-identities').disabled,true);
  h.reply(0);await first;assert.equal(h.loads,1);assert.equal(h.scrolls,1);assert.equal(h.input.value,'');
});

test('retrying a remotely withdrawn submission reports withdrawal instead of promising execution',async()=>{
  const h=composerHarness();h.write('此前从另一端撤回');const pending=h.submit();
  h.reply(0,{delivery:'saved',queue_state:'cancelled',task:{id:'withdrawn-task'}});await pending;
  assert.equal(h.element('notice').textContent,'这条此前已撤回，没有开始执行。');
  assert.equal(h.input.value,'');assert.equal(h.requests.length,1);
});

test('a late successful response preserves newer typing even before its debounce saves',async()=>{
  const h=composerHarness();h.write('已经发送的第一条');const pending=h.submit();
  h.write('正在输入的第二条\n还没写完');h.reply(0);await pending;
  assert.equal(h.input.value,'正在输入的第二条\n还没写完');assert.equal(h.persisted().text,h.input.value);
  assert.equal(h.requests.length,1);
});

test('a late response clears only the submitted context and preserves an active goal draft',async()=>{
  const h=composerHarness();h.write('普通聊天');const pending=h.submit();
  const goal={identity:'daily',goal:{id:'goal-a',objective:'周末计划',revision:3,mode:'note'}};
  h.h.activateComposer(goal);h.write('目标的新情况');h.reply(0);await pending;
  assert.equal(h.input.value,'目标的新情况');assert.equal(h.persisted(goal).text,'目标的新情况');assert.equal(h.persisted(),null);
});

test('an identity epoch change prevents old success from clearing either identity input',async()=>{
  const h=composerHarness();h.write('日常身份的输入');const pending=h.submit();
  assert.equal(h.requests[0].options.headers['X-Wearing-Identity'],'daily');
  const firstId=JSON.parse(h.requests[0].options.body).request_id;
  // Force a host-level identity transition to verify the defensive API epoch guard.
  h.h.state.identityId='overseas';h.h.state.identityEpoch++;h.h.activateComposer({identity:'overseas'});h.write('另一个身份的新输入');
  h.reply(0);await pending;
  assert.equal(h.input.value,'另一个身份的新输入');assert.equal(h.persisted().text,'日常身份的输入');
  assert.equal(h.nonce('日常身份的输入'),firstId);assert.equal(h.loads,0);
});
