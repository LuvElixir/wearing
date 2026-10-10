import {StateSwitch} from './experience/selection';
import {useCallback, useEffect, useMemo, useRef, useState} from 'react';
import {AppState, Linking, Platform, StyleSheet, Text, View} from 'react-native';
import {scopeOf, type Connection} from './core';
import {useThemedStyles, type AppColors} from './app-theme';
import {PrimaryButton} from './experience/primitives';
import {createNativeActionDriver, nativeActionClient, nativeActionsChanged} from './native-action-runtime';
import {emptyNativePolicy, isNativeEdit, nativeRequestSummary, nativeMethodLabel, nativeStateLabel, type NativeDevice, type NativeList, type NativePolicy, type NativeRequest} from './native-action-model';
import type {NativeActionClient} from './native-action-client';

export function NativeActionPanel({connection}: {connection:Connection}) {
  return <NativeActionPanelContent key={scopeOf(connection)} connection={connection}/>;
}
function NativeActionPanelContent({connection}: {connection:Connection}) {
  const s = useThemedStyles(styles), scope = scopeOf(connection), mounted = useRef(false), locked = useRef(false);
  const [device,setDevice] = useState<NativeDevice | null>(null),[policy,setPolicy] = useState<NativePolicy>(emptyNativePolicy),[calendars,setCalendars] = useState<NativeList[]>([]),[reminders,setReminders] = useState<NativeList[]>([]);
  const [items,setItems] = useState<NativeRequest[]>([]),[busy,setBusy] = useState(''),[error,setError] = useState(''),[notice,setNotice] = useState(''),[loaded,setLoaded] = useState(false),[review,setReview] = useState<NativeRequest | null>(null),[inspection,setInspection] = useState('');
  const client = useRef<NativeActionClient | null>(null), active = useCallback(() => mounted.current && AppState.currentState === 'active',[]);
  // Construction only stores active; permissions and operations invoke it later.
  // eslint-disable-next-line react-hooks/refs
  const driver = useMemo(() => createNativeActionDriver(active),[active]);
  async function refresh() {
    const value = await nativeActionClient(connection);
    if (!active()) return;
    client.current = value;
    const next = value ? await value.device() : null;
    if (!active()) return;
    const history = next && value ? await value.history() : [];
    if (!active()) return;
    setDevice(next);setPolicy(next?.policy || emptyNativePolicy());setCalendars(next?.policy.calendars || []);setReminders(next?.policy.reminders || []);setItems(history);setLoaded(true);
  }
  useEffect(() => {mounted.current = true; void Promise.resolve().then(refresh).catch(() => {if (mounted.current) setError('本机能力设置暂未读到，请重试。');}); return () => {mounted.current = false;};
    // Identity keyed by parent; an old identity callback cannot alter this panel.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  },[scope]);
  async function run(label:string, action:()=>Promise<void>) {
    if (locked.current) return;
    locked.current = true;setBusy(label);setError('');setNotice('');
    try {await action();} catch (cause) {if (active()) setError(cause instanceof Error && cause.message !== 'permission' ? cause.message : '系统权限未开启。可以在系统设置中调整后重试。');}
    finally {locked.current = false;if (mounted.current) setBusy('');}
  }
  async function lists(kind:'calendar'|'reminders') {
    if (!driver) return;
    const rows = await driver.lists(kind,true);if (!active()) return;
    if (kind === 'calendar') setCalendars(rows);else setReminders(rows);
  }
  const choose = (kind:'calendars'|'reminders',item:NativeList) => setPolicy(p => ({...p,[kind]:p[kind].some(c=>c.id===item.id) ? p[kind].filter(c=>c.id!==item.id) : [...p[kind],item]}));
  async function save(enabled:boolean) {
    if (!driver || !loaded) return;
    const value = client.current || await nativeActionClient(connection,true);
    if (!value || !active()) return;
    client.current = value;
    const result = await value.configure(device?.revision || 0,enabled,policy);
    nativeActionsChanged();
    if (active()) {setDevice(result);setPolicy(result.policy);setNotice(enabled ? '已保存。保持 Pajio 在前台，任务才能使用所选能力。' : '已停用本机能力，新的任务不会在这台手机执行。');}
  }
  if (Platform.OS !== 'ios') return <Text style={s.description}>iPhone 原生执行请在 iPhone 安装版中设置。</Text>;
  return <View style={s.card}>
    <Text style={s.title}>让 Pajio 使用这台 iPhone</Text>
    <Text style={s.description}>只在 App 前台处理任务。读取和写入范围由你选择；每次新建、修改或删除，都先在手机展示具体内容并确认。离开 App 会停止接收新动作。</Text>
    {!!error && <Text accessibilityRole="alert" style={s.error}>{error}</Text>}{!!notice && <Text accessibilityLiveRegion="polite" style={s.description}>{notice}</Text>}
    <Text style={s.body}>{device?.enabled ? device.online ? '已开启 · 最近连接在前台' : '已开启 · 等待前台连接' : '尚未开启'}</Text>
    <PrimaryButton label="重新读取设置和请求" tone="quiet" disabled={!!busy} onPress={() => void run('刷新',refresh)}/>
    <PrimaryButton label="选择允许读取的系统日历" tone="quiet" disabled={!!busy || !loaded || !driver} onPress={() => void run('日历',()=>lists('calendar'))}/>
    {calendars.map(c=><View key={c.id} style={s.row}><Text style={s.flex}>{c.title}{!c.writable ? ' · 只读' : ''}</Text><StateSwitch accessibilityLabel={'允许任务读取日历：'+c.title} value={policy.calendars.some(l=>l.id===c.id)} disabled={!!busy} onValueChange={()=>choose('calendars',c)}/></View>)}
    <PrimaryButton label="选择允许读取的提醒列表" tone="quiet" disabled={!!busy || !loaded || !driver} onPress={() => void run('提醒',()=>lists('reminders'))}/>
    {reminders.map(c=><View key={c.id} style={s.row}><Text style={s.flex}>{c.title}{!c.writable ? ' · 只读' : ''}</Text><StateSwitch accessibilityLabel={'允许任务读取提醒列表：'+c.title} value={policy.reminders.some(l=>l.id===c.id)} disabled={!!busy} onValueChange={()=>choose('reminders',c)}/></View>)}
    <View style={s.row}><Text style={s.flex}>每次确认后新建日程</Text><StateSwitch accessibilityLabel="允许手机确认后新建日程" disabled={!!busy || !policy.calendars.some(c=>c.writable)} value={policy.calendar_create} onValueChange={v=>setPolicy(p=>({...p,calendar_create:v}))}/></View>
    <View style={s.row}><Text style={s.flex}>每次确认后新建提醒</Text><StateSwitch accessibilityLabel="允许手机确认后新建提醒" disabled={!!busy || !policy.reminders.some(c=>c.writable)} value={policy.reminder_create} onValueChange={v=>setPolicy(p=>({...p,reminder_create:v}))}/></View>
    <View style={s.row}><Text style={s.flex}>每次确认后修改或删除日程</Text><StateSwitch accessibilityLabel="允许手机确认后修改删除单次日程" disabled={!!busy || !policy.calendars.some(c=>c.writable)} value={policy.calendar_edit} onValueChange={v=>setPolicy(p=>({...p,calendar_edit:v}))}/></View>
    <View style={s.row}><Text style={s.flex}>每次确认后修改或删除提醒</Text><StateSwitch accessibilityLabel="允许手机确认后修改删除提醒" disabled={!!busy || !policy.reminders.some(c=>c.writable)} value={policy.reminder_edit} onValueChange={v=>setPolicy(p=>({...p,reminder_edit:v}))}/></View>
    <Text style={s.description}>已有记录须先读取，再引用它修改。重复日程只处理具体一次；重复提醒和提醒日期修改请在系统应用中处理。</Text>
    <View style={s.row}><Text style={s.flex}>每次确认后读取一次位置</Text><StateSwitch accessibilityLabel="允许手机确认后读取一次位置" disabled={!!busy || !driver} value={policy.location} onValueChange={v=>{if (!v) setPolicy(p=>({...p,location:false}));else void run('位置权限',async()=>{if (!await driver?.permission('location',true)) throw new Error('permission');if (active()) setPolicy(p=>({...p,location:true}));});}}/></View>
    <PrimaryButton label={device?.enabled ? '保存所选范围' : '启用所选能力'} loading={busy==='保存'} disabled={!!busy || !loaded || !driver || !(policy.calendars.length || policy.reminders.length || policy.location)} onPress={()=>void run('保存',()=>save(true))}/>
    {device?.enabled && <PrimaryButton label="停用这台手机的任务执行" tone="quiet" disabled={!!busy} onPress={()=>void run('停用',()=>save(false))}/>}
    <PrimaryButton label="打开系统权限设置" tone="quiet" disabled={!!busy} onPress={()=>void run('系统设置',async()=>{await Linking.openSettings();})}/>
    {!!items.length && <Text style={s.title}>最近的手机请求</Text>}
    {items.map(item=><View key={item.id} style={s.history}><Text style={s.body}>{nativeMethodLabel(item.command.method)} · {nativeStateLabel(item.state)}</Text><Text style={s.description}>{item.task_title || '原任务'}{item.reviewed ? ' · 已手动核对' : ''}</Text>
      {item.state==='unknown' && !item.reviewed && <PrimaryButton label="核对这次系统记录" tone="quiet" disabled={!!busy} onPress={()=>{setInspection('');setReview(item);}}/>}</View>)}
    {review && <View style={s.history}><Text style={s.body}>{nativeRequestSummary(review,policy)}</Text>{isNativeEdit(review.command.method) && <PrimaryButton label="读取当前系统记录" tone="quiet" disabled={!!busy || !driver || !device} onPress={()=>void run('读取核对',async()=>{if (driver && device) {const value=await driver.inspect(review,device);if (active()) setInspection(value);}})}/>} {!!inspection && <Text selectable style={s.description}>{inspection}</Text>}<Text style={s.description}>结果不明确时不会自动重做。下面只记录你已经核对，不会创建、修改或删除系统内容，也不会把请求标成成功。</Text>
      <PrimaryButton label="我已在系统应用中核对" disabled={!!busy} onPress={()=>void run('核对',async()=>{if (!client.current) return;await client.current.review(review);if (active()) {setReview(null);await refresh();}})}/>
      <PrimaryButton label="暂不标记" tone="quiet" disabled={!!busy} onPress={()=>setReview(null)}/></View>}
  </View>;
}
const styles = (c:AppColors)=>StyleSheet.create({card:{padding:20,borderRadius:28,borderWidth:1,borderColor:c.line,backgroundColor:c.surface,gap:14},title:{fontSize:19,fontWeight:'600',color:c.ink},body:{fontSize:16,lineHeight:24,color:c.ink},description:{fontSize:13,lineHeight:21,color:c.muted},row:{flexDirection:'row',alignItems:'center',gap:12},flex:{flex:1,fontSize:15,lineHeight:23,color:c.ink},history:{borderTopWidth:StyleSheet.hairlineWidth,borderTopColor:c.line,paddingTop:14,gap:10},error:{fontSize:14,lineHeight:22,color:c.danger}});
