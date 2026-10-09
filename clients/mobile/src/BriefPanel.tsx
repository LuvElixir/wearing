import {useEffect, useMemo, useRef, useState} from 'react';
import {ActivityIndicator, AppState, Platform, StyleSheet, Text, View} from 'react-native';
import DateTimePicker from '@react-native-community/datetimepicker';
import * as Crypto from 'expo-crypto';
import {ArrowLeft, CalendarDays, ChevronRight, FileText, RefreshCw} from 'lucide-react-native';
import {ApiError, Connection, scopeOf} from './core';
import {storage} from './storage';
import {serviceFetch} from './transport';
import {useAppTheme, useThemedStyles, type AppColors} from './app-theme';
import {PrimaryButton, TactilePressable} from './experience/primitives';
import {Briefing, BriefingApi, BriefingRequest, briefingInProgress, briefingStateLabel, validBriefingRequest} from './briefing';
import {ongoingTime} from './ongoing-management';
import {wallClock, wallTimeToInstant} from './ongoing-management-forms';
import BriefPreferencesPanel from './BriefPreferencesPanel';
import {sourceAvailabilityLabel} from './briefing-preferences';

type Props = {connection: Connection; onTask: (id: string) => void; onArtifact: (id: string) => void; onBack?: () => void; isCurrent?: () => boolean; firstRun?: boolean};
const message = (cause: unknown) => cause instanceof Error ? cause.message : '暂时没有完成，请稍后再试。';
const pendingKey = (scope: string) => `briefing-request:${scope}`;
export default function BriefPanel(props: Props) {return <BriefSession key={`${scopeOf(props.connection)}|${props.connection.session?.credentialId || ''}`} {...props}/>;}

