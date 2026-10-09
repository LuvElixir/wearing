const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const window = {};
vm.runInNewContext(fs.readFileSync('src/wearing/web/conversation-drafts.js','utf8'), {window});
const create = window.WearingDrafts.create;
function storage() {
  const data = new Map();
  return {getItem: k => data.get(k) ?? null, setItem: (k,v) => data.set(k,v), removeItem: k => data.delete(k)};
}
const chat = {identity:'daily'};
const goal = {identity:'daily',goal:{id:'goal-a',objective:'出行计划',revision:3,mode:'note'}};
const life = {identity:'daily',life:{id:'life-a',title:'出行笔记',revision:2,kind:'note'}};

test('new page instance recovers text and the original contextual revision',()=>{
 const s=storage(), first=create(()=>s);
 first.save(goal,'新的想法还没写完');
 const next=create(()=>s), restored=next.read(next.last('daily'));
 assert.equal(restored.text,'新的想法还没写完');
 assert.equal(restored.context.goal.revision,3);
 assert.equal(restored.context.goal.mode,'note');
});
test('identity, ordinary chat, goal mode and different records keep distinct drafts',()=>{
 const s=storage(), d=create(()=>s);
 const contexts=[chat,goal,life,{...chat,identity:'overseas'}, {...goal,goal:{...goal.goal,mode:'discuss'}},{...life,life:{...life.life,id:'life-b'}}];
 contexts.forEach((c,i)=>d.save(c,'草稿'+i));
 contexts.forEach((c,i)=>assert.equal(d.read(c).text,'草稿'+i));
 assert.equal(create(()=>s).last('unknown'),null);
});
test('a successful submission clears only its acknowledged text',()=>{
 const s=storage(), d=create(()=>s);
 d.save(chat,'第一条');
 d.save(chat,'正在写第二条');
 assert.equal(d.acknowledge(chat,'第一条'),false);
 assert.equal(d.read(chat).text,'正在写第二条');
 assert.equal(d.acknowledge(chat,'正在写第二条'),true);
 assert.equal(create(()=>s).read(chat),null);
});
test('blanking one topic does not erase another topic',()=>{
 const s=storage(), d=create(()=>s);
 d.save(goal,'补充'); d.save(chat,'普通对话'); d.save(goal,'');
 const next=create(()=>s);
 assert.equal(next.read(goal),null); assert.equal(next.read(chat).text,'普通对话');
});
test('storage denial keeps the latest in-page text and reports inability to persist',()=>{
 const s=storage(); const old=create(()=>s); old.save(chat,'旧内容');
 let warnings=0; s.setItem=()=>{throw new Error('quota');};
 const d=create(()=>s,()=>warnings++);
 assert.equal(d.save(chat,'新内容'),false);
 assert.equal(d.read(chat).text,'新内容'); assert.ok(warnings>0);
});
test('corrupt or mismatched storage cannot move a draft into another context',()=>{
 const s=storage(),d=create(()=>s);
 s.setItem(d.key(chat),'{broken'); assert.equal(d.read(chat),null);
 s.setItem(d.key(chat),JSON.stringify({context:{identity:'foreign'},text:'外部内容'}));
 assert.equal(d.read(chat),null);
 s.setItem(d.key(chat),JSON.stringify({context:chat,text:1})); assert.equal(d.read(chat),null);
});
test('topic metadata is data only and oversized or malformed drafts are rejected',()=>{
 const d=create(()=>storage());
 assert.equal(d.save(chat,'a'.repeat(12001)),false);
 assert.equal(d.save({...goal,goal:{...goal.goal,revision:true}},'x'),false);
 const value={...life,life:{...life.life,title:'<img onerror="bad()">'}};
 assert.equal(d.save(value,'<script>bad()</script>'),true);
 assert.equal(d.read(value).text,'<script>bad()</script>');
});
