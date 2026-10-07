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

type Backup = NativeDraftBackupValue;
type Props = {connection: Connection; active: boolean; snapshot: ComposerState | null;
  command: (command: ComposerCommand) => number | null; onCapture?: () => void;
  onAdd?: () => void; onSend?: () => void; inputScope?: string};

/** Real recorder + the same native input surface as the design preview.
 * Only a persisted WebView draft receipt consumes a transcript. Sending remains
 * an explicit gesture handled by the existing conversation/queue implementation.
 */
export default function VoiceComposer({connection, active, snapshot, command, onCapture, onAdd, onSend, inputScope = ''}: Props) {
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
    const scope = snapshot.pageId + ':' + snapshot.contextKey;
    const changed = context.current !== scope;
    if (changed) {context.current = scope; pending.current = 0; sendSeq.current = 0; setSending(false);}
    if (snapshot.ackSeq >= pending.current || changed) {
      textRef.current = snapshot.text; setText(snapshot.text);
      // This effect consumes an external WebView draft receipt.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      if (snapshot.text) setKeyboard(true);
      if (snapshot.ackSeq >= sendSeq.current) setSending(snapshot.sending);
    }
    if (snapshot.error && !snapshot.sending) setSending(false);
    if (snapshot.ackVoiceId) void voiceAck.current(snapshot.ackVoiceId);
  }, [snapshot]);
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
    if (!textRef.current.trim() || sending || !snapshot?.ready) return;
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
    {snapshot?.contextLabel ? <Text style={s.context} numberOfLines={2}>{snapshot.contextLabel}</Text> : null}
    <IntentComposer active={active && !!snapshot?.ready} offline={false} keyboard={keyboard} text={text}
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
  context:{fontSize:12,lineHeight:18,color:c.accentInk,paddingHorizontal:10,paddingBottom:8},
  retry:{alignSelf:'center',minHeight:44,justifyContent:'center',paddingHorizontal:14},
  retryText:{fontSize:13,lineHeight:20,color:c.accentInk},
});
