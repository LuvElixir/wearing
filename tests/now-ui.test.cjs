const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync('src/wearing/web/now.js','utf8');
const payload={id:'voice-01234567-89ab-cdef-0123-456789abcdef',identity:'daily',text:'周末想出去走走。'};
function setup({ready=true,blocked=false,receipts=new Map(),initial='原有草稿',identity='daily',topic=null}={}){
  const events={},classes=new Set(),notices=[],clicks=[],activityTasks=[],inputEvents=[];
  const input={value:initial,dispatchEvent(event){inputEvents.push(event.type);},focus(){}};
  const dock={classList:{add:x=>classes.add(x)}};
  const element={addEventListener(){},close(){},click(){clicks.push("panel");}};
  const context={window:{WearingHost:{},WearingActivity:{openTask:async id=>{activityTasks.push(id);}}},state:{identityId:identity,identityEpoch:1,topic},composerReady:ready,draftStorageWarning:blocked,Event,
    document:{getElementById:id=>id==='message-input'?input:element,querySelector:()=>dock,addEventListener:(name,cb)=>{const previous=events[name];events[name]=()=>{previous?.();cb();};}},
    localStorage:{getItem:key=>{if(blocked||context.failRead)throw Error();return receipts.get(key);},setItem:(key,value)=>{if(blocked||context.failJournal||(context.failReceipt&&JSON.parse(value).status==='received'))throw Error();receipts.set(key,value);}},
    composerContext(){return {identity:context.state.identityId,goal:context.state.topic};},
    rememberComposer(){if(context.failDraft)return false;context.saved=input.value;return !blocked;},publishComposer(){context.published=(context.published||0)+1;},notice:text=>notices.push(text)};
  context.window.WearingStore={mode:"local",scope:null,backend:context.localStorage||{getItem:()=>null,setItem:()=>{},removeItem:()=>{}},key:name=>name};
  vm.createContext(context);vm.runInContext(source,context);
  return {context,input,classes,events,notices,clicks,activityTasks,inputEvents,receive:context.window.WearingHost.receiveVoice};
}
test('speech appends literal text without replacing the saved draft',()=>{
  const h=setup();h.receive({...payload,text:'<script>not code</script>'});
  assert.equal(h.input.value,'原有草稿\n<script>not code</script>');assert.equal(h.context.saved,h.input.value);assert(h.classes.has('native-text-open'));
});
test('delivery waits for identity and draft restoration',()=>{
  const h=setup({ready:false});h.receive(payload);assert.equal(h.input.value,'原有草稿');
  h.context.composerReady=true;h.events['wearing-composer-ready']();assert.equal(h.input.value,'原有草稿\n'+payload.text);
});
test('replay is deduplicated across page recreation and storage failure',()=>{
  const receipts=new Map(),h=setup({receipts});h.receive(payload);h.receive(payload);assert.equal(h.input.value,'原有草稿\n'+payload.text);
  const next=setup({receipts});next.receive(payload);assert.equal(next.input.value,'原有草稿');
  const blocked=setup({blocked:true});blocked.receive(payload);blocked.receive(payload);assert.equal(blocked.input.value,'原有草稿\n'+payload.text);
});
test('foreign, empty and oversized speech cannot enter the input',()=>{
  const h=setup();for(const change of [{identity:'other'},{id:'untrusted'},{text:' '},{text:'x'.repeat(12001)}])h.receive({...payload,...change});assert.equal(h.input.value,'原有草稿');
  h.input.value='x'.repeat(11999);h.receive(payload);assert.equal(h.input.value.length,11999);assert(h.notices.at(-1).includes('太长'));
});

test('native review opens only known panels after bootstrap and once per gesture',()=>{
  const h=setup({ready:false}),open=h.context.window.WearingHost.openReview;
  open({id:1,target:'files'});assert.equal(h.clicks.length,0);
  h.context.composerReady=true;h.events['wearing-composer-ready']();assert.equal(h.clicks.length,1);
  open({id:1,target:'files'});open({id:2,target:'constructor'});open({id:3,target:'unknown'});assert.equal(h.clicks.length,1);
  open({id:4,target:'goals'});assert.equal(h.clicks.length,2);
});

