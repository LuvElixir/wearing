import {useCallback, useEffect, useMemo, useRef, useState} from 'react';
import {ActivityIndicator, AppState, Platform, ScrollView, StyleSheet, Switch, Text, TextInput, View} from 'react-native';
import {WebView, type WebViewMessageEvent} from 'react-native-webview';
import * as Crypto from 'expo-crypto';
import {ArrowLeft, Keyboard, Monitor, Smartphone} from 'lucide-react-native';
import {useAppTheme, useThemedStyles, type AppColors} from './app-theme';
import {palettes} from './appearance';
import {type Connection, connectionEndpoint} from './core';
import {registerAccountWork} from './account-work';
import {IconButton, PrimaryButton, TactilePressable} from './experience/primitives';
import {serviceFetch} from './transport';
import {canStream, deviceIdentifier, RemoteDeviceApi, remoteStatusCopy, type RemoteAccess, type RemoteTransport} from './remote-device-model';
import {remoteViewerDocument} from './remote-viewer-document';
import {remoteTextIssue, remoteTextLimits, remoteTextNotice, type RemoteTextCapabilities} from './remote-text-input';

type Props = {connection: Connection; resource: string; name: string; kind: 'computer' | 'android'; onBack: () => void};
type Viewer = {access: RemoteAccess; transport: RemoteTransport; attempt: number};
type Capabilities = RemoteTextCapabilities & {keyboard?: boolean; touch?: boolean; pointer?: boolean; scroll?: boolean};
const messageOf = (error: unknown) => error instanceof Error ? error.message : '这次连接没有完成，请重新检查设备。';
const pauseCopy: Record<string, string> = {
  background: '你已离开接管页面，输入与画面已停止。设备保持暂停。',
  stale_video: '画面暂时没有更新，已停止操作。请重新连接后查看设备。',
  input_unconfirmed: '设备没有确认刚才的操作，已停止发送。请重新连接后检查实际结果。',
  geometry_changed: '设备画面尺寸改变，已停止操作。请重新连接。',
  expired: '本次接管已到期。设备保持暂停，可重新接管。',
  closed: '已结束画面连接。设备保持暂停。',
};
const noticeCopy: Record<string, string> = {
  ascii_only: '这台云手机当前只支持英文、数字和常用符号输入，不支持中文或 %。',
  frame_not_ready: '正在等待新画面，本次操作未发送。',
  input_unavailable: '这台设备暂不支持此操作，本次操作未发送。',
};
const sameSession = (a: RemoteAccess, b: RemoteAccess) => a.session_id === b.session_id && a.epoch === b.epoch;

