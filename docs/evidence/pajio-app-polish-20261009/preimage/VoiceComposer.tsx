import {useThemedStyles, type AppColors} from './app-theme';
import {useEffect, useLayoutEffect, useMemo, useRef, useState} from 'react';
import {StyleSheet, Text, View} from 'react-native';
import type {Connection} from './core';
import {scopeOf} from './core';
import {storage} from './storage';
import * as Crypto from 'expo-crypto';
import {NativeDraftBackup, type NativeDraftBackupValue} from './native-draft-backup';
import {useVoiceInput} from './useVoiceInput';
import type {ComposerCommand, ComposerState} from './native-composer';
import {IntentComposer} from './experience/IntentComposer';
import {TactilePressable} from './experience/primitives';
import {canSubmitConversation} from './conversation-presentation';
import {SharedChatDrafts, observeSharedChatDrafts, type SharedChatDraft} from './share-chat-drafts';

type Backup = NativeDraftBackupValue;
type Props = {connection: Connection; active: boolean; offline?: boolean; snapshot: ComposerState | null;
  command: (command: ComposerCommand) => number | null; onCapture?: () => void;
  onAdd?: () => void; onSend?: () => void; inputScope?: string};

/** Real recorder + the same native input surface as the design preview.
 * Only a persisted WebView draft receipt consumes a transcript. Sending remains
 * an explicit gesture handled by the existing conversation/queue implementation.
 */
