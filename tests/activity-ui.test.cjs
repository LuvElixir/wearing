const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');

const source=fs.readFileSync('src/wearing/web/activity.js','utf8');
const flush=()=>new Promise(resolve=>setImmediate(resolve));
function deferred(){let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};}
function result(id='task-a',changes={}){return {task_id:id,version:'version-'+id,bucket:'results',unread:true,label:'已有回应',title:'一份可核对的结果',summary:'先看看结果，再决定下一步。',...changes};}
function activity(items=[result()],changes={}){
  return {items,total:items.length,unread:items.filter(item=>item.unread).length,
    counts:Object.fromEntries(['attention','active','waiting','results'].map(bucket=>[bucket,items.filter(item=>item.bucket===bucket).length])),
    checked_at:'2026-10-06T12:00:00Z',has_more:false,...changes};
}
function setup(options={}){
  const nodes=new Map(),events=[],calls=[],notices=[],classes=new Set();
  class Element{
    constructor(id){this.id=id;this.hidden=false;this.open=false;this.textContent='';this.html='';this.writes=0;this.listeners=new Map();this.details={open:false};}
    set innerHTML(value){this.html=value;this.writes++;}
    get innerHTML(){return this.html;}
    addEventListener(name,fn,opts){const list=this.listeners.get(name)||[];list.push({fn,once:opts?.once});this.listeners.set(name,list);}
    emit(name){const list=[...(this.listeners.get(name)||[])];this.listeners.set(name,list.filter(item=>!item.once));list.forEach(item=>item.fn());}
    replaceChildren(){this.innerHTML='';}
    closest(selector){return selector==='details'?this.details:null;}
    scrollIntoView(){events.push('scroll:'+this.id);}
    focus(){events.push('focus:'+this.id);}
    close(){this.open=false;events.push('closed:'+this.id);this.emit('close');}
  }
  const element=id=>{if(!nodes.has(id))nodes.set(id,new Element(id));return nodes.get(id);};
  for(const id of ['activity-panel','activity-return','activity-return-title','activity-return-detail','activity-updated','activity-error','activity-list','activity-more','open-activity','activity-refresh','keeps-panel','keep-detail'])element(id);
  const state={identityId:'daily',identityEpoch:1,token:'test',motionPaused:true};
  class StaleIdentity extends Error{}
  const h={state,nodes,element,events,calls,notices,classes,current:options.data||activity(),apiHandler:null,conversationHandler:null,keepHandler:null};
  const context={state,window:{WearingLife:{openView:view=>events.push('view:'+view)}},Date,Intl,Promise,StaleIdentity,
    document:{getElementById:id=>nodes.get(id)||null,body:{classList:{add:key=>classes.add(key),remove:key=>classes.delete(key)}}},
    $:element,esc:value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char])),
    notice:(message,error)=>notices.push({message,error}),busy:async(_,fn)=>fn(),
    openPanel:id=>{element(id).open=true;events.push('open:'+id);},
    closePanel:id=>{events.push('close-request:'+id);if(!options.deferClose)element(id).close();},
    api:async(path,request={})=>{
      const epoch=state.identityEpoch,call={path,method:request.method||'GET',body:request.body?JSON.parse(request.body):null,identity:state.identityId};
      calls.push(call);events.push('api:'+call.method+':'+path);
      let data;
      if(h.apiHandler)data=await h.apiHandler(call);
      else if(path==='/api/activity')data=h.current;
      else if(path==='/api/activity/seen')data=activity(h.current.items.map(item=>request.body.includes(item.task_id)?{...item,unread:false}:item));
      else throw Error('Unexpected API action: '+path);
      // Match app.js: a transport rejection happens before the epoch check.
      if(epoch!==state.identityEpoch)throw new StaleIdentity();
      return data;
    },
    loadConversation:async()=>{
      const epoch=state.identityEpoch;events.push('conversation:load');
      if(h.conversationHandler)await h.conversationHandler();
      if(epoch!==state.identityEpoch)throw new StaleIdentity();
    },
    loadKeep:async id=>{
      const epoch=state.identityEpoch;events.push('keep:load:'+id);
      if(h.keepHandler)await h.keepHandler(id);
      if(epoch!==state.identityEpoch)throw new StaleIdentity();
      element('keep-detail').hidden=false;events.push('keep:visible:'+id);
    },
  };
  if(options.realKeep){
    const app=fs.readFileSync('src/wearing/web/app.js','utf8');
    const start=app.indexOf('async function loadKeep(id'),end=app.indexOf('$("conversation-form").addEventListener',start);
    context.researchMarkup=()=>'';context.turnActions=()=>'';
    vm.runInNewContext(app.slice(start,end),context);
  }
  vm.runInNewContext(source,context);
  h.ui=context.window.WearingActivity;h.StaleIdentity=StaleIdentity;
  h.changeIdentity=()=>{state.identityId='overseas';state.identityEpoch++;h.ui.reset();};
  return h;
}
const seenCalls=h=>h.calls.filter(call=>call.path==='/api/activity/seen');

