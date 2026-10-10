import {Choice} from './experience/selection';
import {useEffect, useMemo, useRef, useState} from 'react';
import {ActivityIndicator, Platform, ScrollView, StyleSheet, Text, View} from 'react-native';
import * as Crypto from 'expo-crypto';
import {Connection, scopeOf} from './core';
import {AppColors, useAppTheme, useThemedStyles} from './app-theme';
import {PrimaryButton} from './experience/primitives';
import {storage} from './storage';
import {serviceFetch} from './transport';
import {digestArtifact} from './artifact-share';
import {shareOriginalBytes} from './workspace-share';
import {categories, componentLabels, eventLabels, HealthCategory, HealthExport, HealthExportRequest, HealthHistory, HealthHistoryApi, healthExportContents, statusLabels} from './health-history';
const labels:Record<HealthCategory,string>={chat:'聊天',voice:'语音',sync:'同步',files:'文件',notifications:'通知',devices:'设备',performance:'速度与稳定性',other:'其他'};
const time=(value:string|null)=>value?new Date(value).toLocaleString('zh-CN'):'尚无记录';
type Contents=ReturnType<typeof healthExportContents>;
export default function HealthHistoryPanel({connection}:{connection:Connection}) {return <History key={`${scopeOf(connection)}|${connection.session?.credentialId||connection.development?.accessToken||''}`} connection={connection}/>;}
function History({connection}:{connection:Connection}) {
  const s=useThemedStyles(styles),{colors}=useAppTheme();
  const active=useRef(true),work=useRef(false);
  const api=useMemo(()=>new HealthHistoryApi(connection,digestArtifact,serviceFetch),[connection]);
  const request=useMemo(()=>new HealthExportRequest(storage,api),[api]);
  const [history,setHistory]=useState<HealthHistory|null>(null),[events,setEvents]=useState<HealthHistory['events']>([]),[cursor,setCursor]=useState<number|null>(null);
  const [category,setCategory]=useState<HealthCategory>('other'),[pending,setPending]=useState(false),[report,setReport]=useState<HealthExport|null>(null),[contents,setContents]=useState<Contents|null>(null);
  const [expanded,setExpanded]=useState(false),[busy,setBusy]=useState(false),[notice,setNotice]=useState(''),[error,setError]=useState('');
  function apply(value:HealthHistory,older=false){if(!active.current)return;setHistory(value);setEvents(previous=>older?[...previous,...value.events.filter(item=>!previous.some(prior=>prior.id===item.id))]:value.events);setCursor(value.next_before_event);}
  useEffect(()=>{active.current=true;api.setActive(true);return()=>{active.current=false;api.setActive(false);};},[api]);
  async function run(action:()=>Promise<void>){if(work.current||!active.current)return;work.current=true;setBusy(true);setNotice('');setError('');try{await action();}catch(cause){if(active.current)setError(cause instanceof Error?cause.message:'本次操作尚未完成，请重试。');}finally{const saved=await request.pending().catch(()=>null);work.current=false;if(active.current){if(saved){setPending(true);setCategory(saved.category);}setBusy(false);}}}
  async function load(){await run(async()=>{const saved=await request.pending();if(!active.current)return;setPending(!!saved);if(saved)setCategory(saved.category);apply(await api.load());});}
  async function generate(){await run(async()=>{const metadata=await request.run(Crypto.randomUUID(),category);if(!active.current)return;setContents(null);setReport(metadata);setCategory(metadata.category);setPending(true);const value=await api.contents(metadata);if(!active.current)return;setContents(value);setNotice('诊断文件已准备好，还没有发送。可以阅读下方完整内容。');});}
  async function share(){if(!report||!contents)return;await run(async()=>{const bytes=new TextEncoder().encode(JSON.stringify(contents,null,2));await shareOriginalBytes(async()=>bytes,report.filename,'application/json',()=>active.current);if(active.current)setNotice('分享面板已关闭，请在目标 App 确认保存或发送结果。');});}
  return <View style={s.card}>
    <Text style={s.title}>运行历史</Text><Text style={s.copy}>查看最近 7 天的检查记录，以及发现问题、状态变化和恢复的时间。</Text>
    <PrimaryButton label={expanded?'收起运行历史':'查看运行历史'} tone="quiet" disabled={busy} onPress={()=>{setExpanded(!expanded);if(!expanded&&!history)void load();}}/>
    {expanded?<>
      {history?<><Text style={s.copy}>最近检查：{time(history.coverage.latest_observed_at)}</Text><Text style={s.copy}>{history.coverage.freshness==='stale'?'检查记录已过时，当前状况需要重新核对。':history.coverage.freshness==='never_observed'?'还没有检查记录。':'以下状态来自最近一次检查。'} {history.sampler_running?'服务正在定期检查。':'定期检查当前未运行。'}</Text>
        {history.samples[0]?.observations.filter(item=>item.component!=='task').map(item=><View key={item.component} style={s.line}><Text style={s.name}>{componentLabels[item.component]}</Text><Text style={s.copy}>{statusLabels[item.status]}</Text></View>)}
        <PrimaryButton label="检查当前状态" tone="quiet" disabled={busy} onPress={()=>{void run(async()=>{apply(await api.sample());if(active.current)setNotice('已取回最近一次检查。短时间连续点击会沿用刚完成的结果。');});}}/>
        <Text style={s.name}>状态变化</Text>{events.length?events.map(event=><View key={event.id} style={s.event}><Text style={s.name}>{componentLabels[event.component]} · {eventLabels[event.kind]}</Text><Text style={s.copy}>{statusLabels[event.status]} · {time(event.observed_at)}</Text>{event.task_id?<Text selectable style={s.foot}>任务 {event.task_id}</Text>:null}{event.condition_started_at?<Text style={s.foot}>本次问题开始于 {time(event.condition_started_at)}</Text>:null}</View>):<Text style={s.copy}>当前范围没有状态变化记录。</Text>}
        {cursor?<PrimaryButton label="查看更早记录" tone="quiet" disabled={busy} onPress={()=>{void run(async()=>apply(await api.load(cursor),true));}}/>:null}
        <Text style={s.foot}>定期检查只能证明采样时刻的状态；没有记录的时段不能视为正常运行。</Text>
      </>:<PrimaryButton label="读取检查记录" disabled={busy} onPress={()=>{void load();}}/>}
      <View style={s.separator}/><Text style={s.name}>导出运行历史</Text><Text style={s.copy}>只包含检查时间、任务编号与状态，不包含对话、文件正文、地址或密钥。文件保留 24 小时。</Text>
      <View style={s.choices}>{categories.map(value=><Choice key={value}  selected={category===value} disabled={busy||pending} onPress={()=>setCategory(value)} style={[s.choice,category===value&&s.selected]}><Text style={category===value?s.selectedText:s.copy}>{labels[value]}</Text></Choice>)}</View>
      <PrimaryButton label={contents?'重新读取本次诊断':pending?'取回上次诊断':'生成并预览诊断'} disabled={busy} onPress={()=>{void generate();}}/>
      {contents&&report?<><Text style={s.foot}>生成于 {time(report.created_at)} · 未发送</Text><ScrollView style={s.preview} nestedScrollEnabled><Text selectable style={s.code}>{JSON.stringify(contents,null,2)}</Text></ScrollView><PrimaryButton label="保存或分享这份诊断" disabled={busy} onPress={()=>{void share();}}/></>:null}
      {report?<PrimaryButton label="准备一份新的诊断" tone="quiet" disabled={busy} onPress={()=>{void run(async()=>{await request.reset();if(active.current){setPending(false);setReport(null);setContents(null);}});}}/>:null}
    </>:null}
    {busy?<ActivityIndicator color={colors.accent}/>:null}{error?<Text style={s.copy} accessibilityLiveRegion="polite">{error}</Text>:null}{notice?<Text style={s.copy} accessibilityLiveRegion="polite">{notice}</Text>:null}
  </View>;
}
const styles=(c:AppColors)=>StyleSheet.create({card:{backgroundColor:c.surface,borderRadius:24,padding:20,gap:12},title:{color:c.ink,fontSize:19,fontWeight:'600'},name:{color:c.ink,fontSize:14,fontWeight:'600'},copy:{color:c.muted,fontSize:14,lineHeight:22},foot:{color:c.muted,fontSize:12,lineHeight:19},line:{flexDirection:'row',justifyContent:'space-between',gap:12},event:{paddingVertical:10,borderBottomWidth:1,borderColor:c.line,gap:4},separator:{height:1,backgroundColor:c.line,marginVertical:8},choices:{flexDirection:'row',flexWrap:'wrap',gap:8},choice:{padding:10,borderRadius:14,borderWidth:1,borderColor:c.line},selected:{backgroundColor:c.selectionSurface,borderColor:c.selectionBorder},selectedText:{color:c.accent,fontSize:14,lineHeight:22},preview:{maxHeight:300,backgroundColor:c.canvas,padding:12,borderRadius:12},code:{fontSize:11,lineHeight:17,color:c.ink,fontFamily:Platform.OS==='ios'?'Menlo':'monospace'}});
