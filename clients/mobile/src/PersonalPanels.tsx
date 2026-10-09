import {useAppTheme, useThemedStyles, type AppColors} from './app-theme';
import {useEffect, useMemo, useState} from 'react';
import {ActivityIndicator, Image, StyleSheet, Text, View} from 'react-native';
import {BookOpen, ChevronRight, Folder, RefreshCw, Settings} from 'lucide-react-native';
import {Connection, MemorySnapshot, WearingApi} from './core';
import {serviceFetch} from './transport';
import {TactilePressable} from './experience/primitives';
import TaskManagementPanel from './TaskManagementPanel';
import {OngoingCreateRequest} from './ongoing-management-forms';

export function MenuRow({title, detail, icon, onPress}: {title: string; detail?: string; icon: React.ReactNode; onPress: () => void}) {
  const {colors: c} = useAppTheme();
  const s = useThemedStyles(makeStyles);

  return <TactilePressable onPress={onPress} accessibilityLabel={title} style={s.row}>
    <View style={s.glyph}>{icon}</View><View style={s.words}><Text style={s.rowTitle}>{title}</Text>{detail ? <Text style={s.detail}>{detail}</Text> : null}</View><ChevronRight size={17} color={c.muted}/>
  </TactilePressable>;
}

export function MemoryPanel({connection}: {connection: Connection}) {
  const {colors: c} = useAppTheme();
  const s = useThemedStyles(makeStyles);

  const api = useMemo(() => new WearingApi(connection, serviceFetch), [connection]);
  const [generation, setGeneration] = useState(0), [data, setData] = useState<MemorySnapshot | null>(null);
  const [error, setError] = useState(''), [loading, setLoading] = useState(true);
  useEffect(() => {
    let live = true;
    api.memory().then(value => {if (live) {setData(value); setError('');}})
      .catch(cause => {if (live) setError(cause instanceof Error ? cause.message : '暂时读不到记忆。');})
      .finally(() => {if (live) setLoading(false);});
    return () => {live = false;};
  }, [api, generation]);
  return <View style={s.panel}>
    <Text style={s.title}>记忆</Text><Text style={s.lead}>一起记着的，可以随时核对。</Text>
    <View style={s.source}><BookOpen size={16} color={c.muted}/><Text style={s.detail}>来自当前身份的长期记忆</Text><TactilePressable accessibilityLabel="刷新记忆" disabled={loading} onPress={() => {setLoading(true); setGeneration(value => value + 1);}} style={s.refresh}>{loading ? <ActivityIndicator size="small" color={c.accent}/> : <RefreshCw size={18} color={c.muted}/>}</TactilePressable></View>
    {error ? <Text accessibilityLiveRegion="polite" style={s.error}>{error}</Text> : null}
    {data?.available ? (['user', 'memory'] as const).map(key => <View key={key} style={s.group}>
      <Text style={s.groupTitle}>{key === 'user' ? '关于你' : '一起积累的经验'}</Text>
      {!data.targets![key].enabled ? <Text style={s.detail}>这部分记忆已关闭，原记录仍保留。</Text> : null}
      {data.targets![key].entries.length ? data.targets![key].entries.map((entry, i) => <View key={i} style={s.memory}><Text selectable style={s.body}>{entry}</Text></View>) : <Text style={s.empty}>还没有记下内容。</Text>}
    </View>) : data ? <Text style={s.empty}>{data.message || '记忆暂时不可用。'}</Text> : null}
    <Text style={s.footnote}>哪里不准确，直接说出要纠正的内容。更新后可以在这里核对。</Text>
  </View>;
}

export function OngoingPanel(props: {connection: Connection; kind: 'goals' | 'schedules'; onManage?: () => void; onTask?: (id: string) => void; createRequest?: OngoingCreateRequest}) {
  return <TaskManagementPanel {...props}/>;
}

export function CompanionPanel({identity, connected, onMemory, onFiles, onSettings}: {identity: string; connected: boolean; onMemory: () => void; onFiles: () => void; onSettings: () => void}) {
  const {colors: c} = useAppTheme();
  const s = useThemedStyles(makeStyles);

  return <View style={s.panel}>
    <View style={s.companion}><Image source={require('../assets/bear/mist-blue.png')} style={s.character} accessibilityLabel="Pajio，穿着雾蓝条纹睡衣的小熊"/><Text style={s.title}>Pajio</Text><Text style={s.lead}>你说，我来做。</Text><Text style={s.connection}>{identity} · {connected ? '已连接' : '等待连接'}</Text></View>
    <MenuRow title="一起记着的" detail="关于你，以及一起积累的经验" icon={<BookOpen size={23} color={c.muted}/>} onPress={onMemory}/>
    <MenuRow title="文件" detail="找到 Pajio 留下的结果" icon={<Folder size={23} color={c.muted}/>} onPress={onFiles}/>
    <MenuRow title="连接与身份" icon={<Settings size={23} color={c.muted}/>} onPress={onSettings}/>
  </View>;
}

const makeStyles = (c: AppColors) => StyleSheet.create({
  panel: {gap: 12}, title: {fontSize: 32, lineHeight: 42, fontWeight: '600', color: c.ink, letterSpacing: -.6},
  lead: {fontSize: 15, lineHeight: 25, color: c.muted},
  row: {minHeight: 76, flexDirection: 'row', alignItems: 'center', gap: 14, paddingVertical: 14},
  glyph: {width: 40, height: 44, alignItems: 'center', justifyContent: 'center'}, words: {flex: 1, gap: 5},
  rowTitle: {fontSize: 17, lineHeight: 25, color: c.ink, fontWeight: '500'}, detail: {fontSize: 13, lineHeight: 21, color: c.muted},
  source: {flexDirection: 'row', alignItems: 'center', gap: 8, marginTop: 8}, refresh: {marginLeft: 'auto', width: 44, height: 44, alignItems: 'center', justifyContent: 'center'},
  group: {gap: 12, marginTop: 14}, groupTitle: {fontSize: 19, lineHeight: 27, fontWeight: '500', color: c.ink},
  memory: {padding: 20, borderRadius: 24, backgroundColor: c.surface}, body: {fontSize: 16, lineHeight: 27, color: c.ink},
  empty: {paddingVertical: 24, fontSize: 15, lineHeight: 25, color: c.muted}, error: {color: c.danger, fontSize: 14, lineHeight: 23},
  footnote: {fontSize: 12, lineHeight: 21, color: c.muted, marginTop: 16},
  blank: {paddingVertical: 48, alignItems: 'center', gap: 12}, blankTitle: {fontSize: 20, lineHeight: 28, color: c.ink, fontWeight: '500'},
  companion: {alignItems: 'center', paddingTop: 14, paddingBottom: 28, gap: 6}, character: {width: 180, height: 190, resizeMode: 'contain', marginBottom: 14},
  connection: {fontSize: 12, lineHeight: 20, color: c.muted, marginTop: 8},
});
