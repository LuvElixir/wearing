import {useEffect, useMemo, useRef, useState} from 'react';
import {ActivityIndicator, AppState, Image, StyleSheet, View} from 'react-native';
import {Button, Text} from 'react-native-paper';
import {useAudioPlayer, useAudioPlayerStatus} from 'expo-audio';
import {ApiError, connectionHeaders, type Connection} from './core';
import {useAppTheme, useThemedStyles, type AppColors} from './app-theme';
import {audioOriginalState, downloadRemoteOriginal, OriginalSource, RemoteAsset, remoteOriginalKind, remoteOriginalSource} from './remote-original-model';
import {shareOriginalBytes} from './workspace-share';
import {serviceFetch} from './transport';

function AudioOriginal({source, connection, retry}: {source: OriginalSource; connection: Connection; retry: () => void}) {
  const {colors: c} = useAppTheme(), s = useThemedStyles(styles);
  const player = useAudioPlayer(source, {updateInterval: 250});
  const status = useAudioPlayerStatus(player);
  const [error, setError] = useState(''), [seeking, setSeeking] = useState(false);
  const active = useRef(true), operation = useRef(false);
  const state = audioOriginalState(status, error);
  useEffect(() => {
    active.current = true;
    const subscription = AppState.addEventListener('change', next => {
      if (next !== 'active') {try {player.pause();} catch { /* Native lifetime may already have ended. */ }}
    });
    // SDK57 releases and stops this hook's player on unmount. Never call its disposed object here.
    return () => {active.current = false; subscription.remove();};
  }, [player]);
  useEffect(() => {
    if (state !== 'loading') return;
    const timer = setTimeout(() => {
      if (!active.current) return;
      try {player.pause();} catch { /* Preserve recovery when the native load failed. */ }
      setError('原录音加载超时，请重试或打开原件。');
    }, 20000);
    return () => clearTimeout(timer);
  }, [state, player]);
  async function toggle() {
    if (operation.current) return;
    operation.current = true;
    try {
      if (status.playing) {player.pause(); return;}
      connectionHeaders(connection); setError('');
      if (status.didJustFinish || status.duration > 0 && status.currentTime >= status.duration) {
        setSeeking(true); await player.seekTo(0);
        if (!active.current) return;
      }
      player.play();
    } catch {if (active.current) setError('原录音暂时无法播放，请重试或打开原件。');}
    finally {operation.current = false; if (active.current) setSeeking(false);}
  }
  return <View style={s.preview}>
    {state === 'loading' ? <View style={s.loading}><ActivityIndicator color={c.muted}/><Text style={s.detail}>正在加载原录音…</Text></View> : null}
    {state === 'error' ? <><Text accessibilityLiveRegion="polite" style={s.error}>{error || '原录音暂时无法播放，请重试或打开原件。'}</Text><Button onPress={retry}>重新加载录音</Button></> : <Button loading={seeking} disabled={seeking || state === 'loading' && !status.playing} onPress={() => {void toggle();}}>{status.playing ? '暂停录音' : '听听原录音'}</Button>}
    {status.isLoaded && Number.isFinite(status.duration) && status.duration > 0 ? <Text style={s.detail}>{Math.floor(status.currentTime)} / {Math.ceil(status.duration)} 秒</Text> : null}
  </View>;
}

function ImageOriginal({source, name, retry}: {source: OriginalSource; name: string; retry: () => void}) {
  const {colors: c} = useAppTheme(), s = useThemedStyles(styles);
  const [state, setState] = useState<'loading' | 'loaded' | 'error'>('loading');
  useEffect(() => {
    if (state !== 'loading') return;
    const timer = setTimeout(() => setState('error'), 20000);
    return () => clearTimeout(timer);
  }, [state]);
  return <View style={s.preview}>
    {state === 'error' ? <><Text accessibilityLiveRegion="polite" style={s.error}>图片暂时没有加载出来，请重试或打开原件。</Text><Button onPress={retry}>重新加载图片</Button></> : <Image source={{...source, cache: 'reload'}} accessibilityLabel={name} style={s.image} onLoad={() => setState('loaded')} onError={() => setState('error')}/>}
    {state === 'loading' ? <View style={s.loading}><ActivityIndicator color={c.muted}/><Text style={s.detail}>正在加载图片…</Text></View> : null}
  </View>;
}

function OriginalContent({connection, asset}: {connection: Connection; asset: RemoteAsset}) {
  const s = useThemedStyles(styles);
  const active = useRef(true), busy = useRef(false);
  const [sharing, setSharing] = useState(false), [shareError, setShareError] = useState(''), [generation, setGeneration] = useState(0);
  const kind = remoteOriginalKind(asset);
  const preview = useMemo(() => {
    try {return {source: remoteOriginalSource(connection, asset), error: ''};}
    catch (cause) {return {source: null, error: cause instanceof ApiError ? cause.message : '原件暂时无法读取，请检查连接。'};}
  }, [connection, asset]);
  useEffect(() => {active.current = true; return () => {active.current = false;};}, []);
  const retry = () => setGeneration(current => current + 1);
  async function share() {
    if (busy.current) return;
    busy.current = true; setSharing(true); setShareError('');
    try {await shareOriginalBytes(() => downloadRemoteOriginal(connection, asset, serviceFetch), asset.name || '原件', asset.mime, () => active.current);}
    catch (cause) {if (active.current) setShareError(cause instanceof Error ? cause.message : '原件暂时无法打开，请重试。');}
    finally {busy.current = false; if (active.current) setSharing(false);}
  }
  return <View style={s.original}>
    <Text style={s.name}>{asset.name || '原件'}</Text>
    {preview.source ? kind === 'image' ? <ImageOriginal key={generation} source={preview.source} name={asset.name} retry={retry}/> : kind === 'audio' ? <AudioOriginal key={generation} source={preview.source} connection={connection} retry={retry}/> : <Text style={s.detail}>这种格式不支持直接预览，可打开原件查看。</Text> : <Text style={s.error}>{preview.error}</Text>}
    <Button accessibilityLabel={`打开或分享原件：${asset.name}`} loading={sharing} disabled={sharing || !preview.source} onPress={() => {void share();}}>打开 / 分享原件</Button>
    {shareError ? <Text accessibilityLiveRegion="polite" style={s.error}>{shareError}</Text> : null}
  </View>;
}

export default function RemoteOriginal(props: {connection: Connection; asset: RemoteAsset}) {
  // A source/credential/identity change disposes media and fences any pending export.
  const {connection, asset} = props;
  const key = `${connection.endpoint}|${connection.identity}|${connection.development?.expiresAt || ''}|${asset.id}|${asset.mime}`;
  return <OriginalContent key={key} {...props}/>;
}

const styles = (c: AppColors) => StyleSheet.create({
  original: {gap: 8, marginVertical: 12}, preview: {gap: 8}, image: {width: '100%', height: 240, resizeMode: 'contain'},
  name: {color: c.ink, fontSize: 15, lineHeight: 22}, detail: {color: c.muted, fontSize: 13, lineHeight: 21},
  error: {color: c.danger, fontSize: 13, lineHeight: 21}, loading: {flexDirection: 'row', justifyContent: 'center', alignItems: 'center', gap: 9, paddingVertical: 12},
});
