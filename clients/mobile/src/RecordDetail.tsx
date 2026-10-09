import {useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState} from 'react';
import {AppState, View} from 'react-native';
import {Button, Text, TextInput} from 'react-native-paper';
import * as Crypto from 'expo-crypto';
import {ApiError, scopeOf, WearingApi, type Connection, type RecordItem} from './core';
import {recordEdit, recordEditChanged, recordPatch, validRecordEdit, withRecordDraft, type RecordEdit} from './record-editor';
import {RecordMutations, lifecycleMutation, mutationAction, mutationDraft, mutationLabel, mutationSyncedLabel, observeRecordMutations, projectRecordMutation, type MutationAction, type RecordMutation} from './record-mutations';
import {commitRecordReceipt, localRecords, mergeRecordVersions} from './record-sync';
import {storage} from './storage';
import {serviceFetch} from './transport';
import {observeDiagnosticError} from './diagnostics-client';
import {useAppTheme} from './app-theme';
import {Sheet} from './experience/primitives';
import TimeField from './TimeField';
import RemoteOriginal from './RemoteOriginal';
import RecordReminderPanel from './RecordReminderPanel';

/** Inputs, pending intent and the canonical server version remain separate. */
type Props = {record: RecordItem; connection: Connection; onChanged: (record: RecordItem) => void; onChat: (record: RecordItem) => void};
export default function RecordDetail(props: Props) {return <RecordDetailSession key={`${scopeOf(props.connection)}|${props.record.id}|${props.connection.session?.credentialId || ''}`} {...props}/>;}
function RecordDetailSession({record, connection, onChanged, onChat}: Props) {
  const {colors: c} = useAppTheme(), scope = scopeOf(connection), key = `record-edit:${scope}:${record.id}`;
  const mutations = useMemo(() => new RecordMutations(storage, () => Crypto.randomUUID()), []), api = useMemo(() => new WearingApi(connection, serviceFetch), [connection]);
  const [base, setBase] = useState(record), [edit, setEdit] = useState(() => recordEdit(record));
  const [entry, setEntry] = useState<RecordMutation | null>(null), [latest, setLatest] = useState<RecordItem | null>(null), [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false), [ready, setReady] = useState(false), [confirmArchive, setConfirmArchive] = useState(false);
  const lock = useRef(false), live = useRef(true), dirty = useRef(false), currentEdit = useRef(edit), generation = useRef(0), initialized = useRef(false);
  const changeCallback = useRef(onChanged); useLayoutEffect(() => {changeCallback.current = onChanged;});
  const setInput = (value: RecordEdit) => {currentEdit.current = value; setEdit(value);};
  const persist = (value: RecordEdit | null) => withRecordDraft(key, () => storage.put(key, value));
  const readLocal = useCallback(async (hydrate = false) => {
    const ticket = ++generation.current;
    const [records, rows] = await Promise.all([localRecords(storage, scope), mutations.items(scope)]);
    const observed = mergeRecordVersions([record], records.filter(row => row.id === record.id))[0], pending = rows.find(row => row.id === record.id) || null;
    const saved = hydrate ? await withRecordDraft(key, () => storage.get<unknown>(key)) : null;
    if (hydrate && saved !== null && !validRecordEdit(saved)) throw new Error('本机编辑草稿无法核对，原输入仍保留，请不要清除应用数据。');
    if (!live.current || generation.current !== ticket) return;
    setBase(observed); setEntry(pending);
    if (hydrate && validRecordEdit(saved)) {dirty.current = true; setInput(saved); if (saved.revision !== observed.revision && !pending) setLatest(observed);}
    else if (!dirty.current) setInput(pending ? mutationDraft(pending) : recordEdit(observed));
    if (pending?.state === 'conflict') setLatest(pending.latest || null);
    else if (dirty.current && currentEdit.current.revision !== observed.revision && !pending) setLatest(observed);
    else if (!dirty.current) setLatest(null);
    if (hydrate) {initialized.current = true; setReady(true);}
  }, [key, mutations, record, scope]);
  useEffect(() => {
    const sequence = generation; live.current = true;
    let cancelled = false;
    const report = (error: unknown) => {if (!cancelled && live.current) setNotice(error instanceof Error ? error.message : '本机修改暂时无法读取。');};
    const stop = observeRecordMutations(scope, () => {if (initialized.current && !cancelled) void readLocal().catch(report);});
    void Promise.resolve().then(() => {if (!cancelled) return readLocal(true);}).then(() => {if (!cancelled) return readLocal();}).catch(report);
    return () => {cancelled = true; live.current = false; initialized.current = false; sequence.current++; stop();};
  }, [readLocal, scope]);
  function change(patch: Partial<RecordEdit>) {
    if (lock.current || !ready) return;
    const next = {...currentEdit.current, ...patch}; dirty.current = true; setInput(next);
    void persist(next).catch(() => {if (live.current) setNotice('草稿暂未保存在本机，请先留在此页。');});
  }
  async function synchronize(action: MutationAction = 'edit') {
    try {
      await mutations.flush(scope, api, () => live.current && AppState.currentState === 'active', Date.now(), error => observeDiagnosticError(connection, 'record', error));
      if (live.current) {
        await readLocal();
        const [records, pending] = await Promise.all([localRecords(storage, scope), mutations.items(scope)]);
        const saved = records.find(row => row.id === record.id);
        if (saved && live.current) {
          changeCallback.current(saved);
          if (!pending.some(row => row.id === record.id)) setNotice(mutationSyncedLabel(action, saved, dirty.current));
        }
      }
    }
    catch (error) {observeDiagnosticError(connection, 'record', error); if (live.current) setNotice(error instanceof Error ? error.message : '修改已保留，请稍后再同步。');}
  }
  async function save(completion?: boolean) {
    if (lock.current || !ready) return;
    lock.current = true; setBusy(true); setNotice('');
    try {
      if (lifecycleMutation(entry)) throw new Error('请先取回移除或恢复的回执，再编辑这条记录。');
      if (latest || entry?.state === 'conflict') throw new Error('请先核对最新版本，再决定保留哪份内容。');
      const draft = {...currentEdit.current};
      const patch = completion === undefined ? recordPatch(base, draft) : {completed: completion};
      const pending = await mutations.enqueue(scope, {...base, revision: completion === undefined ? draft.revision : base.revision}, patch, completion === undefined ? {key, value: draft} : undefined);
      if (!live.current) return;
      setEntry(pending);
      if (completion === undefined) {dirty.current = false; setInput(mutationDraft(pending));}
      setNotice('修改已保存在本机。同步完成前，可以离开此页，稍后继续。');
      void synchronize();
    } catch (error) {observeDiagnosticError(connection, 'record', error); if (live.current) setNotice(error instanceof Error ? error.message : '本机保存未完成，请保留输入。');}
    finally {lock.current = false; if (live.current) setBusy(false);}
  }
  async function perform(action: 'read' | 'archive' | 'restore' | 'retry') {
    if (lock.current || !ready) return;
    lock.current = true; setBusy(true); setNotice('');
    try {
      if (action === 'read') {
        const response = await api.record(base.id);
        await commitRecordReceipt(storage, scope, response);
        const value = (await localRecords(storage, scope)).find(row => row.id === base.id) || response;
        const pending = await mutations.inspect(scope, base.id, value);
        if (live.current) {
          setBase(value); setEntry(pending);
          const needsReview = pending ? pending.state === 'conflict' : dirty.current;
          setLatest(needsReview ? value : null);
          if (!needsReview && !pending) setInput(recordEdit(value));
          setNotice(pending && pending.state !== 'conflict' ? '原操作还未确认。已读取现状，请先取回同一次操作回执，输入仍保留。' : needsReview ? '已读取最新版本。两份内容都保留着，请选择如何继续。' : '已读取最新版本，内容已同步。');
        }
        return;
      }
      if (action === 'archive' || action === 'restore') {
        const target = action === 'restore' && latest?.deleted_at ? latest : base;
        const draft = dirty.current || entry ? {key, value: {...currentEdit.current}} : undefined;
        const pending = await mutations.enqueueLifecycle(scope, target, action, draft, action === 'restore' && entry?.state === 'conflict' ? entry.generation : undefined);
        if (!live.current) return;
        if (draft) dirty.current = true;
        setEntry(pending); setLatest(null); setConfirmArchive(false);
        setNotice(`${action === 'archive' ? '移除' : '恢复'}操作已保存在本机，联网后同步。原件和编辑草稿仍保留。`);
        void synchronize(action);
        return;
      }
      if (entry) throw new Error('请先同步或核对本机操作，再重新整理原件。');
      const value = await api.retryCapture(base);
      await commitRecordReceipt(storage, scope, value);
      if (!live.current) return;
      setBase(value); changeCallback.current(value);
      setNotice('已重新排队整理，原件仍然保留。');
    } catch (error) {
      observeDiagnosticError(connection, 'record', error);
      if (!live.current) return;
      setNotice(error instanceof Error ? error.message : '操作尚未确认，请读取最新版本核对。');
      if (error instanceof ApiError && error.status === 409) {try {const value = await api.record(base.id); if (live.current) setLatest(value);} catch {/* Keep input and the explicit read action. */}}
    } finally {lock.current = false; if (live.current) setBusy(false);}
  }
  async function reconcile(keepInput: boolean) {
    if (!latest || lock.current || entry?.state === 'sending') return;
    lock.current = true; setBusy(true);
    try {
      const draft = {...currentEdit.current};
      if (entry) {
        const replacement = keepInput ? recordPatch(latest, {...draft, revision: latest.revision}) : undefined;
        const pending = await mutations.resolve(scope, base.id, entry.generation, latest, keepInput, replacement, {key, value: draft});
        if (!live.current) return;
        dirty.current = false; setBase(latest); setEntry(pending); setLatest(null); setInput(pending ? mutationDraft(pending) : recordEdit(latest));
        setNotice(keepInput ? '已保留你的修改，正在同步。' : '已采用服务端最新内容。');
        if (keepInput) void synchronize();
      } else {
        const next = keepInput ? {...draft, revision: latest.revision} : recordEdit(latest);
        await persist(keepInput ? next : null);
        if (!live.current) return;
        dirty.current = keepInput; setBase(latest); setInput(next); setLatest(null); setNotice(keepInput ? '已保留你的输入，请核对后保存。' : '已采用最新内容。');
      }
    } catch (error) {observeDiagnosticError(connection, 'record', error); if (live.current) setNotice(error instanceof Error ? error.message : '未能处理冲突，两份内容仍保留。');}
    finally {lock.current = false; if (live.current) setBusy(false);}
  }
  async function reconcileLifecycle(keepAction: boolean) {
    if (!latest || !entry || !lifecycleMutation(entry) || entry.state !== 'conflict' || lock.current) return;
    lock.current = true; setBusy(true);
    const action = mutationAction(entry);
    try {
      const pending = await mutations.resolveLifecycle(scope, base.id, entry.generation, latest, keepAction);
      if (!live.current) return;
      setBase(latest); setEntry(pending);
      setLatest(!pending && dirty.current && currentEdit.current.revision !== latest.revision ? latest : null);
      if (!dirty.current) setInput(recordEdit(latest));
      changeCallback.current(latest);
      setNotice(pending ? '已按你核对的版本保留操作，正在同步。' : '已采用记录当前状态，本机草稿仍保留。');
      if (pending) void synchronize(action);
    } catch (error) {observeDiagnosticError(connection, 'record', error); if (live.current) setNotice(error instanceof Error ? error.message : '操作仍保留，请重新核对。');}
    finally {lock.current = false; if (live.current) setBusy(false);}
  }
  const effective = entry ? projectRecordMutation(entry, base) : base;
  const card = {padding: 20, borderRadius: 24, backgroundColor: c.surface, gap: 12};
  return <View style={{gap: 20}}>
    <Text style={{fontSize: 28, fontWeight: '600', color: c.ink}}>{base.deleted_at ? '已删除的记录' : base.kind === 'event' ? '编辑日程' : base.kind === 'task' ? '编辑待办' : '编辑笔记'}</Text>
    <Text style={{color: c.muted}}>{base.deleted_at ? '这条记录和原件仍可恢复，本机修改会继续保留。' : '编辑和待同步修改会留在手机里，回来可以继续。'}</Text>
    {notice ? <Text accessibilityLiveRegion="polite" style={{color: c.muted, lineHeight: 23}}>{notice}</Text> : null}
    {!ready && <Button onPress={() => {void readLocal(true).then(() => readLocal()).catch(error => {if (live.current) setNotice(error instanceof Error ? error.message : '仍无法读取，原输入已保留。');});}}>重新读取本机编辑</Button>}
    {entry ? <View style={card}><Text style={{fontWeight: '600', color: c.ink}}>{mutationLabel(entry)}</Text>{entry.error ? <Text style={{color: c.muted}}>{entry.error}</Text> : null}{entry.state !== 'conflict' && <Button disabled={busy} onPress={() => {void mutations.retry(scope, base.id).then(() => synchronize(mutationAction(entry))).catch(error => {if (live.current) setNotice(error.message);});}}>{lifecycleMutation(entry) ? '取回这次操作回执' : '立即重试同步'}</Button>}{entry.state === 'conflict' && !latest ? <Button disabled={busy} onPress={() => void perform('read')}>读取最新版，核对修改</Button> : null}</View> : null}
    <View pointerEvents={busy || !ready || lifecycleMutation(entry) || base.deleted_at ? 'none' : 'auto'} style={{gap: 16}}>
      <TextInput mode="outlined" multiline label="记录内容" accessibilityLabel="记录内容" value={edit.text} onChangeText={text => change({text})} maxLength={12000} contentStyle={{minHeight: 150}}/>
      {base.kind === 'event' && <View style={card}>{/^\d{4}-\d{2}-\d{2}$/.test(edit.start) && <Text style={{color: c.muted}}>当前为全天日程。调整时间后会变为具体时段。</Text>}<TimeField label="开始时间" value={new Date(edit.start)} onChange={date => change({start: date.toISOString()})}/><TimeField label="结束时间" value={new Date(edit.end)} onChange={date => change({end: date.toISOString()})}/></View>}
      {base.kind === 'task' && <View style={card}>{edit.due ? <><TimeField label="截止时间" value={new Date(edit.due)} onChange={date => change({due: date.toISOString()})}/><Button disabled={busy || !!base.deleted_at || lifecycleMutation(entry)} onPress={() => change({due: ''})}>取消截止时间</Button></> : <Button disabled={busy || !!base.deleted_at || lifecycleMutation(entry)} onPress={() => change({due: new Date(Date.now() + 3600000).toISOString()})}>选择截止时间</Button>}<Text style={{color: c.muted}}>时间需点击保存修改后生效，设置截止时间不会自动开启提醒。</Text><Button disabled={busy || !!base.deleted_at || !!latest || lifecycleMutation(entry) || entry?.state === 'conflict'} onPress={() => void save(!effective.completed)}>{effective.completed ? '设为未完成' : '标记完成'}</Button></View>}
    </View>
    {latest && <View style={card}><Text style={{fontWeight: '600', color: c.ink}}>服务端最新版本 · {latest.deleted_at ? '已删除' : new Date(latest.updated_at).toLocaleString('zh-CN')}</Text><Text selectable style={{color: c.ink, lineHeight: 24}}>{latest.content}</Text>{latest.kind === 'event' && <Text>{latest.start_at} → {latest.end_at}</Text>}{latest.kind === 'task' && <Text>{latest.completed ? '已完成' : '未完成'}</Text>}{entry && lifecycleMutation(entry) ? <><Text style={{color: c.muted}}>原{mutationAction(entry) === 'archive' ? '移除' : '恢复'}操作没有执行。请按这个版本重新确认；本机编辑草稿不受影响。</Text><Button disabled={busy || entry.state !== 'conflict'} onPress={() => void reconcileLifecycle(true)}>{mutationAction(entry) === 'archive' ? '仍要移除这个版本' : '恢复这个版本'}</Button><Button disabled={busy || entry.state !== 'conflict'} onPress={() => void reconcileLifecycle(false)}>保留当前状态，取消这项操作</Button></> : <><Button disabled={busy || !!entry && entry.state !== 'conflict' || !!latest.deleted_at} onPress={() => void reconcile(true)}>{entry ? '保留我的修改并同步' : '保留我的输入，继续编辑'}</Button><Button disabled={busy || !!entry && entry.state !== 'conflict'} onPress={() => void reconcile(false)}>采用最新内容</Button></>}</View>}
    {base.deleted_at ? <Button mode="contained" loading={busy} disabled={busy || !ready || !!entry && (lifecycleMutation(entry) || entry.state !== 'conflict' || !latest?.deleted_at)} onPress={() => void perform('restore')}>恢复这条记录</Button> : <Button mode="contained" loading={busy} disabled={busy || !ready || !!latest || lifecycleMutation(entry) || entry?.state === 'conflict' || !recordEditChanged(effective, edit)} onPress={() => void save()}>保存修改</Button>}
    <Button disabled={busy || !ready || entry?.state === 'sending'} onPress={() => void perform('read')}>读取最新版本</Button>
    {base.kind !== 'note' && <RecordReminderPanel connection={connection} record={base} blocked={busy || !ready || !!entry || !!latest || recordEditChanged(base, edit)}/>}
    {base.capture && <View style={card}><Text style={{fontWeight: '600', color: c.ink}}>原话与原件</Text><Text selectable style={{color: c.muted, lineHeight: 24}}>{base.capture.original_text}</Text>{base.capture.assets.map(asset => <RemoteOriginal key={asset.id} asset={asset} connection={connection}/>)}{!base.deleted_at && base.capture.id && ['failed', 'paused'].includes(base.capture.state) && <Button disabled={busy || !!entry} onPress={() => void perform('retry')}>重新整理原件</Button>}</View>}
    {!base.deleted_at && <><Button onPress={() => onChat(base)}>接着和 Pajio 聊</Button><Button textColor={c.danger} disabled={busy || !!entry} onPress={() => setConfirmArchive(true)}>移到最近删除</Button></>}
    <Sheet visible={confirmArchive} onDismiss={() => {if (!busy) setConfirmArchive(false);}} title="移到最近删除？"><Text style={{color: c.muted, lineHeight: 24}}>这条记录会从日历、待办和笔记中移除。你可以在「最近删除」中恢复，原件也会保留。未保存的编辑会继续留在本机。离线时先保存移除操作，联网后同步；若其他地方已有修改，会请你核对后再执行。</Text><Button mode="contained" disabled={busy} loading={busy} onPress={() => void perform('archive')}>移到最近删除</Button><Button disabled={busy} onPress={() => setConfirmArchive(false)}>保留记录</Button></Sheet>
  </View>;
}
