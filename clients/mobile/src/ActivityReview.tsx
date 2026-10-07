import {useAppTheme, useThemedStyles, type AppColors} from './app-theme';
import {useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState} from 'react';
import {ActivityIndicator, Modal, Pressable, ScrollView, StyleSheet, Text, View} from 'react-native';
import {SafeAreaView} from 'react-native-safe-area-context';
import {ArrowRight, ChevronRight, RefreshCw, X} from 'lucide-react-native';
import {ActivityBucket, ActivityItem, ActivitySnapshot, activitySummary, Connection, WearingApi} from './core';
import {serviceFetch} from './transport';
import {PajamaBear} from './PajamaBear';
import type {OutfitId} from './wardrobe';

type Props = {connection: Connection; active: boolean; connected: boolean; open: boolean; onOpenChange: (open: boolean) => void; onOpenTask: (taskId: string) => void; compact?: boolean; identity?: string; outfit?: OutfitId};
const groups: {bucket: ActivityBucket; title: string; empty: string}[] = [
  {bucket: 'attention', title: '等你处理', empty: '暂时没有需要你处理的事。'},
  {bucket: 'active', title: '正在推进', empty: '暂时没有进行中的事。'},
  {bucket: 'waiting', title: '已排队', empty: '暂时没有排队中的事。'},
  {bucket: 'results', title: '已有结果', empty: '有结果后，会留在这里。'},
];
function time(value: string) {return new Date(value).toLocaleString('zh-CN', {month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit'});}

/** One scoped, read-only view. The conversation acknowledges a result after opening it. */
export default function ActivityReview({connection, active, connected, open, onOpenChange, onOpenTask, compact = false, identity = '日常', outfit}: Props) {
  const {colors: c} = useAppTheme();
  const s = useThemedStyles(makeStyles);

  const api = useMemo(() => new WearingApi(connection, serviceFetch), [connection]);
  const [snapshot, setSnapshot] = useState<ActivitySnapshot | null>(null);
  const snapshotRef = useRef<ActivitySnapshot | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [fresh, setFresh] = useState(false);
  const live = useRef(true), activeRef = useRef(active), pending = useRef(false);
  useLayoutEffect(() => {activeRef.current = active;}, [active]);
  useEffect(() => {live.current = true; return () => {live.current = false;};}, []);
  const refresh = useCallback(async () => {
    if (!activeRef.current || pending.current) return;
    pending.current = true; setLoading(true);
    try {
      const data = await api.activity();
      if (!live.current || !activeRef.current) return;
      snapshotRef.current = data; setSnapshot(data); setFresh(true); setError('');
    } catch (cause) {
      if (!live.current || !activeRef.current) return;
      setFresh(false); setError(cause instanceof Error ? cause.message : '暂时读不到进展，请稍后重试。');
    } finally {pending.current = false; if (live.current) setLoading(false);}
  }, [api]);
  useEffect(() => {
    if (!active) return;
    if (!connected && !snapshotRef.current) return;
    refresh();
    // Only the visible, foreground conversation refreshes. There is no background worker.
    const timer = setInterval(refresh, 15000);
    return () => clearInterval(timer);
  }, [active, connected, refresh]);
  if (!active) return null;
  const stale = !!snapshot && (!fresh || !!error || !connected);
  const entrySummary = !snapshot ? (loading ? '正在查看…' : '暂时读不到进展') : stale ? `保留上次进展 · ${time(snapshot.checked_at)}` : activitySummary(snapshot);
  function openTask(item: ActivityItem) {onOpenChange(false); onOpenTask(item.task_id);}
  return <>
    <Pressable accessibilityRole="button" accessibilityLabel={`查看进展，${entrySummary}`} onPress={() => {onOpenChange(true); refresh();}} style={({pressed}) => [compact ? s.compactEntry : s.entry, pressed && s.pressed]}>
      {compact ? <><View><PajamaBear outfit={outfit} portrait size={32}/><View style={[s.compactDot,{position:'absolute',right:0,bottom:0,backgroundColor:snapshot?.counts.active ? c.accent : connected ? c.success : c.muted}]}/></View><View style={{flex:1,gap:2}}><Text numberOfLines={1} style={s.compactTitle}>{identity}</Text><Text numberOfLines={1} style={s.compactSubtitle}>{!connected ? '等待连接' : snapshot?.items.find(item=>item.bucket==='active')?.title || (snapshot?.total ? entrySummary : '你说，我来做')}</Text></View><ChevronRight size={14} color={c.muted}/></> : <><View style={s.entryHeading}><Text style={s.entryTitle}>进展</Text>{!!snapshot?.unread && <View style={s.badge}><Text style={s.badgeText}>{snapshot.unread}</Text></View>}</View><Text numberOfLines={1} style={[s.entrySummary, stale && s.staleText]}>{entrySummary}</Text><ChevronRight size={17} color={c.muted}/></>}
    </Pressable>
    <Modal visible={open} animationType="slide" presentationStyle="pageSheet" onRequestClose={() => onOpenChange(false)}>
      <SafeAreaView style={s.sheet}>
        <View style={s.heading}><View style={s.headingText}><Text style={s.eyebrow}>WEARING</Text><Text style={s.title}>进展</Text></View><Pressable accessibilityRole="button" accessibilityLabel="关闭进展，回到对话" onPress={() => onOpenChange(false)} style={s.iconButton}><X size={23} color={c.muted}/></Pressable></View>
        <View style={s.updateRow}><Text style={s.updated}>{snapshot ? `${stale ? '上次读取' : '读取于'} · ${time(snapshot.checked_at)}` : '连接后查看真实进展'}</Text><Pressable accessibilityRole="button" accessibilityLabel="刷新进展" disabled={loading} onPress={refresh} style={s.refresh}>{loading ? <ActivityIndicator size="small" color={c.accent}/> : <RefreshCw size={15} color={c.accent}/>}<Text style={s.refreshText}>{loading ? '读取中' : '刷新'}</Text></Pressable></View>
        <ScrollView contentContainerStyle={s.content}>
          {(error || (!connected && snapshot)) && <View style={s.notice} accessibilityLiveRegion="polite"><Text style={s.noticeText}>{snapshot ? `暂时无法确认最新状态。以下保留 ${time(snapshot.checked_at)} 查看时的内容。` : error}</Text></View>}
          {!snapshot && !error && <Text style={s.empty}>正在查看交给 Wearing 的事…</Text>}
          {snapshot && snapshot.total === 0 ? <View style={s.first}><Text style={s.firstTitle}>还没有交给我的事</Text><Text style={s.firstText}>回到对话说一个想法。之后的进展、需要你处理的步骤和结果，都会留在这里。</Text><Pressable accessibilityRole="button" onPress={() => onOpenChange(false)} style={s.returnButton}><Text style={s.refreshText}>回到对话</Text><ArrowRight size={16} color={c.accent}/></Pressable></View> : snapshot && groups.map(group => {
            const items = snapshot.items.filter(item => item.bucket === group.bucket);
            return <View key={group.bucket} style={s.group}><View style={s.groupHeading}><Text style={s.groupTitle}>{stale ? `${group.title} · 上次` : group.title}</Text><Text style={s.count}>{snapshot.counts[group.bucket]}</Text></View>
              {group.bucket === 'waiting' && snapshot.counts.waiting > 0 && <Text style={s.summary}>{stale ? '上次读取时，这些事尚未开始执行。' : '这些事尚未开始执行。'}</Text>}
              {items.map(item => <Pressable key={item.task_id} accessibilityRole="button" accessibilityLabel={`${item.unread ? '未读，' : ''}${item.title}，${item.label}，打开原对话`} onPress={() => openTask(item)} style={({pressed}) => [s.card, pressed && s.pressed]}>
                <View style={s.cardMeta}>{item.unread && <View style={s.dot}/>}<Text style={[s.label, group.bucket === 'attention' && s.attention]}>{item.label}</Text><Text style={s.itemTime}>{time(item.updated_at)}</Text></View>
                <Text style={s.cardTitle}>{item.title}</Text>{!!item.summary && <Text style={s.summary}>{item.summary}</Text>}
                <View style={s.forward}><Text style={s.forwardText}>{group.bucket === 'attention' ? '查看这一步' : group.bucket === 'results' ? '查看结果' : group.bucket === 'waiting' ? '查看这条安排' : '查看进展'}</Text><ArrowRight size={15} color={c.muted}/></View>
              </Pressable>)}
              {!items.length && <Text style={s.empty}>{snapshot.counts[group.bucket] ? '更多内容可从对话中回看。' : group.empty}</Text>}
            </View>;
          })}
          {snapshot?.has_more && <Text style={s.more}>这里显示最近的进展，更早的内容仍在对话里。</Text>}
        </ScrollView>
      </SafeAreaView>
    </Modal>
  </>;
}

const makeStyles = (c: AppColors) => StyleSheet.create({
  compactEntry: {minHeight: 46, flex: 1, maxWidth: 245, flexDirection: 'row', alignItems: 'center', gap: 9, borderRadius: 25, paddingHorizontal: 14, paddingVertical: 7, backgroundColor: c.surface, borderWidth: 1, borderColor: c.line},
  compactDot: {width: 6, height: 6, borderRadius: 3}, compactTitle: {fontSize: 14, lineHeight: 19, fontWeight: '600', color: c.ink}, compactSubtitle: {fontSize: 10, lineHeight: 15, color: c.muted},
  entry: {marginHorizontal: 20, marginBottom: 10, paddingVertical: 11, paddingHorizontal: 14, minHeight: 48, borderWidth: 1, borderColor: c.line, borderRadius: 16, backgroundColor: c.surface, flexDirection: 'row', alignItems: 'center', gap: 12},
  entryHeading: {flexDirection: 'row', alignItems: 'center', gap: 7}, entryTitle: {color: c.ink, fontSize: 14, fontWeight: '600'}, entrySummary: {flex: 1, fontSize: 12, color: c.muted},
  badge: {backgroundColor: c.soft, borderRadius: 10, minWidth: 19, paddingHorizontal: 5, paddingVertical: 2, alignItems: 'center'}, badgeText: {fontSize: 11, color: c.accent, fontWeight: '600'}, staleText: {color: c.muted},
  sheet: {flex: 1, backgroundColor: c.surface}, heading: {paddingHorizontal: 24, paddingTop: 18, flexDirection: 'row', alignItems: 'center'}, headingText: {flex: 1}, eyebrow: {fontSize: 10, letterSpacing: 2.8, color: c.muted}, title: {fontSize: 29, fontWeight: '600', color: c.ink, marginTop: 7},
  iconButton: {width: 44, height: 44, alignItems: 'center', justifyContent: 'center'}, updateRow: {paddingHorizontal: 24, paddingBottom: 9, flexDirection: 'row', alignItems: 'center', gap: 12}, updated: {flex: 1, color: c.muted, fontSize: 12, lineHeight: 19}, refresh: {minHeight: 44, flexDirection: 'row', alignItems: 'center', gap: 7}, refreshText: {color: c.accent, fontSize: 13, fontWeight: '500'},
  content: {padding: 24, paddingTop: 10, paddingBottom: 40, width: '100%', maxWidth: 680, alignSelf: 'center'}, notice: {backgroundColor: c.soft, borderRadius: 13, padding: 14, marginBottom: 24}, noticeText: {fontSize: 13, lineHeight: 21, color: c.muted},
  group: {marginBottom: 28, gap: 10}, groupHeading: {flexDirection: 'row', alignItems: 'center', gap: 9, marginBottom: 3}, groupTitle: {fontSize: 16, color: c.ink, fontWeight: '600'}, count: {fontSize: 13, color: c.muted},
  card: {backgroundColor: c.surface, borderWidth: 1, borderColor: c.line, borderRadius: 19, padding: 18, gap: 11}, cardMeta: {flexDirection: 'row', alignItems: 'center', gap: 6, flexWrap: 'wrap'}, dot: {height: 5, width: 5, borderRadius: 3, backgroundColor: c.accent}, label: {fontSize: 11, color: c.muted}, attention: {color: c.accent}, itemTime: {fontSize: 11, color: c.muted, marginLeft: 'auto'}, cardTitle: {fontSize: 17, lineHeight: 25, fontWeight: '500', color: c.ink}, summary: {fontSize: 14, lineHeight: 23, color: c.muted}, forward: {flexDirection: 'row', alignItems: 'center', justifyContent: 'flex-end', gap: 7, marginTop: 4}, forwardText: {fontSize: 12, color: c.muted},
  empty: {fontSize: 13, lineHeight: 22, color: c.muted, paddingVertical: 9}, first: {paddingTop: 50, gap: 16}, firstTitle: {fontSize: 22, lineHeight: 32, color: c.ink}, firstText: {fontSize: 15, lineHeight: 26, color: c.muted}, returnButton: {flexDirection: 'row', alignItems: 'center', gap: 9, alignSelf: 'flex-start', minHeight: 44}, more: {fontSize: 12, lineHeight: 20, textAlign: 'center', color: c.muted}, pressed: {opacity: .65},
});