test('native activity waits for bootstrap and opens the requested task once per gesture',()=>{
  const h=setup({ready:false}),open=h.context.window.WearingHost.openReview;
  open({id:10,target:'activity',taskId:'task-a'});assert.equal(h.activityTasks.length,0);
  h.context.composerReady=true;h.events['wearing-composer-ready']();
  assert.deepEqual(h.activityTasks,['task-a']);assert.equal(h.clicks.length,0);
  open({id:10,target:'activity',taskId:'task-a'});assert.deepEqual(h.activityTasks,['task-a']);
  open({id:11,target:'activity',taskId:'task-b'});assert.deepEqual(h.activityTasks,['task-a','task-b']);
});

test('native activity rejects malformed task identifiers before navigation',()=>{
  const h=setup(),open=h.context.window.WearingHost.openReview;
  for(const [index,taskId] of [undefined,null,42,'','../task-a','<script>','x'.repeat(65)].entries())open({id:index+1,target:'activity',taskId});
  open({id:1.5,target:'activity',taskId:'task-a'});open({id:'12',target:'activity',taskId:'task-a'});
  assert.equal(h.activityTasks.length,0);assert.equal(h.clicks.length,0);
});

test('native activity gives connection feedback only to the identity that opened it',async()=>{
  const h=setup();let reject;
  h.context.window.WearingActivity.openTask=()=>new Promise((_,fail)=>{reject=fail;});
  h.context.window.WearingHost.openReview({id:1,target:'activity',taskId:'task-a'});
  h.context.state.identityId='overseas';h.context.state.identityEpoch++;
  reject(Error('old identity unavailable'));await new Promise(resolve=>setImmediate(resolve));
  assert.equal(h.notices.length,0);
  h.context.window.WearingHost.openReview({id:2,target:'activity',taskId:'task-b'});
  reject(Error('current identity unavailable'));await new Promise(resolve=>setImmediate(resolve));
  assert.equal(h.notices.length,1);assert.match(h.notices[0],/暂时打不开/);
});

test('native search opens the App search without submitting or disturbing a draft',()=>{
  const h=setup({ready:false});let searches=0;
  h.context.window.WearingHost.openSearch=()=>searches++;
  h.context.window.WearingHost.openReview({id:1,target:'search'});assert.equal(searches,0);
  h.context.composerReady=true;h.events['wearing-composer-ready']();assert.equal(searches,1);
  h.context.window.WearingHost.openReview({id:1,target:'search'});assert.equal(searches,1);
  assert.equal(h.input.value,'原有草稿');assert.deepEqual(h.clicks,[]);
});

test('native suggestions wait for restoration and append one editable literal draft',()=>{
  const h=setup({ready:false}),open=h.context.window.WearingHost.openReview;
  open({id:11,target:'draft',text:'<b>准备简报</b>'});assert.equal(h.input.value,'原有草稿');
  h.context.composerReady=true;h.events['wearing-composer-ready']();
  assert.equal(h.input.value,'原有草稿\n<b>准备简报</b>');assert.equal(h.context.saved,h.input.value);
  assert.deepEqual(h.inputEvents,['input']);assert.equal(h.context.published,1);
  open({id:11,target:'draft',text:'<b>准备简报</b>'});assert.equal(h.inputEvents.length,1);
  assert.deepEqual(h.clicks,[]);assert.deepEqual(h.activityTasks,[]);
});

test('invalid or oversized suggestions preserve existing input and never invoke actions',()=>{
  const h=setup(),open=h.context.window.WearingHost.openReview;
  for(const [index,text] of [null,42,'',' ','x'.repeat(12001)].entries())open({id:index+1,target:'draft',text});
  assert.equal(h.input.value,'原有草稿');assert.equal(h.inputEvents.length,0);
  h.input.value='x'.repeat(11999);open({id:20,target:'draft',text:'明天见'});
  assert.equal(h.input.value.length,11999);assert.equal(h.inputEvents.length,0);assert.match(h.notices.at(-1),/太长/);
});

