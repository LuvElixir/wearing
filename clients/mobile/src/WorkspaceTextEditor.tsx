import {useEffect, useMemo, useRef, useState} from 'react';
import {ActivityIndicator, ScrollView, Text, TextInput, View} from 'react-native';
import * as Crypto from 'expo-crypto';
import {ApiError, Connection, scopeOf} from './core';
import {useAppTheme} from './app-theme';
import {PrimaryButton} from './experience/primitives';
import {storage} from './storage';
import {serviceFetch} from './transport';
import {RecoveryText, TEXT_LIMIT, TextDocument, TextReceipt, TextRequest, WorkspaceTextApi, WorkspaceTextDrafts, comparisonSummary, textSize} from './workspace-text';

type Props = {connection: Connection; path: string; onClose: () => void; onSaved: () => void; onOpen: (path: string) => void};
const digest = (text: string) => Crypto.digestStringAsync(Crypto.CryptoDigestAlgorithm.SHA256, text);
const issue = (cause: unknown) => cause instanceof Error ? cause.message : '暂时无法读取文档。';
export default function WorkspaceTextEditor(props: Props) {return <Editor key={`${scopeOf(props.connection)}|${props.connection.session?.credentialId || ''}|${props.path}`} {...props}/>;}
function Editor({connection, path, onClose, onSaved, onOpen}: Props) {
  const {colors: c} = useAppTheme();
  const api = useMemo(() => new WorkspaceTextApi(connection, digest, serviceFetch), [connection]);
  const drafts = useMemo(() => new WorkspaceTextDrafts(storage, api, path), [api, path]);
  const session = useRef({live: true, busy: true});
  const [base, setBase] = useState<TextDocument | null>(null), [text, setText] = useState('');
  const [latest, setLatest] = useState<TextDocument | null>(null), [recovery, setRecovery] = useState<RecoveryText | null>(null);
  const [pending, setPending] = useState<TextRequest | null>(null), [receipt, setReceipt] = useState<TextReceipt | null>(null);
  const [busy, setBusy] = useState(true), [conflict, setConflict] = useState(false), [error, setError] = useState(''), [notice, setNotice] = useState('');
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const current = {live: true, busy: true}; session.current = current;
    void (async () => {
      try {
        const draft = await drafts.get();
        if (!current.live) return;
        if (draft) {setBase(draft.base); setText(draft.text); setPending(draft.pending); setNotice('已恢复这份文档的本机草稿。');}
        const document = await api.load(path);
        if (!current.live) return;
        if (!draft) {setBase(document); setText(document.text);}
        else if (document.revision !== draft.base.revision) {setLatest(document); if (!draft.pending) setConflict(true);}
        else setBase(document);
      } catch (cause) {if (current.live) setError(issue(cause));}
      finally {current.busy = false; if (current.live) setBusy(false);}
    })();
    return () => {current.live = false;};
  }, [api, drafts, path, attempt]);
  async function run(action: () => Promise<void>) {
    const current = session.current;
    if (current.busy) return;
    current.busy = true; setBusy(true); setError(''); setNotice('');
    try {await action();}
    catch (cause) {if (current.live) {setError(issue(cause)); if (cause instanceof ApiError && cause.status === 409) setConflict(true);}}
    finally {
      current.busy = false;
      if (current.live) {const draft = await drafts.get().catch(() => undefined); if (current.live) {if (draft !== undefined) setPending(draft?.pending || null); setBusy(false);}}
    }
  }
  function change(value: string) {
    if (!base) return;
    const current = session.current;
    setText(value); setReceipt(null); setNotice('正在保留本机草稿…');
    void drafts.update(base, value).then(() => {if (current.live) setNotice('草稿已保留在本机，尚未写回文件。');}).catch(cause => {if (current.live) {setError(issue(cause)); setNotice('本机草稿尚未保存，请保留此页并重试。');}});
  }
  async function save() {
    if (!base) return;
    const current = session.current;
    const saved = await drafts.save(base, text, pending?.request_key || Crypto.randomUUID());
    if (!current.live) return;
    setReceipt(saved); setPending(null); setConflict(false); setLatest(null); setRecovery(null);
    setNotice(saved.save_mode === 'copy' ? '已保存可编辑副本，导入原件保持不变。' : '文档已保存，修改前的内容可在恢复版本中查看。');
    onSaved();
    if (saved.path === path) {
      const fresh = await api.load(path);
      if (!current.live) return;
      setBase(fresh); setText(fresh.text);
      if (fresh.revision !== saved.revision) setNotice('这次保存已完成，文档随后又有更新；现在显示最新内容。');
    }
  }
  async function compare() {
    const current = session.current, document = await api.load(path);
    if (!current.live) return;
    setLatest(document);
    if (!pending && base && document.revision !== base.revision) setConflict(true);
    else if (base && document.revision === base.revision) setBase(document);
    setNotice('最新版已读取，你的草稿没有改动。');
  }
  async function rebase() {
    if (!latest || !conflict) return;
    const current = session.current;
    await drafts.rebase(latest, text);
    if (!current.live) return;
    setBase(latest); setPending(null); setConflict(false); setLatest(null);
    setNotice('已按最新版继续编辑，保留了你的文字。请核对后保存，保存会替换最新版全文。');
  }
  async function readRecovery(id: string) {
    const current = session.current, value = await api.recovery(path, id);
    if (current.live) setRecovery(value);
  }
  async function useRecovery() {
    if (!base || !recovery || pending) return;
    const current = session.current;
    await drafts.update(base, recovery.text);
    if (!current.live) return;
    setText(recovery.text); setRecovery(null); setNotice('恢复内容已放进草稿。核对后点击保存，才会写回文档。');
  }
  const body = {color: c.ink, fontSize: 15, lineHeight: 24}, muted = {color: c.muted, fontSize: 13, lineHeight: 21};
  const count = textSize(text);
  return <View style={{padding: 18, borderRadius: 20, backgroundColor: c.surface, borderWidth: 1, borderColor: c.line, gap: 14}}>
    <Text style={{...body, fontWeight: '600'}}>编辑文档</Text>
    <Text style={muted}>{base?.save_mode === 'copy' ? '导入原件保留；保存会创建一份可编辑副本。' : '仅修改当前文档。保存前检查版本，并保留修改前内容。'}</Text>
    {base ? <>
      {base.blocked_reason ? <Text style={muted}>{base.blocked_reason}</Text> : null}
      <TextInput multiline accessibilityLabel="文档草稿" editable={!busy && !pending} value={text} onChangeText={change} textAlignVertical="top" autoCorrect={false} maxLength={TEXT_LIMIT} style={{...body, minHeight: 260, maxHeight: 520, padding: 12, borderRadius: 12, borderWidth: 1, borderColor: c.line, backgroundColor: c.canvas}}/>
      <Text style={{...muted, color: count > TEXT_LIMIT ? c.danger : c.muted}}>{count} / {TEXT_LIMIT} 字节 · UTF-8</Text>
      {pending ? <Text style={muted}>上次保存还需核对。先取回原回执，避免重复覆盖。</Text> : null}
      <PrimaryButton label={pending ? '取回上次保存回执' : base.save_mode === 'copy' ? '确认另存可编辑副本' : '确认保存文档'} disabled={busy || conflict || receipt?.save_mode === 'copy' || (!pending && !base.editable) || count > TEXT_LIMIT || (!pending && text === base.text)} onPress={() => {void run(save);}}/>
      <PrimaryButton label="读取最新版并比较" tone="quiet" disabled={busy} onPress={() => {void run(compare);}}/>
      {latest ? <View style={{gap: 10}}><Text style={body}>文件里的最新版</Text><Text style={muted}>{comparisonSummary(latest.text, text)}</Text><ScrollView style={{maxHeight: 240, borderWidth: 1, borderColor: c.line, padding: 10}} nestedScrollEnabled><Text selectable style={body}>{latest.text || '（空文档）'}</Text></ScrollView>{conflict ? <PrimaryButton label="按最新版继续编辑，保留我的文字" tone="quiet" disabled={busy} onPress={() => {void run(rebase);}}/> : null}</View> : null}
      {base.history.length ? <View style={{gap: 10}}><Text style={body}>修改前的恢复版本</Text>{base.history.map(item => <PrimaryButton key={item.id} label={new Date(item.created_at).toLocaleString('zh-CN')} tone="quiet" disabled={busy} onPress={() => {void run(() => readRecovery(item.id));}}/>)}</View> : null}
      {recovery ? <View style={{gap: 10}}><Text style={body}>恢复版本预览</Text><ScrollView style={{maxHeight: 240}} nestedScrollEnabled><Text selectable style={body}>{recovery.text || '（空文档）'}</Text></ScrollView><PrimaryButton label="把此版本放进草稿" tone="quiet" disabled={busy || !!pending} onPress={() => {void run(useRecovery);}}/></View> : null}
    </> : !busy ? <PrimaryButton label="重新读取文档与草稿" tone="quiet" onPress={() => {setBusy(true); setAttempt(value => value + 1);}}/> : null}
    {receipt?.save_mode === 'copy' ? <><Text selectable style={muted}>{receipt.path}</Text><PrimaryButton label="打开已保存的副本" onPress={() => onOpen(receipt.path)}/></> : null}
    {busy ? <ActivityIndicator color={c.muted}/> : null}
    {error ? <Text accessibilityLiveRegion="polite" style={{...muted, color: c.danger}}>{error}</Text> : null}
    {notice ? <Text accessibilityLiveRegion="polite" style={muted}>{notice}</Text> : null}
    <PrimaryButton label={receipt ? '收起编辑' : '收起编辑，保留草稿'} tone="quiet" disabled={busy} onPress={() => {void run(async () => {const current = session.current; if (base && !pending && !receipt) await drafts.update(base, text); if (current.live) onClose();});}}/>
  </View>;
}
