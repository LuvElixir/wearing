import {useAppTheme, useThemedStyles, type AppColors} from './app-theme';
import {useEffect, useRef, useState} from 'react';
import {ActivityIndicator, Pressable, StyleSheet, Text, View} from 'react-native';
import {AlertCircle, Archive, ArrowUpRight, Check, ChevronRight, CircleHelp, Clock3, FileText, RefreshCw, Square} from 'lucide-react-native';
import {ActivityItem, ActivitySnapshot, ApiError, Connection, WearingApi} from './core';
import {appendActivityPage} from './activity-pages';
import {useActivitySnapshot} from './use-activity-snapshot';
import {activityPresentation, groupActivityItems} from './activity-presentation';
import {serviceFetch} from './transport';
import PendingDecisionsPanel from './PendingDecisionsPanel';
import {TactilePressable} from './experience/primitives';

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
const statusIcons = {alert: AlertCircle, clock: Clock3, file: FileText, check: Check, stop: Square, archive: Archive, help: CircleHelp};

/** Agent tasks and their actual receipts; personal checkboxes live separately. */
export default function AgentTaskList({connection, onTask, onGoals, onDraft}: Props) {
  const {colors: c} = useAppTheme();
  const s = useThemedStyles(makeStyles);

  const {snapshot: firstPage, loading, error: sharedError, stale, scope, refresh} = useActivitySnapshot(connection);
  const [archive, setArchive] = useState<{scope: string; snapshot: ActivitySnapshot} | null>(null);
  const [pagination, setPagination] = useState<{scope: string; mode: 'refresh' | 'more' | null; error: string; expired: boolean; notice: string}>({scope, mode: null, error: '', expired: false, notice: ''});
  const sessionRef = useRef({scope, live: true, pending: false});
  useEffect(() => {
    const session = {scope, live: true, pending: false};
    sessionRef.current = session;
    return () => {session.live = false;};
  }, [scope]);
  const frozen = archive?.scope === scope ? archive.snapshot : null;
  const snapshot = frozen || firstPage;
  const error = !!sharedError;
  const previousState = error || stale || !!frozen;
  const loadingMore = pagination.scope === scope && pagination.mode === 'more';
  const refreshing = pagination.scope === scope && pagination.mode === 'refresh';
  const pageExpired = pagination.scope === scope && pagination.expired;
  const refreshNotice = pagination.scope === scope ? pagination.notice : '';
  const userBusy = refreshing || loadingMore;
  const pageError = pagination.scope === scope ? pagination.error : '';

  const manualRefresh = async () => {
    const session = sessionRef.current;
    if (!session.live || session.scope !== scope || session.pending) return;
    session.pending = true;
    setPagination({scope, mode: 'refresh', error: '', expired: false, notice: ''});
    try {
      const latest = await refresh();
      if (session.live && latest) {
        setArchive(null);
        setPagination({scope, mode: null, error: '', expired: false, notice: '进展已更新'});
      } else if (session.live) {
        // A failed refresh cannot make an expired history cursor usable again.
        setPagination({scope, mode: null, error: '', expired: pageExpired, notice: ''});
      }
    } finally {
      session.pending = false;
      // refresh() returns null on a connection failure and keeps the prior snapshot.
    }
  };
  const loadMore = async () => {
    const session = sessionRef.current;
    if (!session.live || session.scope !== scope || session.pending || !snapshot?.next_cursor) return;
    session.pending = true;
    // Freeze the exact base of this cursor. Shared polling can continue without
    // replacing a history page or splicing a new first page into an older archive.
    const base = snapshot;
    setArchive({scope, snapshot: base});
    setPagination({scope, mode: 'more', error: '', expired: false, notice: ''});
    try {
      const next = await new WearingApi(connection, serviceFetch).activity({cursor: base.next_cursor!});
      if (!session.live) return;
      setArchive({scope, snapshot: appendActivityPage(base, next)});
      setPagination({scope, mode: null, error: '', expired: false, notice: ''});
    } catch (reason) {
      if (session.live) setPagination({scope, mode: null, notice: '', expired: reason instanceof ApiError && reason.status === 409,
        error: reason instanceof ApiError && reason.status === 409 ? '列表已有变化，点刷新后继续查看。当前内容仍会保留。' : '暂时没有读到更多任务，可以重试。'});
    } finally {session.pending = false;}
  };

  const today = localDay(new Date());
  const groups = groupActivityItems(snapshot?.items || []);
  const card = (item: ActivityItem) => {
    const presentation = activityPresentation(item), Icon = statusIcons[presentation.icon];
    const color = presentation.tone === 'danger' ? c.danger : presentation.tone === 'success' ? c.success : presentation.tone === 'active' ? c.accent : presentation.tone === 'attention' ? c.attention : c.muted;
    return <TactilePressable key={item.task_id} pressScale={0.99}
    accessibilityRole="button" accessibilityLabel={`${item.title}，${previousState ? '上次状态，' : ''}${presentation.label}，${presentation.action}`}
    onPress={() => onTask(item.task_id)} style={s.card}>
    <Icon size={19} color={color}/>
    <View style={s.taskWords}><View style={s.titleRow}>{item.unread ? <View style={s.unread}/> : null}<Text style={s.title} numberOfLines={2}>{item.title}</Text></View>
      <View style={s.meta}><Text style={[s.status, {color}]}>{previousState ? '上次 · ' : ''}{presentation.label}</Text><Text style={s.time}>{updated(item.updated_at, localDay(item.updated_at) === today)}</Text></View>
    </View><View style={s.cardAction}><Text style={s.actionLabel}>{presentation.action}</Text><ChevronRight size={15} color={c.muted}/></View>
  </TactilePressable>;
  };

  return <View style={s.container}>
    <PendingDecisionsPanel connection={connection} onTask={onTask}/>
    <View style={s.heading}>
      <View style={s.headingWords}><Text style={s.caption}>交给我的事</Text><Text style={s.refreshStatus} accessibilityLiveRegion="polite">{refreshing ? '正在更新…' : refreshNotice}</Text></View>
      <Pressable accessibilityRole="button" accessibilityLabel={refreshing ? "正在刷新任务" : "刷新任务"} accessibilityState={{busy: refreshing, disabled: userBusy}} disabled={userBusy} onPress={() => {void manualRefresh();}} style={({pressed}) => [s.refresh, pressed && s.pressed]}>
        {refreshing || (!snapshot && loading) ? <ActivityIndicator size="small" color={c.muted}/> : <RefreshCw size={16} color={c.muted}/>}
      </Pressable>
    </View>
    {error ? <View style={s.notice} accessibilityLiveRegion="polite"><Text style={s.noticeText}>{snapshot ? `暂时未连上，保留 ${new Date(snapshot.checked_at).toLocaleTimeString('zh-CN', {hour: '2-digit', minute: '2-digit'})} 查看时的状态。` : '暂时读不到任务，请检查连接后重试。'}</Text><Pressable accessibilityRole="button" accessibilityLabel="重新读取任务" accessibilityState={{busy: refreshing, disabled: userBusy}} disabled={userBusy} onPress={() => {void manualRefresh();}} style={s.retry}><Text style={s.linkText}>{refreshing ? '正在重试…' : '重试'}</Text></Pressable></View> : null}
    {!snapshot && !error ? <Text style={s.loading} accessibilityLiveRegion="polite">正在找回你的任务…</Text> : null}
    {snapshot?.total === 0 ? <View style={s.empty}>
      <Text style={s.emptyTitle}>交代过的事，都会留在这里</Text>
      <Text style={s.emptyText}>处理到哪一步、有什么结果，回来就能看到。</Text>
      <Pressable accessibilityRole="button" onPress={() => onDraft('帮我处理这件事：')} style={({pressed}) => [s.draft, pressed && s.pressed]}><Text style={s.linkText}>交代一件事</Text><ArrowUpRight size={17} color={c.accent}/></Pressable>
    </View> : groups.map(group => <View style={s.group} key={group.key}>
      <Text style={s.groupTitle}>{group.title}</Text>
      {group.items.map(card)}
    </View>)}
    {snapshot ? <Text style={s.more}>已显示 {snapshot.items.length} / {snapshot.filtered_total ?? snapshot.total} 项 · 读取于 {new Date(snapshot.checked_at).toLocaleTimeString('zh-CN', {hour: '2-digit', minute: '2-digit'})}{frozen ? '。正在查看历史记录，点刷新可查看最新进展。' : stale ? '。最新状态尚待确认。' : ''}</Text> : null}
    {pageError ? <Text style={s.noticeText} accessibilityLiveRegion="polite">{pageError}</Text> : null}
    {snapshot?.next_cursor ? <TactilePressable accessibilityRole="button" accessibilityState={{busy: loadingMore}} disabled={userBusy} onPress={() => {void (pageExpired ? manualRefresh() : loadMore());}} style={s.loadMore}>
      {loadingMore ? <ActivityIndicator size="small" color={c.muted}/> : null}<Text style={s.linkText}>{loadingMore ? '正在读取…' : pageExpired ? '刷新任务' : pageError ? '重试加载更多' : '加载更多任务'}</Text>
    </TactilePressable> : snapshot?.has_more ? <Text style={s.more}>当前服务仅提供最近任务，完整过程保留在对话中。</Text> : null}
    <Pressable accessibilityRole="button" accessibilityLabel="查看持续推进的事" onPress={onGoals} style={({pressed}) => [s.goals, pressed && s.pressed]}><Text style={s.goalsText}>持续推进的事</Text><ChevronRight size={17} color={c.muted}/></Pressable>
  </View>;
}

