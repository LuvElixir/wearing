import {useAppTheme, useThemedStyles, type AppColors} from './app-theme';
import {useCallback, useEffect, useRef, useState} from 'react';
import {ActivityIndicator, AppState, Linking, Platform, StyleSheet, Text, View} from 'react-native';
import {requireOptionalNativeModule} from 'expo';
import {CalendarDays, Check, ChevronRight, Image as ImageIcon, MapPin, RefreshCw, Settings2} from 'lucide-react-native';
import {Entrance, PrimaryButton, TactilePressable} from './experience/primitives';
import {CalendarPreview, calendarEventTime, calendarPreviews, LocationPreview, locationDraft, nativeDraftError, selectedCalendarDraft} from './nativeConnectionsModel';

type Permission = {status: string; granted: boolean; canAskAgain: boolean};
type Access = {state: 'checking' | 'available' | 'unavailable' | 'error'; permission?: Permission};
type CalendarApi = typeof import('expo-calendar/legacy');
type LocationApi = typeof import('expo-location');

// Expo Go versions differ: probe before evaluating modules that require native code.
function calendarApi(): CalendarApi | null {
  if (Platform.OS === 'web' || !requireOptionalNativeModule('ExpoCalendar')) return null;
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  return require('expo-calendar/legacy') as CalendarApi;
}
function locationApi(): LocationApi | null {
  if (Platform.OS === 'web' || !requireOptionalNativeModule('ExpoLocation')) return null;
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  return require('expo-location') as LocationApi;
}

function permissionLabel(access: Access) {
  if (access.state === 'checking') return '检查中';
  if (access.state === 'unavailable') return '当前版本不可用';
  if (access.state === 'error') return '暂时无法检查';
  if (access.permission?.granted) return '已允许';
  return access.permission?.status === 'denied' ? '未允许' : '尚未授权';
}

function needsSettings(access: Access) {
  return access.state === 'available' && !!access.permission && !access.permission.granted && !access.permission.canAskAgain;
}

