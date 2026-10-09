import {useEffect, useLayoutEffect, useMemo, useRef, useState} from 'react';
import {ActivityIndicator, Text, TextInput, View} from 'react-native';
import * as Crypto from 'expo-crypto';
import {ApiError, Connection, scopeOf} from './core';
import {useAppTheme} from './app-theme';
import {PrimaryButton, TactilePressable} from './experience/primitives';
import {storage} from './storage';
import {BriefAutomationPanel} from './BriefAutomationPanel';
import {serviceFetch} from './transport';
import {BriefPreferenceApi, BriefPreferences, BriefSettings, PreferenceChanges, PreferenceRequest, PreferenceValues, preferenceValues, sourceAvailabilityLabel} from './briefing-preferences';

type Props = {connection: Connection; onChange: (preferences: BriefPreferences) => void; isCurrent?: () => boolean};
const defaults: PreferenceValues = {interests: [], priorities: '', sources: ['event', 'task', 'note', 'files'], max_items: 3};
export default function BriefPreferencesPanel(props: Props) {
  return <Preferences key={`${scopeOf(props.connection)}|${props.connection.session?.credentialId || ''}`} {...props}/>;
}
function Preferences({connection, onChange, isCurrent}: Props) {
  const {colors: c} = useAppTheme();
  const api = useMemo(() => new BriefPreferenceApi(connection, serviceFetch), [connection]);
  const changes = useMemo(() => new PreferenceChanges(storage, api), [api]);
  const notify = useRef(onChange);
  useLayoutEffect(() => {notify.current = onChange;}, [onChange]);
  const session = useRef({live: true, busy: false});
  const [settings, setSettings] = useState<BriefSettings | null>(null), [form, setForm] = useState(defaults);
  const [interests, setInterests] = useState(''), [expanded, setExpanded] = useState(false);
  const [pending, setPending] = useState<PreferenceRequest | null>(null), [busy, setBusy] = useState(true), [conflict, setConflict] = useState(false), [error, setError] = useState(''), [notice, setNotice] = useState('');
  const apply = (value: PreferenceValues) => {setForm(value); setInterests(value.interests.join('\n'));};
  useEffect(() => {
    const current = {live: true, busy: true}; session.current = current;
    void (async () => {
      try {
        const saved = await changes.pending();
        if (!current.live) return;
        setPending(saved); if (saved) {apply(saved); setExpanded(true);}
        const value = await api.load();
        if (!current.live) return;
        setSettings(value); if (!saved) apply(value.preferences); notify.current(value.preferences);
      } catch (cause) {if (current.live) setError(cause instanceof Error ? cause.message : '设置暂时无法读取。');}
      finally {current.busy = false; if (current.live) setBusy(false);}
    })();
    return () => {current.live = false;};
  }, [api, changes]);
  async function run(work: () => Promise<void>) {
    const current = session.current;
    if (current.busy) return;
    current.busy = true; setBusy(true); setError(''); setNotice('');
    try {await work();} catch (cause) {if (current.live) {setError(cause instanceof Error ? cause.message : '设置尚未保存。'); if (cause instanceof ApiError && cause.status === 409) setConflict(true);}}
    finally {current.busy = false; if (current.live) {const saved = await changes.pending().catch(() => pending); if (current.live) {setPending(saved); setBusy(false);}}}
  }
  async function refresh(keepInput = false) {
    const current = session.current, value = await api.load();
    if (!current.live) return;
    if (keepInput) await changes.discardConflict();
    if (!current.live) return;
    setSettings(value); notify.current(value.preferences); setConflict(false);
    if (!settings && !pending) apply(value.preferences);
    setNotice(keepInput ? '已读取最新版本，你的输入保留。核对后再点保存。' : '已更新偏好与来源状态，未保存的输入保留。');
  }
  async function save() {
    const current = session.current;
    if (!settings && !pending) return;
    const values = preferenceValues({...form, interests: interests.split('\n').map(v => v.trim()).filter(Boolean)});
    const request = pending || {...values, revision: settings!.preferences.revision, request_key: Crypto.randomUUID()};
    const saved = await changes.save(request);
    if (!current.live) return;
    setPending(null); apply(saved); setConflict(false);
    setSettings(previous => previous ? {...previous, preferences: saved, available_sources: previous.available_sources.map(source => ({...source, selected: saved.sources.includes(source.id)}))} : null);
    notify.current(saved); setNotice('偏好已保存，下一次生成会使用这版设置；已有简报不会改变。');
  }
  const text = {color: c.ink, fontSize: 15, lineHeight: 24}, muted = {color: c.muted, fontSize: 13, lineHeight: 21};
  const input = {borderWidth: 1, borderColor: c.line, color: c.ink, backgroundColor: c.surface, borderRadius: 12, padding: 12, fontSize: 16, minHeight: 72};
  const disabled = busy || !!pending;
  return <View style={{padding: 18, gap: 12, borderRadius: 20, borderWidth: 1, borderColor: c.line, backgroundColor: c.surface}}>
    <TactilePressable accessibilityRole="button" accessibilityLabel={expanded ? '收起简报偏好' : '设置兴趣、关注重点与简报来源'} onPress={() => setExpanded(value => !value)} style={{minHeight: 44, justifyContent: 'center'}}>
      <Text style={{...text, fontWeight: '600'}}>简报偏好 {expanded ? '−' : '+'}</Text><Text style={muted}>{settings ? `${settings.preferences.sources.length} 个来源 · 最多 ${settings.preferences.max_items} 项重点 · 设置版本 ${settings.preferences.revision}` : '兴趣、关注重点与资料范围'}</Text>
    </TactilePressable>
    {expanded ? <>
      <Text style={text}>感兴趣的主题</Text><Text style={muted}>每行一个，最多 8 项。例如产品设计、正在学习的领域。</Text>
      <TextInput multiline accessibilityLabel="简报兴趣，每行一个" editable={!disabled && !!settings} value={interests} onChangeText={setInterests} maxLength={487} placeholder="每行一个主题" placeholderTextColor={c.muted} style={input}/>
      <Text style={text}>最近最需要关注什么</Text><TextInput multiline accessibilityLabel="简报关注重点" editable={!disabled && !!settings} value={form.priorities} onChangeText={priorities => setForm(value => ({...value, priorities}))} maxLength={1000} placeholder="例如：本周上线进展，需要我决定的事" placeholderTextColor={c.muted} style={input}/>
      <Text style={text}>使用哪些资料</Text><Text style={muted}>这里只读已保存的记录与文件；飞书生成时再核对授权。选择来源不会自动连接应用或获取手机权限。</Text>
      {settings?.available_sources.map(source => <TactilePressable key={source.id} accessibilityRole="checkbox" accessibilityState={{checked: form.sources.includes(source.id), disabled}} disabled={disabled} onPress={() => setForm(value => ({...value, sources: value.sources.includes(source.id) ? value.sources.filter(id => id !== source.id) : [...value.sources, source.id]}))} style={{minHeight: 52, paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: c.line}}><Text style={text}>{form.sources.includes(source.id) ? '✓ ' : '○ '}{source.label}</Text><Text style={{...muted, color: source.state === 'failed' ? c.danger : c.muted}}>{sourceAvailabilityLabel(source)}</Text></TactilePressable>)}
      <Text style={text}>首屏重点数量</Text><View style={{flexDirection: 'row', gap: 16}}>{[1, 2, 3].map(count => <TactilePressable key={count} accessibilityRole="radio" accessibilityState={{checked: form.max_items === count, disabled}} disabled={disabled} onPress={() => setForm(value => ({...value, max_items: count}))} style={{padding: 12, minWidth: 56, borderRadius: 12, backgroundColor: form.max_items === count ? c.canvas : c.surface}}><Text style={text}>{count} 项</Text></TactilePressable>)}</View>
      {pending ? <Text style={muted}>上次保存尚待核对，先取回原请求的回执再改设置。</Text> : null}
      <PrimaryButton label={pending ? '取回上次保存回执' : '保存简报偏好'} disabled={busy || (!pending && !settings) || conflict} onPress={() => {void run(save);}}/>
      <PrimaryButton label={conflict ? '读取最新版本，保留我的输入' : '刷新偏好与来源'} tone="quiet" disabled={busy} onPress={() => {void run(() => refresh(conflict));}}/>
    </> : null}
    {expanded ? <BriefAutomationPanel connection={connection} isCurrent={isCurrent} preferencesRevision={settings?.preferences.revision ?? null}/> : null}
    {busy ? <ActivityIndicator color={c.muted}/> : null}
    {error ? <><Text accessibilityLiveRegion="polite" style={{...muted, color: c.danger}}>{error}</Text>{!expanded ? <PrimaryButton label="重新读取偏好" tone="quiet" disabled={busy} onPress={() => {void run(() => refresh());}}/> : null}</> : null}
    {notice ? <Text accessibilityLiveRegion="polite" style={muted}>{notice}</Text> : null}
  </View>;
}
