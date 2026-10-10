import {Choice} from './experience/selection';
import {useCallback, useEffect, useMemo, useRef, useState} from 'react';
import {ActivityIndicator, StyleSheet, Text, TextInput, View} from 'react-native';
import * as Crypto from 'expo-crypto';
import {ArrowDown, ArrowLeft, ArrowUp, ChevronRight, RefreshCw} from 'lucide-react-native';
import {scopeOf, WearingApi, type Connection, type RecordItem} from './core';
import {storage} from './storage';
import {serviceFetch} from './transport';
import {useAppTheme, useThemedStyles, type AppColors} from './app-theme';
import {IconButton, PrimaryButton, TactilePressable} from './experience/primitives';
import {RecordMutations, mutationLabel, observeRecordMutations, projectRecordMutation, type RecordMutation} from './record-mutations';
import {TaskListApi, TaskListChanges, appendListPage, listActionLabel, type ListCatalog, type ListPage, type ListRequest, type ListTask, type PendingListChange} from './task-lists';

type Props = {connection: Connection; onRecord: (record: RecordItem) => void; onChanged?: () => void; onBack?: () => void};
const errorMessage = (cause: unknown) => cause instanceof Error ? cause.message : '操作暂未完成，请重试。';
export default function TaskListsPanel(props: Props) {return <TaskListsSession key={`${scopeOf(props.connection)}|${props.connection.session?.credentialId || ''}`} {...props}/>;}
function TaskListsSession({connection, onRecord, onChanged, onBack}: Props) {
  const {colors: c} = useAppTheme(), s = useThemedStyles(styles), scope = scopeOf(connection);
  const api = useMemo(() => new TaskListApi(connection, serviceFetch), [connection]);
  const recordApi = useMemo(() => new WearingApi(connection, serviceFetch), [connection]);
  const changes = useMemo(() => new TaskListChanges(storage, api), [api]);
  const edits = useMemo(() => new RecordMutations(storage, () => Crypto.randomUUID()), []);
  const [catalog, setCatalog] = useState<ListCatalog | null>(null), [page, setPage] = useState<ListPage | null>(null);
  const [selected, setSelected] = useState<string | null>(null), [listsShown, setListsShown] = useState(40);
  const [pending, setPending] = useState<PendingListChange | null>(null), [mutations, setMutations] = useState<RecordMutation[]>([]);
  const [restoring, setRestoring] = useState(true), [restoreError, setRestoreError] = useState(false), [loading, setLoading] = useState(true), [saving, setSaving] = useState(false), [stale, setStale] = useState(true);
  const [error, setError] = useState(''), [notice, setNotice] = useState('');
  const [form, setForm] = useState<'create' | 'rename' | 'add' | 'archive' | 'restore' | null>(null), [name, setName] = useState(''), [title, setTitle] = useState('');
  const [manage, setManage] = useState<string | null>(null);
  const session = useRef({live: true, busy: false, read: 0}), selection = useRef<string | null>(null);
  const refresh = useCallback(async (wanted = selection.current) => {
    const current = session.current, generation = ++current.read;
    setLoading(true); setError('');
    try {
      const next = await api.catalog();
      const id = next.lists.find(row => row.id === wanted)?.id || next.lists.find(row => !row.archived_at)?.id || next.lists[0]?.id || null;
      const items = id ? await api.page(id, 0, next.revision) : null;
      if (!current.live || generation !== current.read) return false;
      selection.current = id; setSelected(id); setCatalog(next); setPage(items); setStale(false);
      return next;
    } catch (cause) {if (current.live && generation === current.read) {setError(errorMessage(cause)); setStale(true);} return false;}
    finally {if (current.live && generation === current.read) setLoading(false);}
  }, [api]);
  useEffect(() => {
    const current = {live: true, busy: false, read: 0}; session.current = current;
    const restore = async () => {
      try {
        const saved = await changes.pending(), local = await edits.items(scope);
        if (!current.live) return;
        setPending(saved); setMutations(local); setRestoreError(false);
        if (saved) {setName(saved.request.name || ''); setTitle(saved.request.title || '');}
      } catch (cause) {if (current.live) {setError(errorMessage(cause)); setRestoreError(true);}}
      finally {if (current.live) {setRestoring(false); await refresh();}}
    };
    void restore();
    const unsubscribe = observeRecordMutations(scope, () => {void edits.items(scope).then(rows => {if (current.live) setMutations(rows);}).catch(cause => {if (current.live) {setRestoreError(true); setError(errorMessage(cause));}});});
    return () => {current.live = false; unsubscribe();};
  }, [changes, edits, refresh, scope]);
  const locked = restoring || restoreError || saving || loading || stale || !!pending || !!mutations.length;
  const selectedList = catalog?.lists.find(row => row.id === selected);
  const act = async (input?: Omit<ListRequest, 'revision' | 'request_key'>) => {
    const current = session.current;
    if (!current.live || current.busy || restoring || restoreError || (input && locked)) return;
    current.busy = true; setSaving(true); setError(''); setNotice('');
    try {
      const request = input ? {...input, revision: catalog!.revision, request_key: Crypto.randomUUID()} : undefined;
      const receipt = await changes.save(request);
      if (!current.live) return;
      setPending(null); setForm(null); setManage(null); setName(''); setTitle('');
      setNotice(`${listActionLabel(request || pending!.request)}，已保存。`);
      onChanged?.();
      await refresh(receipt.action === 'create' ? receipt.lists[0].id : selection.current);
    } catch (cause) {if (current.live) setError(errorMessage(cause));}
    finally {
      try {const saved = await changes.pending(); if (current.live) setPending(saved);}
      catch (cause) {if (current.live) {setRestoreError(true); setError(errorMessage(cause));}}
      current.busy = false; if (current.live) setSaving(false);
    }
  };
  const resolve = async () => {
    const current = session.current;
    if (!current.live || current.busy || !pending || pending.phase === 'pending') return;
    current.busy = true; setSaving(true);
    const original = pending.request;
    try {
      const latest = await refresh(original.list_id || selection.current);
      if (!latest || !current.live) return;
      await changes.discardRejected();
      if (!current.live) return;
      setPending(null); setName(original.name || ''); setTitle(original.title || '');
      setForm((!original.list_id || latest.lists.some(row => row.id === original.list_id)) && ['create', 'rename', 'add', 'archive', 'restore'].includes(original.action) ? original.action as typeof form : null);
      setNotice('已读取最新内容；上次输入已保留，请核对清单后再次确认。');
    } catch (cause) {if (current.live) setError(errorMessage(cause));}
    finally {current.busy = false; if (current.live) setSaving(false);}
  };
  const choose = async (id: string) => {
    if (session.current.busy || loading) return;
    setForm(null); setManage(null); setNotice(''); await refresh(id);
  };
  const more = async () => {
    if (!page || page.next_offset === null || loading || saving || stale) return;
    const current = session.current, generation = ++current.read, previous = page;
    setLoading(true); setError('');
    try {
      const next = await api.page(previous.list.id, previous.next_offset!, previous.revision);
      if (current.live && generation === current.read) setPage(appendListPage(previous, next));
    } catch (cause) {if (current.live && generation === current.read) {setError(errorMessage(cause)); setStale(true);}}
    finally {if (current.live && generation === current.read) setLoading(false);}
  };
  const complete = async (record: ListTask) => {
    const current = session.current;
    if (!current.live || current.busy || restoring || restoreError || pending) return;
    current.busy = true; setSaving(true); setError(''); setNotice('');
    try {
      const local = mutations.find(row => row.id === record.id);
      const shown = local ? projectRecordMutation(local, record) : record;
      await edits.enqueue(scope, record, {completed: !shown.completed});
      if (!current.live) return;
      setNotice('修改已保存在本机，正在同步。');
      const sent = await edits.flush(scope, recordApi, () => current.live);
      if (current.live && sent) {setNotice('事项状态已同步。'); onChanged?.(); await refresh();}
    } catch (cause) {if (current.live) setError(errorMessage(cause));}
    finally {current.busy = false; if (current.live) setSaving(false);}
  };
  return <View style={s.root}>
    <View style={s.row}>{onBack && <IconButton label="返回任务" onPress={onBack}><ArrowLeft color={c.ink} size={20}/></IconButton>}<Text style={s.heading}>我的清单</Text><IconButton label="刷新清单" disabled={saving || loading} onPress={() => {void refresh();}}><RefreshCw color={c.ink} size={20}/></IconButton></View>
    <Text style={s.caption}>购物、出行或日常待办，分开收好。勾选后可以随时恢复。</Text>
    {!!error && <Text accessibilityRole="alert" style={s.error}>{error}</Text>}
    {!!notice && <Text accessibilityLiveRegion="polite" style={s.caption}>{notice}</Text>}
    {restoreError && <Text style={s.error}>本机操作队列尚未恢复。请返回后重新打开，避免重复提交。</Text>}
    {pending && <View style={s.card}><Text style={s.title}>{listActionLabel(pending.request)}</Text><Text style={s.caption}>{pending.phase === 'pending' ? '这次操作的结果还未确认。可以安全取回同一份回执，不会再添加一份。' : '这次操作没有执行。读取最新内容后，保留原输入供你核对。'}</Text><PrimaryButton label={pending.phase === 'pending' ? '取回这次操作回执' : '读取最新清单，保留输入'} loading={saving} disabled={loading} onPress={() => {void (pending.phase === 'pending' ? act() : resolve());}}/></View>}
    {!!mutations.length && <View style={s.card}><Text style={s.caption}>有 {mutations.length} 条待办修改尚未同步，处理完成后即可移动或整理清单。</Text>{mutations.map(row => <TactilePressable key={row.id} accessibilityRole="button" style={s.link} onPress={() => onRecord(projectRecordMutation(row))}><Text style={s.title}>{row.base.title}</Text><Text style={s.caption}>{mutationLabel(row)}</Text></TactilePressable>)}</View>}
    {loading && <ActivityIndicator color={c.accent}/>}
    {catalog && <>
      <View style={s.wrap}>{catalog.lists.slice(0, listsShown).map(list => <Choice variant="chip" key={list.id} selected={list.id === selected} disabled={loading || saving} onPress={() => {void choose(list.id);}} style={[s.chip, list.id === selected && s.selected]}><Text style={s.text}>{list.name}{list.archived_at ? ' · 已归档' : ` · ${list.open}`}</Text></Choice>)}</View>
      {catalog.lists.length > listsShown && <PrimaryButton tone="quiet" label={`查看更多清单（还有 ${catalog.lists.length - listsShown} 份）`} onPress={() => setListsShown(value => value + 40)}/>}
      {!catalog.lists.length && !loading && <Text style={s.caption}>还没有清单，先给要做的事起个名字。</Text>}
      <PrimaryButton tone="quiet" label="新建清单" disabled={locked} onPress={() => {setForm('create'); setName('');}}/>
    </>}
    {selectedList && <View style={s.card}>
      <Text style={s.title}>{selectedList.name}</Text><Text style={s.caption}>{selectedList.open} 项未完成 · 共 {selectedList.total} 项{selectedList.archived_at ? ' · 已归档，事项仍保留' : ''}</Text>
      <View style={s.wrap}><PrimaryButton tone="quiet" label="改名" disabled={locked} onPress={() => {setForm('rename'); setName(selectedList.name);}}/><PrimaryButton tone="quiet" label={selectedList.archived_at ? '恢复清单' : '归档清单'} disabled={locked} onPress={() => setForm(selectedList.archived_at ? 'restore' : 'archive')}/>{!selectedList.archived_at && <PrimaryButton label="添加事项" disabled={locked} onPress={() => {setForm('add'); setTitle('');}}/>}</View>
    </View>}
    {form && <View style={s.card}>
      <Text style={s.title}>{{create: '新建清单', rename: '给清单改名', add: `添加到「${selectedList?.name || ''}」`, archive: `归档「${selectedList?.name || ''}」`, restore: `恢复「${selectedList?.name || ''}」`}[form]}</Text>
      {['create', 'rename'].includes(form) && <TextInput accessibilityLabel="清单名称" placeholder="例如：周末采购" placeholderTextColor={c.faint} style={s.input} value={name} maxLength={80} editable={!saving && !pending} onChangeText={setName}/>}
      {form === 'add' && <TextInput accessibilityLabel="事项名称" placeholder="要做什么？" placeholderTextColor={c.faint} style={s.input} value={title} maxLength={200} editable={!saving && !pending} onChangeText={setTitle}/>}
      {form === 'archive' && <Text style={s.caption}>清单会标为已归档，事项不会删除或自动完成。未完成事项仍会出现在今天和全部待办里。恢复清单后可继续添加或排序。</Text>}
      {form === 'restore' && <Text style={s.caption}>恢复后可继续添加、移动和排序，原事项状态保持不变。</Text>}
      <View style={s.wrap}><PrimaryButton label={form === 'archive' ? '确认归档' : form === 'restore' ? '确认恢复' : '保存'} loading={saving} disabled={locked || (form === 'create' || form === 'rename' ? !name.trim() : form === 'add' ? !title.trim() : false)} onPress={() => {void act(form === 'create' ? {action: form, name: name.trim()} : form === 'rename' ? {action: form, list_id: selected!, name: name.trim()} : form === 'add' ? {action: form, list_id: selected!, title: title.trim(), content: '', timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'Asia/Shanghai'} : {action: form, list_id: selected!});}}/><PrimaryButton tone="quiet" label="取消" disabled={saving} onPress={() => setForm(null)}/></View>
    </View>}
    {page && <View style={s.card}>
      {stale && <Text style={s.caption}>这里是上次读取的内容；刷新成功后才能整理清单。</Text>}
      {!page.items.length && <Text style={s.caption}>清单里还没有事项。</Text>}
      {page.items.map((record, i) => {
        const mutation = mutations.find(row => row.id === record.id), shown = mutation ? projectRecordMutation(mutation, record) : record;
        return <View key={record.id} style={s.item}>
          <View style={s.row}><Choice  selected={!!shown.completed} multiple accessibilityLabel={`${shown.completed ? '恢复未完成' : '完成'}：${record.title}`} style={s.check} disabled={saving || restoring || restoreError || !!pending || mutation?.state === 'conflict'} onPress={() => {void complete(record);}}></Choice><TactilePressable accessibilityRole="button" style={s.record} onPress={() => onRecord(shown)}><Text style={[s.text, shown.completed && s.completed]}>{shown.title}</Text>{mutation && <Text style={s.caption}>{mutationLabel(mutation)}</Text>}</TactilePressable><IconButton label={`整理 ${record.title}`} disabled={locked} onPress={() => setManage(manage === record.id ? null : record.id)}><ChevronRight size={18} color={c.muted}/></IconButton></View>
          {manage === record.id && <View style={s.tools}><View style={s.wrap}><PrimaryButton tone="quiet" leading={<ArrowUp size={16} color={c.ink}/>} label="上移" disabled={locked || i === 0 || !!selectedList?.archived_at} onPress={() => {void act({action: 'reorder', list_id: selected!, record_id: record.id, record_revision: record.revision, before_id: page.items[i - 1].id});}}/><PrimaryButton tone="quiet" leading={<ArrowDown size={16} color={c.ink}/>} label="下移" disabled={locked || !!selectedList?.archived_at || (i >= page.items.length - 1) || (i === page.items.length - 2 && page.next_offset !== null)} onPress={() => {void act({action: 'reorder', list_id: selected!, record_id: record.id, record_revision: record.revision, before_id: page.items[i + 2]?.id || null});}}/></View><Text style={s.caption}>移动到另一份清单</Text><View style={s.wrap}>{catalog?.lists.filter(row => row.id !== selected && !row.archived_at).map(list => <PrimaryButton key={list.id} tone="quiet" label={list.name} disabled={locked} onPress={() => {void act({action: 'move', list_id: selected!, record_id: record.id, record_revision: record.revision, target_list_id: list.id});}}/>)}</View>{!catalog?.lists.some(row => row.id !== selected && !row.archived_at) && <Text style={s.caption}>先新建另一份清单，就可以把事项移过去。</Text>}</View>}
        </View>;
      })}
      <Text style={s.caption}>已显示 {page.items.length} / {page.list.total} 项</Text>
      {page.next_offset !== null && <PrimaryButton tone="quiet" label="加载更多事项" loading={loading} disabled={saving || stale} onPress={() => {void more();}}/>}
    </View>}
  </View>;
}
const styles = (c: AppColors) => StyleSheet.create({
  root: {gap: 14}, row: {flexDirection: 'row', alignItems: 'center', gap: 8}, heading: {fontSize: 26, fontWeight: '600', color: c.ink, flex: 1}, title: {fontSize: 17, fontWeight: '600', color: c.ink}, text: {fontSize: 16, color: c.ink, lineHeight: 24}, caption: {fontSize: 13, color: c.muted, lineHeight: 21}, error: {fontSize: 14, color: c.danger, lineHeight: 22}, card: {backgroundColor: c.surface, borderRadius: 22, padding: 18, gap: 13}, wrap: {flexDirection: 'row', flexWrap: 'wrap', gap: 8}, chip: {minHeight: 44, justifyContent: 'center', borderRadius: 16, paddingHorizontal: 15, paddingVertical: 10, backgroundColor: c.soft}, selected: {backgroundColor: c.selectionSurface, borderWidth: 1, borderColor: c.selectionBorder}, input: {minHeight: 50, padding: 12, borderWidth: 1, borderColor: c.line, borderRadius: 12, color: c.ink, fontSize: 16}, item: {borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: c.line, paddingBottom: 8}, check: {width: 44, height: 44, padding:0, paddingHorizontal:0,paddingVertical:0, alignItems: 'center', justifyContent: 'center'}, circle: {width: 22, height: 22, borderWidth: 1.5, borderColor: c.outline, borderRadius: 7}, record: {flex: 1, minHeight: 44, justifyContent: 'center'}, completed: {textDecorationLine: 'line-through', color: c.muted}, tools: {gap: 10, padding: 12, backgroundColor: c.soft, borderRadius: 14}, link: {minHeight: 44, gap: 5},
});
