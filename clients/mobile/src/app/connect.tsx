import {useEffect, useLayoutEffect, useMemo, useRef, useState} from 'react';
import {router, useLocalSearchParams} from 'expo-router';
import {ActivityIndicator, Platform, Pressable, ScrollView, StyleSheet, Text, View} from 'react-native';
import {SafeAreaProvider, SafeAreaView} from 'react-native-safe-area-context';
import {pairingConnection, WearingApi} from '../core';
import {storage} from '../storage';
import {serviceFetch} from '../transport';
import {AppThemeProvider, useAppTheme, useThemedStyles, type AppColors} from '../app-theme';
import {PajamaBear} from '../PajamaBear';
import {BrandWordmark} from '../BrandWordmark';
import {developmentConnectionsEnabled} from '../development-access';

export default function Connect() {
  return <AppThemeProvider><SafeAreaProvider>{developmentConnectionsEnabled()?<ConnectScreen/>:<PublicEntry/>}</SafeAreaProvider></AppThemeProvider>;
}

function PublicEntry() {
  const {colors:c}=useAppTheme();
  return <SafeAreaView style={{flex:1,backgroundColor:c.canvas,padding:28,justifyContent:'center',gap:24}}><Text style={{color:c.ink,fontSize:22}}>欢迎来到 Pajio</Text><Text style={{color:c.muted,lineHeight:24}}>请回到登录页面，使用邀请码加入或登录已有账号。</Text><Pressable accessibilityRole="button" onPress={()=>router.replace('/')} style={{padding:18,backgroundColor:c.action,borderRadius:20}}><Text style={{color:c.onAction,textAlign:'center'}}>前往登录</Text></Pressable></SafeAreaView>;
}

function ConnectScreen() {
  const {colors: c} = useAppTheme();
  const s = useThemedStyles(makeStyles);
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
  return <SafeAreaView style={s.page}><ScrollView contentContainerStyle={s.content}>
    <View style={s.brand}><PajamaBear size={72}/><View style={{gap: 6}}><BrandWordmark width={88} color={c.ink}/><Text style={s.eyebrow}>开发验收</Text></View></View>
    <Text style={s.title}>连接电脑上的 Pajio</Text>
    <Text style={s.description}>仅用于本轮短期开发验收。请将手机与电脑接入同一可信 Wi-Fi，使用 Expo Go 打开配对链接。连接最多保留 4 小时，到期后需要重新扫码。</Text>
    {pairing.connection ? <View style={s.card}>
      <Text style={s.label}>电脑地址</Text><Text selectable style={s.value}>{pairing.connection.endpoint}</Text>
      <Text style={s.label}>身份</Text><Text style={s.value}>{pairing.connection.identity === 'daily' ? '日常' : pairing.connection.identity}</Text>
      <Text style={s.label}>有效至</Text><Text style={s.value}>{new Date(pairing.connection.development!.expiresAt).toLocaleString()}</Text>
    </View> : null}
    <Text style={s.description}>{Platform.OS === 'web' ? '请用手机上的 Expo Go 打开这份配对链接。' : '连接后可以查看并编辑你的内容。按住说话才会录音，确认发送后才交给 Pajio。'}</Text>
    {pairing.error || error ? <Text style={s.error} accessibilityLiveRegion="polite">{pairing.error || error}</Text> : null}
    <Pressable accessibilityRole="button" accessibilityLabel="验证并连接 Pajio" disabled={!pairing.connection || busy || Platform.OS === 'web'} onPress={connect} style={({pressed}) => [s.button, (!pairing.connection || busy || Platform.OS === 'web') && s.disabled, pressed && s.pressed]}>
      {busy ? <ActivityIndicator color={c.onAction}/> : <Text style={s.buttonText}>连接 Pajio</Text>}
    </Pressable>
    <Pressable accessibilityRole="button" onPress={() => router.replace('/')} style={s.back}><Text style={s.backText}>暂不连接</Text></Pressable>
  </ScrollView></SafeAreaView>;
}
const makeStyles = (c: AppColors) => StyleSheet.create({
  page: {flex: 1, backgroundColor: c.canvas}, content: {padding: 26, paddingTop: 28, gap: 22, maxWidth: 560, width: '100%', alignSelf: 'center'},
  brand: {flexDirection: 'row', alignItems: 'center', gap: 12},
  eyebrow: {fontSize: 12, letterSpacing: 2, color: c.muted}, title: {fontSize: 30, lineHeight: 40, color: c.ink, fontWeight: '600'},
  description: {fontSize: 15, lineHeight: 25, color: c.muted}, card: {borderRadius: 20, padding: 22, backgroundColor: c.surface, borderWidth: 1, borderColor: c.line, gap: 10},
  label: {fontSize: 12, color: c.muted, marginTop: 4}, value: {fontSize: 16, lineHeight: 24, color: c.ink},
  button: {minHeight: 54, padding: 16, alignItems: 'center', justifyContent: 'center', borderRadius: 22, backgroundColor: c.action},
  buttonText: {fontSize: 17, fontWeight: '600', color: c.onAction}, disabled: {opacity: .45}, pressed: {opacity: .7}, error: {fontSize: 14, lineHeight: 22, color: c.danger},
  back: {minHeight: 44, alignItems: 'center', justifyContent: 'center'}, backText: {fontSize: 15, color: c.muted},
});
