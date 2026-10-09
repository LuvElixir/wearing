import {useCallback, useEffect, useRef, useState} from 'react';
import {ActivityIndicator, AppState, Image, Linking, StyleSheet, Text, View} from 'react-native';
import {FileText, Inbox, RefreshCw} from 'lucide-react-native';
import {Connection, scopeOf} from './core';
import {AppColors, useAppTheme, useThemedStyles} from './app-theme';
import {PrimaryButton, TactilePressable} from './experience/primitives';
import {ShareAction, ShareEntry, ShareHandler} from './share-intake-model';
import {receiveSharedIntake, shareIntakeAvailable, shareIntakeQueue} from './share-intake-native';
import {sharedBookmark} from './share-bookmarks';

export function useShareIntake(connection: Connection) {
  const scope = scopeOf(connection), [items, setItems] = useState<ShareEntry[]>([]), [error, setError] = useState(''), [loading, setLoading] = useState(false);
  const active = useRef(false), generation = useRef(0);
  const refresh = useCallback(async () => {
    const token = ++generation.current;
    if (active.current) setLoading(true);
    let failure = '';
    try {await receiveSharedIntake();} catch (error) {failure = error instanceof Error ? error.message : '分享暂时无法读取。';}
    try {
      const entries = await shareIntakeQueue.list(scope);
      if (active.current && generation.current === token) {setItems(entries); setError(failure);}
    } catch {if (active.current && generation.current === token) setError('本机分享队列暂时无法读取，请重试。');}
    finally {if (active.current && generation.current === token) setLoading(false);}
  }, [scope]);
  useEffect(() => {
    active.current = true;
    const sequence = generation;
    void Promise.resolve().then(() => {if (active.current) return refresh();});
    const app = AppState.addEventListener('change', state => {if (state === 'active') void refresh();});
    const links = Linking.addEventListener('url', ({url}) => {if (/^pajio:\/\/expo-sharing(?:[/?]|$)/.test(url)) void refresh();});
    return () => {active.current = false; sequence.current++; app.remove(); links.remove();};
  }, [refresh]);
  return {items, error, loading, refresh, available: shareIntakeAvailable()};
}

