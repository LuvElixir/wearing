import {useEffect, useMemo, useRef, useState} from 'react';
import {ActivityIndicator, StyleSheet, Text, TextInput, View} from 'react-native';
import {ArrowLeft, ChevronRight, Clock3, Plus, RefreshCw, Target} from 'lucide-react-native';
import {Connection, scopeOf} from './core';
import {useAppTheme, useThemedStyles, type AppColors} from './app-theme';
import {PrimaryButton, TactilePressable} from './experience/primitives';
import {serviceFetch} from './transport';
import {OngoingAction, OngoingDetail, OngoingKind, OngoingManagementApi, ongoingActions, ongoingControlBody, ongoingStatus, ongoingTime, scheduleRule} from './ongoing-management';
import TaskManagementForm from './TaskManagementForm';
import {OngoingCreateRequest} from './ongoing-management-forms';

type Props = {connection: Connection; kind: OngoingKind; onManage?: () => void; onTask?: (id: string) => void; createRequest?: OngoingCreateRequest};
const message = (error: unknown) => error instanceof Error ? error.message : '暂时没有完成，请稍后重试。';
const actionLabel: Record<OngoingAction, string> = {pause: '暂停后续', resume: '继续推进', cancel: '结束安排', note: '补充情况', complete: '确认已完成'};

/** Remount synchronously at the identity boundary so no previous identity flashes on screen. */
export default function TaskManagementPanel(props: Props) {
  return <TaskManagementSession key={`${scopeOf(props.connection)}|${props.kind}|${props.createRequest?.id || ''}`} {...props}/>;
}

function TaskManagementSession({connection, kind, onTask, createRequest}: Props) {
  const {colors: c} = useAppTheme(), s = useThemedStyles(makeStyles);
  const api = useMemo(() => new OngoingManagementApi(connection, serviceFetch), [connection]);
  const [items, setItems] = useState<OngoingDetail[]>([]), [loaded, setLoaded] = useState(false);
  const [loading, setLoading] = useState(true), [error, setError] = useState(''), [revision, setRevision] = useState(0);
  const [selected, setSelected] = useState<string | null>(null);
  const [creating, setCreating] = useState(!!createRequest), [created, setCreated] = useState('');
  useEffect(() => {
    let live = true;
    api.list(kind).then(value => {if (live) {setItems(value); setLoaded(true);}})
      .catch(cause => {if (live) setError(message(cause));})
      .finally(() => {if (live) setLoading(false);});
    return () => {live = false;};
  }, [api, kind, revision]);
  const refresh = () => {setLoading(true); setError(''); setRevision(value => value + 1);};
  const changed = (item: OngoingDetail) => setItems(previous => previous.map(entry => entry.id === item.id ? item : entry));
  if (creating) return <TaskManagementForm api={api} scope={scopeOf(connection)} kind={kind} prefill={createRequest} onCancel={() => setCreating(false)} onSaved={item => {
    setCreating(false); setSelected(item.id); setCreated(kind === 'goals' ? '目标约定已保存。检查下面的内容后，点“开始推进”就可以开始。' : '定时安排已保存，可在这里查看和管理。');
  }}/>;
  if (selected) return <TaskManagementDetail key={selected} api={api} scope={scopeOf(connection)} kind={kind} id={selected} onTask={onTask} onChanged={changed} initialFeedback={created}
    onBack={() => {setSelected(null); refresh();}}/>;
  return <View style={s.panel}>
    <View style={s.header}><Text accessibilityRole="header" style={s.sectionTitle}>{kind === 'goals' ? '持续推进的事' : '定时安排'}</Text>
      <TactilePressable accessibilityLabel="刷新安排" onPress={refresh} disabled={loading} style={s.iconButton}>
        {loading ? <ActivityIndicator color={c.muted}/> : <RefreshCw size={18} color={c.muted}/>}
      </TactilePressable></View>
    {error ? <View style={s.notice}><Text style={s.error} accessibilityLiveRegion="polite">{loaded ? '连接暂时中断，以下为上次读取的安排。' : error}</Text><PrimaryButton label="重新读取" tone="quiet" loading={loading} onPress={refresh}/></View> : null}
    {loading && !loaded ? <Text style={s.secondary}>正在读取安排…</Text> : null}
    {!loading && loaded && !items.length ? <View style={s.card}><Text style={s.title}>{kind === 'goals' ? '还没有持续目标' : '还没有定时安排'}</Text><Text style={s.secondary}>{kind === 'goals' ? '交代想持续推进的事，目标和每次进展都会留在这里。' : '告诉我什么时候做什么，之后可在这里暂停或恢复。'}</Text></View> : null}
    {items.map(item => <TactilePressable key={item.id} accessibilityLabel={`${item.title}，${ongoingStatus(item.status, item.kind)}，查看详情`} onPress={() => {setCreated(''); setSelected(item.id);}} style={s.row}>
      {kind === 'goals' ? <Target size={21} color={c.accent}/> : <Clock3 size={21} color={c.accent}/>}
      <View style={s.words}><Text style={s.rowTitle} numberOfLines={2}>{item.title}</Text><Text style={s.secondary}>{ongoingStatus(item.status, item.kind)}</Text>
        {item.schedule ? <Text style={s.caption}>{scheduleRule(item)}{item.schedule.nextRun ? ` · 下次 ${ongoingTime(item.schedule.nextRun, item.schedule.timezone)}` : ''}</Text> : item.next ? <Text style={s.caption} numberOfLines={2}>{item.next}</Text> : null}</View><ChevronRight size={17} color={c.muted}/>
    </TactilePressable>)}
    <TactilePressable accessibilityLabel={kind === 'goals' ? '新建持续目标' : '新建定时安排'} onPress={() => {setCreated(''); setCreating(true);}} style={s.add}>
      <Plus size={20} color={c.accent}/><Text style={s.link}>{kind === 'goals' ? '新建持续目标' : '新建定时安排'}</Text>
    </TactilePressable>
  </View>;
}

