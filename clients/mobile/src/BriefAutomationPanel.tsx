import {Choice,ToggleRow} from './experience/selection';
import {useEffect,useRef,useState} from 'react';
import {Platform,Text,View} from 'react-native';
import DateTimePicker from '@react-native-community/datetimepicker';
import {validTimezone,wallClock,wallTimeToInstant} from './ongoing-management-forms';
import {TextInput} from 'react-native-paper';
import * as Crypto from 'expo-crypto';
import {ApiError,scopeOf,type Connection} from './core';
import {storage} from './storage';
import {serviceFetch} from './transport';
import {accountWorkAllowed,registerAccountWork} from './account-work';
import {PrimaryButton} from './experience/primitives';
import {useAppTheme} from './app-theme';
import {autoPendingKey,autoRequest,BriefAutomationClient,saveAutomation,type AutoRequest,type AutoSettings} from './briefing-automation';
export function BriefAutomationPanel(props:{connection:Connection;preferencesRevision:number|null;isCurrent?:()=>boolean}){return <Panel key={scopeOf(props.connection)+'|'+(props.connection.session?.credentialId||'')} {...props}/>;}
function Panel({connection,preferencesRevision,isCurrent}:{connection:Connection;preferencesRevision:number|null;isCurrent?:()=>boolean}){
 const {colors:c,mode:appearance}=useAppTheme(),alive=useRef(false),controller=useRef<AbortController|null>(null),locked=useRef(false);
 const active=()=>alive.current&&(!isCurrent||isCurrent())&&!!controller.current&&!controller.current.signal.aborted&&accountWorkAllowed(connection);
 const api=()=>new BriefAutomationClient(connection,serviceFetch,active,controller.current?.signal);
 const [state,setState]=useState<AutoSettings|null>(null),[pending,setPending]=useState<AutoRequest|null>(null),[enabled,setEnabled]=useState(false),[time,setTime]=useState('08:00'),[zone,setZone]=useState(Intl.DateTimeFormat().resolvedOptions().timeZone||'Asia/Shanghai'),[grace,setGrace]=useState(120),[busy,setBusy]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState(''),[conflict,setConflict]=useState(false),[receipts,setReceipts]=useState(false),[picker,setPicker]=useState(false),[advanced,setAdvanced]=useState(false);
 const apply=(v:AutoRequest|AutoSettings)=>{setEnabled(v.enabled);setTime(v.local_time);setZone(v.timezone);setGrace(v.grace_minutes);};
 useEffect(()=>{let live=true;const abort=new AbortController();controller.current=abort;alive.current=true;const stop=registerAccountWork(connection,async()=>abort.abort());
  void(async()=>{setBusy(true);try{const raw=await storage.get<unknown>(autoPendingKey(connection)),saved=raw?autoRequest(raw):null;if(!live||!active())return;setPending(saved);if(saved)apply(saved);const loaded=await api().load();if(!live||!active())return;setState(loaded);if(!saved&&loaded.revision)apply(loaded);}catch(e){if(live&&active())setError(e instanceof Error?e.message:'自动简报暂未读取。');}finally{if(live&&active())setBusy(false);}})();
  return()=>{live=false;alive.current=false;abort.abort();stop();};
  // The keyed panel owns this exact account credential.
  // eslint-disable-next-line react-hooks/exhaustive-deps
 },[]);
 async function run(work:()=>Promise<void>){if(!active()||locked.current)return;locked.current=true;setBusy(true);setError('');setNotice('');try{await work();}catch(e){if(active()){setError(e instanceof Error?e.message:'设置暂未完成，原请求已保留。');setConflict(e instanceof ApiError&&e.status===409);}}finally{locked.current=false;if(active()){try{const raw=await storage.get<unknown>(autoPendingKey(connection));if(active())setPending(raw?autoRequest(raw):null);}catch{if(active())setError('本机上次请求无法核对，请保留数据后重新读取。');}finally{if(active())setBusy(false);}}}}
 async function refresh(){const loaded=await api().load();if(!active())return;if(conflict){await storage.put(autoPendingKey(connection),null);if(!active())return;setPending(null);setConflict(false);}setState(loaded);if(!state&&!pending&&loaded.revision)apply(loaded);setNotice('已读取当前状态，未保存的输入仍保留。');}
 async function save(){const body=pending||autoRequest({enabled,local_time:time,timezone:zone,grace_minutes:grace,preferences_revision:preferencesRevision??state?.preferences_revision??0,revision:state?.revision??0,request_key:Crypto.randomUUID()});await saveAutomation(storage,api(),active,body);if(!active())return;setPending(null);setNotice(body.enabled?'自动简报已保存；后台服务在线时会按这个时间准备。':'已关闭后续自动简报；已开始的本轮可到任务页停止。');try{const value=await api().load();if(active()){setState(value);apply(value);}}catch{if(active())setError('设置已保存，状态暂未重新读取。请点刷新核对。');}}
 let pickerValue=new Date();try{pickerValue=new Date(wallTimeToInstant('2026-01-15',time,zone));}catch{/* Invalid advanced input stays editable. */}
 const disabled=busy||!!pending||!state;
 const muted={fontSize:13,lineHeight:22,color:c.muted};
 return <View style={{gap:12,paddingTop:16,borderTopWidth:1,borderColor:c.line}}>
  <Text accessibilityRole="header" style={{color:c.ink,fontSize:17,fontWeight:'600'}}>每天自动准备简报</Text>
  <Text style={muted}>在服务端执行，关闭 App 后仍可运行。服务离线时只在允许补做时间内整理当天这一份；超时或跨天会跳过。同一天已有你的手动简报时沿用原回执。</Text>
  <ToggleRow label="每天准备简报" value={enabled} disabled={disabled} onValueChange={setEnabled}/>
  <PrimaryButton tone="quiet" label={'每天 '+time+' 准备'} disabled={disabled||!validTimezone(zone)} onPress={()=>setPicker(true)}/>
  {picker&&validTimezone(zone)&&<View><DateTimePicker value={pickerValue} mode="time" timeZoneName={zone} is24Hour locale="zh-CN" themeVariant={appearance==='night'?'dark':'light'} display={Platform.OS==='ios'?'spinner':'default'} onChange={(event,value)=>{if(Platform.OS!=='ios')setPicker(false);if(event.type==='set'&&value)setTime(wallClock(value,zone).time);}}/>{Platform.OS==='ios'&&<PrimaryButton label="选好了" tone="quiet" onPress={()=>setPicker(false)}/>}</View>}
  <PrimaryButton tone="quiet" label={advanced?'收起时区设置':'高级：时间所在时区'} disabled={busy} onPress={()=>setAdvanced(v=>!v)}/>
  {advanced&&<TextInput mode="outlined" label="时区（默认使用这台设备的时区）" value={zone} onChangeText={value=>{setPicker(false);setZone(value);}} disabled={disabled} autoCapitalize="none"/>}
  <Text style={muted}>错过时间后，允许当天补做多久</Text><View style={{flexDirection:'row',gap:8,flexWrap:'wrap'}}>{[30,60,120].map(value=><Choice variant="chip" key={value} selected={grace===value} label={value+' 分钟'} disabled={disabled} onPress={()=>setGrace(value)}/>)}</View>
  <Text style={muted}>点击保存后生效。当前服务：{state?.enabled&&state.schedule_status==='active'?'已开启':'未开启或已暂停'}。保存后固定使用所选时区，旅行时不会自动改变。</Text>
  <Text style={muted}>安静时段只延后通知，简报仍会准备。通知关闭或未授权不妨碍在今天页查看结果。</Text>
  {state?.preferences_revision!==null&&state?.preferences_revision!==undefined&&<Text style={muted}>自动安排使用偏好版本 {state.preferences_revision}{preferencesRevision!==state.preferences_revision?'；上方偏好已有变化，请点保存将新偏好用于之后的简报。':'。'}</Text>}
  {state?.next_run&&<Text style={muted}>下次计划：{new Date(state.next_run).toLocaleString('zh-CN',{timeZone:state.timezone})}（{state.timezone}）</Text>}
  {(state?.needs_resave||state?.enabled&&state.schedule_status!=='active')&&<Text style={{...muted,color:c.danger}}>自动安排已暂停或被修改，请查看本轮记录，核对后重新保存设置。</Text>}
  {!!state?.reason&&<Text style={muted}>{state.reason}</Text>}
  <PrimaryButton label={pending?'核对上次保存':'保存自动简报设置'} disabled={busy||conflict||!pending&&(!state||enabled&&preferencesRevision===null)} onPress={()=>void run(save)}/>
  <PrimaryButton label={conflict?'读取最新设置，保留输入':'刷新自动简报状态'} tone="quiet" disabled={busy} onPress={()=>void run(refresh)}/>
  {!!pending&&<Text style={muted}>上次请求尚待核对，沿用原保存编号，避免重复安排。</Text>}
  <PrimaryButton label={receipts?'收起最近回执':'查看最近 7 份回执'} tone="quiet" disabled={!state} onPress={()=>setReceipts(v=>!v)}/>
  {receipts&&state?.receipts.map(r=><View key={r.local_date} style={{gap:4,paddingVertical:10,borderBottomWidth:1,borderColor:c.line}}><Text style={{color:c.ink}}>{r.local_date} · {r.state==='skipped'?'已跳过':r.state==='existing'?'沿用当天简报':'已建立生成请求'}</Text>{r.briefing?<Text style={muted}>第 {r.briefing.version} 版 · {({not_started:'等待开始',queued:'排队中',running:'整理中',ready:'图文已发布',text_only:'已有文字结果',needs_attention:'需要处理',failed:'生成失败',stopped:'已停止'} as Record<string,string>)[r.briefing.state]} · {r.briefing.timezone}。可到今天页查看对应日期的简报。</Text>:<Text style={muted}>超过补做窗口或已跨天，没有补做历史资料。</Text>}</View>)}
  {receipts&&state?.receipts.length===0&&<Text style={muted}>还没有到期回执。保存设置不等于简报已经生成。</Text>}
  {!!error&&<Text accessibilityRole="alert" style={{...muted,color:c.danger}}>{error}</Text>}{!!notice&&<Text accessibilityLiveRegion="polite" style={muted}>{notice}</Text>}
 </View>;
}
