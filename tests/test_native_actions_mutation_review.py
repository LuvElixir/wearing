"""Independent MCP -> server claim -> TypeScript runner/driver -> server receipt review.

The OS is a synthetic in-memory adapter in a separate Node process. No native
framework, model, server socket, real record or provider is contacted.
"""
import asyncio
import json
import subprocess
from pathlib import Path

import pytest
from test_native_actions import env, PHONE, SECRET, SESSION, POLICY
from wearing import native_actions_tools
from wearing.native_actions import NativeActionError

ROOT = Path(__file__).resolve().parents[1]
MOBILE = ROOT / 'clients/mobile'
PHONE_SCRIPT = r'''
const {readFileSync}=require('node:fs');
const {createHash}=require('node:crypto');
const {NativeActionDriver}=require('./src/native-action-driver.ts');
const {NativeActionRunner}=require('./src/native-action-runner.ts');
(async()=>{
  const input=JSON.parse(readFileSync(0,'utf8')), raw=input.record, journal=new Map();
  let writes=0,deleted=false,patch=null,options=null;
  const ensureJournal=()=>{if(!Array.from(journal.values()).some(x=>x?.phase==='admitted'))throw new Error('write before durable admission');};
  const api={getCalendarPermissionsAsync:async()=>({granted:true}),getRemindersPermissionsAsync:async()=>({granted:true}),
    getCalendarsAsync:async kind=>[{id:kind==='event'?'cal':'rem',title:'Synthetic',allowsModifications:true}],
    getEventsAsync:async()=>{if(deleted&&input.failReadback)throw new Error('synthetic bridge lost');return deleted?[]:[raw];},
    getRemindersAsync:async()=>deleted?[]:[raw],getEventAsync:async()=>raw,getReminderAsync:async()=>raw,
    updateEventAsync:async(id,value,opts)=>{ensureJournal();writes++;patch=value;options=opts;Object.assign(raw,value);return id;},
    updateReminderAsync:async(id,value)=>{ensureJournal();writes++;patch=value;Object.assign(raw,value);return id;},
    deleteEventAsync:async(id,opts)=>{ensureJournal();writes++;options=opts;deleted=true;},deleteReminderAsync:async()=>{ensureJournal();writes++;deleted=true;}};
  const driver=new NativeActionDriver(api,null,()=>true,()=>Date.parse(input.request.command.created_at),async v=>createHash('sha256').update(v).digest('hex'));
  let data,outcome;
  if(input.mode==='read')data=await driver.execute(input.request,input.device);
  else {
    const store={get:async k=>journal.get(k)||null,put:async(k,v)=>journal.set(k,structuredClone(v))};
    const client={claim:async(r,yes)=>{if(!yes||!input.admitted)throw new Error('no real server admission');return input.admitted;},finish:async(r,o)=>{outcome=o;return {...r,state:o.status,result:o};}};
    const runner=new NativeActionRunner(store,'review-phone',client,driver,()=>true,()=>Date.parse(input.request.command.created_at));
    await runner.run(input.request,input.device,input.request.command.connection_id,true);
    await runner.recover();
  }
  process.stdout.write(JSON.stringify({data,outcome,writes,patch,options,remainingJournal:Array.from(journal.values()).filter(Boolean).length}));
})().catch(e=>{process.stderr.write(String(e.stack));process.exitCode=1;});
'''


def phone(payload):
    result=subprocess.run([str(MOBILE/'node_modules/.bin/tsx'),'-e',PHONE_SCRIPT],cwd=MOBILE,input=json.dumps(payload),text=True,capture_output=True,timeout=12,check=True)
    return json.loads(result.stdout)


def enable(book):
    book.configure('daily',PHONE,SECRET,1,True,{**POLICY,'calendar_edit':True,'reminder_edit':True})
    return book.connect('daily',PHONE,SECRET,2,SESSION,['calendar.read','reminders.read','calendar.update','calendar.delete','reminders.update','reminders.delete'])