function TaskManagementDetail({api, scope, kind, id, onTask, onBack, onChanged, initialFeedback}: {
  api: OngoingManagementApi; scope: string; kind: OngoingKind; id: string; onTask?: (id: string) => void; onBack: () => void; onChanged: (item: OngoingDetail) => void; initialFeedback?: string;
}) {
  const {colors: c} = useAppTheme(), s = useThemedStyles(makeStyles);
  const [item, setItem] = useState<OngoingDetail | null>(null), [generation, setGeneration] = useState(0);
  const [loading, setLoading] = useState(true), [saving, setSaving] = useState(false), [stale, setStale] = useState(false);
  const [error, setError] = useState(''), [feedback, setFeedback] = useState(initialFeedback || ''), [editing, setEditing] = useState(false);
  const [action, setAction] = useState<OngoingAction | null>(null), [note, setNote] = useState(''), [extra, setExtra] = useState('');
  const session = useRef({live: true, busy: false});
  useEffect(() => {
    const current = {live: true, busy: false}; session.current = current;
    return () => {current.live = false;};
  }, [api]);
  useEffect(() => {
    let live = true;
    api.detail(kind, id).then(value => {if (live) {setItem(value); setStale(false);}})
      .catch(cause => {if (live) {setError(message(cause)); setStale(true);}})
      .finally(() => {if (live) setLoading(false);});
    return () => {live = false;};
  }, [api, kind, id, generation]);
  const refresh = () => {setLoading(true); setError(''); setAction(null); setGeneration(value => value + 1);};
  const submit = async () => {
    const current = session.current;
    if (!current.live || current.busy || !item || !action || loading || stale) return;
    const request = {action, note, addSteps: extra.trim() ? Number(extra.trim()) : 0};
    try {ongoingControlBody(item, request);} catch (cause) {setError(message(cause)); return;}
    current.busy = true; setSaving(true); setError(''); setFeedback('');
    try {
      const receipt = await api.control(item, request);
      if (!current.live) return;
      setItem(receipt); onChanged(receipt); setAction(null); setNote(''); setExtra('');
      setFeedback(action === 'pause' ? '已暂停后续安排。正在执行的本轮，请在记录中确认状态。' : action === 'cancel' ? '这项安排已结束，历史记录仍会保留。' : action === 'resume' ? '已恢复安排，可在这里查看后续进展。' : action === 'note' ? '已保存你的补充。' : '已记录你确认完成的结果。');
      // A confirmed mutation and the subsequent read are separate facts.
      try {
        const detail = await api.detail(kind, id);
        if (current.live) {setItem(detail); onChanged(detail); setStale(false);}
      } catch {if (current.live) {setError('操作已保存，最新执行记录暂时没读到，请刷新查看。'); setStale(true);}}
    } catch (cause) {if (current.live) {setError(message(cause)); setStale(true); setAction(null);}}
    finally {current.busy = false; if (current.live) setSaving(false);}
  };
  if (editing && item) return <TaskManagementForm api={api} scope={scope} kind="schedules" item={item} onCancel={() => setEditing(false)} onSaved={receipt => {
    setItem(receipt); onChanged(receipt); setEditing(false); setFeedback('修改已保存，后续按新的安排执行。'); setError(''); setStale(false);
  }}/>;
  const label = (value: OngoingAction) => value === 'resume' ? kind === 'schedules' ? '恢复安排' : item?.goal?.used === 0 ? '开始推进' : '继续推进' : actionLabel[value];
  return <View style={s.panel}>
    <View style={s.header}><TactilePressable accessibilityLabel="返回安排列表" disabled={saving} onPress={onBack} style={s.back}><ArrowLeft size={18} color={c.ink}/><Text style={s.link}>返回列表</Text></TactilePressable>
      <TactilePressable accessibilityLabel="刷新安排详情" disabled={loading || saving} onPress={refresh} style={s.iconButton}>{loading ? <ActivityIndicator color={c.muted}/> : <RefreshCw size={18} color={c.muted}/>}</TactilePressable></View>
    {feedback ? <Text style={s.success} accessibilityLiveRegion="polite">{feedback}</Text> : null}
    {error ? <View style={s.notice}><Text style={s.error} accessibilityLiveRegion="polite">{error}</Text>{stale ? <PrimaryButton label="刷新状态" tone="quiet" loading={loading} disabled={saving} onPress={refresh}/> : null}</View> : null}
    {!item && loading ? <Text style={s.secondary}>正在读取详情…</Text> : null}
    {item ? <>
      <View style={s.card}><Text accessibilityRole="header" style={s.title}>{item.title}</Text><Text style={s.status}>{stale ? '上次状态 · ' : ''}{ongoingStatus(item.status, item.kind)}</Text>
        {item.reason ? <Text selectable style={s.body}>{item.reason}</Text> : null}
        <Text style={s.caption}>更新于 {ongoingTime(item.updatedAt)}</Text>
      </View>
      {item.goal ? <View style={s.card}><Text style={s.sectionTitle}>这件事的约定</Text><Field title="允许的范围" value={item.goal.boundaries}/><Field title="做到什么算完成" value={item.goal.success}/>
        {item.next ? <Field title="下一步" value={item.next}/> : null}<Text style={s.secondary}>已推进 {item.goal.used} 轮 · 约定最多 {item.goal.limit} 轮</Text></View> : null}
      {item.schedule ? <View style={s.card}><Text style={s.sectionTitle}>安排内容</Text><Text selectable style={s.body}>{item.schedule.instruction}</Text><Field title="执行时间" value={`${scheduleRule(item)} · ${item.schedule.timezone}`}/>
        {item.schedule.nextRun ? <Field title="下次执行" value={ongoingTime(item.schedule.nextRun, item.schedule.timezone)}/> : null}
        <Text style={s.caption}>服务在线时执行，结果会回到对话里。暂停后续安排不会撤回已经开始的本轮。</Text>
        {item.status !== 'cancelled' ? <PrimaryButton label="修改内容与时间" tone="quiet" disabled={loading || saving || stale} onPress={() => setEditing(true)}/> : null}</View> : null}
      {ongoingActions(item).length ? <View style={s.card}><Text style={s.sectionTitle}>管理安排</Text>
        {!action ? <View style={s.actions}>{ongoingActions(item).map(value => <TactilePressable key={value} accessibilityLabel={label(value)} disabled={loading || saving || stale} onPress={() => {setAction(value); setNote(''); setExtra(''); setError(''); setFeedback('');}} style={s.action}>
          <Text style={[s.link, value === 'cancel' && {color: c.danger}]}>{label(value)}</Text>
        </TactilePressable>)}</View> : <View style={s.form}>
          <Text style={s.rowTitle}>{actionLabel[action]}</Text><Text style={s.secondary}>{action === 'cancel' ? '结束后不再安排后续执行。已开始的本轮仍需在执行记录中确认，历史内容会保留。' : action === 'pause' ? '先暂停后续，之后可以继续。已开始的本轮需要查看执行记录确认。' : action === 'resume' ? '继续按上面已保存的约定推进。' : action === 'complete' ? '写下你已收到、检查过的具体结果，这件事将标记为完成。' : '补充新的情况或要求，后续会据此重新判断。'}</Text>
          {action === 'note' || action === 'complete' ? <TextInput accessibilityLabel={action === 'note' ? '补充内容' : '实际完成结果'} value={note} onChangeText={setNote} multiline maxLength={2000} editable={!saving} placeholder={action === 'note' ? '有哪些新的情况？' : '具体完成了什么？'} placeholderTextColor={c.muted} style={s.input}/> : null}
          {action === 'resume' && item.goal && item.goal.used >= item.goal.limit ? <View style={s.form}><Text style={s.secondary}>已达到约定轮次。你愿意再增加多少轮？</Text><TextInput accessibilityLabel="明确增加的推进轮次" value={extra} onChangeText={value => setExtra(value.replace(/[^0-9]/g, ''))} keyboardType="number-pad" maxLength={4} editable={!saving} placeholder={`还可增加 ${1000 - item.goal.limit} 轮`} placeholderTextColor={c.muted} style={s.numberInput}/></View> : null}
          <PrimaryButton label={saving ? '正在保存…' : '确认' + label(action)} loading={saving} disabled={loading || stale} tone={action === 'cancel' ? 'danger' : 'accent'} onPress={() => {void submit();}}/>
          <PrimaryButton label="取消操作" tone="quiet" disabled={saving} onPress={() => {setAction(null); setError('');}}/>
        </View>}
      </View> : null}
      <View style={s.card}><Text style={s.sectionTitle}>执行记录</Text>
        {!item.historyLoaded ? <Text style={s.secondary}>刷新后查看最新执行记录。</Text> : !item.runs.length ? <Text style={s.secondary}>还没有开始执行。</Text> : item.runs.map(run => {
          const contents = <><View style={s.words}><Text style={s.rowTitle}>{ongoingStatus(run.status)}</Text><Text style={s.caption}>{ongoingTime(run.at, item.schedule?.timezone)}</Text>{run.summary ? <Text style={s.secondary} numberOfLines={3}>{run.summary}</Text> : null}</View>{run.taskId && onTask ? <ChevronRight size={17} color={c.muted}/> : null}</>;
          return run.taskId && onTask ? <TactilePressable key={run.id} accessibilityLabel={`查看执行记录，${ongoingStatus(run.status)}，${ongoingTime(run.at)}`} disabled={saving} onPress={() => onTask(run.taskId!)} style={s.history}>{contents}</TactilePressable> : <View key={run.id} style={s.history}>{contents}</View>;
        })}
      </View>
      {item.goal?.notes.length ? <View style={s.card}><Text style={s.sectionTitle}>你补充的情况</Text>{item.goal.notes.map(entry => <View key={entry.id} style={s.note}><Text selectable style={s.body}>{entry.text}</Text><Text style={s.caption}>{ongoingTime(entry.at)}</Text></View>)}</View> : null}
    </> : null}
  </View>;
}

