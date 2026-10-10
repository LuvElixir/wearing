import {Choice,StateSwitch} from './experience/selection';
import {useEffect,useRef,useState} from 'react';
import {View} from 'react-native';
import {Button,Text} from 'react-native-paper';
import * as Crypto from 'expo-crypto';
import {scopeOf,type Connection,type RecordItem} from './core';
import {storage} from './storage';
import {serviceFetch} from './transport';
import {useAppTheme} from './app-theme';
import {accountWorkAllowed,registerAccountWork} from './account-work';
import {NativeNotificationsPanel} from './NativeNotificationsPanel';
import {RecordReminderClient,adoptReminderRead,pendingReminder,reminderAdvances,reminderCacheKey,reminderKey,reminderMessage,reminderReceipt,submitReminder,type PendingReminder,type Reminder,type ReminderRequest} from './record-reminders';

type Props={connection:Connection;record:RecordItem;blocked?:boolean};
export default function RecordReminderPanel(props:Props){return <Panel key={`${scopeOf(props.connection)}|${props.connection.session?.credentialId||''}|${props.record.id}|${props.record.revision}`} {...props}/>;}
function Panel({connection,record,blocked=false}:Props){
  const {colors:c}=useAppTheme(),scope=scopeOf(connection),alive=useRef(false),locked=useRef(false),controller=useRef<AbortController|null>(null);
  const [value,setValue]=useState<Reminder|null>(null),[waiting,setWaiting]=useState<PendingReminder|null>(null),[enabled,setEnabled]=useState(false),[advance,setAdvance]=useState(15),[busy,setBusy]=useState(false),[notice,setNotice]=useState(''),[showNotifications,setShowNotifications]=useState(false),[online,setOnline]=useState(false);
  const active=()=>alive.current&&accountWorkAllowed(connection)&&!controller.current?.signal.aborted;
  const api=()=>new RecordReminderClient(connection,serviceFetch,active,controller.current?.signal);
  useEffect(()=>{alive.current=true;const abort=new AbortController();controller.current=abort;const stop=registerAccountWork(connection,async()=>abort.abort());
    void (async()=>{try{
      const pending=pendingReminder(await storage.get(reminderKey(scope,record.id))),cached=await storage.get(reminderCacheKey(scope,record.id));
      if(!active())return;setWaiting(pending);if(pending){setEnabled(pending.request.enabled);setAdvance(pending.request.advance_minutes);}
      if(cached){const saved=reminderReceipt(cached,connection.identity,record.id);setValue(saved);if(!pending){setEnabled(saved.enabled);setAdvance(saved.advance_minutes);}}
      const result=await api().get(record.id);if(!active())return;setValue(result);setOnline(true);if(!pending){setEnabled(result.enabled);setAdvance(result.advance_minutes);}await storage.put(reminderCacheKey(scope,record.id),result);
    }catch(error){if(active())setNotice(error instanceof Error?error.message:'提醒暂未读取。');}})();
    return()=>{alive.current=false;abort.abort();stop();};
    // Keyed to the exact connection and canonical record revision.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  },[]);
  async function run(work:()=>Promise<void>){if(locked.current||!active())return;locked.current=true;setBusy(true);setNotice('');try{await work();}catch(error){if(active())setNotice(error instanceof Error?error.message:'原操作已保留，请重试。');}finally{try{if(active())setWaiting(pendingReminder(await storage.get(reminderKey(scope,record.id))));}catch(error){if(active())setNotice(error instanceof Error?error.message:'本机操作暂未读到，请重试。');}finally{locked.current=false;if(active())setBusy(false);}}}
  async function submit(input?:ReminderRequest){
    const result=await submitReminder(storage,scope,record.id,api(),input,active);if(!active())return;setValue(result);setWaiting(null);setEnabled(result.enabled);setAdvance(result.advance_minutes);setNotice('提醒设置已保存。系统通知是否可用，请查看下方通知设置。');
    // A recovered old receipt is not necessarily the current setting or record time.
    try{const fresh=await api().get(record.id);if(active()){setValue(fresh);setEnabled(fresh.enabled);setAdvance(fresh.advance_minutes);setOnline(true);await storage.put(reminderCacheKey(scope,record.id),fresh);}}catch{if(active()){setOnline(false);setNotice('原设置回执已取回；当前状态暂未读取，请重新读取后再调整。');}}
  }
  const unavailable=value?.status==='unavailable',disabled=busy||blocked||!!waiting||!online||!value;
  return <View style={{gap:12,padding:20,borderRadius:24,backgroundColor:c.surface}}>
    <Text style={{fontSize:17,fontWeight:'600',color:c.ink}}>{record.id.startsWith('recurrence_')?'这一次的提醒':'到期提醒'}</Text>
    <Text style={{color:c.muted,lineHeight:22}}>{value?reminderMessage(value):'读取当前记录的提醒设置。'}{!online&&value?' 当前显示上次读取的设置。':''}</Text>
    {blocked&&<Text style={{color:c.muted}}>请先保存或核对记录修改，再设置提醒。</Text>}
    <View style={{flexDirection:'row',alignItems:'center',justifyContent:'space-between'}}><Text style={{color:c.ink}}>提醒我</Text><StateSwitch value={enabled} disabled={disabled||!!unavailable} onValueChange={setEnabled} accessibilityLabel="开启这条记录的提醒"/></View>
    <View style={{flexDirection:'row',flexWrap:'wrap',gap:4}}>{reminderAdvances.map(minutes=><Choice variant="chip" key={minutes} selected={advance===minutes} disabled={disabled||!enabled||!!unavailable} onPress={()=>setAdvance(minutes)}><Text style={{color:c.ink}}>{minutes===0?'准时':minutes===1440?'提前 1 天':`提前 ${minutes} 分钟`}</Text></Choice>)}</View>
    <Button mode="contained" disabled={disabled||!!unavailable||!value?.record_revision||enabled===value?.enabled&&advance===value?.advance_minutes} loading={busy} onPress={()=>void run(async()=>{if(!value?.record_revision)return;await submit({revision:value.revision,record_revision:value.record_revision,enabled,advance_minutes:advance,request_key:Crypto.randomUUID()});})}>保存提醒设置</Button>
    {!!waiting&&<><Text style={{color:c.muted,lineHeight:22}}>{waiting.error||'上次操作还未确认。输入留在本机，不会重复创建提醒。'}</Text>{waiting.phase==='pending'&&<Button disabled={busy} onPress={()=>void run(()=>submit())}>取回上次设置回执</Button>}</>}
    <Button disabled={busy||waiting?.phase==='pending'} onPress={()=>void run(async()=>{const fresh=await api().get(record.id);if(!active())return;await adoptReminderRead(storage,scope,record.id,fresh);if(active()){setValue(fresh);setWaiting(null);setOnline(true);setNotice('已读取最新状态，所选输入仍保留，请核对后保存。');}})}>读取最新设置，保留选择</Button>
    <Text style={{color:c.muted,fontSize:12,lineHeight:20}}>只提醒你明确设置的记录。改期会调整提醒，移除或完成会停止；恢复后需重新开启。安静时段会延后通知，超过原定时间 1 小时不再补发。</Text>
    <Button onPress={()=>setShowNotifications(value=>!value)}>{showNotifications?'收起通知设置':'查看手机通知设置'}</Button>
    {showNotifications&&<NativeNotificationsPanel connection={connection}/>}
    {!!notice&&<Text accessibilityLiveRegion="polite" style={{color:c.muted,lineHeight:22}}>{notice}</Text>}
  </View>;
}
