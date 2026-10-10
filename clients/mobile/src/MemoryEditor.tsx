import {StateSwitch} from './experience/selection';
import React, {useEffect, useMemo, useRef, useState} from 'react';
import {ScrollView, Text, TextInput, View} from 'react-native';
import {Button} from 'react-native-paper';
import {Connection, MemorySnapshot, WearingApi} from './core';
import {serviceFetch} from './transport';
import {storage} from './storage';
import {useAppTheme} from './app-theme';
import {Sheet, TactilePressable} from './experience/primitives';
import {MemoryDraft, memoryDraftKey, persistMemoryDraft, readMemoryDraft, rebaseMemoryDraft} from './memory-drafts';
import {applyMemoryChange, MemoryHistoryItem, memoryHistoryChanges, memoryHistoryTitle, memoryUndoRequest} from './memory-history';

type Confirm = {kind: 'remove'; index: number; text: string; revision: string} | {kind: 'clear'; count: number; historyCount: number; revision: string} | {kind: 'disable'; revision: string; settings_revision: string} | {kind: 'undo'; item: MemoryHistoryItem; revision: string};
function MemoryContent({connection, target, data, onChanged}: {connection: Connection; target: 'user' | 'memory'; data: MemorySnapshot; onChanged: (data: MemorySnapshot) => void}) {
  const {colors: c} = useAppTheme(), api = useMemo(() => new WearingApi(connection, serviceFetch), [connection]), current = data.targets?.[target];
  const key = memoryDraftKey(connection, target), label = target === 'user' ? '关于你' : '长期记忆';
  const [draft, setDraft] = useState<MemoryDraft | null>(null), [open, setOpen] = useState(false), [confirm, setConfirm] = useState<Confirm | null>(null);
  const [error, setError] = useState(''), [receipt, setReceipt] = useState(''), [busy, setBusy] = useState(false), [ready, setReady] = useState(false), [draftError, setDraftError] = useState('');
  const [historyOpen, setHistoryOpen] = useState(false), [selectedHistory, setSelectedHistory] = useState<string | null>(null), [needsRefresh, setNeedsRefresh] = useState(false);
  const lock = useRef(false), live = useRef(true), latestDraft = useRef<MemoryDraft | null>(null);
  useEffect(() => {live.current = true; void readMemoryDraft(storage, key).then(value => {if (live.current) {latestDraft.current = value; setDraft(value); setReady(true);}}).catch(() => {if (live.current) setDraftError('暂时无法读取本机草稿，请返回后重试。');}); return () => {live.current = false;};}, [key]);
  const supported = !!current?.revision, settingsSupported = !!current?.settings_revision, blocked = busy || needsRefresh;
  const history = current?.history, selected = history?.items.find(item => item.id === selectedHistory), selectedChanges = selected ? memoryHistoryChanges(selected) : null;
  function updateDraft(next: MemoryDraft | null) {
    latestDraft.current = next; setDraft(next); setDraftError('');
    void persistMemoryDraft(storage, key, next).catch(() => {if (live.current) setDraftError('草稿暂时没有保存在手机里，请先保留此页面。');});
  }
  async function fresh() {
    const next = await api.memory();
    if (live.current) {onChanged(next); setNeedsRefresh(false);}
    return next;
  }
  async function reread() {
    if (lock.current) return; lock.current = true; setBusy(true); setError('');
    try {await fresh(); if (live.current) setReceipt('已读取最新版，编辑草稿仍保留。');}
    catch (cause) {if (live.current) setError(cause instanceof Error ? cause.message : '暂时无法读取最新记忆。');}
    finally {lock.current = false; if (live.current) setBusy(false);}
  }
  async function change(body: Parameters<WearingApi['changeMemory']>[0], editing = false) {
    if (lock.current || needsRefresh) return; lock.current = true; setBusy(true); setError(''); setReceipt('');
    try {
      const result = await applyMemoryChange(api, body);
      if (result.state !== 'confirmed') {
        if (live.current) {
          setConfirm(null);
          if (result.state === 'conflict' && result.snapshot) {onChanged(result.snapshot); setNeedsRefresh(false); setError('记忆已有变化，已读取最新版。请重新核对后操作；没有自动重试。');}
          else {setNeedsRefresh(true); setError(result.state === 'conflict' ? '记忆已有变化，暂时无法读取最新版。请先重新读取，再决定下一步。' : '这次修改尚未得到完整确认，请先读取最新记忆，核对是否已经生效。不会自动重试。');}
        }
        return;
      }
      const next = result.snapshot;
      let cleared = !editing;
      if (editing) {try {await persistMemoryDraft(storage, key, null); cleared = true;} catch {if (live.current) setDraftError('记忆已经保存，本机草稿暂时未清理。请核对最新版后收起草稿。');}}
      if (live.current) {onChanged(next); setConfirm(null); if (editing && cleared) {latestDraft.current = null; setDraft(null); setOpen(false);} setReceipt(body.action === 'set_enabled' ? body.enabled ? `${label}已恢复，下次新任务开始使用。` : `${label}已暂停，内容仍保留。` : body.action === 'clear' ? `已清空本页的${label}和修改记录。` : body.action === 'undo' ? '已撤销这次修改，当前记忆已更新。' : body.action === 'remove' ? '已删除这条个人记忆。' : '记忆已保存。');}
    } catch (cause) {
      if (live.current) setError(cause instanceof Error ? cause.message : '记忆暂时没有保存，草稿仍保留。');
    } finally {lock.current = false; if (live.current) setBusy(false);}
  }
  function toggle(enabled: boolean) {if (!current?.revision || !current.settings_revision) return; if (!enabled) setConfirm({kind: 'disable', revision: current.revision, settings_revision: current.settings_revision}); else void change({target, action: 'set_enabled', enabled, revision: current.revision, settings_revision: current.settings_revision});}
  function newDraft(index?: number) {if (!current?.revision) return; if (draft) {setOpen(true); setError('你有一份未完成草稿，先保存或放弃后再编辑另一条。'); return;} updateDraft({version: 1, index, revision: current.revision, text: index === undefined ? '' : current.entries[index], ...(index === undefined ? {} : {baseText: current.entries[index]})}); setOpen(true); setError('');}
  const stale = !!draft && !!current?.revision && draft.revision !== current.revision;
  const rebase = draft && current?.revision ? rebaseMemoryDraft(draft, current.entries, current.revision) : null;
  const confirmStale = !!confirm && (confirm.kind === 'disable' ? confirm.settings_revision !== current?.settings_revision : confirm.revision !== current?.revision || confirm.kind === 'undo' && !memoryUndoRequest(target, data, confirm.item.id));
  return <View style={{gap: 14}}>
    <View style={{backgroundColor: c.surface, padding: 18, borderRadius: 18, gap: 10}}><View style={{flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between'}}><Text style={{color: c.ink, fontSize: 17, fontWeight: '600'}}>使用{label}</Text><StateSwitch accessibilityLabel={`使用${label}`} value={!!current?.enabled} disabled={blocked || !settingsSupported} onValueChange={toggle}/></View><Text style={{color: c.muted, lineHeight: 23}}>{current?.enabled ? '后续新任务可以读取与更新这里的个人记忆。' : '已暂停。后续新任务不会通过个人记忆功能读取或更新这里的内容，已存条目仍可查看和删除。'}</Text>{!settingsSupported ? <Text style={{color: c.muted}}>当前引擎需要更新后才能切换记忆使用状态。</Text> : null}</View>
    {current?.entries.map((entry, index) => <View key={index} style={{backgroundColor: c.surface, padding: 18, borderRadius: 16, gap: 10}}><Text selectable style={{color: c.ink, lineHeight: 26, fontSize: 16}}>{entry}</Text><View style={{flexDirection: 'row', gap: 20}}><TactilePressable accessibilityLabel={`编辑第${index + 1}条记忆`} disabled={blocked || !supported || !ready || !current.enabled} onPress={() => newDraft(index)} style={{minHeight: 44, justifyContent: 'center'}}><Text style={{color: current.enabled ? c.accent : c.muted}}>编辑</Text></TactilePressable><TactilePressable accessibilityLabel={`删除第${index + 1}条记忆`} disabled={blocked || !supported} onPress={() => {setConfirm({kind: 'remove', index, text: entry, revision: current.revision!}); setError('');}} style={{minHeight: 44, justifyContent: 'center'}}><Text style={{color: c.muted}}>删除</Text></TactilePressable></View></View>)}
    {current && !current.entries.length ? <Text style={{color: c.muted}}>这里还没有记下内容。</Text> : null}
    {receipt ? <Text accessibilityLiveRegion="polite" style={{color: c.success}}>{receipt}</Text> : null}{!open && !confirm && error ? <Text style={{color: c.danger}}>{error}</Text> : null}{draftError ? <Text accessibilityLiveRegion="polite" style={{color: c.danger}}>{draftError}</Text> : null}
    {needsRefresh ? <Button disabled={busy} loading={busy} onPress={() => {void reread();}}>读取最新记忆，核对结果</Button> : null}
    {history ? <View style={{gap: 12, paddingVertical: 12}}>
      <Text style={{color: c.ink, fontSize: 17, fontWeight: '600'}}>你的修改记录</Text>
      <Text style={{color: c.muted, fontSize: 13, lineHeight: 21}}>最近 {history.limit} 条，仅记录你在这里做的修改。</Text>
      {history.unconfirmed_changes ? <View style={{gap: 6}}><Text accessibilityLiveRegion="polite" style={{color: c.muted, lineHeight: 23}}>有一次保存未确认，请核对当前记忆。它不会被当作已完成记录，也不会自动重试。</Text><Button disabled={busy} onPress={() => {void reread();}}>核对当前记忆</Button></View> : null}
      {!history.items.length ? <Text style={{color: c.muted}}>还没有已确认的修改记录。</Text> : history.items.slice(0, historyOpen ? history.limit : 3).map(item => {
        const changes = memoryHistoryChanges(item), preview = changes.after[0] || changes.before[0];
        return <TactilePressable key={item.id} accessibilityLabel={`查看${memoryHistoryTitle(item.action)}，${new Date(item.created_at).toLocaleString('zh-CN')}`} disabled={busy} onPress={() => {setSelectedHistory(item.id); setError('');}} style={{backgroundColor: c.surface, padding: 16, borderRadius: 16, gap: 8}}>
          <View style={{flexDirection: 'row', justifyContent: 'space-between', gap: 12}}><Text style={{color: c.ink, fontWeight: '600'}}>{memoryHistoryTitle(item.action)}</Text><Text style={{color: item.undoable ? c.accent : c.muted, fontSize: 13}}>{item.undoable ? '可撤销' : '查看修改'}</Text></View>
          {preview ? <Text numberOfLines={2} style={{color: c.muted, lineHeight: 22}}>{preview}</Text> : null}
          <Text style={{fontSize: 12, color: c.muted}}>{new Date(item.created_at).toLocaleString('zh-CN')}</Text>
        </TactilePressable>;
      })}
      {history.items.length > 3 ? <Button disabled={busy} onPress={() => setHistoryOpen(value => !value)}>{historyOpen ? '收起较早记录' : `查看全部 ${history.items.length} 条记录`}</Button> : null}
    </View> : null}
    {draft && !open ? <Button disabled={busy} onPress={() => setOpen(true)}>继续未完成的编辑</Button> : null}<Button disabled={blocked || !supported || !current?.enabled || !ready} onPress={() => newDraft()}>添加记忆</Button>
    {current && (current.entries.length || history?.items.length || history?.unconfirmed_changes) ? <Button disabled={blocked || !supported} onPress={() => {setConfirm({kind: 'clear', count: current.entries.length, historyCount: history?.items.length || 0, revision: current.revision!}); setError('');}}>清空本页内容和修改记录</Button> : null}
    <Text style={{fontSize: 12, color: c.muted, lineHeight: 20}}>本页只管理当前身份的{label}条目。聊天历史、其他记忆页、文件和已完成任务会保留；暂停不会抹去已经出现在聊天中的信息。</Text>
    <Sheet visible={open && !!draft} onDismiss={() => {if (!busy) setOpen(false);}} title={draft?.index === undefined ? '添加记忆' : '编辑记忆'}>
      <TextInput accessibilityLabel="记忆内容" multiline value={draft?.text || ''} editable={!busy} maxLength={12000} onChangeText={text => {if (draft) updateDraft({...draft, text});}} style={{minHeight: 140, padding: 14, borderRadius: 14, borderWidth: 1, borderColor: c.line, color: c.ink, fontSize: 16, lineHeight: 25}}/>
      {error ? <Text accessibilityLiveRegion="polite" style={{color: c.danger}}>{error}</Text> : null}{draftError ? <Text style={{color: c.danger}}>{draftError}</Text> : null}
      {stale ? <><Text style={{color: c.muted, lineHeight: 23}}>记忆已有更新，你的输入仍在上方。请核对下面的当前内容再继续。</Text><ScrollView style={{maxHeight: 200}} nestedScrollEnabled>{current?.entries.map((text, index) => <Text selectable key={index} style={{color: c.ink, lineHeight: 22}}>{index + 1}. {text}</Text>)}</ScrollView>{rebase?.alreadyPresent ? <><Text style={{color: c.success}}>最新版已包含这段内容，无需重复添加。</Text><Button disabled={busy} onPress={() => {updateDraft(null); setOpen(false);}}>核对完成，收起草稿</Button></> : rebase?.draft ? <Button disabled={busy} onPress={() => {updateDraft(rebase.draft); setError('');}}>已核对，继续使用这份草稿</Button> : <><Text style={{color: c.muted}}>原条目已变化，无法安全定位。可以把草稿另存为一条新记忆。</Text><Button disabled={busy || !current?.revision} onPress={() => {if (draft && current?.revision) updateDraft({version: 1, text: draft.text, revision: current.revision});}}>改为新增记忆</Button></>}</> : null}
      <Button mode="contained" loading={busy} disabled={blocked || !draft?.text.trim() || stale || !current?.enabled} onPress={() => {if (draft) void change({target, action: draft.index === undefined ? 'add' : 'replace', revision: draft.revision, index: draft.index, content: draft.text}, true);}}>保存记忆</Button><Button disabled={busy} onPress={() => {void reread();}}>读取最新记忆，保留草稿</Button><Button disabled={busy} onPress={() => setOpen(false)}>保留草稿并返回</Button><Button disabled={busy} onPress={() => {updateDraft(null); setOpen(false); setError('');}}>放弃这份草稿</Button>
    </Sheet>
    <Sheet visible={!!selected || !!confirm} onDismiss={() => {if (!busy) {setSelectedHistory(null); setConfirm(null);}}} title={confirm ? confirm.kind === 'disable' ? `暂停使用${label}？` : confirm.kind === 'clear' ? '清空本页内容和修改记录？' : confirm.kind === 'undo' ? '撤销这次修改？' : '删除这条个人记忆？' : selected ? memoryHistoryTitle(selected.action) : '修改记录'}>
      {!confirm && selected && selectedChanges ? <>
        <Text style={{color: c.muted, lineHeight: 23}}>你的修改 · {new Date(selected.created_at).toLocaleString('zh-CN')}</Text>
        <ScrollView style={{maxHeight: 360}} nestedScrollEnabled contentContainerStyle={{gap: 12}}>
          {selectedChanges.before.length ? <><Text style={{color: c.muted, fontWeight: '600'}}>移除的内容</Text>{selectedChanges.before.map((text, index) => <Text selectable key={`before-${index}`} style={{color: c.ink, lineHeight: 24}}>{text}</Text>)}</> : null}
          {selectedChanges.after.length ? <><Text style={{color: c.muted, fontWeight: '600'}}>加入的内容</Text>{selectedChanges.after.map((text, index) => <Text selectable key={`after-${index}`} style={{color: c.ink, lineHeight: 24}}>{text}</Text>)}</> : null}
          {!selectedChanges.before.length && !selectedChanges.after.length ? <Text style={{color: c.muted}}>条目文本没有增减；撤销会恢复修改前的状态。</Text> : null}
        </ScrollView>
        {selected.undoable ? <Button mode="contained" disabled={blocked || !current?.enabled || !current.revision} onPress={() => {if (current?.revision) {setConfirm({kind: 'undo', item: selected, revision: current.revision}); setSelectedHistory(null); setError('');}}}>撤销这次修改</Button> : <Text style={{color: c.muted, lineHeight: 23}}>{!current?.enabled ? '本页已暂停使用，恢复后才能撤销符合条件的修改。' : '这条记录目前不能撤销：它可能已被撤销，或记忆后来有了新变化。'}</Text>}
        <Button disabled={busy} onPress={() => setSelectedHistory(null)}>返回记忆</Button>
      </> : null}
      {confirm ? <>
      <Text style={{color: c.muted, lineHeight: 24}}>{confirm?.kind === 'disable' ? `内容会保留。下次新任务不再通过个人记忆功能读取或更新${label}，你可以随时恢复。` : confirm?.kind === 'clear' ? `将删除当前身份「${connection.identity === 'daily' ? '日常' : connection.identity}」的「${label}」中 ${confirm.count} 条记忆，同时删除本页 ${confirm.historyCount} 条修改记录和未确认的修改记录，无法撤销。其他记忆页、对话和文件会保留。` : confirm?.kind === 'undo' ? `将恢复「${label}」在这次修改之前的内容。只有本页之后没有新变化时，才能撤销。` : `仅删除当前身份「${label}」中选择的这一条，不会删除其他记忆、对话或文件。`}</Text>
      {confirm?.kind === 'clear' && draft ? <Text style={{color: c.muted, lineHeight: 23}}>本机未保存的编辑草稿会保留，不在本次清空范围内。</Text> : null}
      {confirm?.kind === 'remove' ? <Text style={{color: c.ink, lineHeight: 24}}>{confirm.text}</Text> : null}
      {confirm?.kind === 'undo' ? <Text style={{color: c.ink, lineHeight: 24}}>{memoryHistoryTitle(confirm.item.action)} · {new Date(confirm.item.created_at).toLocaleString('zh-CN')}</Text> : null}
      {error ? <Text accessibilityLiveRegion="polite" style={{color: c.danger}}>{error}</Text> : null}
      {confirmStale ? <Text style={{color: c.muted}}>内容或设置已有变化，请返回核对后重新选择，旧确认不会继续执行。</Text> : null}
      <Button mode="contained" loading={busy} disabled={blocked || confirmStale} onPress={() => {
        if (!confirm) return;
        if (confirm.kind === 'undo') {const request = memoryUndoRequest(target, data, confirm.item.id); if (request) void change(request); return;}
        void change(confirm.kind === 'disable' ? {target, action: 'set_enabled', revision: confirm.revision, settings_revision: confirm.settings_revision, enabled: false} : confirm.kind === 'clear' ? {target, action: 'clear', revision: confirm.revision} : {target, action: 'remove', revision: confirm.revision, index: confirm.index});
      }}>{confirm?.kind === 'disable' ? '暂停使用' : confirm?.kind === 'clear' ? '清空内容和记录' : confirm?.kind === 'undo' ? '确认撤销' : '删除这条记忆'}</Button>
      <Button disabled={busy} onPress={() => {setConfirm(null); setError('');}}>{confirm.kind === 'undo' ? '暂不撤销' : '保留并返回'}</Button>
      </> : null}
    </Sheet>
  </View>;
}
export function MemoryEditor(props: {connection: Connection; target: 'user' | 'memory'; data: MemorySnapshot; onChanged: (data: MemorySnapshot) => void; onRefresh: () => void}) {return <MemoryContent key={memoryDraftKey(props.connection, props.target)} {...props}/>;}