const makeStyles = (c: AppColors) => StyleSheet.create({
  container: {gap: 12},
  heading: {flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: 8},
  caption: {fontSize: 14, color: c.muted},
  headingWords: {flex: 1, gap: 3},
  refreshStatus: {fontSize: 12, lineHeight: 17, color: c.muted, minHeight: 17},
  refresh: {width: 44, height: 44, alignItems: 'center', justifyContent: 'center', borderRadius: 22},
  group: {gap: 9, marginBottom: 8},
  groupTitle: {fontSize: 16, color: c.ink, marginHorizontal: 10, marginBottom: 5},
  card: {minHeight: 80, flexDirection: 'row', alignItems: 'center', gap: 12, paddingHorizontal: 16, paddingVertical: 16, borderRadius: 18, borderWidth: 1, borderColor: c.line, backgroundColor: c.surface},
  taskWords: {flex: 1, minWidth: 0, gap: 7}, titleRow: {flexDirection: 'row', alignItems: 'center', gap: 7},
  title: {flex: 1, fontSize: 17, lineHeight: 25, color: c.ink},
  unread: {width: 5, height: 5, borderRadius: 3, backgroundColor: c.accent},
  meta: {flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 8},
  status: {fontSize: 13, lineHeight: 20, color: c.muted},
  time: {fontSize: 13, lineHeight: 20, color: c.muted},
  cardAction: {flexDirection: 'row', alignItems: 'center', gap: 2, maxWidth: 100}, actionLabel: {fontSize: 13, lineHeight: 20, color: c.muted, flexShrink: 1},
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
  loadMore: {minHeight: 48, padding: 12, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8, backgroundColor: c.surface, borderRadius: 16},
  pressed: {opacity: .65},
});
