import {useEffect,useRef,useState} from 'react';
import {Text,View} from 'react-native';
import {TextInput} from 'react-native-paper';
import * as Crypto from 'expo-crypto';
import {ApiError,scopeOf,type Connection} from './core';
import {dateKey,type CalendarDate} from './calendar';
import SeriesDateField from './SeriesDateField';
import {civilDateLabel,setSeriesAllDay,shownSeriesEnd,storedSeriesEnd} from './series-date-fields';
import {validTimezone} from './ongoing-management-forms';
import {storage} from './storage';
import {serviceFetch} from './transport';
import {useAppTheme} from './app-theme';
import {PrimaryButton,TactilePressable} from './experience/primitives';
import {accountWorkAllowed,registerAccountWork} from './account-work';
import {CalendarSeriesClient,submitSeriesMutation} from './calendar-series-client';
import {calendarSeriesChanged} from './use-calendar-series';
import RecordReminderPanel from './RecordReminderPanel';
import {occurrenceTemplate,ruleLabel,seriesDraft,seriesDraftKey,seriesEdit,seriesMutation,seriesPendingKey,type Series,type SeriesDraft,type SeriesMutation,type SeriesOccurrence,type SeriesRule,type SeriesTemplate} from './calendar-series-model';

export type CalendarSeriesPanelProps={connection:Connection;seriesId?:string;occurrence?:SeriesOccurrence;initialDay?:CalendarDate;isCurrent:()=>boolean;onChanged:(row:Series)=>void;onOpenSeries:(id:string)=>void};
export function CalendarSeriesPanel(props:CalendarSeriesPanelProps){return <Panel key={scopeOf(props.connection)+'|'+(props.connection.session?.credentialId||'')+'|'+(props.seriesId||props.occurrence?.recurrence.series_id||'new')+'|'+(props.occurrence?.recurrence.occurrence_key||'')} {...props}/>;}
function Panel({connection,seriesId,occurrence,initialDay,isCurrent,onChanged,onOpenSeries}:CalendarSeriesPanelProps){
  const {colors:c}=useAppTheme(),scope=scopeOf(connection),id=seriesId||occurrence?.recurrence.series_id,target=id||'new',alive=useRef(false),locked=useRef(false),controller=useRef<AbortController|null>(null);
  const active=()=>alive.current&&isCurrent()&&accountWorkAllowed(connection)&&!!controller.current&&!controller.current.signal.aborted;
  const api=()=>new CalendarSeriesClient(connection,serviceFetch,active,controller.current?.signal);
  const day=initialDay||{year:new Date().getFullYear(),month:new Date().getMonth()+1,day:new Date().getDate()};
  const initial:SeriesDraft={template:{title:'',content:'',timezone:Intl.DateTimeFormat().resolvedOptions().timeZone||'Asia/Shanghai',all_day:false,start_local:dateKey(day)+'T09:00',end_local:dateKey(day)+'T10:00'},rule:{frequency:'weekly',interval:1,weekdays:[],count:null,until:null}};
  const [row,setRow]=useState<Series|null>(null),[draft,setDraft]=useState<SeriesDraft>(initial),[mode,setMode]=useState<'series'|'once'>(occurrence?'once':'series'),[ready,setReady]=useState(false),[busy,setBusy]=useState(false),[pending,setPending]=useState<SeriesMutation|null>(null),[notice,setNotice]=useState(''),[error,setError]=useState(''),[rejected,setRejected]=useState(false),[confirm,setConfirm]=useState<'archive'|'cancel'|null>(null);
  const [rows,setRows]=useState<Series[]>([]),[next,setNext]=useState<string|null>(null),[showList,setShowList]=useState(false);
  const [advancedTime,setAdvancedTime]=useState(false);
  const [baseConflict,setBaseConflict]=useState(false),[selectedOccurrence,setSelectedOccurrence]=useState<SeriesOccurrence|null>(null);
  const draftKey=seriesDraftKey(scope,target+':'+(occurrence?.recurrence.occurrence_key||'series'));
  useEffect(()=>{let mounted=true;const currentController=new AbortController();controller.current=currentController;alive.current=true;const stop=registerAccountWork(connection,async()=>{currentController.abort();});
    async function begin(){try{
      const raw=await storage.get<unknown>(draftKey),saved=raw?seriesEdit(raw):null,waiting=await storage.get<unknown>(seriesPendingKey(scope,target));
      if(!mounted||!active())return;if(waiting)setPending(seriesMutation(waiting));
      let value:Series|null=null;
      if(id){value=await api().get(id,occurrence?.recurrence.occurrence_key);if(!mounted||!active())return;setRow(value);setSelectedOccurrence(value.selected||null);setDraft({template:value.selected?occurrenceTemplate(value.selected):value.body.template,rule:value.body.rule});if(occurrence&&!value.selected){setMode('series');setNotice('这一次已取消或已不属于当前规则，请查看整个系列与例外列表。');}}
      if(saved){setDraft(saved.draft);setMode(saved.mode==='once'&&!value?.selected?'series':saved.mode);if(value&&saved.baseRevision!==value.revision)setBaseConflict(true);}
      if(mounted&&active())setReady(true);
    }catch(e){if(mounted&&active()){setError(e instanceof Error?e.message:'日程暂未读取。');if(!id)setReady(true);}}}
    void begin();return()=>{mounted=false;alive.current=false;currentController.abort();stop();};
    // Keyed mount owns this exact connection, series and occurrence.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  },[]);
  const run=async(work:()=>Promise<void>)=>{if(locked.current||!active())return;locked.current=true;setBusy(true);setError('');setNotice('');try{await work();}catch(e){if(active()){setError(e instanceof Error?e.message:'这次未完成，输入仍保留。');setRejected(e instanceof ApiError&&[409,422,404].includes(e.status));}}finally{locked.current=false;if(active())setBusy(false);}};
  function edit(nextDraft:SeriesDraft,nextMode=mode,baseRevision: number|null=row?.revision||null){setDraft(nextDraft);setMode(nextMode);setConfirm(null);void storage.put(draftKey,{draft:nextDraft,mode:nextMode,baseRevision}).catch(()=>{if(active())setError('输入未能保存在这台手机，请先不要离开。');});}
  function editTemplate(patch:Partial<SeriesTemplate>){edit({...draft,template:{...draft.template,...patch}});}
  function editRule(patch:Partial<SeriesRule>){edit({...draft,rule:{...draft.rule,...patch}});}
  async function submit(command?:SeriesMutation){
    if(command){if(command.draft)seriesDraft(command.draft);await storage.put(draftKey,{draft,mode,baseRevision:row?.revision||null});}
    const result=await submitSeriesMutation(storage,scope,target,api(),command,active,()=>storage.put(draftKey,null));
    if(!active())return;setRow(result);setPending(null);setConfirm(null);setRejected(false);setNotice('已保存到 Pajio。日程提醒尚未由本次操作启用。');calendarSeriesChanged();
    if(!active())return;onChanged(result);
    // A saved exception may cancel/move the selected instance. Reload before another edit.
    if(id){try{const fresh=await api().get(id,occurrence?.recurrence.occurrence_key);if(active()){setRow(fresh);setSelectedOccurrence(fresh.selected||null);const nextMode=mode==='once'&&fresh.selected?'once':'series';setMode(nextMode);setDraft({template:nextMode==='once'&&fresh.selected?occurrenceTemplate(fresh.selected):fresh.body.template,rule:fresh.body.rule});setBaseConflict(false);}}catch{if(active()){setReady(false);setError('修改已保存，当前版本暂未重新读取。请重新读取后继续编辑。');}}}
  }
  const save=()=>run(async()=>{
    const command:SeriesMutation=row?(mode==='once'&&occurrence?{action:'override',series_id:row.id,revision:row.revision,occurrence_key:occurrence.recurrence.occurrence_key,template:draft.template,request_key:Crypto.randomUUID()}:{action:'update',series_id:row.id,revision:row.revision,draft,request_key:Crypto.randomUUID()}):{action:'create',draft,request_key:Crypto.randomUUID()};
    try{await submit(command);}finally{if(active()){const waiting=await storage.get<unknown>(seriesPendingKey(scope,target));if(active())setPending(waiting?seriesMutation(waiting):null);}}
  });
  const action=(kind:'archive'|'restore'|'cancel'|'reset',key?:string)=>run(async()=>{if(!row)return;const command:SeriesMutation={action:kind,series_id:row.id,revision:row.revision,request_key:Crypto.randomUUID(),...(key?{occurrence_key:key}:{})};try{await submit(command);}finally{if(active()){const waiting=await storage.get<unknown>(seriesPendingKey(scope,target));if(active())setPending(waiting?seriesMutation(waiting):null);}}});
  const disabled=busy||!ready||!!pending||!!row?.deleted_at||baseConflict;
  return <View style={{gap:16,paddingBottom:24}}>
    <Text accessibilityRole="header" style={{fontSize:24,fontWeight:'600',color:c.ink}}>{row?'重复日程':'新建重复日程'}</Text>
    <Text style={{fontSize:14,lineHeight:23,color:c.muted}}>保存在当前身份。基本安排直接保存；不会启动 Agent 定时任务，也不会写入系统日历。</Text>
    {row&&<Text style={{fontSize:13,lineHeight:21,color:c.muted}}>版本 {row.revision} · {ruleLabel(row.body.rule)}{row.deleted_at?' · 已移除':''}</Text>}
    {row&&selectedOccurrence&&<View style={{flexDirection:'row',gap:8}}>{([{id:'once',label:'仅这一次'},{id:'series',label:'整个系列'}] as const).map(item=><PrimaryButton key={item.id} label={(mode===item.id?'✓ ':'')+item.label} disabled={disabled} tone="quiet" onPress={()=>void run(async()=>{const fresh=await api().get(row.id,occurrence?.recurrence.occurrence_key);if(active()){setRow(fresh);setSelectedOccurrence(fresh.selected||null);edit({template:item.id==='once'&&fresh.selected?occurrenceTemplate(fresh.selected):fresh.body.template,rule:fresh.body.rule},item.id==='once'&&fresh.selected?'once':'series',fresh.revision);}})}/>)}</View>}
    {baseConflict&&<View style={{gap:8,padding:16,backgroundColor:c.soft,borderRadius:16}}><Text style={{color:c.ink,lineHeight:23}}>本机草稿基于较旧版本，系列已有新修改。继续会用当前版本为基础保存你的输入。</Text><PrimaryButton label="保留我的输入，继续核对" onPress={()=>setBaseConflict(false)}/><PrimaryButton label="采用当前系列内容" tone="quiet" onPress={()=>{if(row){edit(row.body,'series');setBaseConflict(false);}}}/></View>}
    {mode==='once'&&occurrence&&<Text style={{color:c.muted,lineHeight:21}}>原定日期 {civilDateLabel(occurrence.recurrence.occurrence_key)}。改时间后仍属于这一次。</Text>}
    <TextInput mode="outlined" label="日程标题" value={draft.template.title} onChangeText={title=>editTemplate({title})} disabled={disabled}/>
    <TextInput mode="outlined" label="备注" value={draft.template.content} onChangeText={content=>editTemplate({content})} disabled={disabled} multiline/>
    <PrimaryButton label={draft.template.all_day?'✓ 全天日程':'设为全天日程'} tone="quiet" disabled={disabled} onPress={()=>edit({...draft,template:setSeriesAllDay(draft.template,!draft.template.all_day)})}/>
    <SeriesDateField label="开始" value={draft.template.start_local} allDay={draft.template.all_day} disabled={disabled} onChange={start_local=>editTemplate({start_local})}/>
    <SeriesDateField label={draft.template.all_day?'最后一天':'结束'} value={shownSeriesEnd(draft.template)} allDay={draft.template.all_day} disabled={disabled} onChange={value=>editTemplate({end_local:storedSeriesEnd(value,draft.template.all_day)})}/>
    {draft.template.all_day&&<Text style={{color:c.muted,lineHeight:21}}>从开始日期到最后一天，均包含在这次日程内。</Text>}
    <PrimaryButton label={advancedTime?'收起时区设置':'时区设置'} tone="quiet" disabled={disabled} onPress={()=>setAdvancedTime(value=>!value)}/>
    {advancedTime&&<View style={{gap:8}}><TextInput mode="outlined" label="日程时区" value={draft.template.timezone} onChangeText={timezone=>editTemplate({timezone})} disabled={disabled} autoCapitalize="none" autoCorrect={false}/><PrimaryButton label="使用本机时区" tone="quiet" disabled={disabled} onPress={()=>editTemplate({timezone:Intl.DateTimeFormat().resolvedOptions().timeZone||'Asia/Shanghai'})}/><Text style={{color:c.muted,lineHeight:21}}>默认使用创建时的本机时区。修改时区后，仍按上面选定的当地日期和钟点执行。</Text></View>}
    {!validTimezone(draft.template.timezone)&&<Text accessibilityRole="alert" style={{color:c.danger}}>时区无效，请打开时区设置核对。</Text>}
    {mode==='series'&&<>
      <Text style={{color:c.ink,fontSize:16}}>重复方式</Text><View style={{flexDirection:'row',flexWrap:'wrap',gap:8}}>{(['daily','weekly','monthly','yearly'] as const).map((frequency,index)=><PrimaryButton key={frequency} label={(draft.rule.frequency===frequency?'✓ ':'')+['每天','每周','每月','每年'][index]} tone="quiet" disabled={disabled} onPress={()=>editRule({frequency,weekdays:[]})}/>)}</View>
      <TextInput mode="outlined" label="间隔（1–365）" value={String(draft.rule.interval)} onChangeText={value=>{if(/^\d*$/.test(value))editRule({interval:Number(value)});}} disabled={disabled} keyboardType="number-pad"/>
      {draft.rule.frequency==='weekly'&&<View style={{flexDirection:'row',flexWrap:'wrap',gap:6}}>{[0,1,2,3,4,5,6].map(d=><TactilePressable key={d} accessibilityRole="checkbox" accessibilityState={{checked:draft.rule.weekdays.includes(d)}} accessibilityLabel={'周'+'一二三四五六日'[d]} disabled={disabled} onPress={()=>editRule({weekdays:draft.rule.weekdays.includes(d)?draft.rule.weekdays.filter(v=>v!==d):[...draft.rule.weekdays,d].sort()})} style={{minWidth:44,minHeight:44,borderRadius:12,alignItems:'center',justifyContent:'center',backgroundColor:draft.rule.weekdays.includes(d)?c.soft:c.surface}}><Text style={{color:c.ink}}>{'一二三四五六日'[d]}</Text></TactilePressable>)}</View>}
      <Text style={{fontSize:12,color:c.muted}}>每周未指定星期时，沿用首次日期的星期；已指定时须包含首次日期。</Text>
      <View style={{flexDirection:'row',flexWrap:'wrap',gap:8}}><PrimaryButton label="持续" tone="quiet" disabled={disabled} onPress={()=>editRule({count:null,until:null})}/><PrimaryButton label="按次数" tone="quiet" disabled={disabled} onPress={()=>editRule({count:12,until:null})}/><PrimaryButton label="截止日期" tone="quiet" disabled={disabled} onPress={()=>editRule({count:null,until:draft.template.start_local.slice(0,10)})}/></View>
      {draft.rule.count!==null&&<TextInput mode="outlined" label="重复次数（最多 1000）" value={String(draft.rule.count)} onChangeText={value=>{if(/^\d*$/.test(value))editRule({count:Number(value)});}} disabled={disabled} keyboardType="number-pad"/>}
      {draft.rule.until!==null&&<SeriesDateField label="重复到这一天" value={draft.rule.until} allDay disabled={disabled} onChange={until=>editRule({until})}/>}
      <Text style={{fontSize:13,lineHeight:22,color:c.muted}}>{ruleLabel(draft.rule)}。月末不存在的日期、非闰年的 2 月 29 日和不存在的夏令时时刻会跳过；重复时刻取第一次。</Text>
      {!!row?.exceptions.length&&<Text style={{fontSize:13,lineHeight:22,color:c.muted}}>已有 {row.exceptions.length} 个例外会保留原内容。新规则若不再包含这些原定日期，将拒绝保存；可先在下方恢复该次原规则。</Text>}
    </>}
    {!row?.deleted_at&&<PrimaryButton label={row?(mode==='once'?'保存这一次':'保存整个系列'):'创建重复日程'} disabled={disabled} loading={busy} onPress={()=>void save()}/>}
    {selectedOccurrence && <RecordReminderPanel connection={connection} record={selectedOccurrence} blocked={disabled || JSON.stringify(draft.template) !== JSON.stringify(mode === 'once' ? occurrenceTemplate(selectedOccurrence) : row?.body.template)}/>}
    {!!pending&&<View style={{padding:16,gap:12,backgroundColor:c.soft,borderRadius:16}}><Text style={{color:c.ink,lineHeight:23}}>上次修改待核对。再次核对使用同一编号，不创建第二份。</Text><PrimaryButton label="核对上次保存" disabled={busy} onPress={()=>void run(async()=>{await submit();})}/>{rejected&&<PrimaryButton label="读取最新版本，保留输入" tone="quiet" disabled={busy} onPress={()=>void run(async()=>{const latest=pending.series_id?await api().get(pending.series_id,occurrence?.recurrence.occurrence_key):null;if(!active())return;await storage.put(seriesPendingKey(scope,target),null);if(active()){setRow(latest);setSelectedOccurrence(latest?.selected||null);if(mode==='once'&&!latest?.selected)setMode('series');setPending(null);setRejected(false);setNotice('已读取最新版本；你的输入仍在，请核对后再保存。');}})}/>}</View>}
    {row&&<>
      {row.deleted_at?<PrimaryButton label="恢复整个系列" disabled={busy||!!pending} onPress={()=>void action('restore')}/>:<><PrimaryButton label="移除整个系列" tone="quiet" disabled={disabled} onPress={()=>setConfirm('archive')}/>{occurrence&&<PrimaryButton label="取消这一次" tone="quiet" disabled={disabled} onPress={()=>setConfirm('cancel')}/>}</>}
      {confirm&&<View style={{gap:8,padding:16,backgroundColor:c.soft,borderRadius:16}}><Text style={{color:c.ink,lineHeight:23}}>{confirm==='archive'?'整个系列会从日历隐藏，包括已有例外；可以恢复。':'仅取消这个原定日期的实例，可在例外列表恢复原规则。'}</Text><PrimaryButton label="确认" onPress={()=>void action(confirm,confirm==='cancel'?occurrence?.recurrence.occurrence_key:undefined)} disabled={disabled}/><PrimaryButton label="返回编辑" tone="quiet" onPress={()=>setConfirm(null)}/></View>}
      {!!row.exceptions.length&&<><Text style={{fontSize:17,color:c.ink,fontWeight:'600'}}>单次例外</Text>{row.exceptions.map(exception=><View key={exception.occurrence_key} style={{paddingVertical:10,gap:6,borderBottomWidth:1,borderColor:c.line}}><Text style={{color:c.ink}}>{civilDateLabel(exception.occurrence_key)} · {exception.cancelled?'已取消':exception.title||'已修改'}</Text><PrimaryButton label="恢复这次原规则" tone="quiet" disabled={disabled} onPress={()=>void action('reset',exception.occurrence_key)}/></View>)}</>}
    </>}
    <PrimaryButton label="查看已有及移除的系列" tone="quiet" disabled={busy} onPress={()=>void run(async()=>{const page=await api().list();if(active()){setRows(page.items);setNext(page.next);setShowList(true);}})}/>
    {showList&&<View style={{gap:10}}>{rows.map(item=><TactilePressable key={item.id} disabled={busy||!!pending} onPress={()=>onOpenSeries(item.id)} style={{padding:12,minHeight:64,backgroundColor:c.surface,borderRadius:14,gap:8}}><Text style={{color:c.ink}}>{item.body.template.title}{item.deleted_at?' · 已移除':''}</Text><Text style={{color:c.muted}}>{ruleLabel(item.body.rule)}</Text><Text style={{color:c.accentInk}}>打开系列{item.deleted_at?'并恢复':''}</Text></TactilePressable>)}{next&&<PrimaryButton label="继续查看系列" tone="quiet" disabled={busy} onPress={()=>void run(async()=>{const page=await api().list(next);if(active()){setRows(current=>[...current,...page.items]);setNext(page.next);}})}/>}</View>}
    {!!error&&<Text accessibilityRole="alert" style={{color:c.danger,lineHeight:23}}>{error}</Text>}{!!notice&&<Text accessibilityLiveRegion="polite" style={{color:c.success,lineHeight:23}}>{notice}</Text>}
    {!ready&&<PrimaryButton label="重新读取" tone="quiet" disabled={busy} onPress={()=>void run(async()=>{if(id){const raw=await storage.get<unknown>(draftKey),saved=raw?seriesEdit(raw):null;const value=await api().get(id,occurrence?.recurrence.occurrence_key);if(active()){setRow(value);setSelectedOccurrence(value.selected||null);setDraft(saved?.draft||{template:value.selected?occurrenceTemplate(value.selected):value.body.template,rule:value.body.rule});setMode(saved?.mode==='once'&&value.selected?'once':!saved&&value.selected?'once':'series');setBaseConflict(!!saved&&saved.baseRevision!==value.revision);setReady(true);}}})}/>}
  </View>;
}