export function NativeConnections({onDraft, onPhoto}: {onDraft: (text: string) => void; onPhoto: () => void}) {
  const {colors: c} = useAppTheme();
  const s = useThemedStyles(makeStyles);

  const [calendar, setCalendar] = useState<Access>({state: 'checking'});
  const [location, setLocation] = useState<Access>({state: 'checking'});
  const [events, setEvents] = useState<CalendarPreview[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [calendarReadAt, setCalendarReadAt] = useState<number | null>(null);
  const [position, setPosition] = useState<LocationPreview | null>(null);
  const [busy, setBusy] = useState<'calendar' | 'location' | 'draft' | null>(null);
  const [calendarError, setCalendarError] = useState('');
  const [calendarImportError, setCalendarImportError] = useState('');
  const [locationError, setLocationError] = useState('');
  const [settingsError, setSettingsError] = useState('');
  const active = useRef(true);
  const operation = useRef(false);
  const calendarRevision = useRef(0), locationRevision = useRef(0);

  const checkPermissions = useCallback(async () => {
    // This reads permission state only; it never prompts or collects calendar/location data.
    const checked = await Promise.allSettled([
      Promise.resolve().then(async () => {
        const api = calendarApi();
        return api ? {state: 'available', permission: await api.getCalendarPermissionsAsync()} as Access : {state: 'unavailable'} as Access;
      }),
      Promise.resolve().then(async () => {
        const api = locationApi();
        return api ? {state: 'available', permission: await api.getForegroundPermissionsAsync()} as Access : {state: 'unavailable'} as Access;
      }),
    ]);
    if (!active.current) return;
    const calendarAccess: Access = checked[0].status === 'fulfilled' ? checked[0].value : {state: 'error'};
    const locationAccess: Access = checked[1].status === 'fulfilled' ? checked[1].value : {state: 'error'};
    setCalendar(calendarAccess); setLocation(locationAccess);
    if (!calendarAccess.permission?.granted) {
      calendarRevision.current += 1;
      setEvents([]); setSelected([]); setCalendarReadAt(null);
    }
    if (!locationAccess.permission?.granted) {
      locationRevision.current += 1;
      setPosition(null);
    }
  }, []);

  useEffect(() => {
    active.current = true;
    void Promise.resolve().then(checkPermissions);
    const subscription = AppState.addEventListener('change', state => {
      if (state === 'active') void checkPermissions();
    });
    return () => {active.current = false; subscription.remove();};
  }, [checkPermissions]);

  async function openSettings() {
    setSettingsError('');
    try {await Linking.openSettings();}
    catch {if (active.current) setSettingsError('请到手机「设置」中调整这项权限。');}
  }

  async function readCalendar() {
    if (operation.current) return;
    operation.current = true; setBusy('calendar'); setCalendarError(''); setCalendarImportError('');
    setSelected([]); setEvents([]); setCalendarReadAt(null);
    try {
      const api = calendarApi();
      if (!api) {setCalendar({state: 'unavailable'}); return;}
      let permission = await api.getCalendarPermissionsAsync();
      if (!permission.granted && permission.canAskAgain) permission = await api.requestCalendarPermissionsAsync();
      if (!active.current) return;
      setCalendar({state: 'available', permission});
      if (!permission.granted) return;
      const revision = calendarRevision.current;
      const calendars = await api.getCalendarsAsync(api.EntityTypes.EVENT);
      const start = new Date(), end = new Date(start);
      end.setDate(end.getDate() + 7);
      const items = calendars.length ? await api.getEventsAsync(calendars.map(item => item.id), start, end) : [];
      const currentPermission = await api.getCalendarPermissionsAsync();
      if (!active.current || revision !== calendarRevision.current) return;
      setCalendar({state: 'available', permission: currentPermission});
      if (!currentPermission.granted) return;
      const names = Object.fromEntries(calendars.map(item => [item.id, item.title]));
      setEvents(calendarPreviews(items, names));
      setCalendarReadAt(Date.now());
    } catch {
      if (active.current) setCalendarError('这次没能读到日历，请稍后重试。');
    } finally {
      operation.current = false;
      if (active.current) setBusy(null);
    }
  }

  async function readLocation() {
    if (operation.current) return;
    operation.current = true; setBusy('location'); setLocationError(''); setPosition(null);
    try {
      const api = locationApi();
      if (!api) {setLocation({state: 'unavailable'}); return;}
      let permission = await api.getForegroundPermissionsAsync();
      if (!permission.granted && permission.canAskAgain) permission = await api.requestForegroundPermissionsAsync();
      if (!active.current) return;
      setLocation({state: 'available', permission});
      if (!permission.granted) return;
      if (!await api.hasServicesEnabledAsync()) {setLocationError('手机定位服务尚未开启，可到系统设置中打开。'); return;}
      const revision = locationRevision.current;
      const result = await api.getCurrentPositionAsync({accuracy: api.Accuracy.Balanced});
      const currentPermission = await api.getForegroundPermissionsAsync();
      if (!active.current || revision !== locationRevision.current) return;
      setLocation({state: 'available', permission: currentPermission});
      if (!currentPermission.granted) return;
      setPosition({latitude: result.coords.latitude, longitude: result.coords.longitude, accuracy: result.coords.accuracy, timestamp: result.timestamp});
    } catch {
      if (active.current) setLocationError('这次没能获取位置，请确认定位已开启后重试。');
    } finally {
      operation.current = false;
      if (active.current) setBusy(null);
    }
  }

  async function addDraft(kind: 'calendar' | 'location') {
    if (operation.current) return;
    operation.current = true; setBusy('draft');
    try {
      // Recheck after a possible Settings visit, before handing any preview to chat.
      const permission = kind === 'calendar' ? await calendarApi()?.getCalendarPermissionsAsync() : await locationApi()?.getForegroundPermissionsAsync();
      if (!active.current) return;
      if (!permission?.granted) {await checkPermissions(); return;}
      const text = kind === 'calendar' ? selectedCalendarDraft(events, selected) : position ? locationDraft(position) : '';
      const error = nativeDraftError(text);
      if (error) {
        if (kind === 'calendar') setCalendarImportError(error);
        else setLocationError(error);
        return;
      }
      setCalendarImportError('');
      if (text) onDraft(text);
    } catch {
      if (active.current) {
        if (kind === 'calendar') setCalendarError('权限状态暂时无法确认，请重试。');
        else setLocationError('权限状态暂时无法确认，请重试。');
      }
    } finally {
      operation.current = false;
      if (active.current) setBusy(null);
    }
  }

  const toggle = (key: string) => {setCalendarImportError(''); setSelected(value => value.includes(key) ? value.filter(item => item !== key) : [...value, key]);};
  const unavailableNote = Platform.OS === 'web' ? '请在手机 App 中使用这项能力。' : '当前 App 未提供这项原生能力，更新安装版后可用。';
  return <View style={s.panel}>
    <Text style={s.title}>本机应用</Text>
    <Text style={s.lead}>把日程、照片和位置带到正在做的事里。</Text>
    <View style={s.card}>
      <View style={s.heading}><View style={[s.icon, s.calendarIcon]}><CalendarDays size={25} color={c.ink}/></View><View style={s.words}><Text style={s.name}>日历</Text><Text style={s.detail}>查看未来 7 天，选择要聊的安排</Text></View><Text style={s.status}>{permissionLabel(calendar)}</Text></View>
      {calendar.state === 'unavailable' ? <Text style={s.note}>{unavailableNote}</Text> : <>
        <Text style={s.note}>只读取日程；选好后带入输入框，由你发送。</Text>
        <View style={s.actions}><PrimaryButton label={calendar.permission?.granted ? '读取日程' : needsSettings(calendar) ? '打开系统设置' : '允许读取日历'} tone="quiet" loading={busy === 'calendar'} disabled={busy !== null && busy !== 'calendar'} onPress={() => {void (needsSettings(calendar) ? openSettings() : readCalendar());}} leading={needsSettings(calendar) ? <Settings2 size={17} color={c.ink}/> : <RefreshCw size={17} color={c.ink}/>}/></View>
      </>}
      {calendarError ? <Text accessibilityLiveRegion="polite" style={s.error}>{calendarError}</Text> : null}
      {calendarReadAt !== null ? <Entrance style={s.preview} transitionKey={calendarReadAt}>
        <Text style={s.previewTitle}>未来 7 天 · {events.length} 项</Text>
        {events.length ? <>
          <View style={s.selection}><Text style={s.detail}>已选 {selected.length} 项</Text><TactilePressable onPress={() => {setCalendarImportError(''); setSelected(selected.length === events.length ? [] : events.map(event => event.key));}} accessibilityLabel={selected.length === events.length ? '取消全选日程' : '选择全部日程'} style={s.selectAll}><Text style={s.link}>{selected.length === events.length ? '取消全选' : '全选'}</Text></TactilePressable></View>
          {events.map(event => <TactilePressable key={event.key} accessibilityRole="checkbox" accessibilityState={{checked: selected.includes(event.key)}} accessibilityLabel={`${event.title}，${calendarEventTime(event)}`} onPress={() => toggle(event.key)} style={s.event}>
            <View style={[s.checkbox, selected.includes(event.key) && s.checked]}>{selected.includes(event.key) ? <Check size={14} color={c.surface}/> : null}</View><View style={s.words}><Text style={s.eventTitle}>{event.title}</Text><Text style={s.detail}>{calendarEventTime(event)} · {event.calendar}</Text></View>
          </TactilePressable>)}
          {calendarImportError ? <Text accessibilityLiveRegion="polite" style={s.error}>{calendarImportError}</Text> : null}
          <PrimaryButton label={`带入对话${selected.length ? ` · ${selected.length} 项` : ''}`} disabled={!selected.length || busy !== null} onPress={() => {void addDraft('calendar');}}/>
        </> : <Text style={s.note}>这几天没有读到日程。</Text>}
      </Entrance> : null}
    </View>
    <View style={s.card}>
      <View style={s.heading}><View style={[s.icon, s.locationIcon]}><MapPin size={25} color={c.ink}/></View><View style={s.words}><Text style={s.name}>当前位置</Text><Text style={s.detail}>找附近地点，或安排出行</Text></View><Text style={s.status}>{permissionLabel(location)}</Text></View>
      {location.state === 'unavailable' ? <Text style={s.note}>{unavailableNote}</Text> : <>
        <Text style={s.note}>点按时获取一次，预览后再决定是否带入对话。</Text>
        <View style={s.actions}><PrimaryButton label={needsSettings(location) ? '打开系统设置' : '获取一次位置'} tone="quiet" loading={busy === 'location'} disabled={busy !== null && busy !== 'location'} onPress={() => {void (needsSettings(location) ? openSettings() : readLocation());}} leading={needsSettings(location) ? <Settings2 size={17} color={c.ink}/> : <MapPin size={17} color={c.ink}/>}/></View>
      </>}
      {locationError ? <Text accessibilityLiveRegion="polite" style={s.error}>{locationError}</Text> : null}
      {position ? <Entrance style={s.preview} transitionKey={position.timestamp}><Text style={s.previewTitle}>已获取位置</Text><Text selectable style={s.coordinates}>{position.latitude.toFixed(5)}, {position.longitude.toFixed(5)}</Text><Text style={s.detail}>{new Date(position.timestamp).toLocaleTimeString('zh-CN', {hour: '2-digit', minute: '2-digit'})}{position.accuracy !== null ? ` · 精度约 ${Math.round(position.accuracy)} 米` : ''}</Text><PrimaryButton label="带入对话" disabled={busy !== null} onPress={() => {void addDraft('location');}}/></Entrance> : null}
    </View>
    <TactilePressable onPress={onPhoto} accessibilityLabel="选择照片" style={s.card}>
      <View style={s.heading}><View style={[s.icon, s.photoIcon]}><ImageIcon size={25} color={c.ink}/></View><View style={s.words}><Text style={s.name}>照片</Text><Text style={s.detail}>选择这次想交给我的照片</Text></View><ChevronRight size={20} color={c.muted}/></View>
      <Text style={s.note}>每次由你选择照片。</Text>
    </TactilePressable>
    {busy === 'draft' ? <View style={s.pending}><ActivityIndicator size="small" color={c.accent}/><Text style={s.detail}>正在带入输入框…</Text></View> : null}
    {settingsError ? <Text accessibilityLiveRegion="polite" style={s.error}>{settingsError}</Text> : null}
  </View>;
}

const makeStyles = (c: AppColors) => StyleSheet.create({
  panel: {gap: 16, paddingBottom: 12}, title: {fontSize: 31, lineHeight: 40, fontWeight: '600', color: c.ink, letterSpacing: -.7},
  lead: {fontSize: 16, lineHeight: 25, color: c.muted, marginBottom: 8},
  card: {padding: 20, borderRadius: 28, borderWidth: 1, borderColor: c.line, backgroundColor: c.surface, gap: 14},
  heading: {flexDirection: 'row', alignItems: 'center', gap: 12}, icon: {width: 44, height: 44, borderRadius: 14, alignItems: 'center', justifyContent: 'center'},
  calendarIcon: {backgroundColor: c.soft}, locationIcon: {backgroundColor: c.successSoft}, photoIcon: {backgroundColor: c.soft},
  words: {flex: 1, gap: 4}, name: {fontSize: 18, lineHeight: 25, fontWeight: '500', color: c.ink}, detail: {fontSize: 12, lineHeight: 19, color: c.muted},
  status: {maxWidth: 66, fontSize: 11, lineHeight: 18, color: c.muted, textAlign: 'right'}, note: {fontSize: 13, lineHeight: 22, color: c.muted},
  actions: {alignItems: 'flex-start'}, error: {fontSize: 13, lineHeight: 22, color: c.danger},
  preview: {gap: 12, borderTopWidth: 1, borderTopColor: c.line, paddingTop: 18}, previewTitle: {fontSize: 16, lineHeight: 24, fontWeight: '500', color: c.ink},
  selection: {flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between'}, selectAll: {minHeight: 44, paddingHorizontal: 8, justifyContent: 'center'}, link: {fontSize: 13, color: c.accent},
  event: {minHeight: 60, paddingVertical: 8, flexDirection: 'row', alignItems: 'center', gap: 12}, eventTitle: {fontSize: 15, lineHeight: 23, color: c.ink},
  checkbox: {height: 22, width: 22, borderRadius: 7, borderWidth: 1, borderColor: c.muted, alignItems: 'center', justifyContent: 'center'}, checked: {backgroundColor: c.accent, borderColor: c.accent},
  coordinates: {fontSize: 19, lineHeight: 28, color: c.ink, fontVariant: ['tabular-nums']}, pending: {flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8},
});
