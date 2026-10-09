import {useCallback, useEffect, useMemo, useRef, useState} from 'react';
import {AppState, Linking, Platform, StyleSheet, Text, View} from 'react-native';
import Constants from 'expo-constants';
import {requireOptionalNativeModule} from 'expo';
import * as Crypto from 'expo-crypto';
import type * as Notifications from 'expo-notifications';
import {Bell} from 'lucide-react-native';
import QuietHoursPanel from './QuietHoursPanel';
import {type Connection, scopeOf} from './core';
import {useAppTheme, useThemedStyles, type AppColors} from './app-theme';
import {PrimaryButton} from './experience/primitives';
import {storage} from './storage';
import {serviceFetch} from './transport';
import {observeDiagnosticError} from './diagnostics-client';
import {NotificationClient, notificationInstallation, notificationTarget, providerMessage, validProjectId, type NotificationStatus, type NotificationTarget} from './notification-client';
import {notificationPermissionGranted, registerNativeNotifications} from './notification-native';

export function nativeNotifications(): typeof Notifications | null {
  if (Platform.OS === 'web' || Constants.executionEnvironment === 'storeClient' || !requireOptionalNativeModule('ExpoPushTokenManager') || !requireOptionalNativeModule('ExpoNotificationsEmitter')) return null;
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  return require('expo-notifications') as typeof Notifications;
}
export function notificationProject(): string | null {
  const value = Constants.expoConfig?.extra?.eas?.projectId ?? Constants.easConfig?.projectId;
  return validProjectId(value) ? value : null;
}
async function clientFor(connection: Connection) {return new NotificationClient(connection, await notificationInstallation(storage, () => Crypto.randomUUID()), serviceFetch);}
/** Call before removing authentication on logout / changing accounts. */
export async function disableInstallationNotifications(connection: Connection) {return (await clientFor(connection)).disableInstallation();}

/** Mount once outside tab screens. Callback must authenticate/switch identity,
 * resolve the event through NotificationClient.resolve, THEN navigate. Returning
 * false keeps the cold-start response available until connection/login is ready. */
export function observeNotificationResponses(onTarget: (target: NotificationTarget) => Promise<boolean>, onError: (message: string) => void = () => {}) {
  const api = nativeNotifications();
  if (!api) return () => {};
  api.setNotificationHandler({handleNotification: async () => ({shouldShowBanner: true, shouldShowList: true, shouldPlaySound: false, shouldSetBadge: false})});
  let active = true;
  const processing = new Set<string>(), handled = new Set<string>();
  async function receive(response: Notifications.NotificationResponse | null) {
    const target = notificationTarget(response?.notification.request.content.data);
    if (!target || !response || !active || response.actionIdentifier !== api!.DEFAULT_ACTION_IDENTIFIER) return;
    const key = response.notification.request.identifier + ':' + target.event_key;
    if (processing.has(key) || handled.has(key)) return;
    processing.add(key);
    try {
      if (await onTarget(target) && active) {
        handled.add(key);
        if (api!.getLastNotificationResponse()?.notification.request.identifier === response.notification.request.identifier) api!.clearLastNotificationResponse();
      }
    } catch {if (active) onError('通知对应的任务暂时未能打开，请检查连接后重试。');}
    finally {processing.delete(key);}
  }
  const listener = api.addNotificationResponseReceivedListener(response => {void receive(response);});
  void receive(api.getLastNotificationResponse());
  return () => {active = false; listener.remove();};
}

/** Mount for the connected identity. Refreshes an already-enabled token and
 * reconciles revoked OS permission; it never asks for new permission itself. */
export function NativeNotificationSession({connection, onError}: {connection: Connection; onError?: (message: string) => void}) {
  useEffect(() => {
    const api = nativeNotifications(), project = notificationProject();
    if (!api || !project || (Platform.OS !== 'ios' && Platform.OS !== 'android')) return;
    let active = true, busy = false;
    const platform = Platform.OS;
    const refresh = async () => {
      if (!active || busy) return;
      busy = true;
      try {const client = await clientFor(connection); if (active) await registerNativeNotifications(api, client, project, platform, false, () => active);}
      catch (error) {observeDiagnosticError(connection, 'notifications', error); if (active) onError?.('通知状态未能同步，稍后可在通知设置中重新检查。');}
      finally {busy = false;}
    };
    void refresh();
    const app = AppState.addEventListener('change', state => {if (state === 'active') void refresh();});
    const token = api.addPushTokenListener(() => {void refresh();});
    return () => {active = false; app.remove(); token.remove();};
  }, [connection, onError]);
  return null;
}