test('accepted waiting work is not presented as a user decision or an engine run',async()=>{
  const queued=result('queue-a',{bucket:'waiting',unread:false,label:'已排队',summary:'已接收排队，尚未开始执行。'});
  const h=setup({data:activity([queued])});await h.ui.load(true);
  assert.equal(h.element('activity-return-title').textContent,'1 件已排队，轮到时继续');
  assert.match(h.element('activity-list').innerHTML,/查看排队/);
  assert(!h.element('activity-list').innerHTML.includes('等你处理'));
  assert(!h.element('activity-list').innerHTML.includes('正在推进'));
  h.current=activity([queued,result('active-a',{bucket:'active',unread:false})]);await h.ui.load(true);
  assert.equal(h.element('activity-return-title').textContent,'1 件正在推进 · 1 件已排队');
  assert.equal(h.calls.filter(call=>call.method!=='GET').length,0);
});

test('activity registers its controls before app globals are initialized',()=>{
  const listeners=new Map();
  const context={window:{},document:{getElementById:id=>({addEventListener:name=>listeners.set(id,name)})}};
  vm.runInNewContext(source,context);
  assert.equal(typeof context.window.WearingActivity.openTask,'function');
  for(const id of ['open-activity','activity-return','activity-refresh','activity-list'])assert.equal(listeners.get(id),'click');
});

test('reading activity escapes content and never starts, retries, or approves a task',async()=>{
  const h=setup({data:activity([result('task-a',{title:'<img onerror="run()">',summary:'<script>run()</script>',label:'<b>结果</b>'})])});
  await h.ui.open();
  assert.equal(h.calls.length,1);assert.equal(h.calls[0].method,'GET');assert.equal(h.calls[0].path,'/api/activity');
  const html=h.element('activity-list').innerHTML;
  assert(!html.includes('<img'));assert(!html.includes('<script>'));assert(html.includes('&lt;img'));
  assert(!html.includes('data-action='));assert(!html.includes('data-choice='));assert.equal(seenCalls(h).length,0);
});

test('a result is acknowledged only after the progress panel closes and its own turn gains focus',async()=>{
  const h=setup({deferClose:true});h.element('task-turn-task-a');await h.ui.open();
  const opening=h.ui.openTask('task-a');await flush();
  assert.equal(seenCalls(h).length,0);assert(!h.events.includes('focus:task-turn-task-a'));
  h.element('activity-panel').close();await opening;
  assert(h.events.indexOf('focus:task-turn-task-a')<h.events.indexOf('api:POST:/api/activity/seen'));
  assert.deepEqual(seenCalls(h)[0].body,{items:[{task_id:'task-a',version:'version-task-a'}]});
});

