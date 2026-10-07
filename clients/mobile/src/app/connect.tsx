import {useEffect, useLayoutEffect, useMemo, useRef, useState} from 'react';
import {router, useLocalSearchParams} from 'expo-router';
import {ActivityIndicator, Platform, Pressable, ScrollView, StyleSheet, Text, View} from 'react-native';
import {SafeAreaProvider, SafeAreaView} from 'react-native-safe-area-context';
import {pairingConnection, WearingApi} from '../core';
import {storage} from '../storage';
import {serviceFetch} from '../transport';

export default function Connect() {
  const params = useLocalSearchParams<{endpoint?: string; identity?: string; accessToken?: string; expiresAt?: string}>();
  const {endpoint, identity, accessToken, expiresAt} = params;
  const pairing = useMemo(() => {
    try {return {connection: pairingConnection({endpoint, identity, accessToken, expiresAt}), error: ''};}
    catch (error) {return {connection: null, error: error instanceof Error ? error.message : '配对链接不完整，请重新扫码。'};}
  }, [endpoint, identity, accessToken, expiresAt]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const live = useRef(true), working = useRef(false);
  const selected = useRef(pairing.connection);
  useLayoutEffect(() => {selected.current = pairing.connection;}, [pairing.connection]);
  useEffect(() => {live.current = true; return () => {live.current = false;};}, []);
  async function connect() {
    if (working.current || !pairing.connection || Platform.OS === 'web') return;
    working.current = true; setBusy(true); setError('');
    const connection = pairing.connection;
    try {
      // Verification is read-only. Pairing never records or sends a draft.
      await new WearingApi(connection, serviceFetch).bootstrap();
      if (!live.current || selected.current !== connection) return;
      await storage.put('connection', connection);
      if (live.current && selected.current === connection) router.replace('/');
    } catch (failure) {if (live.current) setError(failure instanceof Error ? failure.message : '暂时无法连接，请确认手机与电脑在同一 Wi-Fi。');}
    finally {working.current = false; if (live.current) setBusy(false);}
  }
  return <SafeAreaProvider><SafeAreaView style={s.page}><ScrollView contentContainerStyle={s.content}>
    <Text style={s.eyebrow}>WEARING · 开发验收</Text>
    <Text style={s.title}>连接电脑上的 Wearing</Text>
    <Text style={s.description}>仅用于本轮短期开发验收。请将手机与电脑接入同一可信 Wi-Fi，使用 Expo Go 打开配对链接。连接最多保留 4 小时，到期后需要重新扫码。</Text>
    {pairing.connection ? <View style={s.card}>
      <Text style={s.label}>电脑地址</Text><Text selectable style={s.value}>{pairing.connection.endpoint}</Text>
      <Text style={s.label}>身份</Text><Text style={s.value}>{pairing.connection.identity === 'daily' ? '日常' : pairing.connection.identity}</Text>
      <Text style={s.label}>有效至</Text><Text style={s.value}>{new Date(pairing.connection.development!.expiresAt).toLocaleString()}</Text>
    </View> : null}
    <Text style={s.description}>{Platform.OS === 'web' ? '请用手机上的 Expo Go 打开这份配对链接。' : '连接后可以查看并编辑你的内容。按住说话才会录音，确认发送后才交给 Wearing。'}</Text>
    {pairing.error || error ? <Text style={s.error} accessibilityLiveRegion="polite">{pairing.error || error}</Text> : null}
    <Pressable accessibilityRole="button" accessibilityLabel="验证并连接 Wearing" disabled={!pairing.connection || busy || Platform.OS === 'web'} onPress={connect} style={({pressed}) => [s.button, (!pairing.connection || busy || Platform.OS === 'web') && s.disabled, pressed && s.pressed]}>
      {busy ? <ActivityIndicator color="white"/> : <Text style={s.buttonText}>连接 Wearing</Text>}
    </Pressable>
    <Pressable accessibilityRole="button" onPress={() => router.replace('/')} style={s.back}><Text style={s.backText}>暂不连接</Text></Pressable>
  </ScrollView></SafeAreaView></SafeAreaProvider>;
}
const s = StyleSheet.create({
  page: {flex: 1, backgroundColor: '#fafafa'}, content: {padding: 26, paddingTop: 52, gap: 22, maxWidth: 560, width: '100%', alignSelf: 'center'},
  eyebrow: {fontSize: 12, letterSpacing: 2, color: '#666d78'}, title: {fontSize: 30, lineHeight: 40, color: '#272c35', fontWeight: '600'},
  description: {fontSize: 15, lineHeight: 25, color: '#666d78'}, card: {borderRadius: 20, padding: 22, backgroundColor: '#fff', gap: 10},
  label: {fontSize: 12, color: '#666d78', marginTop: 4}, value: {fontSize: 16, lineHeight: 24, color: '#272c35'},
  button: {minHeight: 54, padding: 16, alignItems: 'center', justifyContent: 'center', borderRadius: 22, backgroundColor: '#4562dc'},
  buttonText: {fontSize: 17, fontWeight: '600', color: '#fff'}, disabled: {opacity: .45}, pressed: {opacity: .7}, error: {fontSize: 14, lineHeight: 22, color: '#a33039'},
  back: {minHeight: 44, alignItems: 'center', justifyContent: 'center'}, backText: {fontSize: 15, color: '#666d78'},
});