/** The native boundary owns credentials; the isolated video document only sees one short-lived session. */
export function NativeRemoteDevicePanel({connection, resource, name, kind, onBack}: Props) {
  const styles = useThemedStyles(makeStyles), {colors} = useAppTheme();
  const web = useRef<WebView>(null), alive = useRef(false), foreground = useRef(AppState.currentState === 'active');
  const api = useMemo(() => new RemoteDeviceApi(connection, serviceFetch, () => false), [connection]);
  const current = useRef<RemoteAccess | null>(null), viewing = useRef<Viewer | null>(null);
  const desired = useRef(false), returning = useRef(false), opening = useRef(false), mutating = useRef(false), polling = useRef(false);
  const closing = useRef(new Set<string>());
  const attempt = useRef(0), read = useRef(0), deadline = useRef(0), offerPending = useRef(false);
  const [access, setAccess] = useState<RemoteAccess | null>(null), [viewer, setViewer] = useState<Viewer | null>(null);
  const [busy, setBusy] = useState(false), [live, setLive] = useState(false), [controlling, setControlling] = useState(false);
  const [isReturning, setIsReturning] = useState(false);
  const [error, setError] = useState(''), [notice, setNotice] = useState(''), [rtt, setRtt] = useState<number | null>(null);
  const [capabilities, setCapabilities] = useState<Capabilities>({}), [keyboard, setKeyboard] = useState(false), [text, setText] = useState('');
  const [confirmReturn, setConfirmReturn] = useState(false), [safeScreen, setSafeScreen] = useState(false), [scopeConfirmed, setScopeConfirmed] = useState(false);
  const send = useCallback((value: object) => web.current?.injectJavaScript(`window.pajioReceive?.(${JSON.stringify(value).replace(/</g, '\\u003c')});true;`), []);
  const update = useCallback((next: RemoteAccess) => {current.current = next; if (alive.current) setAccess(next);}, []);

  const clearViewer = useCallback(() => {
    send({type: 'stop'}); viewing.current = null; opening.current = false; offerPending.current = false;
    if (alive.current) {setViewer(null); setLive(false); setControlling(false); setIsReturning(false); setKeyboard(false); setText(''); setRtt(null); setCapabilities({}); setConfirmReturn(false); setSafeScreen(false); setScopeConfirmed(false);}
  }, [send]);
  const stop = useCallback((reason: string, close = true) => {
    const previous = current.current, generation = ++attempt.current;
    read.current++; desired.current = false; returning.current = false; deadline.current = 0;
    clearViewer();
    if (alive.current) {setBusy(false); setNotice(previous?.session_id && previous.state !== 'agent_ready' ? '画面和输入已停止，正在确认设备暂停。' : '画面连接已结束。');}
    if (close && previous?.session_id && previous.state !== 'agent_ready') {
      const key = `${previous.session_id}:${previous.epoch}`;
      if (!closing.current.has(key)) {
        closing.current.add(key);
        void api.close(previous).then(next => {if (alive.current && generation === attempt.current) {update(next); setNotice(pauseCopy[reason] || '设备已保持暂停。重新连接后可继续。');}}).catch(() => {
          if (alive.current && generation === attempt.current) {setNotice('画面和输入已停止。'); setError('暂停回执尚未收到，请刷新设备状态；不会自动重新发送操作。');}
        }).finally(() => closing.current.delete(key));
      }
    }
  }, [api, clearViewer, update]);

  const attach = useCallback(async (next: RemoteAccess) => {
    if (!desired.current || !canStream(next) || opening.current || viewing.current || !foreground.current) return;
    const generation = attempt.current; opening.current = true;
    try {
      const transport = await api.transport(next);
      if (!alive.current || !foreground.current || generation !== attempt.current || !desired.current) return;
      const value = {access: next, transport, attempt: generation};
      viewing.current = value; setViewer(value);
    } catch (cause) {
      if (alive.current && generation === attempt.current) {stop('connection_lost'); setError(messageOf(cause));}
    } finally {if (generation === attempt.current) opening.current = false;}
  }, [api, stop]);

  const refresh = useCallback(async () => {
    if (!alive.current || !foreground.current || polling.current || mutating.current) return;
    polling.current = true; const revision = ++read.current;
    try {
      const next = await api.status(resource);
      if (!alive.current || !foreground.current || revision !== read.current) return;
      const previous = current.current;
      // Never close a newer session that replaced this viewer while a status read was in flight.
      if ((desired.current || returning.current) && previous?.session_id && !sameSession(previous, next)) {stop('session_changed'); update(next); return;}
      update(next);
      if (returning.current) {
        if (next.state === 'agent_ready' && next.device_confirmed && previous && sameSession(previous, next) && next.gateway_epoch !== null && next.gateway_epoch > (viewing.current?.access.gateway_epoch ?? -1)) {
          returning.current = false; desired.current = false; deadline.current = 0; attempt.current++;
          clearViewer(); setBusy(false); setNotice('设备已确认交还，Pajio 可以继续操作。');
        } else if (next.state === 'paused') stop('session_changed');
        return;
      }
      if (!desired.current) return;
      if (!['handoff_pending', 'human_private'].includes(next.state)) {stop('session_changed'); return;}
      if (viewing.current && (!canStream(next) || next.gateway_epoch !== viewing.current.access.gateway_epoch)) {stop('expired'); return;}
      if (canStream(next)) void attach(next);
    } catch (cause) {
      if (alive.current && revision === read.current) {
        if (desired.current || returning.current) stop('connection_lost');
        setError(messageOf(cause));
      }
    } finally {polling.current = false;}
  }, [api, resource, update, clearViewer, stop, attach]);

  useEffect(() => {
    alive.current = true; api.setUsable(() => alive.current && foreground.current); const initial = setTimeout(() => {void refresh();}, 0);
    const changed = AppState.addEventListener('change', state => {
      foreground.current = state === 'active';
      if (!foreground.current) stop('background'); else void refresh();
    });
    const blurred = Platform.OS === 'android' ? AppState.addEventListener('blur', () => stop('background')) : null;
    const unregister = registerAccountWork(connection, async () => {stop('closed');});
    const timer = setInterval(() => {
      if (!foreground.current) return;
      if (deadline.current && Date.now() > deadline.current) {stop('connection_lost'); setError('设备尚未确认这次连接，请重新检查后再试。');}
      else void refresh();
    }, 1500);
    return () => {alive.current = false; changed.remove(); blurred?.remove(); unregister(); clearTimeout(initial); clearInterval(timer); stop('closed');};
  }, [api, connection, refresh, stop]);

  async function begin() {
    if (mutating.current || !foreground.current || !deviceIdentifier(resource)) return;
    mutating.current = true; const generation = ++attempt.current; read.current++;
    desired.current = false; returning.current = false; clearViewer();
    setBusy(true); setError(''); setNotice('正在请求设备暂停 Pajio 的操作…');
    try {
      let previous = await api.status(resource);
      if (!alive.current || !foreground.current || generation !== attempt.current) return;
      if (!previous.supported) {update(previous); setNotice('此设备尚未开放远程接管。'); setBusy(false); return;}
      if (previous.session_id && !['agent_ready', 'paused'].includes(previous.state)) {
        previous = await api.close(previous);
        if (!alive.current || !foreground.current || generation !== attempt.current) return;
      }
      const next = await api.begin(previous, Crypto.randomUUID().replaceAll('-', ''));
      if (!alive.current || !foreground.current || generation !== attempt.current) {
        if (next.session_id) void api.close(next).catch(() => {});
        return;
      }
      update(next); desired.current = true; deadline.current = Date.now() + 35000;
      setNotice('等待设备确认，确认后才会连接画面。');
      if (canStream(next)) void attach(next);
    } catch (cause) {if (alive.current && generation === attempt.current) {stop('connection_lost'); setError(messageOf(cause));}}
    finally {mutating.current = false;}
  }
  async function giveBack() {
    const previous = current.current;
    if (!previous || !canStream(previous) || !safeScreen || !scopeConfirmed || mutating.current) return;
    const generation = attempt.current; mutating.current = true; returning.current = true; desired.current = false; read.current++;
    send({type: 'freeze'}); setLive(false); setControlling(false); setIsReturning(true); setKeyboard(false); setText(''); setConfirmReturn(false); setBusy(true);
    deadline.current = Date.now() + 30000; setNotice('等待设备确认交还…');
    try {
      const next = await api.giveBack(previous, true, true);
      if (alive.current && generation === attempt.current) update(next);
    } catch (cause) {if (alive.current && generation === attempt.current) {stop('connection_lost'); setError(messageOf(cause));}}
    finally {mutating.current = false;}
  }
  async function message(event: WebViewMessageEvent) {
    const frame = viewing.current;
    if (!frame || !alive.current || !foreground.current || frame.attempt !== attempt.current || event.nativeEvent.data.length > 150000) return;
    let value: Record<string, unknown>;
    try {value = JSON.parse(event.nativeEvent.data);} catch {stop('invalid_channel'); return;}
    if (!value || typeof value !== 'object') return;
    if (value.type === 'stopped') {if (!returning.current) stop(typeof value.reason === 'string' ? value.reason : 'connection_lost'); return;}
    if (returning.current || !desired.current) return;
    if (value.type === 'offer' && typeof value.sdp === 'string') {
      if (offerPending.current) {stop('negotiation_failed'); return;}
      offerPending.current = true;
      try {
        const answer = await api.offer(frame.access, value.sdp);
        if (alive.current && foreground.current && desired.current && frame.attempt === attempt.current) send(answer);
      } catch (cause) {if (alive.current && frame.attempt === attempt.current) {stop('connection_lost'); setError(messageOf(cause));}}
    } else if (value.type === 'live') {
      deadline.current = 0; setLive(true); setBusy(false); setNotice('画面已连接。点“开始操作”后，可直接触控设备。');
      if (value.capabilities && typeof value.capabilities === 'object') setCapabilities(value.capabilities as Capabilities);
    } else if (value.type === 'control') {setControlling(value.enabled === true); setNotice(value.enabled === true ? '你可以直接触控设备。结束后明确交还，Pajio 才会继续。' : '当前只查看画面。点“开始操作”后，可直接触控设备。');}
    else if (value.type === 'quality' && typeof value.rtt_ms === 'number' && Number.isFinite(value.rtt_ms)) setRtt(Math.max(0, Math.round(value.rtt_ms)));
    else if (value.type === 'notice') setError(remoteTextNotice(String(value.code), capabilities, kind) || noticeCopy[String(value.code)] || '设备拒绝了这次操作，操作不会自动重试。请检查画面后再操作。');
  }
  function submitText() {
    if (!alive.current || !foreground.current || !viewing.current || !controlling || capabilities.keyboard !== true || !text) return;
    const issue = remoteTextIssue(text, capabilities, kind);
    if (issue) {setError(remoteTextNotice(issue, capabilities, kind)!); return;}
    const draft = text; setText(''); setError(''); send({type: 'text', text: draft});
  }
  function sendKey(key: string) {
    if (!alive.current || !foreground.current || !viewing.current || !controlling || capabilities.keyboard !== true) return;
    send({type: 'key', key});
  }
  const html = useMemo(() => viewer ? remoteViewerDocument(viewer.transport, kind, viewer.access.expires_at!) : '', [viewer, kind]);
  const baseUrl = new URL('/remote-viewer-native', connectionEndpoint(connection)).toString();
  const source = useMemo(() => ({html, baseUrl}), [html, baseUrl]);
  const connected = live && !!viewer && !isReturning;
  const keys = kind === 'android' ? [['Back', '返回'], ['Home', '主页'], ['Recents', '最近任务']] : [['Tab', 'Tab'], ['Escape', 'Esc'], ['ArrowUp', '↑'], ['ArrowDown', '↓'], ['ArrowLeft', '←'], ['ArrowRight', '→']];
  return <View style={styles.root}>
    <View style={styles.header}><IconButton label="结束画面连接并返回设备" onPress={() => {stop('closed'); onBack();}}><ArrowLeft size={23} color={colors.ink}/></IconButton>
      <View style={styles.heading}><Text numberOfLines={1} style={styles.title}>{name || (kind === 'android' ? '云手机' : '云电脑')}</Text><Text style={styles.caption}>{connected ? controlling ? '你正在操作 · Pajio 已暂停' : '查看画面 · Pajio 已暂停' : remoteStatusCopy(access)}</Text></View>
      {rtt !== null && connected && <Text style={styles.caption}>{rtt} ms</Text>}
    </View>
    <View style={styles.videoBox}>
      {viewer && Platform.OS !== 'web' && <WebView ref={web} source={source} style={styles.video} originWhitelist={['*']}
        onShouldStartLoadWithRequest={request => request.url === 'about:blank' || request.url === baseUrl}
        onMessage={event => {void message(event);}} onError={() => stop('connection_lost')} onContentProcessDidTerminate={() => stop('connection_lost')}
        onRenderProcessGone={() => stop('connection_lost')} javaScriptEnabled domStorageEnabled={false} incognito sharedCookiesEnabled={false}
        thirdPartyCookiesEnabled={false} allowFileAccess={false} allowFileAccessFromFileURLs={false} allowUniversalAccessFromFileURLs={false}
        mixedContentMode="never" allowsInlineMediaPlayback mediaPlaybackRequiresUserAction={false} allowsBackForwardNavigationGestures={false}
        bounces={false} scrollEnabled={false} setSupportMultipleWindows={false} onOpenWindow={() => stop('unexpected_navigation')}
        webviewDebuggingEnabled={false}/>}
      {!connected && <View style={styles.cover}>{busy ? <ActivityIndicator color={palettes.night.ink}/> : kind === 'android' ? <Smartphone size={44} color={palettes.night.muted}/> : <Monitor size={48} color={palettes.night.muted}/>}
        <Text style={styles.coverTitle}>{busy ? isReturning ? '正在交还设备' : '正在连接设备' : '你的远程设备'}</Text>
        <Text style={styles.coverText}>{Platform.OS === 'web' ? '请在 iPhone 或 Android App 中接管设备。' : '连接后可查看画面，再决定是否开始操作。'}</Text>
      </View>}
    </View>
    <ScrollView style={styles.controls} contentContainerStyle={styles.controlsContent} keyboardShouldPersistTaps="handled">
      {!!error && <Text accessibilityLiveRegion="polite" style={styles.error}>{error}</Text>}
      {!!notice && <Text accessibilityLiveRegion="polite" style={styles.caption}>{notice}</Text>}
      {connected ? <>
        <View style={styles.row}><PrimaryButton style={styles.flex} label={controlling ? '停止操作' : '开始操作'} onPress={() => {setText(''); setKeyboard(false); send({type: 'control', enabled: !controlling});}}/>
          <IconButton label="打开远程键盘" disabled={!controlling || capabilities.keyboard !== true || capabilities.text !== 'unicode'} selected={keyboard} onPress={() => setKeyboard(v => !v)}><Keyboard size={23} color={colors.ink}/></IconButton>
          <PrimaryButton label="交还 Pajio" tone="quiet" onPress={() => {setConfirmReturn(true); setSafeScreen(false); setScopeConfirmed(false);}}/></View>
        {controlling && capabilities.keyboard === true && <View style={styles.keyRow}>{keys.map(([key, label]) => <TactilePressable key={key} accessibilityLabel={`远程${label}`} style={styles.key} onPress={() => sendKey(key)}><Text style={styles.keyText}>{label}</Text></TactilePressable>)}</View>}
        {controlling && capabilities.text !== 'unicode' && <Text style={styles.caption}>此设备的私密输入尚未就绪，暂时不能从 App 发送文字。</Text>}
        {keyboard && controlling && capabilities.keyboard === true && capabilities.text === 'unicode' && <View style={styles.keyboard}>
          <Text style={styles.caption}>每次最多 {remoteTextLimits(capabilities, kind).chars} 个字符。发送到远程当前输入框，发送后立即清空。</Text>
          <View style={styles.row}><TextInput accessibilityLabel="发送到远程输入框的文字" style={styles.input} value={text} onChangeText={setText} secureTextEntry autoCapitalize="none" autoCorrect={false} textContentType="none" autoComplete="off" onSubmitEditing={submitText}/>
            <PrimaryButton label="输入" disabled={!text} onPress={submitText}/></View>
          <View style={styles.keyRow}>{[['Backspace', '删除'], ['Enter', '回车']].map(([key, label]) => <TactilePressable key={key} accessibilityLabel={`远程${label}`} style={styles.key} onPress={() => sendKey(key)}><Text style={styles.keyText}>{label}</Text></TactilePressable>)}</View>
        </View>}
        {confirmReturn && <View style={styles.confirmation}><Text style={styles.title}>确认交还</Text><Text style={styles.caption}>设备确认后，Pajio 会恢复读取与操作。</Text>
          <View style={styles.row}><Text style={styles.flexText}>已离开密码、验证码等私密页面</Text><Switch accessibilityLabel="已离开私密页面" value={safeScreen} onValueChange={setSafeScreen}/></View>
          <View style={styles.row}><Text style={styles.flexText}>允许 Pajio 继续操作这台设备</Text><Switch accessibilityLabel="允许 Pajio 继续操作" value={scopeConfirmed} onValueChange={setScopeConfirmed}/></View>
          <View style={styles.row}><PrimaryButton style={styles.flex} label="确认交还" disabled={!safeScreen || !scopeConfirmed} onPress={() => {void giveBack();}}/><PrimaryButton label="继续接管" tone="quiet" onPress={() => setConfirmReturn(false)}/></View>
        </View>}
        <PrimaryButton label="结束连接，保持暂停" tone="quiet" onPress={() => stop('closed')}/>
      </> : <PrimaryButton label={busy ? isReturning ? '结束画面并检查状态' : '取消连接，保持暂停' : access?.state === 'paused' ? '重新接管' : '接管设备'} disabled={Platform.OS === 'web' || !access?.supported || !deviceIdentifier(resource)} onPress={() => {if (busy) stop('closed'); else void begin();}}/>}
      {!busy && !viewer && <PrimaryButton label="刷新设备状态" tone="quiet" onPress={() => {setError(''); void refresh();}}/>}
    </ScrollView>
  </View>;
}

