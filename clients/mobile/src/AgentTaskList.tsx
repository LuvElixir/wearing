import {useAppTheme, useThemedStyles, type AppColors} from './app-theme';
import {useEffect, useRef, useState} from 'react';
import {ActivityIndicator, AppState, Pressable, StyleSheet, Text, View} from 'react-native';
import {ArrowUpRight, ChevronRight, RefreshCw} from 'lucide-react-native';
import {ActivityItem, ActivitySnapshot, Connection, WearingApi} from './core';
import {serviceFetch} from './transport';

type Props = {
  connection: Connection;
  onTask: (id: string) => void;
  onGoals: () => void;
  onDraft: (text: string) => void;
};

const localDay = (value: string | Date) => {
  const date = value instanceof Date ? value : new Date(value);
  return `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`;
};
const updated = (value: string, today: boolean) => new Date(value).toLocaleString('zh-CN', today
  ? {hour: '2-digit', minute: '2-digit'}
  : {month: 'numeric', day: 'numeric'});

/** Agent tasks and their actual receipts; personal checkboxes live separately. */
export default function AgentTaskList({connection, onTask, onGoals, onDraft}: Props) {
  const {colors: c} = useAppTheme();
  const s = useThemedStyles(makeStyles);

  const scope = `${connection.endpoint}|${connection.identity}|${connection.development?.accessToken || ''}|${connection.development?.expiresAt || ''}`;
  const [result, setResult] = useState<{scope: string; snapshot: ActivitySnapshot} | null>(null);
  const [feedback, setFeedback] = useState<{scope: string; error: boolean; loading: boolean}>({scope, error: false, loading: true});
  const refreshAction = useRef<(() => Promise<void>) | null>(null);
  const snapshot = result?.scope === scope ? result.snapshot : null;
  const loading = feedback.scope !== scope || feedback.loading;
  const error = feedback.scope === scope && feedback.error;

  useEffect(() => {
    let disposed = false, pending = false;
    let foreground = AppState.currentState === 'active' || AppState.currentState === null;
    const refresh = async () => {
      if (disposed || pending || !foreground) return;
      pending = true;
      setFeedback(previous => ({scope, error: previous.scope === scope && previous.error, loading: true}));
      try {
        const next = await new WearingApi(connection, serviceFetch).activity();
        if (disposed) return;
        setResult({scope, snapshot: next});
        setFeedback({scope, error: false, loading: false});
      } catch {
        if (!disposed) setFeedback({scope, error: true, loading: false});
      } finally {pending = false;}
    };
    refreshAction.current = refresh;
    void refresh();
    const timer = setInterval(() => {void refresh();}, 15000);
    const subscription = AppState.addEventListener('change', state => {
      foreground = state === 'active';
      if (foreground) void refresh();
    });
    return () => {
      disposed = true; clearInterval(timer); subscription.remove();
      if (refreshAction.current === refresh) refreshAction.current = null;
    };
  }, [connection, scope]);

  const today = localDay(new Date());
  const all = [...(snapshot?.items || [])].sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at));
  const groups = [
    {title: '今天', today: true, items: all.filter(item => localDay(item.updated_at) === today)},
    {title: '更早', today: false, items: all.filter(item => localDay(item.updated_at) !== today)},
  ];
  const card = (item: ActivityItem, isToday: boolean) => <Pressable key={item.task_id}
    accessibilityRole="button" accessibilityLabel={`${item.title}，${item.label}，查看原对话`}
    onPress={() => onTask(item.task_id)} style={({pressed}) => [s.card, pressed && s.pressed]}>
    <View style={s.titleRow}>{item.unread ? <View style={s.unread}/> : null}<Text style={s.title} numberOfLines={2}>{item.title}</Text></View>
    <View style={s.meta}>
      <Text numberOfLines={1} style={[s.status, item.bucket === 'attention' && s.attention, item.bucket === 'active' && s.active]}>{error ? '上次 · ' : ''}{item.label}</Text>
      <Text style={s.time}>{updated(item.updated_at, isToday)}</Text>
    </View>
  </Pressable>;

  return <View style={s.container}>
    <View style={s.heading}>
      <Text style={s.caption}>交给我的事</Text>
      <Pressable accessibilityRole="button" accessibilityLabel="刷新任务" disabled={loading} onPress={() => {void refreshAction.current?.();}} style={({pressed}) => [s.refresh, pressed && s.pressed]}>
        {loading ? <ActivityIndicator size="small" color={c.muted}/> : <RefreshCw size={16} color={c.muted}/>}
      </Pressable>
    </View>
    {error ? <View style={s.notice} accessibilityLiveRegion="polite"><Text style={s.noticeText}>{snapshot ? `暂时未连上，保留 ${new Date(snapshot.checked_at).toLocaleTimeString('zh-CN', {hour: '2-digit', minute: '2-digit'})} 查看时的状态。` : '暂时读不到任务，请检查连接后重试。'}</Text><Pressable accessibilityRole="button" accessibilityLabel="重新读取任务" disabled={loading} onPress={() => {void refreshAction.current?.();}} style={s.retry}><Text style={s.linkText}>重试</Text></Pressable></View> : null}
    {!snapshot && !error ? <Text style={s.loading} accessibilityLiveRegion="polite">正在找回你的任务…</Text> : null}
    {snapshot?.total === 0 ? <View style={s.empty}>
      <Text style={s.emptyTitle}>交代过的事，都会留在这里</Text>
      <Text style={s.emptyText}>处理到哪一步、有什么结果，回来就能看到。</Text>
      <Pressable accessibilityRole="button" onPress={() => onDraft('帮我处理这件事：')} style={({pressed}) => [s.draft, pressed && s.pressed]}><Text style={s.linkText}>交代一件事</Text><ArrowUpRight size={17} color={c.accent}/></Pressable>
    </View> : groups.filter(group => group.items.length).map(group => <View style={s.group} key={group.title}>
      <Text style={s.groupTitle}>{group.title}</Text>
      {group.items.map(item => card(item, group.today))}
    </View>)}
    {snapshot?.has_more ? <Text style={s.more}>这里显示最近的任务，完整过程保留在对话中。</Text> : null}
    <Pressable accessibilityRole="button" accessibilityLabel="查看持续推进的事" onPress={onGoals} style={({pressed}) => [s.goals, pressed && s.pressed]}><Text style={s.goalsText}>持续推进的事</Text><ChevronRight size={17} color={c.muted}/></Pressable>
  </View>;
}