test('a result outside the conversation is acknowledged only after its matching detail loads',async()=>{
  const h=setup(),detail=deferred();h.keepHandler=()=>detail.promise;
  const opening=h.ui.openTask('task-a');await flush();assert.equal(seenCalls(h).length,0);
  detail.resolve();await opening;
  assert(h.events.indexOf('keep:visible:task-a')<h.events.indexOf('api:POST:/api/activity/seen'));
  assert(h.events.includes('scroll:keep-detail'));assert.equal(seenCalls(h).length,1);
});

test('failed detail loading leaves unread results unread',async()=>{
  const h=setup();h.keepHandler=async()=>{throw Error('detail unavailable');};
  await assert.rejects(h.ui.openTask('task-a'),/detail unavailable/);
  assert.equal(seenCalls(h).length,0);assert(h.element('activity-list').innerHTML.includes('activity-unread'));
});

test('attention and active work can be inspected without approval or execution mutations',async()=>{
  for(const bucket of ['attention','active']){
    const h=setup({data:activity([result('task-a',{bucket,unread:false})])});h.element('task-turn-task-a');
    await h.ui.openTask('task-a');assert.equal(seenCalls(h).length,0);
    assert(h.calls.every(call=>call.method==='GET'));assert(h.events.includes('focus:task-turn-task-a'));
  }
});

test('switching identity invalidates the old pending list without blocking the new identity',async()=>{
  const h=setup(),old=deferred();h.apiHandler=call=>call.identity==='daily'?old.promise:activity([result('task-b',{title:'新身份的结果'})]);
  const previous=h.ui.load(true);h.changeIdentity();await h.ui.load(true);
  old.resolve(activity([result('task-a',{title:'旧身份的结果'})]));await previous;
  assert(h.element('activity-list').innerHTML.includes('新身份的结果'));assert(!h.element('activity-list').innerHTML.includes('旧身份的结果'));
});

test('identity switching while a task opens prevents cross-identity focus and seen writes',async()=>{
  const h=setup(),conversation=deferred();h.element('task-turn-task-a');h.conversationHandler=()=>conversation.promise;
  const opening=h.ui.openTask('task-a');await flush();h.changeIdentity();conversation.resolve();
  await assert.rejects(opening,h.StaleIdentity);assert.equal(seenCalls(h).length,0);assert(!h.events.includes('focus:task-turn-task-a'));
});

test('a failed old-identity acknowledgement cannot show feedback in the new identity',async()=>{
  const h=setup(),ack=deferred();h.element('task-turn-task-a');
  h.apiHandler=call=>call.method==='POST'?ack.promise:h.current;
  const opening=h.ui.openTask('task-a');await flush();assert.equal(seenCalls(h).length,1);
  h.changeIdentity();ack.reject(Error('network disconnected'));await opening;
  assert.equal(h.notices.length,0);assert.equal(h.element('activity-list').innerHTML,'');
});

test('a late background GET cannot restore unread state after a seen acknowledgement',async()=>{
  const h=setup(),conversation=deferred(),oldRead=deferred();h.element('task-turn-task-a');
  h.conversationHandler=()=>conversation.promise;let reads=0;
  h.apiHandler=call=>call.method==='POST'?activity([result('task-a',{unread:false})]):++reads===2?oldRead.promise:h.current;
  const opening=h.ui.openTask('task-a');await flush();const background=h.ui.load(true);await flush();
  conversation.resolve();await opening;oldRead.resolve(h.current);await background;
  assert(!h.element('activity-list').innerHTML.includes('activity-unread'));assert(!h.element('activity-return-title').textContent.includes('新结果'));
});

test('the latest requested task keeps focus when an earlier task loads more slowly',async()=>{
  const h=setup({data:activity([result('task-a'),result('task-b')])}),first=deferred(),second=deferred();
  h.element('task-turn-task-a');h.element('task-turn-task-b');let opens=0;
  h.conversationHandler=()=>++opens===1?first.promise:second.promise;
  const openingA=h.ui.openTask('task-a');await flush();
  const openingB=h.ui.openTask('task-b');await flush();second.resolve();await openingB;
  first.resolve();await openingA;
  assert.deepEqual(h.events.filter(event=>event.startsWith('focus:')),['focus:task-turn-task-b']);
  assert.deepEqual(seenCalls(h).map(call=>call.body.items[0].task_id),['task-b']);
});