export default function VoiceComposer({connection, active, offline = false, snapshot, command, onCapture, onAdd, onSend, inputScope = ''}: Props) {
  const s = useThemedStyles(makeStyles);

  const [text, setText] = useState(''), [keyboard, setKeyboard] = useState(false);
  const [recovery, setRecovery] = useState<Backup | null>(null), [message, setMessage] = useState('');
  const [sending, setSending] = useState(false);
  const latest = useRef({snapshot, command});
  useLayoutEffect(() => {latest.current = {snapshot, command};});
  const pending = useRef(0), sendSeq = useRef(0), context = useRef('');
  const textRef = useRef('');
  const key = 'native-conversation-draft:' + scopeOf(connection);
  const backup = useMemo(() => new NativeDraftBackup(storage, key, () => Crypto.randomUUID()), [key]);
  const sharedDrafts = useMemo(() => new SharedChatDrafts(storage), []);
  const scope = scopeOf(connection);
  const [shared, setShared] = useState<SharedChatDraft[]>([]);
  const [shareSelected, setShareSelected] = useState(''), [shareRemove, setShareRemove] = useState('');
  const shareItem = shared.find(item => item.id === shareSelected) || shared[0];
  const [appendingShare, setAppendingShare] = useState(false);
  const shareBusy = useRef(false), mounted = useRef(true);
  useEffect(() => {
    let live = true; mounted.current = true;
    const reload = () => {void sharedDrafts.list(scope).then(items => {if (live) setShared(items);}).catch(() => {if (live) setMessage('分享文字暂时无法读取，请重新打开聊天。');});};
    reload(); const stop = observeSharedChatDrafts(reload);
    return () => {live = false; mounted.current = false; stop();};
  }, [scope, sharedDrafts]);
  async function appendShare(item: SharedChatDraft) {
    if (shareBusy.current || !active) return;
    const current = latest.current.snapshot;
    if (!current?.ready || current.sending) return;
    shareBusy.current = true; setAppendingShare(true);
    try {
      const action = await sharedDrafts.append(scope, item.id, current.contextKey, current.text);
      const next = latest.current.snapshot;
      if (!mounted.current || next?.pageId !== current.pageId || next.contextKey !== current.contextKey) return;
      const seq = latest.current.command(action);
      if (seq === null) {setMessage('对话暂时未就绪，分享文字仍在本机。'); return;}
      pending.current = seq; setKeyboard(true); setMessage('');
    } catch (error) {if (mounted.current) setMessage(error instanceof Error ? error.message : '分享文字仍在本机，请重试。');}
    finally {shareBusy.current = false; if (mounted.current) setAppendingShare(false);}
  }
  const pendingBackup = useRef<{pageId: string; contextKey: string; text: string; seq: number; saved: Promise<Backup>} | null>(null);
  const submitted = useRef<{pageId: string; contextKey: string; text: string; seq: number} | null>(null);
  const voice = useVoiceInput({connection, active: active && !!snapshot?.ready, onText: result => {
    if (result.identity !== connection.identity || result.scope !== scopeOf(connection)) return;
    const current = latest.current.snapshot;
    if (!current?.ready) return;
    const seq = latest.current.command({kind: 'append', text: result.text, voiceId: result.id});
    if (seq !== null) {pending.current = seq; setKeyboard(true);}
  }});
  const voiceAck = useRef(voice.ack);
  const [voiceNotice, setVoiceNotice] = useState({message: voice.message, phase: voice.phase, dismissed: false});
  if (voiceNotice.message !== voice.message || voiceNotice.phase !== voice.phase) {
    setVoiceNotice({message: voice.message, phase: voice.phase, dismissed: false});
  }
  useEffect(() => {
    if (voiceNotice.phase !== 'idle' || !/^已取消/.test(voiceNotice.message)) return;
    const timer = setTimeout(() => setVoiceNotice(value => ({...value, dismissed: true})), 2300);
    return () => clearTimeout(timer);
  }, [voiceNotice.message, voiceNotice.phase]);
  useLayoutEffect(() => {voiceAck.current = voice.ack;});
  useEffect(() => {
    let live = true;
    backup.load().then(value => {if (live && value?.text) setRecovery(value);})
      .catch(() => {if (live) setMessage('本机草稿暂时无法读取。');});
    return () => {live = false;};
  }, [backup]);
  useEffect(() => {
    if (!snapshot) return;
    const pageContext = snapshot.pageId + ':' + snapshot.contextKey;
    const changed = context.current !== pageContext;
    if (changed) {context.current = pageContext; pending.current = 0; sendSeq.current = 0; setSending(false);}
    if (snapshot.ackSeq >= pending.current || changed) {
      textRef.current = snapshot.text; setText(snapshot.text);
      // This effect consumes an external WebView draft receipt.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      if (snapshot.text) setKeyboard(true);
      if (snapshot.ackSeq >= sendSeq.current) setSending(snapshot.sending);
    }
    if (snapshot.error && !snapshot.sending) setSending(false);
    if (snapshot.ackVoiceId) {
      void voiceAck.current(snapshot.ackVoiceId);
      void sharedDrafts.acknowledge(scope, snapshot.ackVoiceId, snapshot.contextKey).catch(() => setMessage('分享回执暂未保存，重试会核对同一份文字。'));
    }
  }, [snapshot, scope, sharedDrafts]);
  function edit(value: string) {
    if (value.length > 12000) {setMessage('一次最多 12000 字，可以分两次交代。'); return;}
    textRef.current = value; setText(value); setMessage('');
    const current = latest.current.snapshot;
    if (!current?.ready) return;
    const saved = backup.save({text: value, contextKey: current.contextKey});
    saved.catch(() => setMessage('本机草稿暂时没保存好，请保留当前页面。'));
    const seq = command({kind: 'change', text: value});
    pendingBackup.current = {pageId: current.pageId, contextKey: current.contextKey, text: value, seq: seq ?? Number.MAX_SAFE_INTEGER, saved};
    if (seq !== null) pending.current = seq;
  }
  function send() {
    if (!snapshot || !canSubmitConversation({text: textRef.current, sending, offline, ready: snapshot.ready})) return;
    const seq = command({kind: 'send', text: textRef.current});
    if (seq !== null) {pending.current = seq; sendSeq.current = seq; submitted.current = {pageId: snapshot.pageId, contextKey: snapshot.contextKey, text: textRef.current, seq}; setSending(true); onSend?.();}
  }
  // A receipt clears only the exact backup revision it acknowledges. Old page
  // completions cannot erase newer input, including after a component remount.
  useEffect(() => {
    if (!snapshot?.ready || snapshot.error) return;
    const edit = pendingBackup.current, sent = submitted.current;
    if (!edit || edit.pageId !== snapshot.pageId || edit.contextKey !== snapshot.contextKey || snapshot.ackSeq < edit.seq) return;
    const draftReceived = snapshot.text === edit.text;
    const sendReceived = sent && sent.pageId === snapshot.pageId && sent.contextKey === snapshot.contextKey && sent.text === edit.text && snapshot.ackSeq >= sent.seq && !snapshot.sending && !snapshot.text;
    if (!draftReceived && !sendReceived) return;
    let live = true;
    void edit.saved.then(value => backup.clear(value.id).then(cleared => {
      if (live && cleared) setRecovery(current => current?.id === value.id ? null : current);
    })).catch(() => {if (live) setMessage('本机草稿暂时没保存好，请保留当前页面。');});
    return () => {live = false;};
  }, [backup, snapshot]);
  const notice = message || snapshot?.error || (voiceNotice.phase === 'idle' && !voiceNotice.dismissed ? voiceNotice.message : '');
  const canRecover = recovery && snapshot?.contextKey === recovery.contextKey && recovery.text !== text;
  return <View style={s.wrap}>
    {shareItem ? <View style={s.shared}>
      <Text style={s.context}>来自系统分享 · {shared.length} 份待用文字</Text>
      <Text numberOfLines={2} style={s.sharedText}>{shareItem.text}</Text>
      <TactilePressable disabled={appendingShare || !active || !snapshot?.ready || !!snapshot.sending} onPress={() => {void appendShare(shareItem);}} style={s.retry}>
        <Text style={s.retryText}>{appendingShare ? '正在保存…' : shareItem.state === 'appending' ? '核对并带入草稿' : '带入当前草稿'}</Text>
      </TactilePressable>
      {shared.length > 1 ? <TactilePressable disabled={appendingShare} onPress={() => {setShareSelected(shared[(shared.findIndex(item => item.id === shareItem.id) + 1) % shared.length].id); setShareRemove('');}} style={s.retry}><Text style={s.retryText}>查看下一份分享</Text></TactilePressable> : null}
      {shareRemove === shareItem.id ? <>
        <Text style={s.sharedText}>只移除这份待用副本；已经带入输入框或发送的文字会保留。</Text>
        <TactilePressable disabled={appendingShare} onPress={() => {void sharedDrafts.dismiss(scope, shareItem.id).then(() => setShareRemove('')).catch(() => setMessage('待用副本暂未移除，请重试。'));}} style={s.retry}><Text style={s.retryText}>确认移除待用副本</Text></TactilePressable>
        <TactilePressable disabled={appendingShare} onPress={() => setShareRemove('')} style={s.retry}><Text style={s.retryText}>保留</Text></TactilePressable>
      </> : <TactilePressable disabled={appendingShare} onPress={() => setShareRemove(shareItem.id)} style={s.retry}><Text style={s.retryText}>移除待用副本</Text></TactilePressable>}
    </View> : null}
    {offline ? <Text accessibilityLiveRegion="polite" style={s.offline}>当前离线，可先输入；恢复连接后再发送。</Text> : null}
    {snapshot?.contextLabel ? <Text style={s.context} numberOfLines={2}>{snapshot.contextLabel}</Text> : null}
    <IntentComposer active={active && !!snapshot?.ready} offline={offline} keyboard={keyboard} text={text}
      scopeKey={(snapshot ? snapshot.pageId + ':' + snapshot.contextKey : 'loading') + ':' + inputScope}
      voice={voice} notice={notice} sending={sending || !!snapshot?.sending} mediaActions={!!onCapture}
      onKeyboard={setKeyboard} onText={edit} onAppend={()=>{}} onSend={send}
      onEngage={()=>{}} onCamera={()=>onCapture?.()} onAdd={()=>onAdd?.()}/>
    {voice.draft && !voice.draft.acknowledged && voice.phase === 'idle' ? <TactilePressable onPress={()=>{void voice.retry();}} style={s.retry}>
      <Text style={s.retryText}>{voice.draft.text ? '带入已识别文字' : '继续识别录音'}</Text>
    </TactilePressable> : null}
    {canRecover ? <TactilePressable onPress={()=>{edit(text ? text+'\n'+recovery.text : recovery.text);setKeyboard(true);setRecovery(null);}} style={s.retry}>
      <Text style={s.retryText}>恢复本机未确认的草稿</Text>
    </TactilePressable> : null}
  </View>;
}
const makeStyles = (c: AppColors) => StyleSheet.create({
  wrap:{backgroundColor:'transparent'},
  context:{fontSize:13,lineHeight:20,color:c.accentInk,paddingHorizontal:10,paddingBottom:8},
  offline:{fontSize:13,lineHeight:20,color:c.muted,paddingHorizontal:10,paddingBottom:8},
  retry:{alignSelf:'center',minHeight:44,justifyContent:'center',paddingHorizontal:14},
  retryText:{fontSize:13,lineHeight:20,color:c.accentInk},
  shared:{padding:12,marginBottom:8,borderRadius:16,backgroundColor:c.soft,gap:6},
  sharedText:{fontSize:14,lineHeight:21,color:c.ink},
});
