import {useEffect, useRef, useState} from 'react';
import {AppState, Modal, Platform, ScrollView, StyleSheet, Text, View} from 'react-native';
import {scopeOf, type Connection} from './core';
import {storage} from './storage';
import {useThemedStyles, type AppColors} from './app-theme';
import {PrimaryButton} from './experience/primitives';
import {NativeActionRunner} from './native-action-runner';
import {createNativeActionDriver, nativeActionClient, nativeActionNonce, nativeActionsChanged, observeNativeActions} from './native-action-runtime';
import {nativeMethodLabel, nativeRequestSummary, validateNativeDispatch, isNativeWrite, isNativeEdit, type NativeDevice, type NativeRequest} from './native-action-model';
import type {NativeActionClient} from './native-action-client';

type Pending = {request:NativeRequest; device:NativeDevice; runner:NativeActionRunner; connection:string; generation:number};
/** Mounted once for the current authenticated identity, independent of visible tab. */
export function NativeActionSession({connection}: {connection:Connection}) {
  return <NativeActionSessionContent key={scopeOf(connection)} connection={connection}/>;
}
function NativeActionSessionContent({connection}: {connection:Connection}) {
  const s = useThemedStyles(styles), scope = scopeOf(connection);
  const [pending,setPending] = useState<Pending | null>(null), [busy,setBusy] = useState(false), [error,setError] = useState('');
  const generation = useRef(0), pendingRef = useRef<Pending | null>(null), locked = useRef(false);
  const credentialVersion = connection.session?.accessToken || connection.development?.accessToken || '';
  useEffect(() => {
    if (Platform.OS !== 'ios') return;
    const invalidate = () => ++generation.current;
    let mounted = true, epoch = invalidate(), running = false, client:NativeActionClient | null = null, session = '', timer:ReturnType<typeof setTimeout> | undefined;
    let device:NativeDevice | null = null;
    const active = () => mounted && generation.current === epoch && AppState.currentState === 'active';
    const stop = () => {
      epoch = ++generation.current;
      if (timer) clearTimeout(timer);
      const old = session, oldClient = client; session = ''; device = null;
      pendingRef.current = null; setPending(null); setBusy(false); setError('');
      if (oldClient && old) void oldClient.disconnect(old).catch(() => {});
    };
    async function tick() {
      if (running || !active()) return;
      running = true;
      const started = epoch;
      try {
        client = client || await nativeActionClient(connection);
        if (!client || !active() || epoch !== started) return;
        const driver = createNativeActionDriver(() => active() && epoch === started);
        if (!driver) return;
        if (!session) {
          device = await client.device();
          if (!active() || epoch !== started || !device?.enabled) return;
          const capabilities = await driver.capabilities(device.policy);
          if (!active() || epoch !== started) return;
          const opened = nativeActionNonce();
          device = await client.connect(device,opened,capabilities);
          if (!active() || epoch !== started) {void client.disconnect(opened).catch(() => {}); return;}
          session = opened;
          const recovery = new NativeActionRunner(storage,scope,client,driver,() => active() && epoch === started);
          await recovery.recover();
        }
        if (!active() || epoch !== started || !device) return;
        // A permission change in Settings revokes local execution immediately.
        const capabilities = await driver.capabilities(device.policy);
        if (!active() || epoch !== started) return;
        if (capabilities.join('|') !== [...device.capabilities].sort().join('|')) {stop(); return;}
        const requests = await client.poll(session);
        if (!active() || epoch !== started) return;
        const r = requests[0];
        if (pendingRef.current && (!r || r.id !== pendingRef.current.request.id)) {pendingRef.current = null; setPending(null);}
        if (!r || pendingRef.current || locked.current) return;
        validateNativeDispatch(r,device,session,Date.now());
        const runner = new NativeActionRunner(storage,scope,client,driver,() => active() && epoch === started);
        if (isNativeWrite(r.command.method) || r.command.method === 'location.read') {
          const next = {request:r,device,runner,connection:session,generation:started}; pendingRef.current = next; setPending(next); setError('');
        } else {
          locked.current = true;
          try {await runner.run(r,device,session,true);} finally {locked.current = false;}
        }
      } catch {
        // Detailed native failures remain in the scoped journal/history. A lost
        // network call must not re-dispatch an admitted OS operation.
        if (active() && epoch === started) stop();
      } finally {
        running = false;
        if (active()) timer = setTimeout(() => void tick(),3000);
      }
    }
    const app = AppState.addEventListener('change', state => {if (state !== 'active') stop(); else {epoch = ++generation.current; void tick();}});
    const changed = observeNativeActions(() => {stop(); if (AppState.currentState === 'active') void tick();});
    void tick();
    return () => {mounted = false; epoch = invalidate(); if (timer) clearTimeout(timer); app.remove(); changed(); pendingRef.current = null; const old = session; if (client && old) void client.disconnect(old).catch(() => {});};
    // Credentials and full scope, not token refresh object identity, own this executor.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scope,credentialVersion]);
  async function decide(approve:boolean) {
    const p = pendingRef.current;
    if (!p || locked.current || p.generation !== generation.current || AppState.currentState !== 'active') return;
    locked.current = true; setBusy(true); setError('');
    try {await p.runner.run(p.request,p.device,p.connection,approve); if (p.generation === generation.current) {pendingRef.current = null; setPending(null);} nativeActionsChanged();}
    catch (cause) {if (p.generation === generation.current) setError(cause instanceof Error ? cause.message : '尚未完成，请稍后在本机能力中核对。');}
    finally {locked.current = false; if (p.generation === generation.current) setBusy(false);}
  }
  return <Modal transparent visible={!!pending} animationType="fade" onRequestClose={() => {if (!busy) void decide(false);}}>
    <View style={s.overlay}><View style={s.card}>
      <Text style={s.title}>{pending ? nativeMethodLabel(pending.request.command.method) : '手机请求'}</Text>
      <ScrollView style={s.scroll}><Text style={s.label}>来自：{pending?.request.task_title || '当前任务'}</Text><Text style={s.body}>{pending ? nativeRequestSummary(pending.request,pending.device.policy) : ''}</Text></ScrollView>
      <Text style={s.label}>{pending && isNativeWrite(pending.request.command.method) ? pending.request.command.method.endsWith('.delete') ? '确认后会从系统应用删除这条记录；这次操作不能在 Pajio 中撤销。' : isNativeEdit(pending.request.command.method) ? '只修改上方列出的内容。系统记录有变化时会停止，需重新读取。' : '确认后将直接保存到这台 iPhone 的系统应用。只允许本次新建。' : '只允许这次获取位置，并用于当前任务。'}</Text>
      {!!error && <Text accessibilityRole="alert" style={s.error}>{error}</Text>}
      <PrimaryButton label={pending && isNativeWrite(pending.request.command.method) ? pending.request.command.method.endsWith('.delete') ? '确认删除这一次记录' : '确认并保存到手机' : '允许这一次位置读取'} loading={busy} disabled={busy} onPress={() => void decide(true)}/>
      <PrimaryButton label="这次不允许" tone="quiet" disabled={busy} onPress={() => void decide(false)}/>
    </View></View>
  </Modal>;
}
const styles = (c:AppColors) => StyleSheet.create({overlay:{flex:1,backgroundColor:c.scrim,padding:22,justifyContent:'center'},card:{backgroundColor:c.surface,borderRadius:28,padding:24,gap:16,maxHeight:'85%'},scroll:{maxHeight:300},title:{fontSize:22,fontWeight:'600',color:c.ink},body:{fontSize:17,lineHeight:26,color:c.ink},label:{fontSize:13,lineHeight:20,color:c.muted},error:{fontSize:14,lineHeight:21,color:c.danger}});
