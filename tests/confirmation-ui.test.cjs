const {test}=require('node:test');
const assert=require('node:assert/strict');
const ui=require('../src/wearing/web/confirmations.js');
const fs=require('node:fs');
const vm=require('node:vm');
const card={title:'保存测试笔记',action:'仅保存这条合成记录',impact:'仅当前测试身份',confirm_label:'确认保存'};
test('confirmation escapes content and binds both choices to the same request',()=>{
  const html=ui.pending('task-a',{request_id:'r-a',card_state:'pending',card:{...card,action:'<img onerror="oops">'}});
  assert(!html.includes('<img'));assert(html.includes('&lt;img'));
  assert.equal((html.match(/data-request="r-a"/g)||[]).length,2);
  assert(html.includes('data-choice="once"'));assert(html.includes('data-choice="deny"'));
});
test('answered, uncertain, and submitting cards cannot be clicked again',()=>{
  for(const state of ['answered','unknown','sending','expired']){
    const html=ui.pending('task',{request_id:'r',card_state:state,card});
    assert.equal((html.match(/disabled/g)||[]).length,2);
  }
  assert.equal((ui.pending('task',{request_id:'r',card_state:'pending',card},true).match(/disabled/g)||[]).length,2);
});
test('compact prompt preserves consequences without duplicate impact or idle hint',()=>{
  const html=ui.pending('task',{request_id:'r',card_state:'pending',card});
  assert(html.includes(card.impact));assert(html.includes('role="status" hidden'));
  assert(!html.includes('需要你决定'));assert(!html.includes('确认后，我会接着做'));
  const repeated=ui.pending('task',{request_id:'r',card_state:'pending',card:{...card,impact:card.action}});
  assert.equal(repeated.split(card.action).length-1,1);
  assert(ui.pending('task',{request_id:'r',card_state:'pending',card},true).includes('正在送出…'));
});
test('invalid card offers no action and receipts never claim business success',()=>{
  const invalid=ui.pending('task',{request_id:'r',card_invalid:true});
  assert(!invalid.includes('data-choice'));assert(invalid.includes('data-action="stop"'));
  const rows=[{request_id:'r',state:'answered',choice:'once',card}];
  assert.equal(ui.history(rows,'r'),'');
  const receipt=ui.history(rows);
  assert(receipt.includes('已确认'));assert(receipt.includes('执行结果看后续回应'));assert(!receipt.includes('data-choice'));
});
test('secondary connector failure cannot starve the conversation or mark it offline',async()=>{
  const source=fs.readFileSync(require.resolve('../src/wearing/web/app.js'),'utf8');
  const start=source.indexOf('async function pollConversation(){'),end=source.indexOf('setInterval(pollConversation,3000);',start);
  const calls=[];
  const context={state:{identityEpoch:1,token:'test',connected:true,deployment:'cloud',lastStatus:0},document:{hidden:false},window:{},Date,Promise,
    lastComputerCheck:0,lastPhoneCheck:0,lastGoalUpdates:Date.now(),selectedGoal:null,StaleIdentity:class extends Error{},
    $:()=>({open:false}),loadStatus:async()=>calls.push('status'),loadConversation:async()=>calls.push('conversation'),
    loadDesktopApprovals:async()=>{calls.push('desktop');throw Error('device unavailable');},loadComputer:async()=>calls.push('computer'),
    updateCompanion:()=>{throw Error('should not mark disconnected');}};
  vm.createContext(context);vm.runInContext(source.slice(start,end),context);
  await context.pollConversation();
  assert.deepEqual(calls.slice(0,2),['status','conversation']);
  assert(calls.includes('computer'));assert.equal(context.state.connected,true);assert.equal(context.state.polling,false);
});
