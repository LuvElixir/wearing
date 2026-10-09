import {useEffect, useRef, useState} from 'react';
import {StyleSheet, Switch, Text, TextInput, View} from 'react-native';
import * as Crypto from 'expo-crypto';
import {type Connection, scopeOf} from './core';
import {storage} from './storage';
import {serviceFetch} from './transport';
import {NotificationClient, notificationInstallation, quietMinute, quietTime, type QuietHours} from './notification-client';
import {useAppTheme, useThemedStyles, type AppColors} from './app-theme';
import {PrimaryButton} from './experience/primitives';
import {observeDiagnosticError} from './diagnostics-client';

export default function QuietHoursPanel({connection}: {connection: Connection}) {return <QuietHoursSession key={scopeOf(connection)} connection={connection}/>;}
function QuietHoursSession({connection}: {connection: Connection}) {
  const {colors: c} = useAppTheme(), s = useThemedStyles(styles);
  const [saved, setSaved] = useState<QuietHours | null>(null), [enabled, setEnabled] = useState(false);
  const [start, setStart] = useState('22:00'), [end, setEnd] = useState('08:00'), [zone, setZone] = useState('Asia/Shanghai');
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [notice, setNotice] = useState('');
  const live = useRef(false), locked = useRef(false);
  const client = async () => new NotificationClient(connection, await notificationInstallation(storage, () => Crypto.randomUUID()), serviceFetch);
  function apply(value: QuietHours) {setSaved(value); setEnabled(value.enabled); setStart(quietTime(value.start_minute)); setEnd(quietTime(value.end_minute)); setZone(value.timezone);}
  async function load() {
    if (locked.current) return;
    locked.current = true; setBusy(true); setError(''); setNotice('');
    try {const result = await (await client()).quietHours(); if (live.current) apply(result);}
    catch (cause) {observeDiagnosticError(connection, 'notifications', cause); if (live.current) setError(cause instanceof Error ? cause.message : '时段未能读取。');}
    finally {locked.current = false; if (live.current) setBusy(false);}
  }
  useEffect(() => {
    live.current = true; let cancelled = false;
    void Promise.resolve().then(() => {if (!cancelled) return load();});
    return () => {cancelled = true; live.current = false;};
    // The parent remounts this editor whenever the connection scope changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  async function save() {
    if (locked.current || !saved) return;
    locked.current = true; setBusy(true); setError(''); setNotice('');
    try {
      const startMinute = quietMinute(start), endMinute = quietMinute(end);
      if (startMinute === endMinute) throw new Error('开始与结束时间不能相同。全天不接收请关闭进展通知。');
      const api = await client();
      if (!live.current) return;
      const result = await api.saveQuietHours({...saved, enabled, start_minute: startMinute, end_minute: endMinute, timezone: zone.trim()});
      if (live.current) {apply(result); setNotice(enabled ? '已保存。安静时段结束后会发送仍有效的进展；通知登记到期时，需要重新登录并开启通知。' : '已关闭安静时段。');}
    } catch (cause) {observeDiagnosticError(connection, 'notifications', cause); if (live.current) setError(cause instanceof Error ? cause.message : '保存尚未确认，请重新读取核对。');}
    finally {locked.current = false; if (live.current) setBusy(false);}
  }
  return <View style={s.card}>
    <View style={s.row}><Text style={s.title}>安静时段</Text><Switch accessibilityLabel="启用安静时段" value={enabled} disabled={busy || !saved} onValueChange={setEnabled} trackColor={{true:c.accent}}/></View>
    <Text style={s.copy}>这台手机在当前身份的通知安排。任务照常推进，确认和结果会留在 App 内。已经交给系统的推送无法撤回。</Text>
    <View style={s.row}><View style={s.field}><Text style={s.label}>开始</Text><TextInput accessibilityLabel="安静时段开始" value={start} onChangeText={setStart} editable={!busy && !!saved} placeholder="22:00" maxLength={5} style={s.input}/></View><View style={s.field}><Text style={s.label}>结束</Text><TextInput accessibilityLabel="安静时段结束" value={end} onChangeText={setEnd} editable={!busy && !!saved} placeholder="08:00" maxLength={5} style={s.input}/></View></View>
    <Text style={s.label}>时区</Text><TextInput accessibilityLabel="安静时段时区" value={zone} onChangeText={setZone} autoCapitalize="none" autoCorrect={false} editable={!busy && !!saved} style={s.input}/>
    <PrimaryButton label="使用手机当前时区" tone="quiet" disabled={busy || !saved} onPress={() => {try {setZone(Intl.DateTimeFormat().resolvedOptions().timeZone);} catch {setError('手机时区未能读取，可填写 Asia/Shanghai。');}}}/>
    {error ? <Text accessibilityRole="alert" style={s.error}>{error}</Text> : null}
    {notice ? <Text accessibilityLiveRegion="polite" style={s.copy}>{notice}</Text> : null}
    <PrimaryButton label="保存安静时段" disabled={busy || !saved} loading={busy} onPress={() => {void save();}}/>
    <PrimaryButton label="重新读取已保存的时段" tone="quiet" disabled={busy} onPress={() => {void load();}}/>
  </View>;
}
const styles = (c: AppColors) => StyleSheet.create({card:{backgroundColor:c.surface,borderRadius:24,padding:20,gap:14},row:{flexDirection:'row',alignItems:'center',justifyContent:'space-between',gap:16},field:{flex:1,gap:8},title:{fontSize:19,fontWeight:'600',color:c.ink},copy:{fontSize:14,lineHeight:23,color:c.muted},label:{fontSize:14,color:c.ink},input:{minHeight:48,fontSize:16,color:c.ink,borderWidth:1,borderColor:c.line,borderRadius:12,paddingHorizontal:12},error:{fontSize:14,lineHeight:23,color:c.danger}});