def original(kind):
    common={'id':'synthetic-native-id','calendarId':'cal' if kind=='calendar' else 'rem','title':'Original','notes':'Keep original','location':'Original location'}
    if kind=='calendar':return {**common,'startDate':'2026-10-08T01:00:00Z','endDate':'2026-10-08T02:00:00Z','allDay':False,'availability':'busy','recurrenceRule':{'frequency':'weekly','interval':1}}
    return {**common,'dueDate':'2026-10-09T00:00:00Z','completed':False} # realistic SDK57 no allDay


async def tool(book,method,params,key):
    pending=asyncio.create_task(native_actions_tools.dispatch(book.store,'daily','native_request',{'installation_id':PHONE,'method':method,'params':params,'request_key':key}))
    await asyncio.sleep(0)
    queued=book.poll('daily',PHONE,SECRET,SESSION)['items']
    assert len(queued)==1
    return pending,queued[0]


@pytest.mark.parametrize('method,fail_readback',[('calendar.update',False),('calendar.delete',False),('reminders.update',False),('reminders.delete',False),('calendar.delete',True)])
async def test_real_tool_command_phone_journal_driver_and_server_receipt(env,monkeypatch,method,fail_readback):
    book,_,_=env;device=enable(book);monkeypatch.setattr(native_actions_tools,'NativeActions',lambda _:book)
    kind=method.split('.')[0];raw=original(kind)
    params={'calendar_ids':['cal'],'start':'2026-10-08T00:00:00Z','end':'2026-10-09T00:00:00Z'} if kind=='calendar' else {'calendar_ids':['rem']}
    pending,r=await tool(book,kind+'.read',params,'review-read')
    book.claim('daily',PHONE,SECRET,SESSION,r['id'],r['fingerprint'],True)
    result=await asyncio.to_thread(phone,{'mode':'read','request':r,'device':device,'record':raw})
    book.finish('daily',PHONE,SECRET,SESSION,r['id'],r['fingerprint'],{'status':'succeeded','code':'ok','data':result['data']})
    read=await pending;ref=read['references'][0]['record_ref']
    patch={'title':'Updated title'} if method.endswith('.update') else None
    pending,r=await tool(book,method,{'record_ref':ref,**({'patch':patch} if patch else {})},'review-edit')
    assert r['command']['params']['target']==result['data']['items'][0]
    with pytest.raises(NativeActionError):book.finish('daily',PHONE,SECRET,SESSION,r['id'],r['fingerprint'],{'status':'unknown','code':'interrupted','data':{}})
    admitted=book.claim('daily',PHONE,SECRET,SESSION,r['id'],r['fingerprint'],True)
    result=await asyncio.to_thread(phone,{'mode':'run','request':r,'admitted':admitted,'device':device,'record':raw,'failReadback':fail_readback})
    assert result['writes']==1 and result['remainingJournal']==0
    finished=book.finish('daily',PHONE,SECRET,SESSION,r['id'],r['fingerprint'],result['outcome'])
    response=await pending;assert response==finished and response['state']==('unknown' if fail_readback else 'succeeded')
    replay=await native_actions_tools.dispatch(book.store,'daily','native_request',{'installation_id':PHONE,'method':method,'params':{'record_ref':ref,**({'patch':patch} if patch else {})},'request_key':'review-edit'})
    assert replay==response
    if kind=='calendar':assert result['options']=={'instanceStartDate':'2026-10-08T01:00:00.000Z','futureEvents':False}
    if method=='reminders.update':
        assert result['outcome']['data']['record']['all_day'] is None
        assert not {'allDay','dueDate','startDate','recurrenceRule','alarms'} & result['patch'].keys()
    with pytest.raises(NativeActionError):book.request('daily',PHONE,method,{'record_ref':ref,**({'patch':patch} if patch else {})},'new-key-duplicate')