function BriefSession({connection, onTask, onArtifact, onBack, isCurrent, firstRun}: Props) {
  const {colors: c, mode} = useAppTheme(), s = useThemedStyles(makeStyles);
  const api = useMemo(() => new BriefingApi(connection, serviceFetch), [connection]);
  const [timezone, setTimezone] = useState(() => Intl.DateTimeFormat().resolvedOptions().timeZone || 'Asia/Shanghai');
  const [date, setDate] = useState(() => wallClock(new Date(), timezone).date), [picker, setPicker] = useState(false);
  const [pickerDate, setPickerDate] = useState(date);
  const [items, setItems] = useState<Briefing[]>([]), [selected, setSelected] = useState<string | null>(null);
  const [loading, setLoading] = useState(true), [loaded, setLoaded] = useState(false), [stale, setStale] = useState(false), [revision, setRevision] = useState(0);
  const [saving, setSaving] = useState(false), [restoring, setRestoring] = useState(true), [restoreFailed, setRestoreFailed] = useState(false), [restoreRevision, setRestoreRevision] = useState(0);
  const [pending, setPending] = useState<BriefingRequest | null>(null), [error, setError] = useState('');
  const [preferencesRevision, setPreferencesRevision] = useState<number | null>(null);
  const session = useRef({live: true, busy: false});
  const scope = scopeOf(connection);
  useEffect(() => {
    const current = {live: true, busy: false}; session.current = current;
    return () => {current.live = false;};
  }, [api]);
  useEffect(() => {
    let live = true;
    storage.get<unknown>(pendingKey(scope)).then(value => {
      if (!live || value === null) return;
      if (!validBriefingRequest(value)) throw new Error('上次简报请求暂时无法恢复，请先检查已有简报，避免重复生成。');
      setPending(value);
    }).catch(cause => {if (live) {setRestoreFailed(true); setError(message(cause));}})
      .finally(() => {if (live) setRestoring(false);});
    return () => {live = false;};
  }, [scope, restoreRevision]);
  useEffect(() => {
    let live = true, busy = false, timer: ReturnType<typeof setTimeout> | undefined;
    let foreground = AppState.currentState === 'active' || AppState.currentState === null;
    const read = async () => {
      if (!live || busy || !foreground) return;
      busy = true; clearTimeout(timer);
      let delay: number | null = null;
      try {
        const values = await api.list(date, timezone);
        if (!live) return;
        setItems(values); setLoaded(true); setStale(false); setError('');
        if (values.some(item => ['queued', 'running', 'needs_attention'].includes(item.state))) delay = 5000;
      } catch (cause) {if (live) {setError(message(cause)); setStale(true); delay = 15000;}}
      finally {
        busy = false;
        if (live) {setLoading(false); if (delay && foreground) timer = setTimeout(() => {void read();}, delay);}
      }
    };
    void read();
    const lifecycle = AppState.addEventListener('change', state => {foreground = state === 'active'; if (foreground) void read(); else clearTimeout(timer);});
    return () => {live = false; clearTimeout(timer); lifecycle.remove();};
  }, [api, date, timezone, revision]);
  const refresh = () => {setLoading(true); setError(''); setRevision(value => value + 1);};
  const changeDate = (value: string) => {setDate(value); setItems([]); setSelected(null); setLoaded(false); setLoading(true); setError(''); setPicker(false);};
  const create = async () => {
    const current = session.current;
    if (!current.live || current.busy || restoring || restoreFailed || (!pending && (!loaded || stale || loading || preferencesRevision === null))) return;
    const request = pending || {date, timezone, request_key: Crypto.randomUUID(), base_version: items[0]?.version || 0, preferences_revision: preferencesRevision!};
    current.busy = true; setSaving(true); setError('');
    let sent = false;
    try {
      await storage.put(pendingKey(scope), request);
      if (!current.live) return;
      setPending(request); sent = true;
      const receipt = await api.create(request);
      // Clear only this identity's original request after receiving the owned, validated result.
      await storage.put(pendingKey(scope), null);
      if (!current.live) return;
      setPending(null); setSelected(receipt.id);
      if (receipt.timezone !== timezone) setTimezone(receipt.timezone);
      if (receipt.date !== date || receipt.timezone !== timezone) changeDate(receipt.date);
      else setItems(previous => [receipt, ...previous.filter(item => item.id !== receipt.id)].sort((a, b) => b.version - a.version));
      setRevision(value => value + 1);
    } catch (cause) {
      if (!current.live) return;
      if (sent && cause instanceof ApiError && [400, 401, 403, 404, 409, 422].includes(cause.status)) {
        try {await storage.put(pendingKey(scope), null); if (current.live) setPending(null);} catch { /* Keep the stable request when local cleanup cannot be confirmed. */ }
        setRevision(value => value + 1);
      }
      setError(message(cause));
    } finally {current.busy = false; if (current.live) setSaving(false);}
  };
  const latest = items[0], displayed = items.find(item => item.id === selected) || latest;
  const createLabel = pending ? '取回上次生成回执' : latest?.state === 'not_started' ? '继续准备原简报' : latest ? '重新整理一版' : firstRun ? '整理我的第一份简报' : '生成这一天的图文简报';
  return <View style={s.stack}>
    {onBack ? <TactilePressable accessibilityLabel="返回今天" onPress={onBack} disabled={saving} style={s.back}><ArrowLeft size={18} color={c.ink}/><Text style={s.link}>今天</Text></TactilePressable> : null}
    <View style={s.header}><View><Text accessibilityRole="header" style={s.title}>每日简报</Text><Text style={s.secondary}>把已知的事，整理成清楚的一页。</Text></View><TactilePressable accessibilityLabel="刷新简报状态" onPress={refresh} disabled={loading || saving} style={s.round}>{loading ? <ActivityIndicator color={c.muted}/> : <RefreshCw size={20} color={c.ink}/>}</TactilePressable></View>
    {firstRun && !displayed && <Text style={s.secondary}>你的初始选择已保存。先核对下面可用的资料，再点生成；没有资料也可以稍后回来，不需要补写一段自我介绍。</Text>}
    <BriefPreferencesPanel connection={connection} isCurrent={isCurrent} showSourceSummary={firstRun} onChange={value => setPreferencesRevision(value.revision)}/>
    <TactilePressable accessibilityLabel={'选择简报日期，' + date} disabled={saving || restoring} onPress={() => {setPickerDate(date); setPicker(value => !value);}} style={s.date}><CalendarDays size={19} color={c.accent}/><Text style={s.label}>{date}</Text><Text style={s.caption}>{timezone}</Text></TactilePressable>
    {picker ? <View><DateTimePicker value={new Date(wallTimeToInstant(pickerDate, '12:00', timezone))} mode="date" timeZoneName={timezone} locale="zh-CN" themeVariant={mode === 'night' ? 'dark' : 'light'} display={Platform.OS === 'ios' ? 'spinner' : 'default'} onChange={(event, value) => {
      if (Platform.OS !== 'ios') setPicker(false);
      if (event.type === 'set' && value) {const day = wallClock(value, timezone).date; if (Platform.OS === 'ios') setPickerDate(day); else changeDate(day);}
    }}/>{Platform.OS === 'ios' ? <PrimaryButton label="查看这一天" tone="quiet" onPress={() => changeDate(pickerDate)}/> : null}</View> : null}
    {error ? <Text style={s.error} accessibilityLiveRegion="polite">{error}</Text> : null}
    {stale ? <Text style={s.caption}>当前连接不可用，下面保留上次读到的简报。</Text> : null}
    {restoring ? <Text style={s.secondary}>正在检查上次提交…</Text> : restoreFailed ? <PrimaryButton label="重新读取上次请求" tone="quiet" onPress={() => {setRestoring(true); setRestoreFailed(false); setRestoreRevision(value => value + 1);}}/> : null}
    {pending ? <Text style={s.notice}>{pending.date} 的生成请求已保留。先取回同一次回执，再开始其他版本。</Text> : null}
    {!displayed && !loading && loaded ? <View style={s.card}><FileText size={28} color={c.accent}/><Text style={s.heading}>这一天还没有简报</Text><Text style={s.secondary}>按已保存的兴趣、关注重点与来源整理。数据不足或部分来源失败会列明；保存后回来就能继续查看。</Text></View> : null}
    {displayed ? <>
      <View style={s.card}><View style={s.header}><Text style={s.heading}>{briefingStateLabel[displayed.state]}</Text><Text style={s.caption}>第 {displayed.version} 版</Text></View>
        <Text style={s.caption}>更新于 {ongoingTime(displayed.updated_at, displayed.timezone)}</Text>
        <Text style={s.caption}>{displayed.preferences ? `使用偏好版本 ${displayed.preferences.revision} · 最多 ${displayed.preferences.max_items} 项重点${displayed.preferences.revision !== preferencesRevision && preferencesRevision !== null ? ' · 设置已有变化，下次生成生效' : ''}` : '历史简报未记录偏好版本'}</Text>
        {displayed.state === 'running' || displayed.state === 'queued' ? <View style={s.inline}><ActivityIndicator color={c.accent}/><Text style={s.secondary}>{displayed.state === 'queued' ? '等前面的事完成后继续，无需留在这一页。' : '可以先忙别的，返回后继续查看同一次整理。'}</Text></View> : null}
        {displayed.state === 'not_started' ? <Text style={s.secondary}>请求已保存，还没有开始执行。连接可用后可以继续原任务。</Text> : null}
        {displayed.error ? <Text style={s.error}>{displayed.error}</Text> : null}
        {displayed.delivery.blocked_reason ? <Text style={s.secondary}>{displayed.delivery.blocked_reason}</Text> : null}
        {displayed.output ? <Text selectable style={s.body}>{displayed.output}</Text> : null}
        {displayed.task_id ? <PrimaryButton label="查看本次任务与进展" tone="quiet" disabled={saving} onPress={() => onTask(displayed.task_id!)}/> : null}
      </View>
      {displayed.artifacts.map(artifact => <TactilePressable key={artifact.id} accessibilityLabel={'打开图文简报：' + artifact.title} disabled={saving} onPress={() => onArtifact(artifact.id)} style={s.card}>
        <View style={s.header}><FileText size={24} color={c.accent}/><ChevronRight size={19} color={c.muted}/></View><Text style={s.heading}>{artifact.title}</Text><Text style={s.body}>{artifact.summary}</Text>
        {artifact.sources.length ? <Text style={s.caption}>成果注明的来源：{artifact.sources.join('；')}</Text> : <Text style={s.caption}>这份成果暂未注明来源。</Text>}
        {artifact.limitations.length ? <Text style={s.secondary}>尚有缺口：{artifact.limitations.join('；')}</Text> : null}
        <Text style={s.caption}>{artifact.checks.content === 'verified' && artifact.checks.render === 'verified' ? '图文核对已记录' : '文件已保存，图文内容与呈现仍需核对。'}</Text>
      </TactilePressable>)}
      <View style={s.card}><Text style={s.heading}>开始时的来源情况</Text><Text style={s.caption}>以下是创建请求时的可用性，不代表模型已读过；实际使用来源以成果说明为准。</Text>
        {displayed.sources.some(source => ['failed', 'not_connected', 'unavailable'].includes(source.state)) ? <Text style={s.error}>部分来源不可用；有资料的部分仍可整理，缺失内容不会补造。</Text> : null}
        {displayed.sources.map(source => <View key={source.id} style={s.source}><View style={s.header}><Text style={s.label}>{source.label}</Text><Text style={[s.secondary, source.state === 'failed' && {color: c.danger}]}>{sourceAvailabilityLabel(source)}</Text></View><Text style={s.caption}>观察于 {ongoingTime(source.observed_at, displayed.timezone)}</Text></View>)}
      </View>
    </> : null}
    {(pending || !latest || !briefingInProgress(latest) || latest.state === 'not_started') ? <PrimaryButton label={createLabel} loading={saving} disabled={restoring || restoreFailed || (!pending && (loading || stale || !loaded || preferencesRevision === null))} onPress={() => {void create();}}/> : null}
    {latest && !briefingInProgress(latest) && !pending ? <Text style={s.caption}>重新整理会创建新版本，之前的简报仍保留。</Text> : null}
    {items.length > 1 ? <View style={s.card}><Text style={s.heading}>当日版本</Text>{items.map(item => <TactilePressable key={item.id} accessibilityLabel={`查看第 ${item.version} 版简报，${briefingStateLabel[item.state]}`} onPress={() => setSelected(item.id)} style={s.version}><View style={s.words}><Text style={s.label}>第 {item.version} 版 · {briefingStateLabel[item.state]}</Text><Text style={s.caption}>{ongoingTime(item.created_at, item.timezone)}</Text></View><ChevronRight size={17} color={c.muted}/></TactilePressable>)}</View> : null}
  </View>;
}
const makeStyles = (c: AppColors) => StyleSheet.create({
  stack: {gap: 16}, header: {flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 10},
  title: {fontSize: 28, lineHeight: 39, fontWeight: '500', color: c.ink}, heading: {fontSize: 18, lineHeight: 28, fontWeight: '600', color: c.ink},
  label: {fontSize: 15, lineHeight: 24, color: c.ink}, secondary: {fontSize: 14, lineHeight: 23, color: c.muted}, caption: {fontSize: 12, lineHeight: 20, color: c.muted},
  body: {fontSize: 16, lineHeight: 27, color: c.ink}, round: {width: 44, height: 44, justifyContent: 'center', alignItems: 'center'},
  card: {backgroundColor: c.surface, borderWidth: 1, borderColor: c.line, borderRadius: 20, padding: 18, gap: 12},
  date: {flexDirection: 'row', alignItems: 'center', flexWrap: 'wrap', minHeight: 48, gap: 9}, inline: {flexDirection: 'row', alignItems: 'center', gap: 10},
  error: {fontSize: 14, lineHeight: 23, color: c.danger}, notice: {fontSize: 14, lineHeight: 23, color: c.accent},
  source: {gap: 4, borderTopColor: c.line, borderTopWidth: StyleSheet.hairlineWidth, paddingTop: 10},
  version: {flexDirection: 'row', alignItems: 'center', gap: 10, minHeight: 54}, words: {flex: 1, gap: 4},
  back: {flexDirection: 'row', alignItems: 'center', gap: 7, minHeight: 44}, link: {fontSize: 15, color: c.accent},
});
