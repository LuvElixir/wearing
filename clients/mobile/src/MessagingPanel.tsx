import {useCallback, useEffect, useMemo, useRef, useState} from 'react';
import {ActivityIndicator, Linking, StyleSheet, Text, TextInput, View} from 'react-native';
import {ArrowLeft, CheckCircle2, ChevronRight, MessageCircle, RefreshCw} from 'lucide-react-native';
import {ApiError, Connection} from './core';
import {AppColors, useAppTheme, useThemedStyles} from './app-theme';
import {PrimaryButton, TactilePressable} from './experience/primitives';
import {allowedMessagingUsers, MessagingApi, MessagingProvider, MessagingSnapshot, messagingConfigurationError} from './messaging-model';

const stateLabels = {not_configured: '未连接', configured: '已验证 · 未启用', connecting: '正在连接', listening: '正在接收', error: '连接需检查'};
function MessagingContent({connection, fetcher}: {connection: Connection; fetcher?: typeof fetch}) {
  const {colors: c} = useAppTheme(), s = useThemedStyles(styles);
  const api = useMemo(() => new MessagingApi(connection, fetcher), [connection, fetcher]);
  const [data, setData] = useState<MessagingSnapshot | null>(null), [selected, setSelected] = useState<MessagingProvider | null>(null);
  const [busy, setBusy] = useState('load'), [error, setError] = useState(''), [notice, setNotice] = useState('');
  const [secret, setSecret] = useState(''), [appId, setAppId] = useState(''), [users, setUsers] = useState(''), [editing, setEditing] = useState(false), [removing, setRemoving] = useState(false);
  const active = useRef(true), operation = useRef(false), sequence = useRef(0);
  const refresh = useCallback(async (silent = false) => {
    if (operation.current) return;
    const ticket = ++sequence.current;
    if (!silent) {setBusy('load'); setError('');}
    try {const result = await api.list(); if (active.current && ticket === sequence.current) setData(result);}
    catch (error) {if (active.current && ticket === sequence.current && !silent) setError(error instanceof ApiError ? error.message : '渠道状态暂时无法读取。');}
    finally {if (active.current && ticket === sequence.current && !silent) setBusy('');}
  }, [api]);
  useEffect(() => {active.current = true; void Promise.resolve().then(() => {if (active.current) return refresh();}); const timer = setInterval(() => {if (active.current) void refresh(true);}, 15000); return () => {active.current = false; clearInterval(timer);};}, [refresh]);
  const channel = data?.channels.find(item => item.provider === selected);
  function open(provider: MessagingProvider) {
    const item = data?.channels.find(item => item.provider === provider);
    setSelected(provider); setSecret(''); setAppId(provider === 'feishu' ? item?.bot_id || '' : ''); setUsers(item?.allowed_users.join('\n') || ''); setEditing(!item?.configured); setRemoving(false); setNotice(''); setError('');
  }
  async function act(action: 'save' | 'toggle' | 'disconnect') {
    if (!selected || !channel || operation.current || busy) return;
    const configuration = {secret: secret.trim(), allowed_users: allowedMessagingUsers(users), ...(selected === 'feishu' ? {app_id: appId.trim()} : {})};
    if (action === 'save') {const invalid = messagingConfigurationError(selected, configuration); if (invalid) {setError(invalid); return;}}
    operation.current = true; sequence.current++; setBusy(action); setError(''); setNotice('');
    try {
      const result = action === 'save' ? await api.configure(selected, configuration) : action === 'toggle' ? await api.enabled(channel, !channel.enabled) : await api.disconnect(channel);
      if (!active.current) return;
      setData(result); setSecret(''); setEditing(action === 'disconnect'); setRemoving(false);
      setNotice(action === 'save' ? '凭据已验证并保存。点“启用”后才会开始接收和回复。' : action === 'disconnect' ? '已断开并移除服务端凭据，对话仍保留。' : channel.enabled ? '已停用，不再接收和回复。' : '已启用。现在可以从允许的账号私聊机器人。');
    } catch (error) {if (active.current) setError(error instanceof ApiError ? error.message : '这次操作没有完成。');}
    finally {operation.current = false; if (active.current) setBusy('');}
  }
  async function instructions() {
    try {await Linking.openURL(selected === 'telegram' ? 'https://core.telegram.org/bots/features#botfather' : 'https://open.feishu.cn/app');}
    catch {if (active.current) setError('这次没有打开配置页面，请稍后重试。');}
  }
  return <View style={s.panel}>
    <View style={s.heading}>{selected ? <TactilePressable disabled={!!busy} accessibilityLabel="返回聊天渠道" style={s.round} onPress={() => {setSelected(null); setSecret(''); setError(''); setNotice('');}}><ArrowLeft size={20} color={c.ink}/></TactilePressable> : null}<View style={s.words}><Text style={s.title}>{selected === 'telegram' ? 'Telegram' : selected === 'feishu' ? '飞书' : '聊天渠道'}</Text><Text style={s.copy}>{selected ? '从常用聊天工具继续与你的 Pajio 对话。' : '连上之后，任务和进展会回到同一个地方。'}</Text></View><TactilePressable disabled={!!busy} accessibilityLabel="刷新聊天渠道" style={s.round} onPress={() => {void refresh();}}><RefreshCw size={20} color={c.ink}/></TactilePressable></View>
    {busy ? <View style={s.loading}><ActivityIndicator color={c.accent}/><Text style={s.copy}>{busy === 'save' ? '正在验证凭据…' : busy === 'load' ? '正在读取…' : '正在保存…'}</Text></View> : null}
    {error ? <Text accessibilityLiveRegion="polite" style={s.error}>{error}</Text> : null}
    {notice ? <View style={s.notice}><CheckCircle2 size={18} color={c.accent}/><Text accessibilityLiveRegion="polite" style={s.copy}>{notice}</Text></View> : null}
    {!selected ? data?.channels.map(item => <TactilePressable key={item.provider} disabled={!!busy} onPress={() => open(item.provider)} style={s.card} accessibilityLabel={`配置${item.provider === 'feishu' ? '飞书' : 'Telegram'}聊天渠道`}><View style={s.heading}><MessageCircle size={25} color={c.accent}/><View style={s.words}><Text style={s.name}>{item.provider === 'feishu' ? '飞书' : 'Telegram'}</Text><Text style={s.copy}>{stateLabels[item.state]}</Text></View><ChevronRight size={20} color={c.muted}/></View></TactilePressable>) : channel ? <>
      <View style={s.card}><Text style={s.name}>{stateLabels[channel.state]}</Text>{channel.configured ? <Text style={s.copy}>{channel.name} · 允许 {channel.allowed_users.length} 个个人账号</Text> : null}{channel.error ? <Text style={s.error}>{channel.error}</Text> : null}
        <Text style={s.copy}>启用后，只接收你列出的账号发来的私聊，并把结果回复给该账号。任务会同步显示在 App，需要批准的操作仍由你在 App 中确认。</Text>
        {channel.uncertain_replies ? <Text style={s.error}>有 {channel.uncertain_replies} 次回复无法确认送达。为避免重复发送，完整结果保留在 App 对话里。</Text> : null}
        {channel.configured && !editing ? <>
          <PrimaryButton label={channel.enabled ? '停用渠道' : '启用并接收回复'} tone={channel.enabled ? 'quiet' : undefined} disabled={!!busy || !channel.can_enable} loading={busy === 'toggle'} onPress={() => {void act('toggle');}}/>
          {!channel.enabled ? <PrimaryButton label="更换设置" tone="quiet" disabled={!!busy} onPress={() => {setEditing(true); setNotice('');}}/> : null}
          {removing ? <View style={s.actions}><Text style={s.copy}>断开会停用接收，并移除服务端保存的凭据。</Text><PrimaryButton label="断开并移除凭据" disabled={!!busy} onPress={() => {void act('disconnect');}}/><PrimaryButton label="保留连接" tone="quiet" disabled={!!busy} onPress={() => setRemoving(false)}/></View> : <TactilePressable disabled={!!busy} style={s.action} onPress={() => setRemoving(true)}><Text style={s.link}>断开连接</Text></TactilePressable>}
        </> : null}
      </View>
      {editing ? <View style={s.card}><Text style={s.name}>连接设置</Text>
        <Text style={s.copy}>{selected === 'telegram' ? '用 BotFather 创建一个专供 Pajio 的机器人，填写 Token 和你自己的数字用户 ID。已使用其他 Webhook 的机器人需要单独配置。' : '创建企业自建应用，开启机器人，申请 im:message:send_as_bot 与接收私聊消息权限；发布应用，在事件订阅中选择长连接并添加 im.message.receive_v1。填写允许使用的个人 Open ID。'}</Text>
        <PrimaryButton label={selected === 'telegram' ? '查看 BotFather 配置说明' : '打开飞书开放平台'} tone="quiet" disabled={!!busy} onPress={() => {void instructions();}}/>
        {selected === 'feishu' ? <><Text style={s.label}>App ID</Text><TextInput accessibilityLabel="飞书 App ID" value={appId} onChangeText={setAppId} autoCapitalize="none" autoCorrect={false} editable={!busy} placeholder="cli_…" placeholderTextColor={c.muted} style={s.input}/></> : null}
        <Text style={s.label}>{selected === 'telegram' ? 'Bot Token' : 'App Secret'}</Text><TextInput accessibilityLabel={selected === 'telegram' ? 'Telegram Bot Token' : '飞书 App Secret'} value={secret} onChangeText={setSecret} secureTextEntry autoCapitalize="none" autoCorrect={false} autoComplete="off" editable={!busy} placeholder="只保存到你的 Pajio 服务" placeholderTextColor={c.muted} style={s.input}/>
        <Text style={s.label}>{selected === 'telegram' ? '允许的个人数字 ID' : '允许的个人 Open ID'}</Text><TextInput accessibilityLabel="允许使用机器人的个人用户 ID" value={users} onChangeText={setUsers} autoCapitalize="none" autoCorrect={false} multiline editable={!busy} placeholder={selected === 'telegram' ? '每行一个数字 ID' : '每行一个 ou_ 开头的 Open ID'} placeholderTextColor={c.muted} style={[s.input, s.multiline]}/>
        <PrimaryButton label="验证并保存" disabled={!!busy} loading={busy === 'save'} onPress={() => {void act('save');}}/>
        {channel.configured ? <PrimaryButton label="取消更改" tone="quiet" disabled={!!busy} onPress={() => {setEditing(false); setSecret(''); setError('');}}/> : null}
      </View> : null}
    </> : null}
  </View>;
}
export function MessagingPanel(props: {connection: Connection; fetcher?: typeof fetch}) {return <MessagingContent key={`${props.connection.endpoint}|${props.connection.identity}|${props.connection.development?.expiresAt}`} {...props}/>;}
const styles = (c: AppColors) => StyleSheet.create({
  panel: {gap: 18}, heading: {flexDirection: 'row', alignItems: 'center', gap: 12}, words: {flex: 1, gap: 6}, title: {fontSize: 28, lineHeight: 38, fontWeight: '600', color: c.ink}, copy: {fontSize: 13, lineHeight: 22, color: c.muted},
  round: {height: 44, width: 44, borderRadius: 22, backgroundColor: c.surface, alignItems: 'center', justifyContent: 'center'}, card: {padding: 20, borderRadius: 24, backgroundColor: c.surface, borderWidth: 1, borderColor: c.line, gap: 16},
  name: {fontSize: 18, lineHeight: 27, fontWeight: '500', color: c.ink}, loading: {flexDirection: 'row', alignItems: 'center', gap: 10}, notice: {flexDirection: 'row', alignItems: 'flex-start', gap: 10, padding: 15, backgroundColor: c.soft, borderRadius: 20},
  error: {fontSize: 13, lineHeight: 22, color: c.danger}, actions: {gap: 12}, action: {minHeight: 44, justifyContent: 'center'}, link: {fontSize: 14, color: c.accent}, label: {fontSize: 14, lineHeight: 21, fontWeight: '500', color: c.ink},
  input: {minHeight: 48, fontSize: 16, lineHeight: 23, padding: 14, borderWidth: 1, borderColor: c.line, borderRadius: 16, color: c.ink, backgroundColor: c.canvas}, multiline: {minHeight: 95, textAlignVertical: 'top'},
});