test('a slower earlier fallback cannot replace the latest selected task detail',async()=>{
  const h=setup({realKeep:true,data:activity([result('task-a'),result('task-b')])}),first=deferred(),second=deferred();
  h.apiHandler=call=>call.path==='/api/tasks/task-a'?first.promise:call.path==='/api/tasks/task-b'?second.promise:h.current;
  const openingA=h.ui.openTask('task-a');await flush();
  const openingB=h.ui.openTask('task-b');await flush();
  second.resolve({id:'task-b',title:'最新选择 B',prompt:'B',events:[]});await openingB;
  first.resolve({id:'task-a',title:'较早选择 A',prompt:'A',events:[]});await openingA;
  assert(h.element('keep-detail').innerHTML.includes('最新选择 B'));
  assert(!h.element('keep-detail').innerHTML.includes('较早选择 A'));
  assert.deepEqual(seenCalls(h).map(call=>call.body.items[0].task_id),['task-b']);
});

test('disconnect preserves old work with an honest timestamp and recovery does not rebuild unchanged controls',async()=>{
  const h=setup();await h.ui.load(true);const before=h.element('activity-list').innerHTML,writes=h.element('activity-list').writes;
  h.ui.disconnected();assert.equal(h.element('activity-list').innerHTML,before);
  assert.match(h.element('activity-return-title').textContent,/连接中断/);assert.match(h.element('activity-updated').textContent,/上次查看/);
  h.current={...h.current,checked_at:'2026-10-06T12:05:00Z'};await h.ui.load(true);
  assert.equal(h.element('activity-error').textContent,'');assert.match(h.element('activity-updated').textContent,/读取于/);
  assert.equal(h.element('activity-list').writes,writes);
});

test('conversation polling failure also marks activity as disconnected',async()=>{
  const app=fs.readFileSync('src/wearing/web/app.js','utf8');
  const start=app.indexOf('async function pollConversation(){'),end=app.indexOf('setInterval(pollConversation,3000);',start);
  let stale=0;const context={state:{identityEpoch:1,token:'test',connected:true,polling:false,lastStatus:Date.now()},
    window:{WearingActivity:{disconnected:()=>stale++}},document:{hidden:false},Date,StaleIdentity:class extends Error{},
    loadConversation:async()=>{throw Error('offline');},updateCompanion(){},$:()=>({textContent:'',classList:{remove(){}}})};
  vm.createContext(context);vm.runInContext(app.slice(start,end),context);await context.pollConversation();
  assert.equal(stale,1);assert.equal(context.state.connected,false);assert.equal(context.state.polling,false);
});

test('an old-identity polling rejection cannot mark the current identity offline',async()=>{
  const app=fs.readFileSync('src/wearing/web/app.js','utf8');
  const start=app.indexOf('async function pollConversation(){'),end=app.indexOf('setInterval(pollConversation,3000);',start);
  const conversation=deferred();let stale=0;
  const context={state:{identityEpoch:1,token:'test',connected:true,polling:false,lastStatus:Date.now()},
    window:{WearingActivity:{disconnected:()=>stale++}},document:{hidden:false},Date,StaleIdentity:class extends Error{},
    loadConversation:()=>conversation.promise,updateCompanion(){},$:()=>({textContent:'',classList:{remove(){}}})};
  vm.createContext(context);vm.runInContext(app.slice(start,end),context);
  const poll=context.pollConversation();context.state.identityEpoch=2;conversation.reject(Error('old request disconnected'));await poll;
  assert.equal(stale,0);assert.equal(context.state.connected,true);
});
