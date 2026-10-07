import {useAppTheme, useThemedStyles, type AppColors} from './app-theme';
import {useEffect, useMemo, useRef, useState} from 'react';
import {ActivityIndicator, AppState, StyleSheet, Text, View} from 'react-native';
import {ArrowUpRight, CalendarDays, CheckCheck, ChevronRight, Clock3, FileText, RefreshCw, Sparkles, Sun} from 'lucide-react-native';
import {ActivitySnapshot, Connection, RecordItem, WearingApi} from './core';
import {serviceFetch} from './transport';
import {eventOccursOn} from './calendar';
import {useLocalDate} from './use-local-date';
import {TactilePressable} from './experience/primitives';

type Props = {connection: Connection; records: RecordItem[]; connected: boolean; onCalendar:()=>void; onRecord:(item:RecordItem)=>void; onTask:(id:string)=>void; onDraft:(text:string)=>void};
export default function TodayPanel({connection, records, connected, onCalendar, onRecord, onTask, onDraft}: Props) {
  const {colors: c} = useAppTheme();
  const s = useThemedStyles(makeStyles);

  const today = useLocalDate();
  const api = useMemo(()=>new WearingApi(connection, serviceFetch),[connection]);
  const [activity,setActivity]=useState<ActivitySnapshot|null>(null), [loading,setLoading]=useState(true), [error,setError]=useState('');
  const refreshAction=useRef<(()=>Promise<void>)|null>(null);
  useEffect(()=>{
    let live=true,pending=false,foreground=AppState.currentState==='active'||AppState.currentState===null;
    const refresh=async()=>{if(!live||pending||!foreground)return;pending=true;
      try{const value=await api.activity();if(live){setActivity(value);setError('');}}
      catch{if(live)setError('暂时无法更新任务进展；已读到的内容会保留。');}
      finally{pending=false;if(live)setLoading(false);}
    };
    refreshAction.current=refresh;void refresh();
    const timer=setInterval(()=>{void refresh();},15000);
    const subscription=AppState.addEventListener('change',state=>{foreground=state==='active';if(foreground)void refresh();});
    return()=>{live=false;clearInterval(timer);subscription.remove();if(refreshAction.current===refresh)refreshAction.current=null;};
  },[api]);
  const events = today ? records.filter(r=>r.kind==='event' && eventOccursOn(r,today)).sort((a,b)=>(a.start_at||'').localeCompare(b.start_at||'')) : [];
  const tasks = records.filter(r=>r.kind==='task'&&!r.completed);
  const attention=activity?.items.filter(item=>item.bucket==='attention')||[];
  const recent=activity?.items.filter(item=>item.bucket==='results').slice(0,3)||[];
  const stale=!!error||!connected;
  return <View style={s.stack}>
    <View style={s.head}><Text style={s.title}>今天</Text><TactilePressable accessibilityLabel="更新今日概览" onPress={()=>{setLoading(true);void refreshAction.current?.();}} disabled={loading} style={s.round}>{loading?<ActivityIndicator color={c.muted}/>:<RefreshCw size={20} color={c.ink}/>}</TactilePressable></View>
    <Text style={s.timestamp}>{activity ? `任务进展读取于 ${new Date(activity.checked_at).toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit'})}` : '今日概览'}{stale?' · 暂未确认最新状态':''}</Text>
    <View style={[s.card,s.hero]}>
      <View style={s.inline}><Sun size={19} color={c.accent}/><Text style={s.date}>{new Date().toLocaleDateString('zh-CN',{month:'long',day:'numeric',weekday:'long'})}</Text></View>
      <Text style={s.hello}>{attention.length ? '有件事，等你拿主意。' : events.length ? '今天的安排，心里有数。' : '今天，从容一点。'}</Text>
      <Text style={s.body}>{loading&&!activity ? '正在整理已同步的日程和任务…' : `${events.length ? `今天有 ${events.length} 项日程。` : '目前没有已同步的今日日程。'}${tasks.length ? `还有 ${tasks.length} 件待办，可以按自己的节奏来。` : '想做什么，直接交代给我。'}${attention.length?' 有需要你决定的步骤，已放在下面。':''}`}</Text>
      <View style={s.tags}><Text style={s.tag}>日程 · {events.length}</Text><Text style={s.tag}>待办 · {tasks.length}</Text>{activity ? <Text style={s.tag}>进行中 · {activity.counts.active}</Text>:null}</View>
      <Text style={s.source}>日程与待办来自本机已同步记录{!connected?' · 当前连接不可用':''}</Text>
    </View>
    {attention.map(item=><TactilePressable key={item.task_id} accessibilityLabel={'查看需要处理的步骤：'+item.title} onPress={()=>onTask(item.task_id)} style={s.card}>
      <Text style={s.attention}>{item.label}</Text><Text style={s.cardTitle}>{item.title}</Text><Text numberOfLines={4} style={s.body}>{item.summary}</Text><View style={s.trailing}><Text style={s.action}>查看这一步</Text><ArrowUpRight size={17} color={c.ink}/></View>
    </TactilePressable>)}
    <View style={s.card}>
      <TactilePressable accessibilityLabel="打开完整日历" onPress={onCalendar} style={s.sectionHead}><View style={s.inline}><CalendarDays size={19} color={c.accent}/><Text style={s.sectionTitle}>今日安排</Text></View><ChevronRight size={19} color={c.muted}/></TactilePressable>
      {events.length ? events.map(item=><TactilePressable key={item.id} onPress={()=>onRecord(item)} style={s.event}><Text style={s.eventTime}>{item.start_at?.length===10?'全天':new Date(item.start_at!).toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit'})}</Text><Text style={s.eventTitle}>{item.title}</Text></TactilePressable>):<Text style={s.body}>留点空白也很好。往后几天的安排，都可以在日历里查看。</Text>}
    </View>
    {recent.length ? <View style={s.card}><View style={s.inline}><CheckCheck size={19} color={c.success}/><Text style={s.sectionTitle}>最近有了这些结果</Text></View>{recent.map(item=><TactilePressable key={item.task_id} onPress={()=>onTask(item.task_id)} style={s.result}><View style={{flex:1,gap:5}}><Text numberOfLines={2} style={s.resultTitle}>{item.title}</Text><Text numberOfLines={2} style={s.body}>{item.summary}</Text></View><ChevronRight size={18} color={c.muted}/></TactilePressable>)}</View>:null}
    <TactilePressable onPress={()=>onDraft('请根据我已连接且有权限访问的信息，整理今天的图文简报：接下来的安排、需要我决定的事、最新进展。区分事实和建议，附来源与更新时间；没有数据的部分请直说。')} accessibilityLabel="准备图文简报的消息" style={s.briefing}>
      <Sparkles size={22} color={c.accent}/><View style={{flex:1,gap:5}}><Text style={s.sectionTitle}>准备一份图文简报</Text><Text style={s.body}>结合已连接的信息，整理成好读的结果。</Text></View><ArrowUpRight size={20} color={c.ink}/>
    </TactilePressable>
    {error ? <Text accessibilityLiveRegion="polite" style={s.source}>{error}</Text>:null}
  </View>;
}

export function ScheduleSuggestions({onDraft}:{onDraft:(text:string)=>void}) {
  const {colors: c} = useAppTheme();
  const s = useThemedStyles(makeStyles);

  const items=[{title:'每日优先事项简报',detail:'从日程、待办和消息中整理最重要的几件事。',icon:CheckCheck,text:'每天早上八点，整理我的日程、待办和已连接应用的信息，给我一份每日优先事项图文简报。请先说明可用来源并确认定时安排。'}, {title:'今日会议准备',detail:'提前整理背景、议程和需要确认的问题。',icon:CalendarDays,text:'请为我设置每天早上九点的会议准备，读取当天已授权日历，整理会议背景、议程和需要确认的问题。请先确认可用来源和安排。'}, {title:'每周项目进展',detail:'把进展、需要处理的事和下一步放在一起。',icon:FileText,text:'每周五下午五点，汇总已交代项目的进展、阻碍和下一步。请先确认范围与定时安排。'}, {title:'截止事项提前检查',detail:'看看未来两周有什么需要提前准备。',icon:Clock3,text:'每天晚上八点，检查未来两周已记录的截止事项，提醒我提前准备材料。请先确认来源与定时安排。'}];
  return <View style={s.stack}><Text style={s.sectionTitle}>为你推荐</Text>{items.map(({title,detail,icon:Icon,text})=><TactilePressable key={title} accessibilityLabel={'准备设置：'+title} onPress={()=>onDraft(text)} style={s.suggestion}><Icon size={23} color={c.ink}/><View style={{flex:1,gap:6}}><Text style={s.sectionTitle}>{title}</Text><Text style={s.body}>{detail}</Text></View><ArrowUpRight size={18} color={c.muted}/></TactilePressable>)}</View>;
}
const makeStyles = (c: AppColors) => StyleSheet.create({
  stack:{gap:18},head:{flexDirection:'row',alignItems:'center',justifyContent:'space-between',marginBottom:2},title:{fontSize:34,lineHeight:44,fontWeight:'500',color:c.ink,letterSpacing:-.7},round:{width:44,height:44,borderRadius:23,alignItems:'center',justifyContent:'center',backgroundColor:c.surface,borderWidth:1,borderColor:c.line},timestamp:{textAlign:'center',fontSize:12,lineHeight:22,color:c.muted,marginVertical:8},
  card:{padding:22,borderRadius:27,gap:14,backgroundColor:c.surface,borderWidth:1,borderColor:c.line},hero:{backgroundColor:c.surface,paddingVertical:24},inline:{flexDirection:'row',alignItems:'center',gap:8},date:{fontSize:13,lineHeight:21,color:c.accent,fontWeight:'600'},hello:{fontSize:25,lineHeight:35,fontWeight:'600',color:c.ink,letterSpacing:-.5},body:{fontSize:14,lineHeight:24,color:c.muted},tags:{flexDirection:'row',flexWrap:'wrap',gap:7},tag:{fontSize:12,lineHeight:20,color:c.muted,backgroundColor:c.soft,paddingVertical:5,paddingHorizontal:12,borderRadius:17},source:{fontSize:11,lineHeight:19,color:c.muted},sectionTitle:{fontSize:16,lineHeight:24,fontWeight:'500',color:c.ink},sectionHead:{minHeight:44,flexDirection:'row',alignItems:'center',justifyContent:'space-between'},event:{minHeight:44,flexDirection:'row',gap:16,paddingVertical:8,alignItems:'center'},eventTime:{fontSize:13,color:c.accent,minWidth:42},eventTitle:{fontSize:16,lineHeight:25,color:c.ink,flex:1},cardTitle:{fontSize:20,lineHeight:29,fontWeight:'500',color:c.ink},attention:{fontSize:13,color:c.accent,fontWeight:'600'},trailing:{flexDirection:'row',alignItems:'center',justifyContent:'flex-end',gap:5},action:{fontSize:13,color:c.ink},result:{flexDirection:'row',gap:12,alignItems:'center',paddingVertical:10},resultTitle:{fontSize:16,lineHeight:25,color:c.ink},briefing:{flexDirection:'row',alignItems:'center',gap:12,padding:20,borderRadius:26,backgroundColor:c.surface,borderWidth:1,borderColor:c.line},suggestion:{flexDirection:'row',alignItems:'flex-start',gap:13,padding:18,borderRadius:25,backgroundColor:c.surface,borderWidth:1,borderColor:c.line},
});
