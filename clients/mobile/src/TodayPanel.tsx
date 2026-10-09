import type {OngoingCreateRequest} from './ongoing-management-forms';
import type {ReactNode} from 'react';
import {useAppTheme, useThemedStyles, type AppColors} from './app-theme';
import {ActivityIndicator, StyleSheet, Text, View} from 'react-native';
import {AlertCircle, Archive, ArrowUpRight, CalendarDays, Check, CheckCheck, ChevronRight, CircleHelp, Clock3, FileText, RefreshCw, Square} from 'lucide-react-native';
import {ActivityItem, Connection, RecordItem} from './core';
import {activityPresentation} from './activity-presentation';
import {useActivitySnapshot} from './use-activity-snapshot';
import {eventOccursOn} from './calendar';
import {useLocalDate} from './use-local-date';
import {TactilePressable} from './experience/primitives';

const statusIcons = {alert: AlertCircle, clock: Clock3, file: FileText, check: Check, stop: Square, archive: Archive, help: CircleHelp};

type Props = {connection: Connection; records: RecordItem[]; connected: boolean; calendarStatus?:ReactNode; onRefreshRecords?:()=>Promise<void>; onCalendar:()=>void; onRecord:(item:RecordItem)=>void; onTask:(id:string)=>void; onBriefing:()=>void; onDraft?:(text:string)=>void};
export default function TodayPanel({connection, records, connected, calendarStatus, onRefreshRecords, onCalendar, onRecord, onTask, onBriefing}: Props) {
  const {colors: c} = useAppTheme();
  const s = useThemedStyles(makeStyles);

  const today = useLocalDate();
  const {snapshot: activity, loading, error, stale: cachedStale, refresh} = useActivitySnapshot(connection);
  const events = today ? records.filter(r=>r.kind==='event' && eventOccursOn(r,today)).sort((a,b)=>(a.start_at||'').localeCompare(b.start_at||'')) : [];
  const tasks = records.filter(r=>r.kind==='task'&&!r.completed);
  const items = [...(activity?.items || [])].sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at));
  const attention = items.filter(item => activityPresentation(item).kind === 'attention');
  const attentionCount = activity?.counts.attention || 0;
  const delivered = items.filter(item => activityPresentation(item).kind === 'result').slice(0, 3);
  const active = items.filter(item => activityPresentation(item).group === 'active').slice(0, 3);
  const waiting = items.filter(item => activityPresentation(item).group === 'waiting').slice(0, 3);
  const history = items.filter(item => ['failed', 'stopped', 'closed', 'unknown'].includes(activityPresentation(item).kind)).slice(0, 3);
  const stale = cachedStale || !connected;
  const row = (item: ActivityItem, index: number, length: number) => {
    const presentation = activityPresentation(item), Icon = statusIcons[presentation.icon];
    const color = presentation.tone === 'danger' ? c.danger : presentation.tone === 'success' ? c.success : presentation.tone === 'active' ? c.accent : presentation.tone === 'attention' ? c.attention : c.muted;
    return <TactilePressable key={item.task_id} accessibilityLabel={`${item.title}，${presentation.label}，${presentation.action}`} onPress={() => onTask(item.task_id)} style={[s.taskRow, index < length - 1 && s.divider]}>
      <Icon size={19} color={color}/><View style={s.rowWords}><View style={s.rowMeta}><Text style={[s.rowStatus, {color}]}>{presentation.label}</Text>{item.unread ? <Text style={s.rowUnread}>未读</Text> : null}</View><Text numberOfLines={2} style={s.resultTitle}>{item.title}</Text>{item.summary && presentation.kind !== 'active' && presentation.kind !== 'waiting' ? <Text numberOfLines={2} style={s.body}>{item.summary}</Text> : null}</View><ChevronRight size={18} color={c.muted}/>
    </TactilePressable>;
  };
  const limited = (shown: number, total: number) => total > shown ? <Text style={s.source}>当前显示 {shown} 项，共 {total} 项；本页仅展示最近读取到的部分内容。</Text> : null;
  return <View style={s.stack}>
    <View style={s.head}><View style={s.headingWords}><Text style={s.title}>今天</Text><Text style={s.date}>{new Date().toLocaleDateString('zh-CN',{month:'long',day:'numeric',weekday:'long'})}</Text></View><TactilePressable accessibilityLabel="更新今日概览" onPress={()=>{void refresh();void onRefreshRecords?.();}} disabled={loading} style={s.round}>{loading?<ActivityIndicator color={c.muted}/>:<RefreshCw size={20} color={c.ink}/>}</TactilePressable></View>
    <Text style={s.timestamp}>{activity ? `${stale ? '上次读取' : '任务进展读取于'} ${new Date(activity.checked_at).toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit'})}` : loading ? '正在读取任务进展…' : '任务进展暂未读取'}{stale?' · 暂未确认最新状态':''}</Text>
    {error ? <Text accessibilityLiveRegion="polite" style={s.source}>{error}</Text> : null}
    {attentionCount > 0 ? <View style={s.section}><Text style={s.sectionTitle}>等你处理 · {attentionCount}{stale ? ' · 上次读取' : ''}</Text>
      {attention.map(item => {
        const presentation = activityPresentation(item);
        return <TactilePressable key={item.task_id} accessibilityLabel={`${presentation.label}：${item.title}，${presentation.action}`} onPress={() => onTask(item.task_id)} style={s.card}>
          <Text style={s.attention}>{presentation.label}</Text><Text style={s.cardTitle}>{item.title}</Text>{item.summary ? <Text numberOfLines={4} style={s.body}>{item.summary}</Text> : null}<View style={s.trailing}><Text style={s.action}>{presentation.action}</Text><ArrowUpRight size={17} color={c.ink}/></View>
        </TactilePressable>;
      })}{limited(attention.length, attentionCount)}
    </View> : activity ? <Text style={s.source}>{stale ? '上次读取时，没有需要你处理的步骤。' : '目前没有需要你处理的步骤。'}</Text> : null}
    {delivered.length ? <View style={s.section}><Text style={s.sectionTitle}>最近返回的内容{stale ? ' · 上次读取' : ''}</Text><View style={s.rows}>{delivered.map((item, index) => row(item, index, delivered.length))}</View></View> : null}
    {activity && activity.counts.active > 0 ? <View style={s.section}><Text style={s.sectionTitle}>正在推进 · {activity.counts.active}{stale ? ' · 上次读取' : ''}</Text>{active.length ? <View style={s.rows}>{active.map((item, index) => row(item, index, active.length))}</View> : null}{limited(active.length, activity.counts.active)}</View> : null}
    {activity && activity.counts.waiting > 0 ? <View style={s.section}><Text style={s.sectionTitle}>已排队 · {activity.counts.waiting}{stale ? ' · 上次读取' : ''}</Text>{waiting.length ? <View style={s.rows}>{waiting.map((item, index) => row(item, index, waiting.length))}</View> : null}{limited(waiting.length, activity.counts.waiting)}</View> : null}
    {history.length ? <View style={s.section}><Text style={s.sectionTitle}>历史记录{stale ? ' · 上次读取' : ''}</Text><View style={s.rows}>{history.map((item, index) => row(item, index, history.length))}</View></View> : null}
    {activity?.has_more ? <Text style={s.source}>任务进展仅包含最近读取到的部分记录。</Text> : null}
    <View style={s.card}>
      <TactilePressable accessibilityLabel="打开完整日历" onPress={onCalendar} style={s.sectionHead}><View style={s.inline}><CalendarDays size={19} color={c.ink}/><Text style={s.sectionTitle}>今日安排</Text></View><ChevronRight size={19} color={c.muted}/></TactilePressable>
      {events.length ? events.map((item, index) => <TactilePressable key={item.id} onPress={() => onRecord(item)} style={[s.event, index < events.length - 1 && s.divider]}><Text style={s.eventTime}>{item.start_at?.length===10?'全天':new Date(item.start_at!).toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit'})}</Text><Text style={s.eventTitle}>{item.title}</Text></TactilePressable>) : <Text style={s.body}>目前没有已同步的今日日程。</Text>}
      <Text style={s.source}>已读取的安排 · {events.length} 项日程 · {tasks.length} 件未完成待办{!connected ? ' · 当前连接不可用' : ''}</Text>
      {calendarStatus}
    </View>
    <TactilePressable onPress={onBriefing} accessibilityLabel="打开每日图文简报" style={s.briefing}>
      <FileText size={22} color={c.ink}/><View style={s.rowWords}><Text style={s.sectionTitle}>每日图文简报</Text><Text style={s.body}>设置兴趣与关注重点，选择资料来源，再整理新一份简报。</Text></View><ArrowUpRight size={20} color={c.ink}/>
    </TactilePressable>
  </View>;

}

export function ScheduleSuggestions({onCreate}:{onCreate:(request:Omit<OngoingCreateRequest,'id'>)=>void}) {
  const {colors: c} = useAppTheme();
  const s = useThemedStyles(makeStyles);

  const items=[{title:'每日优先事项简报',detail:'从日程、待办和消息中整理最重要的几件事。',icon:CheckCheck,text:'每天早上八点，整理我的日程、待办和已连接应用的信息，给我一份每日优先事项图文简报。请先说明可用来源并确认定时安排。'}, {title:'今日会议准备',detail:'提前整理背景、议程和需要确认的问题。',icon:CalendarDays,text:'请为我设置每天早上九点的会议准备，读取当天已授权日历，整理会议背景、议程和需要确认的问题。请先确认可用来源和安排。'}, {title:'每周项目进展',detail:'把进展、需要处理的事和下一步放在一起。',icon:FileText,text:'每周五下午五点，汇总已交代项目的进展、阻碍和下一步。请先确认范围与定时安排。'}, {title:'截止事项提前检查',detail:'看看未来两周有什么需要提前准备。',icon:Clock3,text:'每天晚上八点，检查未来两周已记录的截止事项，提醒我提前准备材料。请先确认来源与定时安排。'}];
  return <View style={s.stack}><Text style={s.sectionTitle}>为你推荐</Text>{items.map(({title,detail,icon:Icon,text})=><TactilePressable key={title} accessibilityLabel={'准备设置：'+title} onPress={()=>onCreate({title,instruction:text.replace(/请先.*$/,''),repeat:title==='每周项目进展'?'weekly':'daily',time:title==='今日会议准备'?'09:00':title==='每周项目进展'?'17:00':title==='截止事项提前检查'?'20:00':'08:00',weekday:5,timezone:Intl.DateTimeFormat().resolvedOptions().timeZone||'Asia/Shanghai'})} style={s.suggestion}><Icon size={23} color={c.ink}/><View style={{flex:1,gap:6}}><Text style={s.sectionTitle}>{title}</Text><Text style={s.body}>{detail}</Text></View><ArrowUpRight size={18} color={c.muted}/></TactilePressable>)}</View>;
}
const makeStyles = (c: AppColors) => StyleSheet.create({
  stack: {gap: 18}, section: {gap: 10}, head: {flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: 2}, headingWords: {gap: 6}, title: {fontSize: 30, lineHeight: 38, fontWeight: '500', color: c.ink, letterSpacing: -.7},
  round: {width: 44, height: 44, borderRadius: 16, alignItems: 'center', justifyContent: 'center', backgroundColor: c.surface, borderWidth: StyleSheet.hairlineWidth, borderColor: c.line}, timestamp: {fontSize: 13, lineHeight: 20, color: c.muted, marginTop: -8}, date: {fontSize: 14, lineHeight: 22, color: c.muted},
  card: {padding: 18, borderRadius: 16, gap: 12, backgroundColor: c.surface, borderWidth: StyleSheet.hairlineWidth, borderColor: c.line}, rows: {paddingHorizontal: 16, borderRadius: 16, backgroundColor: c.surface, borderWidth: StyleSheet.hairlineWidth, borderColor: c.line}, taskRow: {minHeight: 68, flexDirection: 'row', gap: 12, alignItems: 'center', paddingVertical: 14}, divider: {borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: c.line}, rowWords: {flex: 1, minWidth: 0, gap: 5}, rowMeta: {flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 8}, rowStatus: {fontSize: 13, lineHeight: 20, color: c.muted}, rowUnread: {fontSize: 13, lineHeight: 20, color: c.accent},
  inline: {flexDirection: 'row', alignItems: 'center', gap: 8}, body: {fontSize: 14, lineHeight: 24, color: c.muted}, source: {fontSize: 13, lineHeight: 20, color: c.muted}, sectionTitle: {fontSize: 16, lineHeight: 24, fontWeight: '500', color: c.ink}, sectionHead: {minHeight: 44, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between'}, event: {minHeight: 48, flexDirection: 'row', gap: 16, paddingVertical: 10, alignItems: 'center'}, eventTime: {fontSize: 13, color: c.ink, minWidth: 42}, eventTitle: {fontSize: 16, lineHeight: 25, color: c.ink, flex: 1},
  cardTitle: {fontSize: 19, lineHeight: 28, fontWeight: '500', color: c.ink}, attention: {fontSize: 13, color: c.attention, fontWeight: '600'}, trailing: {flexDirection: 'row', alignItems: 'center', justifyContent: 'flex-end', gap: 5}, action: {fontSize: 13, color: c.ink}, resultTitle: {fontSize: 16, lineHeight: 25, color: c.ink}, briefing: {flexDirection: 'row', alignItems: 'center', gap: 12, padding: 18, borderRadius: 16, backgroundColor: c.surface, borderWidth: StyleSheet.hairlineWidth, borderColor: c.line}, suggestion: {flexDirection: 'row', alignItems: 'flex-start', gap: 13, padding: 18, borderRadius: 16, backgroundColor: c.surface, borderWidth: StyleSheet.hairlineWidth, borderColor: c.line},
});
