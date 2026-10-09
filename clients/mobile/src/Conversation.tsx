import {conversationThemeScript} from './appearance';
import {useAppTheme, useThemedStyles, type AppColors} from './app-theme';
import {useEffect, useMemo, useRef, useState} from 'react';
import {ActivityIndicator, Pressable, StyleSheet, Text, useWindowDimensions, View} from 'react-native';
import {useNetworkState} from 'expo-network';
import {ArrowUpRight, Mic} from 'lucide-react-native';
import {WebView} from 'react-native-webview';
import {connectionEndpoint, connectionHeaders, scopeOf} from './core';
import VoiceComposer from './VoiceComposer';
import {composerScript, readComposerState, type ComposerCommand, type ComposerState} from './native-composer';
import {allowsConversationNavigation, nativeConversationLink} from './conversationLink';

import type {ConversationProps} from './conversation-props';
import {AppDock} from './experience/AppDock';
import {conversationTextScaleScript, isDeviceOffline} from './conversation-presentation';
import {artifactNavigationScript, readArtifactNavigation} from './artifact-navigation';

// A changed endpoint/identity must not leave another connection's WebView visible.
export default function Conversation(props: ConversationProps) {
  const url = nativeConversationLink(connectionEndpoint(props.connection, true), props.connection.identity, props.record);
  return <ConversationPage key={scopeOf(props.connection) + '|' + url + '|' + (props.connection.session?.credentialId ?? props.connection.development?.expiresAt ?? '')} {...props} url={url}/>;
}

