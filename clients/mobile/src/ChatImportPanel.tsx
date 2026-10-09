import React, {useEffect, useLayoutEffect, useRef, useState} from 'react';
import {ActivityIndicator, StyleSheet, Text, View} from 'react-native';
import * as DocumentPicker from 'expo-document-picker';
import {Check, FileText, MessageCircle, RefreshCw, Trash2, Upload} from 'lucide-react-native';
import {ApiError, scopeOf, type Connection} from './core';
import {storage} from './storage';
import {OnboardingActivity} from './onboarding-client';
import {serviceFetch} from './transport';
import {accountWorkAllowed, registerAccountWork} from './account-work';
import {chatImportWorkAllowed, discardChatPickerCopy, readChatImportFile} from './chat-import-native';
import {ChatImportApi, ChatImportJournal, type ChatImportDetail, type ChatImportDraft, type ChatImportPending, type ChatImportSummary} from './chat-import-client';
import {shareIntakeQueue} from './share-intake-native';
import {useAppTheme, useThemedStyles, type AppColors} from './app-theme';
import {PrimaryButton, TactilePressable} from './experience/primitives';

type Props = {connection: Connection; identityName: string; shareId?: string; isCurrent: () => boolean; onShareConsumed?: () => void};
export function ChatImportPanel(props: Props) {return <ChatImportContent key={scopeOf(props.connection) + '|' + (props.connection.session?.credentialId || '') + '|' + (props.connection.session?.expiresAt || props.connection.development?.expiresAt || '') + '|' + (props.connection.session?.accessToken ? 'signed-in' : 'local') + '|' + (props.shareId || '')} {...props}/>;}
function ChatImportContent({connection, identityName, shareId, isCurrent, onShareConsumed}: Props) {
  const {colors: c} = useAppTheme(), s = useThemedStyles(styles);
  const lock = useRef(false), [activity] = useState(() => new OnboardingActivity(isCurrent));
  useLayoutEffect(() => {activity.mount(); activity.update(isCurrent); return () => activity.stop();}, [activity, isCurrent]);
  const active = () => activity.active() && accountWorkAllowed(connection) && chatImportWorkAllowed(connection);
  const [api] = useState(() => new ChatImportApi(connection, serviceFetch, active));
  const [journal] = useState(() => new ChatImportJournal(storage, api));
  const [draft, setDraft] = useState<ChatImportDraft | null>(null), [pending, setPending] = useState<ChatImportPending | null>(null), [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [notice, setNotice] = useState(''), [listError, setListError] = useState('');
  const [batches, setBatches] = useState<ChatImportSummary[]>([]), [cursor, setCursor] = useState<string | null>(null), [deleting, setDeleting] = useState<string | null>(null), [messageLimit, setMessageLimit] = useState(20), [missing, setMissing] = useState(false);
  const [selectedBatch, setSelectedBatch] = useState<string | null>(null), [batchDetail, setBatchDetail] = useState<ChatImportDetail | null>(null), [detailLimit, setDetailLimit] = useState(20);
  async function refresh(more = false) {
    try {const page = await api.list(more ? cursor || undefined : undefined); if (active()) {setBatches(previous => more ? [...previous, ...page.items.filter(item => !previous.some(old => old.import_id === item.import_id))] : page.items); setCursor(page.next_cursor); setListError('');}}
    catch (cause) {if (active()) setListError(cause instanceof Error ? cause.message : '暂时无法读取已导入聊天。');}
  }
  async function reloadDraft() {const [d, p] = await Promise.all([journal.draft(), journal.pending()]); if (active()) {setDraft(d); setPending(p);}}
  async function openShared(id: string) {
    const entry = await shareIntakeQueue.claimChatImport(id, scopeOf(connection));
    if (!active()) return;
    if (entry.files.length !== 1 || !/\.(txt|zip)$/i.test(entry.files[0].path)) throw new Error('每次请选择一份原始聊天 ZIP 或 TXT。其他附件请保留在原文件中。');
    const file = entry.files[0], parsed = await readChatImportFile(file.uri, file.path, active);
    parsed.shareId = id; await journal.retain(parsed); if (active()) {setDraft(parsed); setMessageLimit(20);}
  }
  useEffect(() => {
    activity.mount();
    const unregister = registerAccountWork(connection, async () => {activity.stop();});
    void (async () => {
      try {
        const [d, p] = await Promise.all([journal.draft(), journal.pending()]);
        if (!active()) return; setDraft(d); setPending(p);
        if (shareId && !d && !p) {lock.current = true; setBusy(true); await openShared(shareId);}
        else if (shareId && (d?.shareId || p?.shareId) !== shareId) setNotice('先处理手机上保留的这批聊天；新的分享仍在收件箱。');
      } catch (cause) {if (active()) setError(cause instanceof Error ? cause.message : '本机聊天预览暂时无法读取。');}
      finally {lock.current = false; if (active()) {setBusy(false); setReady(true);}}
      if (active()) await refresh();
    })();
    return () => {activity.stop(); unregister();};
    // The wrapper remounts for every account, credential and shared item.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  async function run(work: () => Promise<void>) {
    if (lock.current || !active()) return; lock.current = true; setBusy(true); setError(''); setNotice('');
    try {await work();}
    catch (cause) {if (active()) {setError(cause instanceof Error ? cause.message : '暂时未完成，请重试。'); setMissing(cause instanceof ApiError && cause.status === 410);}}
    finally {lock.current = false; if (active()) {setBusy(false); await reloadDraft().catch(() => {});}}
  }
  async function pick() {
    const result = await DocumentPicker.getDocumentAsync({type: ['application/zip', 'application/x-zip-compressed', 'text/plain'], multiple: false, copyToCacheDirectory: true});
    if (result.canceled) return;
    const file = result.assets[0];
    try {if (!active()) return; const parsed = await readChatImportFile(file.uri, file.name, active); await journal.retain(parsed); if (active()) {setDraft(parsed); setMessageLimit(20);}}
    finally {discardChatPickerCopy(file.uri);}
  }
  async function chooseAuthor(selfAuthor: string | null) {if (!draft) return; const next = {...draft, selfAuthor}; await journal.retain(next); if (active()) setDraft(next);}
  async function confirm() {
    const id = pending?.shareId || draft?.shareId; if (id) await shareIntakeQueue.beginChatImport(id, scopeOf(connection));
    const result = await journal.confirm();
    if (result.shareId) await shareIntakeQueue.completeChatImport(result.shareId, scopeOf(connection));
    await journal.finish();
    if (active()) {setDraft(null); setPending(null); setNotice(result.receipt.status === 'deleted' ? '这批聊天此前已删除，没有重新导入。' : '选定聊天已导入当前身份。作者原话会保留来源，不会直接当作你的偏好。'); await refresh(); onShareConsumed?.();}
  }
  async function discard() {
    const id = draft?.shareId; await journal.discard(); if (id) await shareIntakeQueue.cancel(id);
    if (active()) {setDraft(null); setNotice('已移除本机聊天预览，原文件不受影响。'); onShareConsumed?.();}
  }
  const duplicate = draft && batches.find(batch => batch.source_sha256 === draft.sourceHash);
  return <View style={s.panel}>
    <View style={s.row}><MessageCircle color={c.accent} size={28}/><Text style={s.title}>导入选定聊天</Text></View>
    <Text style={s.lead}>把想让 Pajio 了解的那一段带过来。先在手机预览，确认后才导入「{identityName}」。</Text>
    <View style={s.card}><Text style={s.heading}>从微信带过来</Text><Text style={s.copy}>如果微信提供“转发到其他应用”，可多选消息、合并转发，再分享给 Pajio。也可以选一份已保存的聊天 ZIP 或 TXT。</Text><Text style={s.muted}>不同微信版本的入口可能不同。这里仅支持带作者、日期和时间的选定聊天文件；不会读取整段聊天历史。文件最多 15 MB、500 条消息。</Text></View>
    {(!ready || busy) && <View style={s.row}><ActivityIndicator color={c.accent}/><Text style={s.muted}>{!ready ? '读取本机预览…' : '正在处理这批聊天…'}</Text></View>}
    {error ? <Text accessibilityLiveRegion="polite" style={s.error}>{error}</Text> : null}
    {notice ? <Text accessibilityLiveRegion="polite" style={s.copy}>{notice}</Text> : null}
    {!draft && !pending ? <PrimaryButton label="选择聊天 ZIP 或 TXT" leading={<Upload size={19} color={c.canvas}/>} disabled={!ready || busy} onPress={() => {void run(pick);}}/> : null}
    {draft ? <View style={s.card}>
      <View style={s.row}><FileText size={23} color={c.accent}/><Text style={s.heading}>{draft.preview.title}</Text></View>
      <Text style={s.copy}>{draft.preview.messages.length} 条消息 · {draft.preview.authors.length} 位作者</Text>
      <Text style={s.muted}>{draft.preview.start} — {draft.preview.end}{'\n'}时间照原文件展示；未推断时区。</Text>
      <Text style={s.muted}>图片、语音、视频及文件附件均未导入，Pajio 不会看到或听到它们的内容。{draft.preview.attachments.length ? `ZIP 另有 ${draft.preview.attachments.length} 个附件，仅在本机检查文件目录。` : ''}</Text>
      {draft.preview.attachments.slice(0, 8).map((item, i) => <Text key={i} style={s.muted}>未导入 · {item.name}</Text>)}
      <Text style={s.heading}>哪一位是你？</Text><Text style={s.muted}>可不选。即使选了，也会区分你的原话、转述和其他人的观点。</Text>
      <View accessibilityRole="radiogroup" style={s.options}>{[null, ...draft.preview.authors].map(author => <TactilePressable key={author ?? '__unknown__'} accessibilityRole="radio" accessibilityState={{checked: draft.selfAuthor === author}} accessibilityLabel={author || '暂不指定本人'} disabled={busy || !!pending} onPress={() => {void run(() => chooseAuthor(author));}} style={[s.option, draft.selfAuthor === author && {borderColor: c.accent}]}><Text style={s.copy}>{author || '暂不指定'}</Text>{draft.selfAuthor === author ? <Check size={16} color={c.accent}/> : null}</TactilePressable>)}</View>
      <Text style={s.heading}>消息预览</Text>
      {draft.preview.messages.slice(0, messageLimit).map(message => <View key={message.id} style={s.message}><Text style={s.author}>{message.author}</Text><Text style={s.muted}>{message.sent_at}</Text><Text selectable style={s.copy}>{message.text || '（原文件未提供文字内容）'}</Text></View>)}
      {messageLimit < draft.preview.messages.length ? <PrimaryButton label={`继续预览（剩余 ${draft.preview.messages.length - messageLimit} 条）`} tone="quiet" disabled={busy} onPress={() => setMessageLimit(n => n + 20)}/> : null}
      {duplicate ? <Text style={s.error}>这份文件已在当前列表中导入过。请先查看下方批次，避免重复保存。</Text> : null}
      <Text style={s.muted}>确认后会将以上文字发送至当前 Pajio 服务，作为可删除的聊天来源。不会自动发消息或执行文件中的指令。</Text>
    </View> : null}
    {pending ? <Text style={s.muted}>上次导入结果尚需核对。重试会查询同一编号，服务未收到时才补交原请求。{!pending.request && !draft ? '本机文字已清除，仅保留结果查询编号。' : ''}</Text> : null}
    {(draft || pending) ? <PrimaryButton label={pending ? '重试并核对导入' : `确认导入 ${draft!.preview.messages.length} 条消息`} disabled={busy || !ready || !!duplicate && !pending} loading={busy} onPress={() => {void run(confirm);}}/> : null}
    {draft && !pending ? <PrimaryButton label="移除本机预览" tone="quiet" disabled={busy} onPress={() => {void run(discard);}}/> : null}
    {missing && pending && !pending.request ? <PrimaryButton label="清除空请求，重新选择文件" tone="quiet" disabled={busy} onPress={() => {void run(async () => {await journal.clearMissing(); if (active()) {setMissing(false); setPending(null);}});}}/> : null}
    <View style={s.row}><Text style={[s.heading, s.grow]}>已导入的聊天</Text><TactilePressable accessibilityLabel="刷新已导入聊天" style={s.circle} disabled={busy} onPress={() => {void run(() => refresh());}}><RefreshCw size={20} color={c.ink}/></TactilePressable></View>
    {listError ? <Text style={s.error}>{listError}</Text> : null}
    {!batches.length && !listError ? <Text style={s.muted}>当前身份还没有已导入的聊天。</Text> : null}
    {batches.map(batch => <View style={s.card} key={batch.import_id}>
      <TactilePressable accessibilityLabel={`查看导入批次 ${batch.conversation_title}`} disabled={busy} onPress={() => {if (selectedBatch === batch.import_id) {setSelectedBatch(null); setBatchDetail(null);} else void run(async () => {const data = await api.detail(batch.import_id); if (active()) {setBatchDetail(data); setSelectedBatch(batch.import_id); setDetailLimit(20);}});}}><Text style={s.heading}>{batch.conversation_title}</Text><Text style={s.muted}>{batch.message_count} 条消息 · {batch.created_at}</Text></TactilePressable>
      {selectedBatch === batch.import_id ? <><Text style={s.copy}>作者：{batch.authors.join('、')}{'\n'}本人：{batch.self_author || '未指定'}</Text><Text selectable style={s.muted}>来源批次：{batch.import_id}{'\n'}附件内容未导入。</Text>{batchDetail?.import_id === batch.import_id ? <>{batchDetail.messages.slice(0, detailLimit).map(message => <View style={s.message} key={message.id}><Text style={s.author}>{message.author}</Text><Text style={s.muted}>{message.sent_at}</Text><Text selectable style={s.copy}>{message.text || '（无文字内容）'}</Text><Text selectable style={s.muted}>来源消息 · {message.id}</Text></View>)}{detailLimit < batchDetail.messages.length ? <PrimaryButton label="继续查看消息" tone="quiet" onPress={() => setDetailLimit(n => n + 20)}/> : null}</> : null}</> : null}
      {deleting === batch.import_id ? <><Text style={s.copy}>移除这批来源、消息和来源索引。已生成的对话或结果可能仍含引用，可另行删除对应内容。</Text><PrimaryButton label="确认移除这批聊天" tone="danger" disabled={busy} onPress={() => {void run(async () => {await api.remove(batch.import_id); if (active()) {setDeleting(null); setNotice('已移除这批聊天来源。'); await refresh();}});}}/><PrimaryButton label="保留" tone="quiet" disabled={busy} onPress={() => setDeleting(null)}/></> : <TactilePressable accessibilityLabel={`移除聊天 ${batch.conversation_title}`} disabled={busy} style={s.rowButton} onPress={() => setDeleting(batch.import_id)}><Trash2 size={17} color={c.muted}/><Text style={s.muted}>移除这批聊天</Text></TactilePressable>}
    </View>)}
    {cursor ? <PrimaryButton label="加载更早的导入" tone="quiet" disabled={busy} onPress={() => {void run(() => refresh(true));}}/> : null}
  </View>;
}
const styles = (c: AppColors) => StyleSheet.create({panel: {gap: 18}, row: {flexDirection: 'row', alignItems: 'center', gap: 12}, title: {fontSize: 27, fontWeight: '600', color: c.ink}, lead: {fontSize: 16, lineHeight: 26, color: c.muted}, heading: {fontSize: 18, lineHeight: 25, color: c.ink, fontWeight: '600'}, card: {padding: 20, gap: 14, backgroundColor: c.surface, borderRadius: 24, borderWidth: 1, borderColor: c.line}, copy: {fontSize: 15, lineHeight: 24, color: c.ink}, muted: {fontSize: 13, lineHeight: 21, color: c.muted}, error: {fontSize: 14, lineHeight: 23, color: c.danger}, options: {gap: 8}, option: {padding: 12, borderWidth: 1, borderColor: c.line, borderRadius: 12, flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center'}, message: {paddingVertical: 12, gap: 5, borderBottomWidth: 1, borderColor: c.line}, author: {fontSize: 14, color: c.ink, fontWeight: '600'}, grow: {flex: 1}, circle: {minHeight: 44, minWidth: 44, justifyContent: 'center', alignItems: 'center'}, rowButton: {flexDirection: 'row', gap: 8, minHeight: 44, alignItems: 'center'}});
