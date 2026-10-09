import {useEffect, useMemo, useRef, useState} from 'react';
import {ActivityIndicator, StyleSheet, Text, View, useWindowDimensions} from 'react-native';
import {WebView} from 'react-native-webview';
import {ArrowLeft, FileText, RefreshCw} from 'lucide-react-native';
import {Connection, scopeOf} from './core';
import {serviceFetch} from './transport';
import {useAppTheme, useThemedStyles, type AppColors} from './app-theme';
import {PrimaryButton, TactilePressable} from './experience/primitives';
import {ArtifactApi, ArtifactDocument, artifactNavigationAllowed, artifactPreviewDocument} from './artifact-client';
import {digestArtifact, shareArtifact} from './artifact-share';
import {ongoingTime} from './ongoing-management';
import ArtifactChoicePanel from './ArtifactChoicePanel';

type Props = {connection: Connection; artifactId: string; onBack: () => void; onTask?: (id: string) => void; onArtifact?: (id: string) => void};
const message = (cause: unknown) => cause instanceof Error ? cause.message : '暂时无法打开这份结果，请重试。';
export default function ArtifactPanel(props: Props) {return <ArtifactSession key={`${scopeOf(props.connection)}|${props.artifactId}`} {...props}/>;}
function ArtifactSession({connection, artifactId, onBack, onTask, onArtifact}: Props) {
  const {colors: c, mode} = useAppTheme(), s = useThemedStyles(makeStyles), dimensions = useWindowDimensions();
  const api = useMemo(() => new ArtifactApi(connection, digestArtifact, serviceFetch), [connection]);
  const [document, setDocument] = useState<ArtifactDocument | null>(null), [loading, setLoading] = useState(true), [error, setError] = useState('');
  const [revision, setRevision] = useState(0), [sharing, setSharing] = useState(false), [renderFailed, setRenderFailed] = useState(false);
  const session = useRef({live: true, sharing: false});
  useEffect(() => {
    const current = {live: true, sharing: false}; session.current = current;
    return () => {current.live = false;};
  }, [api]);
  useEffect(() => {
    let live = true;
    api.document(artifactId).then(value => {if (live) setDocument(value);})
      .catch(cause => {if (live) setError(message(cause));}).finally(() => {if (live) setLoading(false);});
    return () => {live = false;};
  }, [api, artifactId, revision]);
  const html = useMemo(() => document ? artifactPreviewDocument(document.html, c.surface) : '', [document, c.surface]);
  const refresh = () => {setDocument(null); setLoading(true); setRenderFailed(false); setError(''); setRevision(value => value + 1);};
  const share = async () => {
    const current = session.current;
    if (!document || !current.live || current.sharing) return;
    current.sharing = true; setSharing(true); setError('');
    try {await shareArtifact(api, document.metadata, () => current.live);}
    catch (cause) {if (current.live) setError(message(cause));}
    finally {current.sharing = false; if (current.live) setSharing(false);}
  };
  return <View style={s.stack}>
    <View style={s.header}><TactilePressable accessibilityLabel="返回上一页" onPress={onBack} disabled={sharing} style={s.back}><ArrowLeft size={18} color={c.ink}/><Text style={s.link}>返回</Text></TactilePressable><TactilePressable accessibilityLabel="重新读取图文结果" onPress={refresh} disabled={loading || sharing} style={s.round}>{loading ? <ActivityIndicator color={c.accent}/> : <RefreshCw size={19} color={c.ink}/>}</TactilePressable></View>
    {error ? <View style={s.notice}><Text style={s.error} accessibilityLiveRegion="polite">{error}</Text><PrimaryButton label={document ? '重新打开预览' : '重新读取'} tone="quiet" disabled={sharing} loading={loading} onPress={refresh}/></View> : null}
    {!document && loading ? <View style={s.card}><ActivityIndicator color={c.accent}/><Text style={s.secondary}>正在读取并校验这份结果…</Text></View> : null}
    {document ? <>
      <View style={s.card}><View style={s.header}><FileText size={24} color={c.accent}/><Text style={s.caption}>第 {document.metadata.revision} 版</Text></View><Text accessibilityRole="header" style={s.title}>{document.metadata.title}</Text><Text selectable style={s.body}>{document.metadata.summary}</Text><Text style={s.caption}>保存于 {ongoingTime(document.metadata.created_at)} · {(document.metadata.size / 1024).toFixed(1)} KB</Text></View>
      <View style={[s.preview, {height: Math.max(380, Math.min(760, dimensions.height * .7))}]}>
        {/* Let every URL reach our deny-by-default callback. A narrower WebView
            whitelist would hand excluded links to React Native Linking first. */}
        {!renderFailed ? <WebView key={`${artifactId}|${revision}|${mode}`} source={{html, baseUrl: 'about:blank'}} originWhitelist={['*']}
          onShouldStartLoadWithRequest={request => artifactNavigationAllowed(request.url, request.isTopFrame)}
          javaScriptEnabled javaScriptCanOpenWindowsAutomatically={false} setSupportMultipleWindows
          onOpenWindow={() => { /* Untrusted result popups are never handed to the OS. */ }}
          incognito cacheEnabled={false} sharedCookiesEnabled={false} thirdPartyCookiesEnabled={false} domStorageEnabled={false}
          allowFileAccess={false} allowFileAccessFromFileURLs={false} allowUniversalAccessFromFileURLs={false} mixedContentMode="never"
          geolocationEnabled={false} mediaPlaybackRequiresUserAction allowsInlineMediaPlayback={false} allowsAirPlayForMediaPlayback={false}
          allowsLinkPreview={false} dataDetectorTypes="none" nestedScrollEnabled showsVerticalScrollIndicator
          onError={() => {setRenderFailed(true); setError('预览暂时没有打开，文件仍保留。可以重新读取或保存原文件。');}}
          onContentProcessDidTerminate={() => {setRenderFailed(true); setError('预览进程已退出，请重新打开。');}}
          style={s.webview}/>
          : <View style={s.card}><Text style={s.secondary}>预览暂不可用。可重试或保存原文件。</Text><PrimaryButton label="重试预览" tone="quiet" onPress={refresh}/></View>}
      </View>
      <Text style={s.caption}>此处只展示已保存的图文。外部链接和联网操作已关闭，文件校验通过不代表内容或呈现已经核对。</Text>
      <ArtifactChoicePanel connection={connection} artifact={document.metadata} onTask={onTask} onArtifact={onArtifact}/>
      <PrimaryButton label="保存或分享 HTML 原件" loading={sharing} onPress={() => {void share();}}/>
      <View style={s.card}><Text style={s.heading}>依据与说明</Text>
        <Facts title="成果注明的来源" values={document.metadata.sources} empty="这份成果尚未注明来源。"/>
        {document.metadata.assumptions.length ? <Facts title="采用的假设" values={document.metadata.assumptions}/> : null}
        {document.metadata.limitations.length ? <Facts title="尚未覆盖的部分" values={document.metadata.limitations}/> : null}
        <Text style={s.caption}>内容核对：{document.metadata.checks.content === 'verified' ? '已记录' : '尚未记录'} · 呈现核对：{document.metadata.checks.render === 'verified' ? '已记录' : '尚未记录'}</Text>
      </View>
      {onTask ? <PrimaryButton label="查看生成这份结果的任务" tone="quiet" disabled={sharing} onPress={() => onTask(document.metadata.task_id)}/> : null}
      {document.metadata.previous_id && onArtifact ? <PrimaryButton label="查看上一版" tone="quiet" disabled={sharing} onPress={() => onArtifact(document.metadata.previous_id!)}/> : null}
    </> : null}
  </View>;
}
function Facts({title, values, empty}: {title: string; values: string[]; empty?: string}) {
  const s = useThemedStyles(makeStyles);
  return <View style={s.facts}><Text style={s.heading}>{title}</Text>{values.length ? values.map((value, index) => <Text key={index} selectable style={s.secondary}>{value}</Text>) : <Text style={s.secondary}>{empty}</Text>}</View>;
}
const makeStyles = (c: AppColors) => StyleSheet.create({
  stack: {gap: 15}, header: {flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 10},
  back: {minHeight: 44, flexDirection: 'row', alignItems: 'center', gap: 8}, round: {width: 44, height: 44, alignItems: 'center', justifyContent: 'center'},
  card: {backgroundColor: c.surface, borderWidth: 1, borderColor: c.line, borderRadius: 20, padding: 18, gap: 12},
  title: {fontSize: 24, lineHeight: 34, fontWeight: '600', color: c.ink}, heading: {fontSize: 16, lineHeight: 25, fontWeight: '500', color: c.ink},
  body: {fontSize: 16, lineHeight: 26, color: c.ink}, secondary: {fontSize: 14, lineHeight: 24, color: c.muted}, caption: {fontSize: 12, lineHeight: 20, color: c.muted},
  link: {fontSize: 15, color: c.accent}, error: {fontSize: 14, lineHeight: 23, color: c.danger}, notice: {gap: 12}, facts: {gap: 7},
  preview: {overflow: 'hidden', borderRadius: 18, borderColor: c.line, borderWidth: 1, backgroundColor: c.surface}, webview: {flex: 1, backgroundColor: 'transparent'},
});