export type ShareIntakePanelProps = {connection: Connection; identityName?: string; onChooseIdentity?: () => void; onCapture: ShareHandler; onDraft: ShareHandler; onBookmark?: ShareHandler; onChanged?: () => void; onChatImport?: (id: string) => void};
function ShareIntakeContent({connection, identityName, onChooseIdentity, onCapture, onDraft, onBookmark, onChanged, onChatImport}: ShareIntakePanelProps) {
  const {colors: c} = useAppTheme(), s = useThemedStyles(styles), intake = useShareIntake(connection), scope = scopeOf(connection);
  const [selected, setSelected] = useState<string | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState(''), [notice, setNotice] = useState('');
  const alive = useRef(true), operation = useRef(false);
  useEffect(() => {alive.current = true; return () => {alive.current = false;};}, []);
  const entry = intake.items.find(item => item.id === selected);
  const archive = entry?.files.some(file => /\.zip$/i.test(file.path));
  const chatFile = entry?.files.length === 1 && /\.(txt|zip)$/i.test(entry.files[0].path);
  async function run(id: string, action: ShareAction | 'cancel') {
    if (operation.current) return;
    operation.current = true; setBusy(true); setError(''); setNotice('');
    try {
      if (action === 'cancel') await shareIntakeQueue.cancel(id);
      else {const handler = action === 'capture' ? onCapture : action === 'bookmark' ? onBookmark : onDraft; if (!handler) throw new Error('请更新 App 后重试收藏。'); await shareIntakeQueue.submit(id, scope, action, handler);}
      if (!alive.current) return;
      setSelected(null); setNotice(action === 'cancel' ? '已移除这份分享副本，原文件不受影响。' : action === 'draft' ? '已保存在聊天的待用文字中，可追加到现有草稿。' : '已放入当前身份的记录同步队列。');
      await intake.refresh(); onChanged?.();
    } catch (error) {if (alive.current) setError(error instanceof Error ? error.message : '尚未确认处理结果，请重试。');}
    finally {operation.current = false; if (alive.current) setBusy(false);}
  }
  return <View style={s.panel}>
    <View style={s.row}><View style={s.grow}><Text style={s.title}>分享收件箱</Text><Text style={s.muted}>从其他 App 分享来的内容，先在这里看看。</Text></View><TactilePressable disabled={busy || intake.loading} accessibilityLabel="刷新分享收件箱" onPress={() => {void intake.refresh();}} style={s.refresh}><RefreshCw color={c.ink} size={20}/></TactilePressable></View>
    <View style={s.card}><Text style={s.label}>导入身份</Text><Text style={s.heading}>{identityName || connection.identity}</Text><Text style={s.muted}>确认前只保存在手机，不会发送给助手。</Text>{onChooseIdentity ? <PrimaryButton label="选择其他身份" tone="quiet" disabled={busy || entry?.state === 'bound'} onPress={onChooseIdentity}/> : null}</View>
    {intake.loading ? <ActivityIndicator color={c.accent}/> : null}
    {error || intake.error ? <Text accessibilityLiveRegion="polite" style={s.error}>{error || intake.error}</Text> : null}
    {notice ? <Text accessibilityLiveRegion="polite" style={s.muted}>{notice}</Text> : null}
    {!intake.available ? <Text style={s.muted}>系统分享入口需要安装包含分享扩展的新版 App。</Text> : null}
    {entry ? <View style={s.card}>
      <Text style={s.heading}>确认这份内容</Text>
      {entry.text ? <Text selectable style={s.copy}>{entry.text}</Text> : null}
      {entry.files.map(file => <View key={file.id} style={s.attachment}>{file.mime.startsWith('image/') ? <Image source={{uri: file.uri}} resizeMode="contain" style={s.image} accessibilityLabel={file.name}/> : <FileText color={c.accent} size={30}/>}<Text style={s.copy}>{file.name}</Text><Text style={s.muted}>{(file.size / 1024 / 1024).toFixed(2)} MB · {file.mime}</Text></View>)}
      {entry.state === 'bound' ? <Text style={s.muted}>上次保存结果尚需核对。重试会使用同一个编号和身份，不会另建一份。</Text> : null}
      {chatFile && onChatImport && (!entry.action || entry.action === 'chat-import') ? <PrimaryButton label="预览为微信选定聊天" disabled={busy} onPress={() => onChatImport(entry.id)}/> : null}
      {archive ? <Text style={s.muted}>聊天 ZIP 需要先预览作者、时间和消息，再确认导入。附件不会作为普通记录直接上传。</Text> : null}
      {!archive && (!entry.action || entry.action === 'capture') ? <PrimaryButton label={entry.state === 'bound' ? '重试并核对导入' : '确认导入当前身份'} loading={busy} disabled={busy} onPress={() => {void run(entry.id, 'capture');}}/> : null}
      {!entry.files.length && (!entry.action || entry.action === 'draft') ? <PrimaryButton label={entry.state === 'bound' ? '重试并核对聊天草稿' : '带入聊天草稿'} tone="quiet" disabled={busy} onPress={() => {void run(entry.id, 'draft');}}/> : null}
      {onBookmark && !entry.files.length && sharedBookmark(entry.text) && (!entry.action || entry.action === 'bookmark') ? <PrimaryButton label={entry.state === 'bound' ? '重试并核对收藏' : '收藏链接'} tone="quiet" disabled={busy} onPress={() => {void run(entry.id, 'bookmark');}}/> : null}
      <PrimaryButton label="稍后处理" tone="quiet" disabled={busy} onPress={() => setSelected(null)}/>
      {entry.state === 'pending' ? <PrimaryButton label="移除这份分享" tone="danger" disabled={busy} onPress={() => {void run(entry.id, 'cancel');}}/> : null}
    </View> : intake.items.length ? intake.items.map(item => <TactilePressable key={item.id} disabled={busy} accessibilityLabel={`预览分享 ${item.text.slice(0, 40) || item.files[0]?.name}`} onPress={() => {setSelected(item.id); setNotice(''); setError('');}} style={s.card}><Text numberOfLines={3} style={s.copy}>{item.text || item.files[0]?.name}</Text><Text style={s.muted}>{item.files.length ? `${item.files.length} 个附件 · ` : ''}{item.state === 'bound' ? '等待核对保存结果' : '仅保存在手机 · 点击预览'}</Text></TactilePressable>) : !intake.loading ? <View style={s.card}><Inbox size={30} color={c.muted}/><Text style={s.heading}>还没有待处理的分享</Text><Text style={s.copy}>在浏览器、照片或文件里点系统“分享”，选择 Pajio。支持网页、文字、图片、PDF 和选定聊天 ZIP，一次最多 4 个文件。</Text></View> : null}
  </View>;
}
export function ShareIntakePanel(props: ShareIntakePanelProps) {
  return <ShareIntakeContent key={`${scopeOf(props.connection)}|${props.connection.session?.credentialId || ''}|${props.connection.session?.expiresAt || props.connection.development?.expiresAt || ''}`} {...props}/>;
}
const styles = (c: AppColors) => StyleSheet.create({
  panel: {gap: 18}, row: {flexDirection: 'row', alignItems: 'center', gap: 12}, grow: {flex: 1, gap: 8}, title: {fontSize: 28, fontWeight: '600', color: c.ink},
  card: {padding: 20, borderRadius: 24, backgroundColor: c.surface, borderWidth: 1, borderColor: c.line, gap: 14}, heading: {fontSize: 19, lineHeight: 27, fontWeight: '500', color: c.ink},
  copy: {fontSize: 16, lineHeight: 25, color: c.ink}, muted: {fontSize: 13, lineHeight: 21, color: c.muted}, label: {fontSize: 13, color: c.muted}, error: {fontSize: 14, lineHeight: 22, color: c.danger},
  refresh: {minHeight: 48, minWidth: 48, alignItems: 'center', justifyContent: 'center', borderRadius: 24, backgroundColor: c.surface}, attachment: {gap: 8, paddingVertical: 10}, image: {width: '100%', height: 160, borderRadius: 12, backgroundColor: c.soft},
});
