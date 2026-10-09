import type * as Notifications from 'expo-notifications';
import {validProjectId, type NotificationClient, type NotificationStatus} from './notification-client';
import {boundedNativeRead} from './nativeConnectionsModel';

export type NativeNotificationApi = Pick<typeof Notifications, 'getPermissionsAsync' | 'requestPermissionsAsync' | 'getExpoPushTokenAsync' | 'setNotificationChannelAsync'>;
export const notificationPermissionGranted = (value: {granted: boolean; ios?: {status: number}}) => value.granted || value.ios?.status === 3;
export async function registerNativeNotifications(api: NativeNotificationApi, client: NotificationClient, projectId: string | null, platform: 'ios' | 'android', ask: boolean, active: () => boolean = () => true): Promise<NotificationStatus> {
  const check = () => {if (!active()) throw new Error('当前身份已切换，请重新打开通知设置。');};
  if (!validProjectId(projectId)) throw new Error('当前安装包尚未配置推送项目，请安装配置完成的版本。');
  const server = await client.status(); check();
  if (!ask && !server.enabled) return server;
  if (!server.configured || server.project_id !== projectId) throw new Error('通知服务与当前安装包尚未准备好，请稍后重试。');
  if (platform === 'android') await api.setNotificationChannelAsync('pajio-progress', {name: '通知与提醒', importance: 3, sound: null, enableVibrate: false});
  check();
  let permission = await api.getPermissionsAsync(); check();
  if (!notificationPermissionGranted(permission) && ask && permission.canAskAgain) {
    permission = await api.requestPermissionsAsync({ios: {allowAlert: true, allowSound: false, allowBadge: false}}); check();
  }
  if (!notificationPermissionGranted(permission)) {
    if (server.enabled) await client.disable();
    if (ask) throw new Error('系统通知尚未允许。可以在手机设置中允许 Pajio 发送通知。');
    return {...server, enabled: false, reason: 'permission_denied'};
  }
  const token = await boundedNativeRead(api.getExpoPushTokenAsync({projectId}), '手机通知凭据暂时未能取得，请检查网络后重新开启。'); check();
  return client.register(token.data, projectId, platform);
}
