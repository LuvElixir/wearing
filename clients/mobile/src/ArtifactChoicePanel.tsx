import {useEffect, useMemo, useRef, useState} from 'react';
import {ActivityIndicator, StyleSheet, Text, View} from 'react-native';
import * as Crypto from 'expo-crypto';
import {Check, ChevronRight} from 'lucide-react-native';
import {ApiError, type Connection, scopeOf} from './core';
import type {ArtifactMetadata} from './artifact-client';
import {ArtifactChoiceApi, choicePendingKey, choiceTaskPending, validChoiceRequest, type ChoiceRequest, type ChoiceState} from './artifact-choices';
import {storage} from './storage';
import {serviceFetch} from './transport';
import {useAppTheme, useThemedStyles, type AppColors} from './app-theme';
import {PrimaryButton, TactilePressable} from './experience/primitives';

type Props = {connection: Connection; artifact: ArtifactMetadata; onTask?: (id: string) => void; onArtifact?: (id: string) => void};
export default function ArtifactChoicePanel(props: Props) {
  return <ChoiceSession key={`${scopeOf(props.connection)}|${props.artifact.id}`} {...props}/>;
}
function ChoiceSession({connection, artifact, onTask, onArtifact}: Props) {
  const {colors: c} = useAppTheme(), s = useThemedStyles(makeStyles);
  const api = useMemo(() => new ArtifactChoiceApi(connection, artifact.id, artifact.revision, artifact.task_id, serviceFetch), [connection, artifact.id, artifact.revision, artifact.task_id]);
  const key = choicePendingKey(scopeOf(connection), artifact.id);
  const [state, setState] = useState<ChoiceState | null>(null), [pending, setPending] = useState<ChoiceRequest | null>(null);
  const [selected, setSelected] = useState(''), [loading, setLoading] = useState(true), [saving, setSaving] = useState(false), [revision, setRevision] = useState(0);
  const [error, setError] = useState(''), [loaded, setLoaded] = useState(false);
  const session = useRef({live: true, busy: false});
  useEffect(() => {const current = {live: true, busy: false}; session.current = current; return () => {current.live = false;};}, [api]);
  useEffect(() => {
    let live = true;
    Promise.all([api.read(), storage.get<unknown>(key)]).then(async ([value, saved]) => {
      if (saved !== null && (!validChoiceRequest(saved) || saved.artifact_revision !== artifact.revision)) throw new Error('上次选择暂时无法恢复，请先查看原任务，避免重复提交。');
      if (!live) return;
      if (saved && value.selection?.request_key === saved.request_key && value.selection.choice_id === saved.choice_id && value.selection.revision === saved.selection_revision + 1) {
        await storage.put(key, null); saved = null;
      }
      if (!live) return;
      setState(value); setPending(saved as ChoiceRequest | null); setLoaded(true); setError('');
    }).catch(cause => {if (live) setError(cause instanceof Error ? cause.message : '暂时没有读到选择，请重试。');})
      .finally(() => {if (live) setLoading(false);});
    return () => {live = false;};
  }, [api, artifact.revision, key, revision]);
  const option = state?.choices.find(item => item.id === selected);
  const submit = async () => {
    const current = session.current;
    if (!current.live || current.busy || !loaded || !state || (!pending && (!option || !!state.newer_id || choiceTaskPending(state.selection)))) return;
    const body = pending || {request_key: Crypto.randomUUID(), choice_id: option!.id, artifact_revision: artifact.revision, selection_revision: state.revision};
    current.busy = true; setSaving(true); setError('');
    try {
      await storage.put(key, body);
      if (!current.live) return;
      setPending(body);
      const receipt = await api.choose(body);
      await storage.put(key, null);
      if (!current.live) return;
      setPending(null); setSelected(''); setState({...state, revision: receipt.revision, selection: receipt});
    } catch (cause) {
      if (!current.live) return;
      if (cause instanceof ApiError && [400, 401, 403, 404, 409, 422].includes(cause.status)) {
        try {await storage.put(key, null); if (current.live) {setPending(null); setLoaded(false);}} catch { /* Keep exact intent if local cleanup fails. */ }
      }
      if (current.live) setError(cause instanceof Error ? cause.message : '选择尚未取得回执，请重新读取。');
    } finally {current.busy = false; if (current.live) setSaving(false);}
  };
  if (!loading && !error && !state?.choices.length && !pending) return null;
  return <View style={s.card}>
    <Text accessibilityRole="header" style={s.title}>接下来怎么做</Text>
    {loading ? <ActivityIndicator color={c.accent}/> : null}
    {error ? <Text style={s.error} accessibilityLiveRegion="polite">{error}</Text> : null}
    {state?.selection ? <View style={s.receipt}>
      <Text style={s.body}>{state.selection.queue_state === 'cancelled' ? '这项选择已撤回' : choiceTaskPending(state.selection) ? '选择已保存，进展会回到对话' : '这项选择已有进展'}</Text>
      {onTask ? <PrimaryButton label="查看这项选择的任务" tone="quiet" disabled={saving} onPress={() => onTask(state.selection!.task_id)}/> : null}
    </View> : null}
    {pending ? <><Text style={s.body}>上次选择还在等待回执，先找回这一次提交。</Text><PrimaryButton label="取回上次选择回执" loading={saving} disabled={!loaded || loading} onPress={() => {void submit();}}/></> : null}
    {state?.newer_id ? <><Text style={s.caption}>这份结果已有新版本。</Text>{onArtifact ? <PrimaryButton label="打开最新一版" tone="quiet" disabled={saving} onPress={() => onArtifact(state.newer_id!)}/> : null}</> : null}
    {loaded && state && !state.newer_id && !pending && !choiceTaskPending(state.selection) ? state.choices.map(choice => <TactilePressable key={choice.id}
      accessibilityRole="radio" accessibilityState={{checked: selected === choice.id}} accessibilityLabel={choice.label} disabled={saving}
      onPress={() => setSelected(choice.id)} style={[s.option, selected === choice.id && {borderColor: c.accent}]}>
      <Text style={s.body}>{choice.label}</Text>{selected === choice.id ? <Check size={18} color={c.accent}/> : <ChevronRight size={18} color={c.muted}/>}
    </TactilePressable>) : null}
    {option && !pending && loaded && !state?.newer_id && !choiceTaskPending(state?.selection || null) ? <View style={s.receipt}>
      <Text style={s.caption}>确认后，将这段要求交给 Pajio 继续处理：</Text><Text selectable style={s.body}>{option.instruction}</Text>
      <PrimaryButton label="确认选择，继续处理" loading={saving} onPress={() => {void submit();}}/>
    </View> : null}
    <PrimaryButton label="重新读取选择状态" tone="quiet" disabled={saving || loading} onPress={() => {setLoading(true); setLoaded(false); setRevision(n => n + 1);}}/>
  </View>;
}
const makeStyles = (c: AppColors) => StyleSheet.create({
  card: {gap: 12, padding: 18, borderRadius: 20, borderWidth: 1, borderColor: c.line, backgroundColor: c.surface},
  title: {color: c.ink, fontSize: 18, lineHeight: 28, fontWeight: '600'}, body: {color: c.ink, fontSize: 15, lineHeight: 24, flexShrink: 1},
  caption: {color: c.muted, fontSize: 13, lineHeight: 22}, error: {color: c.danger, fontSize: 14, lineHeight: 23},
  option: {flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', minHeight: 50, gap: 10, padding: 14, borderRadius: 14, borderWidth: 1, borderColor: c.line},
  receipt: {gap: 10},
});