function Field({title, value}: {title: string; value: string}) {
  const s = useThemedStyles(makeStyles);
  return <View style={s.field}><Text style={s.secondary}>{title}</Text><Text selectable style={s.body}>{value}</Text></View>;
}

const makeStyles = (c: AppColors) => StyleSheet.create({
  panel: {gap: 14}, header: {flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between'},
  card: {backgroundColor: c.surface, borderWidth: 1, borderColor: c.line, borderRadius: 22, padding: 20, gap: 14},
  row: {backgroundColor: c.surface, borderWidth: 1, borderColor: c.line, borderRadius: 18, padding: 17, minHeight: 86, flexDirection: 'row', alignItems: 'center', gap: 12},
  words: {flex: 1, minWidth: 0, gap: 5}, title: {fontSize: 24, lineHeight: 33, fontWeight: '600', color: c.ink}, rowTitle: {fontSize: 16, lineHeight: 24, fontWeight: '500', color: c.ink},
  sectionTitle: {fontSize: 17, lineHeight: 25, fontWeight: '600', color: c.ink}, secondary: {fontSize: 14, lineHeight: 23, color: c.muted},
  caption: {fontSize: 12, lineHeight: 19, color: c.muted}, body: {fontSize: 16, lineHeight: 26, color: c.ink},
  iconButton: {height: 44, width: 44, alignItems: 'center', justifyContent: 'center'}, back: {minHeight: 44, flexDirection: 'row', alignItems: 'center', gap: 8},
  link: {fontSize: 15, lineHeight: 22, color: c.accent}, add: {minHeight: 52, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8},
  status: {fontSize: 14, color: c.accent}, notice: {gap: 10, padding: 12}, error: {fontSize: 14, lineHeight: 23, color: c.danger}, success: {fontSize: 14, lineHeight: 23, color: c.success},
  field: {gap: 4}, actions: {flexDirection: 'row', flexWrap: 'wrap', gap: 8}, action: {minHeight: 46, borderRadius: 14, paddingVertical: 12, paddingHorizontal: 16, backgroundColor: c.canvas},
  form: {gap: 12}, input: {minHeight: 116, padding: 14, borderWidth: 1, borderColor: c.line, borderRadius: 14, backgroundColor: c.canvas, color: c.ink, fontSize: 16, lineHeight: 24, textAlignVertical: 'top'},
  numberInput: {minHeight: 50, padding: 14, borderWidth: 1, borderColor: c.line, borderRadius: 14, backgroundColor: c.canvas, color: c.ink, fontSize: 16},
  history: {minHeight: 65, flexDirection: 'row', alignItems: 'center', gap: 12, paddingVertical: 12, borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: c.line},
  note: {gap: 6, paddingTop: 10, borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: c.line},
});