const makeStyles = (c: AppColors) => StyleSheet.create({
  root: {flex: 1, backgroundColor: c.canvas}, header: {flexDirection: 'row', alignItems: 'center', gap: 12, paddingHorizontal: 16, paddingVertical: 10},
  heading: {flex: 1, gap: 4}, title: {fontSize: 17, fontWeight: '600', color: c.ink}, caption: {fontSize: 13, lineHeight: 19, color: c.muted},
  videoBox: {flex: 1, minHeight: 180, backgroundColor: palettes.night.canvas, overflow: 'hidden'}, video: {flex: 1, backgroundColor: palettes.night.canvas},
  cover: {position: 'absolute', top: 0, right: 0, bottom: 0, left: 0, alignItems: 'center', justifyContent: 'center', gap: 15, padding: 30, backgroundColor: palettes.night.canvas},
  coverTitle: {fontSize: 18, color: palettes.night.ink}, coverText: {fontSize: 14, lineHeight: 22, color: palettes.night.muted, textAlign: 'center'},
  controls: {flexGrow: 0, maxHeight: '50%'}, controlsContent: {padding: 16, gap: 12}, row: {flexDirection: 'row', alignItems: 'center', gap: 10},
  flex: {flex: 1}, flexText: {flex: 1, fontSize: 14, lineHeight: 21, color: c.ink}, error: {fontSize: 13, lineHeight: 20, color: c.danger},
  keyRow: {flexDirection: 'row', flexWrap: 'wrap', gap: 8}, key: {minWidth: 44, minHeight: 44, paddingHorizontal: 16, justifyContent: 'center', alignItems: 'center', borderRadius: 12, backgroundColor: c.soft}, keyText: {fontSize: 14, color: c.ink},
  keyboard: {gap: 10}, input: {flex: 1, minHeight: 48, fontSize: 16, color: c.ink, borderWidth: 1, borderColor: c.outline, borderRadius: 12, paddingHorizontal: 12},
  confirmation: {gap: 14, padding: 16, borderWidth: 1, borderColor: c.line, borderRadius: 16, backgroundColor: c.surface},
});