const makeStyles = (c: AppColors) => StyleSheet.create({
  container: {gap: 12},
  heading: {flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: 8},
  caption: {fontSize: 14, color: c.muted},
  refresh: {width: 44, height: 44, alignItems: 'center', justifyContent: 'center', borderRadius: 22},
  group: {gap: 9, marginBottom: 8},
  groupTitle: {fontSize: 16, color: c.ink, marginHorizontal: 10, marginBottom: 5},
  card: {minHeight: 76, flexDirection: 'row', alignItems: 'center', gap: 14, paddingHorizontal: 20, paddingVertical: 17, borderRadius: 26, borderWidth: 1, borderColor: c.line, backgroundColor: c.surface},
  titleRow: {flex: 1, flexDirection: 'row', alignItems: 'center', gap: 7},
  title: {flex: 1, fontSize: 17, lineHeight: 25, color: c.ink},
  unread: {width: 5, height: 5, borderRadius: 3, backgroundColor: c.accent},
  meta: {maxWidth: 112, alignItems: 'flex-end', gap: 5},
  status: {fontSize: 11, lineHeight: 17, color: c.muted},
  time: {fontSize: 10, lineHeight: 15, color: c.muted},
  attention: {color: c.ink, fontWeight: '600'}, active: {color: c.accent},
  loading: {padding: 20, fontSize: 14, color: c.muted},
  notice: {flexDirection: 'row', alignItems: 'center', gap: 12, paddingLeft: 14},
  noticeText: {flex: 1, fontSize: 12, lineHeight: 19, color: c.muted},
  retry: {minHeight: 44, justifyContent: 'center', paddingHorizontal: 12},
  empty: {paddingHorizontal: 22, paddingVertical: 28, borderRadius: 26, backgroundColor: c.surface, borderWidth: 1, borderColor: c.line, gap: 10},
  emptyTitle: {fontSize: 18, lineHeight: 27, color: c.ink},
  emptyText: {fontSize: 14, lineHeight: 23, color: c.muted},
  draft: {flexDirection: 'row', alignItems: 'center', gap: 8, minHeight: 44, alignSelf: 'flex-start'},
  linkText: {fontSize: 14, color: c.accent},
  goals: {minHeight: 48, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: 12, marginTop: 2},
  goalsText: {fontSize: 14, color: c.muted},
  more: {fontSize: 12, lineHeight: 20, color: c.muted, paddingHorizontal: 12},
  pressed: {opacity: .65},
});