function ConversationPage({url, active = true, visible = true, showComposer = true, compactComposer = false, connection, reviewRequest, content, navigation, onCapture, onAdd, onSend, onOpenChat, onArtifact, inputScope}: ConversationProps & {url: string}) {
  const {colors: c, mode} = useAppTheme();
  const s = useThemedStyles(makeStyles);

  const web = useRef<WebView>(null);
  const {fontScale} = useWindowDimensions();
  const offline = isDeviceOffline(useNetworkState());
  const themeScript = conversationThemeScript(mode) + conversationTextScaleScript(fontScale) + (onArtifact ? artifactNavigationScript(connection.identity) : '');
  useEffect(() => {web.current?.injectJavaScript(themeScript);}, [themeScript]);
  const [snapshot,setSnapshot] = useState<ComposerState | null>(null);
  const snapshotRef = useRef<ComposerState | null>(null), sequence = useRef(0);
  const retiredPages = useRef(new Set<string>());
  const [loading, setLoading] = useState(true);
  const [slow, setSlow] = useState(false);
  const [error, setError] = useState('');
  const [expired, setExpired] = useState(false);
  useEffect(() => {
    const expiresAt=connection.session?.expiresAt || connection.development?.expiresAt;
    if (!expiresAt) return;
    const delay = Math.max(0, Date.parse(expiresAt) - Date.now());
    const timer = setTimeout(() => setExpired(true), delay + 1);
    return () => clearTimeout(timer);
  }, [connection.development, connection.session]);
  const source = useMemo(() => {
    if (expired) return null;
    try {return {uri: url, headers: connectionHeaders(connection)};}
    catch {return null;}
  }, [url, connection, expired]);
  // The page can acknowledge draft state only, never request native capabilities.
  const visibilityScript = `window.WearingHost && window.WearingHost.setActive(${active && visible ? 'true' : 'false'}); true;`;
  const reviewScript = reviewRequest ? `window.WearingHost && window.WearingHost.openReview && window.WearingHost.openReview(${JSON.stringify(reviewRequest)}); true;` : 'true;';
  useEffect(() => {if(active && visible)web.current?.injectJavaScript(reviewScript);}, [reviewScript,active,visible]);
  useEffect(() => {web.current?.injectJavaScript(visibilityScript);}, [visibilityScript]);
  useEffect(() => {
    if (!loading) return;
    const timer = setTimeout(() => setSlow(true), 12000);
    return () => clearTimeout(timer);
  }, [loading]);
  function retry() {
    try {connectionHeaders(connection);}
    catch {setExpired(true); return;}
    setError(''); setSlow(false); setLoading(true); web.current?.reload();
  }
  function command(value: ComposerCommand) {
    const current = snapshotRef.current;
    if (!source || !active || !current?.ready || loading || error) return null;
    const seq = ++sequence.current;
    web.current?.injectJavaScript(composerScript(current, seq, value));
    return seq;
  }
  const pairingExpired = !source;
  const message = pairingExpired ? (connection.session?'请到「我的 → 连接与身份」重新登录。本机草稿和录音仍会保留。':'短期配对已过期，请在电脑上重新生成链接。本机草稿和录音仍会保留。') : offline ? '当前没有网络连接。恢复连接后，点「重新打开」继续。' : error || (slow ? '连接比平时慢，可以稍候或重试。' : '正在打开对话…');
  const expandedComposer = showComposer && !compactComposer;
  return <View style={s.page}>
    <View style={s.page}>
    <View style={[s.webContent, !visible && s.retained]} pointerEvents={visible ? 'auto' : 'none'} accessibilityElementsHidden={!visible} importantForAccessibility={visible ? 'auto' : 'no-hide-descendants'}>
    {source && <WebView ref={web} source={source} style={s.page}
      injectedJavaScriptBeforeContentLoaded={themeScript}
      originWhitelist={['*']}
      scalesPageToFit={false} textZoom={100} setBuiltInZoomControls={false} setDisplayZoomControls={false}
      allowsBackForwardNavigationGestures={false} bounces={false}
      onShouldStartLoadWithRequest={request => {
        try {connectionHeaders(connection); return allowsConversationNavigation(request.url, url);}
        catch {return false;}
      }}
      onOpenWindow={() => {}}
      onLoadStart={() => {setLoading(true); setSlow(false); setError('');if(snapshotRef.current)retiredPages.current.add(snapshotRef.current.pageId);snapshotRef.current=null;setSnapshot(null);sequence.current=0;}}
      onLoadEnd={() => {setLoading(false); web.current?.injectJavaScript(themeScript+visibilityScript+(active?reviewScript:"")+'document.dispatchEvent(new Event("wearing-composer-state")); true;');}}
      onMessage={event=>{
        const artifactId = readArtifactNavigation(event.nativeEvent.data, event.nativeEvent.url, connection);
        if (artifactId && active && visible) {onArtifact?.(artifactId); return;}
        const value=readComposerState(event.nativeEvent.data,event.nativeEvent.url,connection);
        if(!value||retiredPages.current.has(value.pageId)||(snapshotRef.current && snapshotRef.current.pageId!==value.pageId))return;
        if(snapshotRef.current?.pageId===value.pageId && value.ackSeq<snapshotRef.current.ackSeq)return;
        snapshotRef.current=value; sequence.current=Math.max(sequence.current,value.ackSeq);setSnapshot(value);
      }}
      onError={() => {setError('暂时没打开对话，请检查 Pajio 的连接。'); setLoading(false);}}
      onHttpError={event => {if (event.nativeEvent.url.split('#')[0] === url.split('#')[0]) {setError('对话服务暂时不可用，可以稍后重试。'); setLoading(false);}}}
      onContentProcessDidTerminate={() => {setError('对话页面需要重新载入，重新打开后可恢复已保存的本机草稿。'); setLoading(false);}}
      onRenderProcessGone={() => {setError('对话页面需要重新载入，重新打开后可恢复已保存的本机草稿。'); setLoading(false);}}
      renderError={() => <View style={s.page}/>}
      automaticallyAdjustContentInsets={false} contentInsetAdjustmentBehavior="never"
      automaticallyAdjustsScrollIndicatorInsets={false}
      keyboardDisplayRequiresUserAction={true}
      allowsInlineMediaPlayback mediaPlaybackRequiresUserAction
      javaScriptCanOpenWindowsAutomatically={false} mixedContentMode="never"
      allowFileAccess={false} allowFileAccessFromFileURLs={false} allowUniversalAccessFromFileURLs={false}
    />}
    {(loading || error || pairingExpired) ? <View style={s.status} accessibilityLiveRegion="polite">
      {loading && !slow && !pairingExpired && !offline ? <ActivityIndicator color={c.accent} size="small"/> : null}
      <Text style={s.message}>{message}</Text>
      {!pairingExpired && (error || slow || offline) ? <Pressable accessibilityRole="button" accessibilityLabel="重新打开对话" onPress={retry} style={({pressed}) => [s.retry, pressed && s.pressed]}><Text style={s.retryText}>重新打开</Text></Pressable> : null}
    </View> : null}
    </View>
    {!visible ? content : null}
    </View>
    <AppDock>
      <View style={!expandedComposer && s.hiddenComposer} accessibilityElementsHidden={!expandedComposer} importantForAccessibility={expandedComposer ? 'auto' : 'no-hide-descendants'}>
      <VoiceComposer connection={connection} active={active&&expandedComposer&&!loading&&!error&&!pairingExpired} offline={offline} snapshot={snapshot} command={command} onCapture={onCapture} onAdd={onAdd} onSend={onSend} inputScope={inputScope}/>
      </View>
      {showComposer && compactComposer && onOpenChat ? <Pressable accessibilityRole="button" accessibilityLabel={snapshot?.text ? '回到聊天，继续未发送的草稿' : '打开聊天，交代一件事'} onPress={onOpenChat} style={({pressed}) => [s.compactComposer, pressed && s.pressed]}>
        <Mic size={18} color={c.muted}/><Text style={s.compactText}>{snapshot?.text ? '继续草稿' : '交代一件事'}</Text><ArrowUpRight size={18} color={c.muted}/>
      </Pressable> : null}
      {navigation}
    </AppDock>
  </View>;
}
const makeStyles = (c: AppColors) => StyleSheet.create({
  page: {flex: 1, backgroundColor: 'transparent'},
  hiddenComposer: {display: 'none'},
  compactComposer: {minHeight: 48, paddingHorizontal: 14, paddingVertical: 10, flexDirection: 'row', gap: 10, alignItems: 'center', backgroundColor: c.surface, borderRadius: 16, borderWidth: StyleSheet.hairlineWidth, borderColor: c.line},
  compactText: {flex: 1, fontSize: 15, lineHeight: 22, color: c.ink},
  // WKWebView must keep a layout when a review tab is the launch route. A
  // display:none ancestor can stall its initial load and disable every composer.
  webContent: {position: 'absolute', top: 0, right: 0, bottom: 0, left: 0},
  retained: {opacity: 0, zIndex: -1},
  status: {position: 'absolute', top: 0, right: 0, bottom: 0, left: 0, alignItems: 'center', justifyContent: 'center', padding: 32, gap: 16, backgroundColor: c.canvas},
  message: {fontSize: 15, lineHeight: 24, textAlign: 'center', color: c.muted},
  retry: {minHeight: 44, paddingHorizontal: 20, paddingVertical: 12, borderRadius: 14, backgroundColor: c.soft},
  retryText: {fontSize: 15, color: c.accent, fontWeight: '600'},
  pressed: {opacity: .7},
});