test('suggestion journal failure preserves existing input with feedback and never sends',()=>{
  const h=setup({blocked:true});h.context.window.WearingHost.openReview({id:1,target:'draft',text:'整理图文简报'});
  assert.equal(h.input.value,'原有草稿');assert.match(h.notices.at(-1),/草稿/);
  assert.deepEqual(h.clicks,[]);assert.deepEqual(h.activityTasks,[]);
});

test('retained draft requests do not append again after WebView recreation or sending',()=>{
  const receipts=new Map(),request={id:77,target:'draft',text:'准备明日简报'},h=setup({receipts});
  h.context.window.WearingHost.openReview(request);
  const restored=h.input.value,next=setup({receipts,initial:restored});
  next.context.window.WearingHost.openReview(request);
  assert.equal(next.input.value,restored);assert.equal(next.inputEvents.length,0);
  const afterSend=setup({receipts,initial:''});afterSend.context.window.WearingHost.openReview(request);
  assert.equal(afterSend.input.value,'');assert.equal(afterSend.inputEvents.length,0);
  next.context.window.WearingHost.openReview({id:78,target:'draft',text:'准备明日简报'});
  assert.equal(next.input.value,restored+'\n准备明日简报','a new user gesture must not be suppressed');
  const other=setup({receipts,identity:'overseas'});other.context.window.WearingHost.openReview(request);
  assert.equal(other.input.value,'原有草稿\n准备明日简报','receipt keys are scoped to the current identity');
});

test('reload after draft persistence but before receipt write recovers without double append',()=>{
  const receipts=new Map(),request={id:81,target:'draft',text:'准备简报'},h=setup({receipts});
  h.context.failReceipt=true;h.context.window.WearingHost.openReview(request);
  assert.equal(h.context.saved,'原有草稿\n准备简报');
  assert.equal(JSON.parse(receipts.get('wearing-native-draft:v1:daily:81')).status,'pending');
  const next=setup({receipts,initial:h.context.saved});next.context.window.WearingHost.openReview(request);
  assert.equal(next.input.value,h.context.saved);assert.equal(next.inputEvents.length,0);
  assert.equal(JSON.parse(receipts.get('wearing-native-draft:v1:daily:81')).status,'received');
});

test('draft save failure keeps a pending receipt and repeated event retries without duplication',()=>{
  const receipts=new Map(),request={id:83,target:'draft',text:'准备简报'},h=setup({receipts});
  h.context.failDraft=true;h.context.window.WearingHost.openReview(request);
  assert.equal(h.context.saved,undefined);assert.equal(h.input.value,'原有草稿\n准备简报');
  assert.equal(JSON.parse(receipts.get('wearing-native-draft:v1:daily:83')).status,'pending');
  h.context.failDraft=false;h.context.window.WearingHost.openReview(request);
  assert.equal(h.context.saved,h.input.value);assert.equal(h.inputEvents.length,1);
  assert.equal(JSON.parse(receipts.get('wearing-native-draft:v1:daily:83')).status,'received');
});

test('pending draft receipts cannot overwrite newer edits or migrate to another topic',()=>{
  const request={id:87,target:'draft',text:'准备简报'};
  for(const change of [{initial:'我已经改写了草稿'},{topic:{id:'new-goal'},initial:'原有草稿'}]){
    const receipts=new Map(),h=setup({receipts});h.context.failReceipt=true;h.context.window.WearingHost.openReview(request);
    const next=setup({receipts,...change});next.context.window.WearingHost.openReview(request);
    assert.equal(next.input.value,change.initial);assert.equal(next.inputEvents.length,0);assert.match(next.notices.at(-1),/已经变化/);
  }
});