export function NativeNotificationsPanel({connection}: {connection: Connection}) {
  return <View style={{gap:16}}><NotificationSettings key={scopeOf(connection)} connection={connection}/><QuietHoursPanel connection={connection}/></View>;
}
function NotificationSettings({connection}: {connection: Connection}) {
  const s = useThemedStyles(styles), {colors} = useAppTheme();
  const api = useMemo(() => nativeNotifications(), []), project = notificationProject();
  const [status, setStatus] = useState<NotificationStatus | null>(null), [permitted, setPermitted] = useState<boolean | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState('');
  const mounted = useRef(false), locked = useRef(false);
  const refresh = useCallback(async () => {
    if (locked.current || !mounted.current) return;
    locked.current = true; setBusy(true); setError('');
    try {
      const client = await clientFor(connection), value = await client.status();
      const permission = api ? await api.getPermissionsAsync() : null;
      const allowed = permission ? notificationPermissionGranted(permission) : null;
      if (!mounted.current) return;
      const latest = allowed === false && value.enabled ? await client.disable() : value;
      if (mounted.current) {setStatus(latest); setPermitted(allowed);}
    } catch (cause) {observeDiagnosticError(connection, 'notifications', cause); if (mounted.current) setError(cause instanceof Error ? cause.message : '通知状态未能读取。');}
    finally {locked.current = false; if (mounted.current) setBusy(false);}
  }, [api, connection]);
  useEffect(() => {
    mounted.current = true; void Promise.resolve().then(refresh);
    const listener = AppState.addEventListener('change', state => {if (state === 'active') void refresh();});
    return () => {mounted.current = false; listener.remove();};
  }, [refresh]);
  async function change(enable: boolean) {
    if (locked.current) return;
    locked.current = true; setBusy(true); setError('');
    try {
      const client = await clientFor(connection);
      if (!mounted.current) return;
      let value: NotificationStatus;
      if (enable) {
        if (!api || (Platform.OS !== 'ios' && Platform.OS !== 'android')) throw new Error('请使用支持推送通知的 Pajio 安装包。');
        value = await registerNativeNotifications(api, client, project, Platform.OS, true, () => mounted.current);
        if (mounted.current) setPermitted(true);
      } else value = await client.disable();
      if (mounted.current) setStatus(value);
    } catch (cause) {if (mounted.current) setError(cause instanceof Error ? cause.message : '通知设置尚未完成，请重新检查。');}
    finally {locked.current = false; if (mounted.current) setBusy(false);}
  }
  const available = !!api && !!project && status?.configured && status.project_id === project;
  return <View style={s.card}>
    <View style={s.heading}><Bell size={22} color={colors.accent}/><Text style={s.title}>通知与提醒</Text></View>
    <Text style={s.body}>新的结果、需要你确认的事项，以及你开启的日程和待办提醒，会尝试通过系统通知提醒你。锁屏仅显示提示，不展示内容。</Text>
    {!api ? <Text style={s.note}>当前运行环境尚不支持远程推送，需要安装配置完成的 Pajio 原生版本。</Text> : !project ? <Text style={s.note}>此安装包尚未配置推送项目，配置完成并重新构建后可开启。</Text> : null}
    {status ? <Text style={s.note}>{providerMessage(status)}</Text> : null}
    {permitted === false ? <Text style={s.note}>手机系统还没有允许通知。</Text> : null}
    {!!error && <Text accessibilityRole="alert" style={s.error}>{error}</Text>}
    <PrimaryButton label={status?.enabled ? '停止当前身份的通知' : '开启通知与提醒'} onPress={() => {void change(!status?.enabled);}} disabled={busy || (!status?.enabled && !available)} loading={busy}/>
    <View style={s.actions}><PrimaryButton label="重新检查" tone="quiet" onPress={() => {void refresh();}} disabled={busy}/>{api ? <PrimaryButton label="手机通知设置" tone="quiet" onPress={() => {void Linking.openSettings().catch(() => setError('系统设置未能打开，请在手机设置中找到 Pajio。'));}}/> : null}</View>
  </View>;
}
const styles = (c: AppColors) => StyleSheet.create({card: {backgroundColor: c.surface, borderRadius: 24, padding: 20, gap: 14}, heading: {flexDirection: 'row', gap: 10, alignItems: 'center'},
  title: {fontSize: 19, fontWeight: '600', color: c.ink}, body: {fontSize: 15, lineHeight: 23, color: c.ink}, note: {fontSize: 14, lineHeight: 21, color: c.muted}, error: {color: c.danger, fontSize: 14, lineHeight: 21}, actions: {flexDirection: 'row', flexWrap: 'wrap', gap: 10}});
