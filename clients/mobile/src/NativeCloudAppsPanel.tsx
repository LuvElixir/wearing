import {Choice} from './experience/selection';
import {useCallback, useEffect, useMemo, useRef, useState} from 'react';
import {ActivityIndicator, Linking, StyleSheet, Text, TextInput, View} from 'react-native';
import {ArrowLeft, CalendarDays, Check, ChevronRight, Cloud, FileText, Folder, RefreshCw} from 'lucide-react-native';
import {ApiError, Connection} from './core';
import {AppColors, useAppTheme, useThemedStyles} from './app-theme';
import {PrimaryButton, TactilePressable} from './experience/primitives';
import {CloudAppsApi, CloudCalendar, CloudDocument, CloudEvent, CloudFeature, CloudFile, CloudPage, CloudState, officialFeishuUrl, upcomingCalendarRange} from './cloud-apps-model';

const labels = {not_configured: '连接飞书', configured: '待授权', authorizing: '等待你在飞书授权', authorization_expired: '这次授权已到期', connected: '已连接', expired: '需要重新授权'};
type Browser = {kind: 'files'; title: string; folders: {token: string; title: string}[]; page: CloudPage<CloudFile>} | {kind: 'calendars'; page: CloudPage<CloudCalendar>} | {kind: 'events'; title: string; calendar: string; start: number; end: number; page: CloudPage<CloudEvent>} | {kind: 'document'; title: string; token: string; documentKind: string; page: CloudDocument};
function eventTime(event: CloudEvent) {const start = event.start_time; if (start?.date) return start.date + ' · 全天'; const ms = Number(start?.timestamp) * 1000; return Number.isFinite(ms) && ms > 0 ? new Date(ms).toLocaleString('zh-CN', {month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'}) : '时间以飞书日历为准';}
function CloudAppsContent({connection, fetcher}: {connection: Connection; fetcher?: typeof fetch}) {
  const {colors: c} = useAppTheme(), s = useThemedStyles(styles);
  const api = useMemo(() => new CloudAppsApi(connection, fetcher), [connection, fetcher]);
  const [data, setData] = useState<CloudState | null>(null), [busy, setBusy] = useState('正在读取连接…'), [error, setError] = useState('');
  const [appId, setAppId] = useState(''), [secret, setSecret] = useState(''), [features, setFeatures] = useState<CloudFeature[]>(['documents', 'calendar']);
  const [removing, setRemoving] = useState(false), [browser, setBrowser] = useState<Browser | null>(null), [documentLink, setDocumentLink] = useState('');
  const active = useRef(true), working = useRef(false), polling = useRef(false), sequence = useRef(0);
  const run = useCallback(async <T,>(label: string, work: () => Promise<T>, commit: (value: T) => void) => {
    if (working.current) return;
    working.current = true; const ticket = ++sequence.current; setBusy(label); setError('');
    try {const result = await work(); if (active.current && ticket === sequence.current) commit(result);}
    catch (error) {if (active.current && ticket === sequence.current) setError(error instanceof ApiError ? error.message : '这次操作没有完成，请重试。');}
    finally {working.current = false; if (active.current && ticket === sequence.current) setBusy('');}
  }, []);
  const refresh = useCallback(() => run('正在读取连接…', () => api.list(), setData), [api, run]);
  useEffect(() => {const generation = sequence; active.current = true; void Promise.resolve().then(() => {if (active.current) return refresh();}); return () => {active.current = false; generation.current++;};}, [refresh]);
  const authorization = data?.authorization;
  useEffect(() => {
    if (!authorization) return;
    const timer = setInterval(() => {
      if (!active.current || working.current || polling.current) return;
      polling.current = true; const ticket = ++sequence.current;
      void api.poll(authorization.id).then(result => {if (active.current && ticket === sequence.current) {setData(result); setError('');}}).catch(error => {if (active.current && ticket === sequence.current) setError(error instanceof ApiError ? error.message : '暂时无法确认授权结果。');}).finally(() => {polling.current = false;});
    }, Math.max(5, authorization.interval) * 1000);
    return () => clearInterval(timer);
  }, [api, authorization]);
  async function open(url: string) {if (!officialFeishuUrl(url)) {setError('这个链接不是有效的飞书页面。'); return;} try {await Linking.openURL(url);} catch {if (active.current) setError('没有打开飞书页面，请重试。');}}
  function browseFiles(folders: {token: string; title: string}[] = []) {const current = folders[folders.length - 1]; void run('正在读取文件…', () => api.files(current?.token), page => setBrowser({kind: 'files', title: current?.title || '我的云空间', folders, page}));}
  function browseCalendars() {void run('正在读取日历…', () => api.calendars(), page => setBrowser({kind: 'calendars', page}));}
  function readDocument(token: string, title: string, kind = 'docx') {void run('正在读取正文…', () => api.document(token, kind), page => setBrowser({kind: 'document', title: page.title || title, token, documentKind: kind, page}));}
  function browseEvents(calendar: CloudCalendar) {const {start, end} = upcomingCalendarRange(); void run('正在读取未来 7 天日程…', () => api.events(calendar.calendar_id, start, end), page => setBrowser({kind: 'events', title: calendar.summary_alias || calendar.summary || '飞书日历', calendar: calendar.calendar_id, start, end, page}));}
  function more() {
    if (!browser) return;
    if (browser.kind === 'document') {const selected = browser; if (selected.page.next_offset === null) return; void run('正在读取下一段…', () => api.document(selected.token, selected.documentKind, selected.page.next_offset!), page => setBrowser({...selected, page})); return;}
    const next = browser.page.next_page_token;
    if (!next) return;
    if (browser.kind === 'files') {const selected = browser; void run('正在读取更多文件…', () => api.files(selected.folders.at(-1)?.token, next), page => setBrowser({...selected, page: {...page, items: [...selected.page.items, ...page.items]}}));}
    if (browser.kind === 'calendars') {const selected = browser; void run('正在读取更多日历…', () => api.calendars(next), page => setBrowser({...selected, page: {...page, items: [...selected.page.items, ...page.items]}}));}
    if (browser.kind === 'events') {const selected = browser; void run('正在读取更多日程…', () => api.events(selected.calendar, selected.start, selected.end, next), page => setBrowser({...selected, page: {...page, items: [...selected.page.items, ...page.items]}}));}
  }
  function back() {setError(''); if (browser?.kind === 'files' && browser.folders.length) browseFiles(browser.folders.slice(0, -1)); else if (browser?.kind === 'events') browseCalendars(); else setBrowser(null);}
  return <View style={s.panel}>
    <View style={s.heading}>{browser ? <TactilePressable accessibilityLabel="返回云端应用" disabled={!!busy} onPress={back} style={s.round}><ArrowLeft size={20} color={c.ink}/></TactilePressable> : <Cloud size={28} color={c.accent}/>}<View style={s.words}><Text style={s.title}>{browser ? browser.kind === 'calendars' ? '飞书日历' : browser.title : '云端应用'}</Text><Text style={s.copy}>{browser ? '来自当前身份授权的飞书账号' : '把文档与日程接给 Pajio，省去反复说明。'}</Text></View>{!browser ? <TactilePressable accessibilityLabel="刷新云端应用连接" disabled={!!busy} onPress={() => {void refresh();}} style={s.round}><RefreshCw size={20} color={c.ink}/></TactilePressable> : null}</View>
    {busy ? <View style={s.heading}><ActivityIndicator color={c.accent}/><Text style={s.copy}>{busy}</Text></View> : null}
    {error ? <Text style={s.error} accessibilityLiveRegion="polite">{error}</Text> : null}
    {browser ? <>
      {browser.kind === 'files' ? <View style={s.card}>{browser.page.items.length ? browser.page.items.map((file, index) => <TactilePressable key={`${file.token}-${index}`} disabled={!!busy} style={s.row} onPress={() => {
        if (file.type === 'folder') browseFiles([...browser.folders, {token: file.token, title: file.name}]);
        else if (file.type === 'docx' || file.type === 'wiki') readDocument(file.token, file.name, file.type);
        else if (file.url && officialFeishuUrl(file.url)) void open(file.url);
        else setError('这种文件暂时无法直接阅读，请在飞书云空间打开。');
      }}>{file.type === 'folder' ? <Folder size={22} color={c.accent}/> : <FileText size={22} color={c.muted}/>}<View style={s.words}><Text style={s.name}>{file.name}</Text><Text style={s.copy}>{file.type === 'folder' ? '文件夹' : ['docx', 'wiki'].includes(file.type) ? '点开阅读' : '在飞书中打开'}</Text></View><ChevronRight size={19} color={c.muted}/></TactilePressable>) : <Text style={s.copy}>这个文件夹暂时没有可见文件。也可以返回连接页，粘贴一篇飞书文档的链接来阅读。</Text>}</View> : null}
      {browser.kind === 'calendars' ? <View style={s.card}>{browser.page.items.length ? browser.page.items.map((calendar, index) => <TactilePressable key={`${calendar.calendar_id}-${index}`} disabled={!!busy} style={s.row} onPress={() => browseEvents(calendar)}><CalendarDays size={22} color={c.accent}/><View style={s.words}><Text style={s.name}>{calendar.summary_alias || calendar.summary || '飞书日历'}</Text><Text style={s.copy}>查看未来 7 天日程</Text></View><ChevronRight size={19} color={c.muted}/></TactilePressable>) : <Text style={s.copy}>当前账号暂无可见日历。</Text>}</View> : null}
      {browser.kind === 'events' ? <View style={s.card}><Text style={s.copy}>未来 7 天 · {new Date(browser.start * 1000).toLocaleDateString('zh-CN')}</Text>{browser.page.items.length ? browser.page.items.map((event, index) => <View key={`${event.event_id}-${index}`} style={s.event}><Text style={s.copy}>{eventTime(event)}{event.status === 'cancelled' ? ' · 已取消' : ''}</Text><Text selectable style={s.name}>{event.summary || '未命名日程'}</Text>{event.description ? <Text selectable style={s.body}>{event.description}</Text> : null}{event.location?.name ? <Text style={s.copy}>{event.location.name}</Text> : null}</View>) : <Text style={s.copy}>这个时间范围内没有日程。</Text>}</View> : null}
      {browser.kind === 'document' ? <View style={s.card}><Text style={s.copy}>正文第 {browser.page.offset + 1}–{browser.page.offset + browser.page.content.length} 字符 · 共 {browser.page.total_characters} 字符</Text><Text selectable style={s.body}>{browser.page.content || '文档正文为空。'}</Text>{browser.page.offset > 0 ? <PrimaryButton label="回到正文开头" tone="quiet" disabled={!!busy} onPress={() => readDocument(browser.token, browser.title, browser.documentKind)}/> : null}</View> : null}
      {(browser.kind === 'document' ? browser.page.next_offset !== null : browser.page.has_more) ? <PrimaryButton label={browser.kind === 'document' ? '阅读下一段' : '加载更多'} tone="quiet" disabled={!!busy} onPress={more}/> : null}
      <PrimaryButton label="返回连接管理" tone="quiet" disabled={!!busy} onPress={() => {setBrowser(null); setError('');}}/>
    </> : data ? <>
      <View style={s.card}><Text style={s.name}>飞书 · {data.revocation_pending ? '已停用，等待撤销' : labels[data.state]}</Text>{data.account_name ? <Text style={s.copy}>{data.account_name}</Text> : null}
        {data.error ? <Text style={s.error}>{data.error}</Text> : null}
        <Text style={s.copy}>授权后，Pajio 可以查看你允许访问的文档和日程。聊天机器人渠道单独管理。</Text>
        {data.capabilities.filter(item => item.requested).map(item => <View key={item.id} style={s.row}><View style={s.words}><Text style={s.label}>{item.label}</Text><Text style={s.copy}>{item.authorized ? '已授权查看' : '等待用户授权或应用权限开通'}</Text></View>{item.authorized ? <Check size={20} color={c.accent}/> : null}</View>)}
        {authorization ? <View style={s.authorize}><Text style={s.name}>请在飞书中完成授权</Text><Text style={s.copy}>如果飞书要求输入确认码，请使用：</Text><Text selectable style={s.code}>{authorization.user_code}</Text><Text style={s.copy}>完成后回到这里，连接状态会自动更新。</Text><PrimaryButton label="打开飞书授权页" disabled={!!busy} onPress={() => {void open(authorization.url);}}/></View> : null}
        {data.configured && !data.revocation_pending && !authorization ? <PrimaryButton label={data.state === 'connected' ? '重新授权' : '前往飞书授权'} disabled={!!busy} onPress={() => {if (data.revision) void run('正在准备授权…', () => api.authorize(data.revision!), result => {setData(result); if (result.authorization) void open(result.authorization.url);});}}/> : null}
        {data.state === 'connected' && !data.revocation_pending ? <><PrimaryButton label="检查连接" tone="quiet" disabled={!!busy} onPress={() => {void run('正在检查飞书连接…', () => api.check(), setData);}}/>{data.capabilities.some(item => item.id === 'documents' && item.authorized) ? <PrimaryButton label="浏览我的云空间" tone="quiet" disabled={!!busy} onPress={() => browseFiles()}/> : null}{data.capabilities.some(item => item.id === 'calendar' && item.authorized) ? <PrimaryButton label="查看我的飞书日历" tone="quiet" disabled={!!busy} onPress={browseCalendars}/> : null}</> : null}
        {data.configured ? data.revocation_pending || removing ? <View style={s.actions}><Text style={s.copy}>停止 Pajio 访问，并向飞书撤销当前授权。App 中已有的对话和结果会保留。</Text><PrimaryButton label={data.revocation_pending ? '重试撤销' : '断开并撤销授权'} disabled={!!busy} onPress={() => {if (data.revision) void run('正在撤销授权…', () => api.disconnect(data.revision!), result => {setData(result); setRemoving(false); setSecret('');});}}/>{!data.revocation_pending ? <PrimaryButton label="保留连接" tone="quiet" disabled={!!busy} onPress={() => setRemoving(false)}/> : null}</View> : <PrimaryButton label="断开连接" tone="quiet" disabled={!!busy} onPress={() => setRemoving(true)}/> : null}
      </View>
      {!data.configured ? <View style={s.card}><Text style={s.name}>配置飞书应用</Text><Text style={s.copy}>使用已发布的企业自建应用，在开放平台开通下列用户权限，再填写 App ID 与 App Secret。凭据只保存到你的 Pajio 服务。</Text><PrimaryButton label="打开飞书开放平台" tone="quiet" disabled={!!busy} onPress={() => {void open('https://open.feishu.cn/app');}}/>
        <Text style={s.label}>App ID</Text><TextInput accessibilityLabel="飞书应用 App ID" value={appId} onChangeText={setAppId} editable={!busy} autoCapitalize="none" autoCorrect={false} placeholder="cli_…" placeholderTextColor={c.muted} style={s.input}/><Text style={s.label}>App Secret</Text><TextInput accessibilityLabel="飞书应用 App Secret" value={secret} onChangeText={setSecret} editable={!busy} secureTextEntry autoCapitalize="none" autoCorrect={false} autoComplete="off" placeholder="仅保存到服务端" placeholderTextColor={c.muted} style={s.input}/>
        {data.capabilities.map(item => <Choice key={item.id}  selected={features.includes(item.id)} multiple disabled={!!busy} style={s.row} onPress={() => setFeatures(current => current.includes(item.id) ? current.filter(key => key !== item.id) : [...current, item.id])}><View style={s.words}><Text style={s.name}>{item.label}</Text><Text selectable style={s.copy}>{item.scopes.join('\n')}</Text></View></Choice>)}<Text selectable style={s.copy}>后台续期权限：offline_access</Text><PrimaryButton label="保存应用配置" disabled={!!busy} onPress={() => {void run('正在保存配置…', () => api.configure(appId.trim(), secret.trim(), features), result => {setData(result); setSecret('');});}}/>
      </View> : null}
      {data.capabilities.some(item => item.id === 'documents' && item.authorized) ? <View style={s.card}><Text style={s.name}>直接阅读文档</Text><Text style={s.copy}>粘贴你有权访问的飞书新版文档或知识库链接。</Text><TextInput accessibilityLabel="飞书文档链接" value={documentLink} onChangeText={setDocumentLink} autoCapitalize="none" autoCorrect={false} editable={!busy} placeholder="https://…feishu.cn/docx/…" placeholderTextColor={c.muted} style={s.input}/><PrimaryButton label="读取文档" disabled={!!busy || !documentLink.trim()} onPress={() => readDocument(documentLink.trim(), '飞书文档')}/></View> : null}
    </> : !busy ? <PrimaryButton label="重新读取连接" onPress={() => {void refresh();}}/> : null}
  </View>;
}
export function NativeCloudAppsPanel(props: {connection: Connection; fetcher?: typeof fetch}) {return <CloudAppsContent key={`${props.connection.endpoint}|${props.connection.identity}|${props.connection.development?.expiresAt}`} {...props}/>;}
const styles = (c: AppColors) => StyleSheet.create({
  panel: {gap: 18}, heading: {flexDirection: 'row', alignItems: 'center', gap: 12}, words: {flex: 1, gap: 5}, title: {fontSize: 27, lineHeight: 37, fontWeight: '600', color: c.ink}, name: {fontSize: 17, lineHeight: 25, fontWeight: '500', color: c.ink}, copy: {fontSize: 13, lineHeight: 22, color: c.muted}, body: {fontSize: 16, lineHeight: 28, color: c.ink},
  card: {padding: 20, borderRadius: 24, backgroundColor: c.surface, borderWidth: 1, borderColor: c.line, gap: 15}, round: {width: 44, height: 44, alignItems: 'center', justifyContent: 'center', borderRadius: 22, backgroundColor: c.surface}, row: {minHeight: 52, flexDirection: 'row', alignItems: 'center', gap: 12, paddingVertical: 7}, error: {color: c.danger, fontSize: 13, lineHeight: 22}, label: {fontSize: 14, lineHeight: 22, fontWeight: '500', color: c.ink},
  input: {minHeight: 48, padding: 14, borderRadius: 16, borderWidth: 1, borderColor: c.line, backgroundColor: c.canvas, color: c.ink, fontSize: 16, lineHeight: 23}, authorize: {gap: 12, padding: 16, borderRadius: 20, backgroundColor: c.soft}, code: {fontSize: 27, lineHeight: 37, letterSpacing: 2, color: c.ink}, actions: {gap: 12}, event: {gap: 7, paddingVertical: 15, borderTopWidth: 1, borderTopColor: c.line},
});
