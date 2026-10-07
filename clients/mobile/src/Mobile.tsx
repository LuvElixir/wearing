import {AppThemeProvider, useAppTheme, useThemedStyles, type AppColors} from './app-theme';
/** MODE: Operate. THESIS: keep a thought, photo or voice clip first, even offline.
 * Warm day and night surfaces, quiet task state, and the selected pajama bear.
 * Native insets, keyboard and Back; canonical records; no invented cloud state.
 * FINISH: captured renders, independent finish verdict and implementation documentation.
 */
import {useEffect, useLayoutEffect, useRef, useState} from 'react';
import {router, useLocalSearchParams} from 'expo-router';
import {AccessibilityInfo, Animated, AppState, BackHandler, Easing, Image, Keyboard, Pressable, KeyboardAvoidingView, Platform, ScrollView, StyleSheet, TextInput as Input, useWindowDimensions, View} from 'react-native';
import {Button, Checkbox, MD3DarkTheme, MD3LightTheme, PaperProvider, Switch, Text, TextInput} from 'react-native-paper';
import {SafeAreaProvider, SafeAreaView} from 'react-native-safe-area-context';
import {StatusBar} from 'expo-status-bar';
import * as Crypto from 'expo-crypto';
import * as Picker from 'expo-image-picker';
import {ImageManipulator, SaveFormat} from 'expo-image-manipulator';
import {AudioModule, RecordingPresets, setAudioModeAsync, useAudioRecorder, useAudioRecorderState} from 'expo-audio';
import {Camera, Image as ImageIcon, ChevronLeft, Clock3, FileText, Folder, Mic, Search, Plus, RefreshCw, Settings, Target, X} from 'lucide-react-native';
import {Connection, Kind, makeDraft, Media, Outbox, Pending, RecordItem, scopeOf, WearingApi, connectionEndpoint} from './core';
import {keepMedia, preview, storage} from './storage';
import TimeField from './TimeField';
import RetainedConversation from './RetainedConversation';
import ActivityReview from './ActivityReview';
import type {ReviewRequest} from './conversationLink';
import RemoteOriginal from './RemoteOriginal';
import {serviceFetch} from './transport';
import {BottomNavigation, type BottomNavigationPage} from './experience/BottomNavigation';
import {IconButton, Sheet, TactilePressable} from './experience/primitives';
import {MenuRow, OngoingPanel} from './PersonalPanels';
import MonthCalendar from './MonthCalendar';
import TodayPanel, {ScheduleSuggestions} from './TodayPanel';
import AgentTaskList from './AgentTaskList';
import {MemoryLibrary, SettingsHub} from './PersonalHub';
import {useWardrobe} from './useWardrobe';
import {NativeConnections} from './NativeConnections';
import {AppBackdrop} from './experience/AppBackdrop';
import {eventOccursOn, localDateTime, type CalendarDate} from './calendar';
import {useLocalDate} from './use-local-date';

type Form = {id: string; text: string; kind: Kind; media: Media[]; organize: boolean; start: string; end: string};
type Screen = 'capture' | 'tools' | 'tasks' | 'agenda' | 'notes' | 'conversation' | 'settings' | 'detail' | 'memory' | 'companion' | 'today' | 'connection' | 'native';
function tabForScreen(screen: Screen): BottomNavigationPage | null {
  return screen==='conversation'?'now':screen==='today'||screen==='agenda'||screen==='notes'?'review':screen==='tasks'?'goals':screen==='memory'?'memory':screen==='companion'?'companion':null;
}
const blank = (): Form => {const start = new Date(); start.setMinutes(Math.ceil(start.getMinutes() / 30) * 30, 0, 0); return {id: Crypto.randomUUID(), text: '', kind: 'note', media: [], organize: true, start: start.toISOString(), end: new Date(start.getTime() + 1800000).toISOString()};};
const voiceOptions = {...RecordingPresets.HIGH_QUALITY, numberOfChannels: 1, bitRate: 64000, directory: 'document' as const};
const kinds = {note: '笔记', task: '任务', event: '日程'};
const stages: {[key: string]: string} = {queued: '等 Wearing 来整理', extracting: '正在读原件', organizing: 'Wearing 正在整理', done: 'Wearing 已整理', saved: '原话与原件已保存', failed: '原件已保存，整理可重试', paused: '原件已保存，整理暂停', conflict: '保留了你的编辑'};

function Original({media}: {media: Media}) {
  const {colors: c} = useAppTheme();
  const s = useThemedStyles(makeStyles);

  const [uri, setUri] = useState('');
  useEffect(() => {let live = true; preview(media.id).then(value => {if (live) setUri(value);}).catch(() => {}); return () => {live = false;};}, [media.id]);
  return <View style={s.media}>{media.mime.startsWith('image/') && uri ? <Image source={{uri}} style={s.thumbnail} accessibilityLabel={media.name}/> : <Mic size={22} color={c.muted}/>}<View style={{flex: 1}}><Text>{media.name}</Text><Text variant="bodySmall" style={s.muted}>原件已留在本机</Text></View></View>;
}

function Mobile() {
  const {colors: c, mode} = useAppTheme();
  const s = useThemedStyles(makeStyles);

  const wide = useWindowDimensions().width >= 840;
  const [connection, setConnection] = useState<Connection | null>(null); const current = useRef<Connection | null>(null);
  const wardrobe = useWardrobe(connection);
  const [identities, setIdentities] = useState<{id: string; name: string}[]>([]);
  const {view,memoryPath,memoryFile,memorySection,hubSection} = useLocalSearchParams<{view?: string;memoryPath?:string;memoryFile?:string;memorySection?:string;hubSection?:string}>();
  const screen: Screen = ['capture','tools','tasks','agenda','notes','conversation','settings','detail','memory','companion','today','connection','native'].includes(view || '') ? view as Screen : 'conversation';
  const [menu, setMenu] = useState(false), [adding, setAdding] = useState(false);
  const [taskTab, setTaskTab] = useState<'tasks' | 'goals' | 'schedules'>('tasks');
  const [lastTab, setLastTab] = useState<BottomNavigationPage>(()=>tabForScreen(screen)||'now');
  const [lastReview,setLastReview] = useState<'agenda'|'tasks'|'notes'>('agenda');
  const today = useLocalDate();
  const [selectedDate, setSelectedDate] = useState<CalendarDate | null>(null);
  const calendarDate = selectedDate || today;
  const setScreen = (next: Screen) => {if(next==='agenda'||next==='tasks'||next==='notes')setLastReview(next);const tab=tabForScreen(next);if(tab)setLastTab(tab);router.setParams({view:next,memoryPath:'',memoryFile:'',memorySection:'',hubSection:''});};
  const primary = ['conversation','today','agenda','tasks','notes','memory','companion'].includes(screen);
  const selectedTab = tabForScreen(screen)||lastTab;
  function selectTab(tab: BottomNavigationPage) {Keyboard.dismiss();setLastTab(tab);setReviewRequest(null);setScreen(tab==='now'?'conversation':tab==='review'?'today':tab==='goals'?'tasks':tab);}
  function goBack(){
    if((screen==='settings'||screen==='companion')&&hubSection){router.setParams({hubSection:''});return;}
    if(screen==='memory'&&memoryFile){router.setParams({memoryFile:''});return;}
    if(screen==='memory'&&memoryPath){router.setParams({memoryPath:memoryPath.split('/').slice(0,-1).join('/')});return;}
    if(screen==='memory'&&memorySection){router.setParams({memorySection:''});return;}
    if(screen==='agenda'||screen==='notes'){setScreen('today');return;}
    if(screen==='native'||screen==='connection'){setScreen('settings');return;}
    setScreen(primary?'conversation':screen==='detail'&&detail?(detail.kind==='task'?'tasks':detail.kind==='event'?'agenda':'notes'):screen==='capture'?lastReview:lastTab==='now'?'conversation':lastTab==='review'?'today':lastTab==='goals'?'tasks':lastTab);
  }
  const [reviewRequest,setReviewRequest] = useState<ReviewRequest | null>(null);
  const [activityOpen, setActivityOpen] = useState(false);
  function prepareMessage(text:string){setReviewRequest({id:Date.now(),target:'draft',text});setScreen('conversation');}
  function openReviewTool(target:'files'|'goals'|'schedules'){setMenu(false);setReviewRequest({id:Date.now(),target});setScreen('conversation');}
  function openActivityTask(taskId: string) {setActivityOpen(false); setChatRecord(null); setReviewRequest({id: Date.now(), target: 'activity', taskId}); setScreen('conversation');}
  const screenRef = useRef(screen);
  useLayoutEffect(() => {screenRef.current = screen;}, [screen]);
  const [form, setForm] = useState<Form>(blank); const formRef = useRef(form);
  useLayoutEffect(() => {formRef.current = form;}, [form]);
  const draftTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [records, setRecords] = useState<RecordItem[]>([]); const [pending, setPending] = useState<Pending[]>([]);
  const [message, setMessage] = useState(''); const [connected, setConnected] = useState(false);
  const [busy, setBusy] = useState(false); const syncBusy = useRef(false); const [saving, setSaving] = useState(false); const [ready, setReady] = useState(false);
  const [address, setAddress] = useState(''); const [identity, setIdentity] = useState('daily');
  const [foreground, setForeground] = useState(AppState.currentState === 'active');
  const [chatRecord, setChatRecord] = useState<RecordItem | null>(null);
  const [detail, setDetail] = useState<RecordItem | null>(null); const [edit, setEdit] = useState('');
  const recorder = useAudioRecorder(voiceOptions); const voice = useAudioRecorderState(recorder, 250); const voiceBusy = useRef(false);
  const voiceConnection = useRef<Connection | null>(null); const voiceStop = useRef<Promise<boolean> | null>(null);
  const voiceRecovery = useRef<{uri: string; connection: Connection | null} | null>(null);
  const input = useRef<Input>(null); const [outbox] = useState(() => new Outbox(storage));
  const [scene] = useState(() => new Animated.Value(1));
  const previousScreen = useRef(screen);
  const [reduceMotion, setReduceMotion] = useState(true);
  const [manualSync, setManualSync] = useState(false);
  const [moreCapture, setMoreCapture] = useState(false);
  const [inputFocused, setInputFocused] = useState(false);
  useEffect(() => {
    let mounted = true;
    AccessibilityInfo.isReduceMotionEnabled().then(value => {if (mounted) setReduceMotion(value);}).catch(() => {});
    const subscription = AccessibilityInfo.addEventListener('reduceMotionChanged', setReduceMotion);
    return () => {mounted = false; subscription.remove();};
  }, []);
  useEffect(() => {
    const switchingRecords=['agenda','tasks','notes'].includes(previousScreen.current)&&['agenda','tasks','notes'].includes(screen);
    previousScreen.current=screen;
    scene.stopAnimation();
    if (reduceMotion||switchingRecords) {scene.setValue(1); return;}
    scene.setValue(0);
    const animation = Animated.timing(scene, {toValue: 1, duration: 240, easing: Easing.out(Easing.cubic), useNativeDriver: Platform.OS !== 'web'});
    animation.start();
    return () => animation.stop();
  }, [screen, reduceMotion, scene]);
  async function refresh() {setManualSync(true);try {await synchronize(current.current, true);} finally {setManualSync(false);}}
  const handlers = useRef({activateConnection, synchronize, stopVoice, goBack});
  useLayoutEffect(() => {handlers.current = {activateConnection, synchronize, stopVoice, goBack};});
  async function local(connection: Connection) {
    const scope = scopeOf(connection);
    const [cache, receipts, items] = await Promise.all([storage.get<RecordItem[]>(`snapshot:${scope}`), storage.get<RecordItem[]>(`receipts:${scope}`), outbox.items(scope)]);
    if (current.current !== connection) return;
    const merged = new Map((cache || []).map(item => [item.id, item]));
    for (const receipt of receipts || []) if (!merged.has(receipt.id)) merged.set(receipt.id, receipt);
    setRecords([...merged.values()].sort((a, b) => b.updated_at.localeCompare(a.updated_at))); setPending(items);
  }
  async function synchronize(connection = current.current, allowPending = !connection?.development) {
    if (!connection || syncBusy.current || AppState.currentState !== 'active') return;
    syncBusy.current = true; setBusy(true);
    try {
      const api = new WearingApi(connection, serviceFetch); const data = await api.bootstrap();
      if (current.current !== connection) return;
      setIdentities(data.identities); setConnected(true);
      // Opening a short-term development pairing must not send an existing queue.
      const sent = allowPending ? await outbox.flush(scopeOf(connection), api, () => current.current === connection && AppState.currentState === 'active') : 0;
      const snapshot = await api.snapshot(); await storage.put(`snapshot:${scopeOf(connection)}`, snapshot.items.filter(item => !item.deleted_at));
      const receipts = await storage.get<RecordItem[]>(`receipts:${scopeOf(connection)}`) || [];
      await storage.put(`receipts:${scopeOf(connection)}`, receipts.filter(r => !snapshot.items.some(item => item.id === r.id)));
      if (current.current === connection && sent) setMessage(sent + ' 条记录已同步，Wearing 也能接着看。');
    } catch (error) {if (current.current === connection) {setConnected(false); setMessage(error instanceof Error ? error.message : '暂时没连上，原件仍在本机。');}}
    finally {await local(connection); syncBusy.current = false; setBusy(false); if (current.current && current.current !== connection) synchronize(current.current);}
  }
  async function activateConnection(connection: Connection) {
    if (voiceBusy.current && !voiceStop.current) throw new Error('麦克风正在准备，请稍后再切换。');
    if ((recorder.isRecording || voiceStop.current || voiceRecovery.current) && !await stopVoice()) throw new Error('录音还没保存好，暂时没有切换身份。');
    if (draftTimer.current) clearTimeout(draftTimer.current);
    if (current.current) await storage.put(`draft:${scopeOf(current.current)}`, formRef.current);
    current.current = connection; setConnection(connection); setConnected(false); setRecords([]); setPending([]); setDetail(null); setChatRecord(null); setReviewRequest(null); setActivityOpen(false); setLastReview('agenda');
    router.setParams({memoryPath:'',memoryFile:'',memorySection:'',hubSection:''});
    const saved = await storage.get<Form>(`draft:${scopeOf(connection)}`); if (current.current !== connection) return;
    const next = saved ? {...saved, id: saved.id || Crypto.randomUUID()} : blank(); formRef.current = next;
    setForm(next); setAddress(connection.endpoint); setIdentity(connection.identity);
    await storage.put('connection', connection); await local(connection); synchronize(connection);
  }
  useEffect(() => {
    let active = true;
    (async () => {try {
      const stored = await storage.get<Connection>('connection');
      const connection = stored || {endpoint: Platform.OS === 'web' ? window.location.origin + '/' : 'http://127.0.0.1:8765/', identity: 'daily'};
      connection.endpoint = connectionEndpoint(connection, true); if (!active) return;
      await handlers.current.activateConnection(connection); setReady(true);
    } catch (error) {setMessage(error instanceof Error ? error.message : '本机存储暂时无法打开，尚未保存新记录。请检查存储空间后重试。');}})();
    return () => {active = false;};
  }, []);
  useEffect(() => {
    if (!connection || !ready) return;
    draftTimer.current = setTimeout(() => {storage.put(`draft:${scopeOf(connection)}`, form).catch(() => setMessage('草稿还没保存好，请保留输入并检查存储空间。'));}, 150);
    return () => {if (draftTimer.current) clearTimeout(draftTimer.current);};
  }, [form, connection, ready]);
  useEffect(() => {
    const timer = setInterval(() => {handlers.current.synchronize();}, 15000);
    const listener = AppState.addEventListener('change', state => {setForeground(state === 'active'); if (state === 'active') handlers.current.synchronize(); else handlers.current.stopVoice();});
    const back = BackHandler.addEventListener('hardwareBackPress', () => {if (screenRef.current !== 'conversation') {handlers.current.goBack(); return true;} return false;});
    return () => {clearInterval(timer); listener.remove(); back.remove();};
  }, []);
  useEffect(() => {if (voice.isRecording && voice.durationMillis >= 180000) handlers.current.stopVoice();}, [voice.durationMillis, voice.isRecording]);
  async function addOriginal(uri: string, name: string, mime: string, connection = current.current) {
    if (!connection || current.current !== connection) throw new Error('身份已切换，原件没有加入新身份。');
    if (formRef.current.media.length >= 4) throw new Error('一次最多放四份原件。');
    const media = await keepMedia(uri, {id: Crypto.randomUUID(), name, mime, size: 0});
    if (media.size > 15 * 1024 * 1024) throw new Error('这份原件超过 15 MB，请选一份较小的。');
    if (current.current !== connection) {setMessage('身份已切换，这份原件未加入新身份。'); return;}
    const next = {...formRef.current, media: [...formRef.current.media, media]};
    await storage.put(`draft:${scopeOf(connection)}`, next); formRef.current = next; setForm(next); setMessage('原件已留在本机，可以再补一句。');
  }
  async function photo(camera: boolean) {
    const intended = current.current;
    try {
      if (voiceBusy.current && !voiceStop.current) throw new Error('麦克风正在准备，请稍后再选图。');
      if ((recorder.isRecording || voiceStop.current || voiceRecovery.current) && !await stopVoice()) throw new Error('先把这段录音保存好，再选图。');
      if (camera && !(await Picker.requestCameraPermissionsAsync()).granted) throw new Error('还没有相机权限，可以先选一张图片。');
      const result = camera ? await Picker.launchCameraAsync({mediaTypes: ['images'], quality: .8}) : await Picker.launchImageLibraryAsync({mediaTypes: ['images'], quality: 1, selectionLimit: 1});
      if (result.canceled) return;
      if (current.current !== intended) throw new Error('身份已切换，这次选取没有加入新身份。请在原身份重新选择。');
      const asset = result.assets[0]; let uri = asset.uri; let mime = asset.mimeType || 'image/jpeg'; let name = asset.fileName || '随手拍.jpg';
      if (!['image/jpeg', 'image/png', 'image/webp'].includes(mime) || asset.width * asset.height > 24000000) {
        const context = ImageManipulator.manipulate(uri); if (asset.width > 2400) context.resize({width: 2400});
        const image = await (await context.renderAsync()).saveAsync({format: SaveFormat.JPEG, compress: .85});
        uri = image.uri; mime = 'image/jpeg'; name = name.replace(/\.[^.]+$/, '') + '.jpg';
      }
      await addOriginal(uri, name, mime, intended);
    } catch (error) {setMessage(error instanceof Error ? error.message : '图片没有保存好，请重新选择。');}
  }
  async function stopVoice(): Promise<boolean> {
    if (voiceStop.current) return voiceStop.current;
    if (!recorder.isRecording && !voiceRecovery.current) return !voiceBusy.current;
    const intended = voiceRecovery.current?.connection || voiceConnection.current; voiceBusy.current = true;
    voiceStop.current = (async () => {
      try {if (recorder.isRecording) {await recorder.stop(); if (recorder.uri) voiceRecovery.current = {uri: recorder.uri, connection: intended};}
        if (!voiceRecovery.current) throw new Error('录音文件尚未生成。');
        await addOriginal(voiceRecovery.current.uri, Platform.OS === 'web' ? '随口说的.webm' : '随口说的.m4a', Platform.OS === 'web' ? 'audio/webm' : 'audio/mp4', intended); voiceRecovery.current = null; return true;}
      catch {setMessage('录音暂时没保存好，请保留页面，再点「说一句」重试。'); return false;}
      finally {voiceBusy.current = false; voiceConnection.current = null; voiceStop.current = null;}
    })();
    return voiceStop.current;
  }
  async function recordVoice() {
    if (recorder.isRecording || voiceRecovery.current) {await stopVoice(); return;}
    if (voiceBusy.current || !ready || !current.current) return;
    const intended = current.current; const intendedScreen = screenRef.current; voiceBusy.current = true;
    try {
      if (formRef.current.media.length >= 4) throw new Error('一次最多放四份原件。');
      if (!(await AudioModule.requestRecordingPermissionsAsync()).granted) throw new Error('还没有麦克风权限，可以先写一句。');
      await setAudioModeAsync({allowsRecording: true, playsInSilentMode: true, allowsBackgroundRecording: false, shouldPlayInBackground: false});
      await recorder.prepareToRecordAsync();
      if (current.current !== intended || screenRef.current !== intendedScreen || AppState.currentState !== 'active') throw new Error('页面已经切换，本次没有开始录音。');
      voiceConnection.current = intended; recorder.record(); setMessage('正在录音，最长三分钟。说完后点「说完了」。');
    } catch (error) {voiceConnection.current = null; setMessage(error instanceof Error ? error.message : '麦克风暂时无法使用。');}
    finally {voiceBusy.current = false;}
  }
  async function save() {
    if (!connection || saving || !ready) return; setSaving(true);
    try {
      if (voiceBusy.current && !voiceStop.current) throw new Error('麦克风正在准备，请稍后再保存。');
      if ((recorder.isRecording || voiceStop.current || voiceRecovery.current) && !await stopVoice()) throw new Error('录音还没保存好，输入保留在这里。');
      const connection = current.current!; const form = formRef.current;
      const text = form.text.trim() || (form.media.some(m => m.mime.startsWith('image/')) ? '随手拍下的' : form.media.length ? '随口说的' : '');
      const draft = makeDraft(text, form.kind, new Date(form.start), new Date(form.end));
      if (draftTimer.current) clearTimeout(draftTimer.current);
      const empty = blank();
      await outbox.enqueue({id: form.id, scope: scopeOf(connection), draft, media: form.media, uploaded: [], organize: form.organize, state: 'pending', attempts: 0, nextAt: 0, createdAt: new Date().toISOString()}, [`draft:${scopeOf(connection)}`, empty]);
      formRef.current = empty; setForm(empty);
      setMessage('已留在本机。连接后会同步给 Wearing。'); await local(connection); synchronize(connection, true);
    } catch (error) {setMessage(error instanceof Error ? error.message : '没有保存成功，输入仍在这里。');}
    finally {setSaving(false);}
  }
  async function connect() {
    try {
      const prior = current.current;
      const connection: Connection = {endpoint: address, identity, ...(prior?.development && address.trim().replace(/\/$/, '') === prior.endpoint.replace(/\/$/, '') && identity === prior.identity ? {development: prior.development} : {})};
      connection.endpoint = connectionEndpoint(connection); setBusy(true);
      const data = await new WearingApi(connection, serviceFetch).bootstrap(); setIdentities(data.identities);
      await activateConnection(connection); setScreen('conversation'); setMessage('已连接，可以继续说。');
    } catch (error) {setMessage(error instanceof Error ? error.message : '连接没有成功，原连接仍在。');}
    finally {setBusy(false);}
  }
  async function toggle(item: RecordItem) {
    if (!connection || !connected) {setMessage('完成状态要连上 Wearing 后保存，原记录没有修改。'); return;}
    try {await new WearingApi(connection, serviceFetch).update(item, {completed: !item.completed}); await synchronize();}
    catch (error) {setMessage('完成状态尚未确认，请同步核对后再操作。' + (error instanceof Error ? error.message : ''));}
  }
  function open(item: RecordItem) {setDetail(item); setEdit(item.content || item.title); setScreen('detail');}
  async function saveEdit() {
    if (!detail || !connection) return;
    try {const content = edit.trim(); if (!content) throw new Error('请保留一点内容。');
      await new WearingApi(connection, serviceFetch).update(detail, {title: content.split('\n')[0].slice(0, 200), content}); await synchronize(); setScreen(detail.kind==='task'?'tasks':detail.kind==='event'?'agenda':'notes'); setMessage('修改已保存。');}
    catch (error) {setMessage('修改尚未确认。输入保留在当前页面；恢复连接后请先核对，再保存。' + (error instanceof Error ? error.message : ''));}
  }
  const name = identities.find(i => i.id === connection?.identity)?.name || '日常';
  const events = records.filter(r => r.kind === 'event').sort((a, b) => (a.start_at || '').localeCompare(b.start_at || ''));
  const todayEvents = today ? events.filter(r => eventOccursOn(r, today)) : [];
  const selectedEvents = calendarDate ? events.filter(r => eventOccursOn(r, calendarDate)) : [];
  function row(item: RecordItem) {return <View key={item.id} style={s.row}>{item.kind === 'task' && <Checkbox.Android status={item.completed ? 'checked' : 'unchecked'} onPress={() => toggle(item)} accessibilityLabel={(item.completed ? '重开：' : '完成：') + item.title}/>}<Pressable accessibilityRole="button" accessibilityLabel={item.title} onPress={() => open(item)} style={({pressed}) => [s.recordBody, pressed && s.pressed]}><Text numberOfLines={2} style={[s.recordTitle, item.completed && {textDecorationLine: 'line-through', color: c.muted}]}>{item.title}</Text><Text style={s.recordMeta}>{item.kind === 'event' ? (/^\d{4}-\d{2}-\d{2}$/.test(item.start_at || '') ? `${Number(item.start_at!.slice(5,7))}月${Number(item.start_at!.slice(8,10))}日 · 全天` : new Date(item.start_at!).toLocaleString('zh-CN', {month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit'})) : item.capture ? stages[item.capture.state] || '原件已保存' : kinds[item.kind]}</Text>{item.content !== item.title && <Text numberOfLines={2} style={s.excerpt}>{item.content}</Text>}</Pressable></View>;}


  const content = <ScrollView key={screen} keyboardShouldPersistTaps="handled" keyboardDismissMode="on-drag" maximumZoomScale={1} minimumZoomScale={1} pinchGestureEnabled={false} contentContainerStyle={[s.scroll, wide && {maxWidth: 980, alignSelf: 'center', width: '100%'}]}>
    {screen === 'today' && connection && <TodayPanel key={scopeOf(connection)} connection={connection} records={records} connected={connected} onCalendar={()=>setScreen('agenda')} onRecord={open} onTask={openActivityTask} onDraft={prepareMessage}/>}
    {screen === 'native' && <NativeConnections onDraft={prepareMessage} onPhoto={()=>{setScreen('capture');void photo(false);}}/>}
    {screen === 'capture' && <>
      <View style={s.greeting}><View style={{flex: 1}}><Text variant="headlineLarge" style={s.heading}>补记记录</Text><Text variant="bodyLarge" style={s.muted}>也可以直接补充或修改记录。</Text></View></View>
      <View style={[s.composer, inputFocused && s.composerFocused]}><Input ref={input} multiline value={form.text} onChangeText={text => setForm(p => ({...p, text}))} placeholder="一个念头、一件小事…" placeholderTextColor={c.muted} accessibilityLabel="随手记一下" maxLength={12000} style={s.input} onFocus={() => setInputFocused(true)} onBlur={() => setInputFocused(false)} selectionColor={c.accent}/>
        {form.media.map(media => <View key={media.id} style={{flexDirection: 'row', alignItems: 'center'}}><View style={{flex: 1}}><Original media={media}/></View><Button accessibilityLabel={'从草稿移除：' + media.name} onPress={() => setForm(p => ({...p, media: p.media.filter(m => m.id !== media.id)}))}><X size={20} color={c.muted}/></Button></View>)}
        {moreCapture && <View style={s.captureMore}>
        <View style={s.actions}><Button icon={() => <Camera size={20} color={c.accent}/>} onPress={() => photo(true)}>拍一下</Button><Button icon={() => <Mic size={20} color={voice.isRecording ? c.danger : c.accent}/>} onPress={recordVoice}>{voice.isRecording ? '说完了 ' + Math.floor(voice.durationMillis / 1000) + 's' : '说一句'}</Button><Button onPress={() => photo(false)}>选图</Button></View>
        <View style={s.segment}>{(Object.keys(kinds) as Kind[]).map(kind => <Pressable key={kind} accessibilityRole="button" accessibilityState={{selected: form.kind === kind}} onPress={() => {setForm(p => ({...p, kind})); if (!voice.isRecording) setMoreCapture(false);}} style={[s.kindItem, form.kind === kind && s.kindSelected]}><Text style={[s.kindText, form.kind === kind && {color: c.ink, fontWeight: '600'}]}>{kinds[kind]}</Text></Pressable>)}</View>
</View>}
        {form.kind === 'event' && <View style={{gap: 16, marginVertical: 16}}><TimeField label="开始" value={new Date(form.start)} onChange={date => setForm(p => ({...p, start: date.toISOString()}))}/><TimeField label="结束" value={new Date(form.end)} onChange={date => setForm(p => ({...p, end: date.toISOString()}))}/></View>}
        {form.media.length > 0 && <View style={s.switchRow}><Text style={{flex: 1}}>让 Wearing 整理原件</Text><Switch value={form.organize} onValueChange={organize => setForm(p => ({...p, organize}))} accessibilityLabel="让 Wearing 整理原件"/></View>}
        <View style={s.saveRow}><Pressable accessibilityRole="button" accessibilityLabel="添加照片、语音或选择记录类型" accessibilityState={{expanded: moreCapture}} onPress={() => setMoreCapture(value => voice.isRecording || !value)} style={({pressed}) => [s.moreButton, moreCapture && s.navSelected, pressed && s.pressed]}><Plus size={22} strokeWidth={1.7} color={c.muted}/></Pressable><Text style={[s.muted, {flex: 1, fontSize: 12}]}>{form.kind === 'note' ? '先留住，不必想清楚。' : kinds[form.kind]}</Text><Button mode="contained" onPress={save} loading={saving} disabled={saving || !ready} contentStyle={s.buttonSize}>记下</Button></View>
      </View>
      {pending.length > 0 && <View style={s.section}><Text variant="titleMedium">{pending.length} 条已留在本机</Text>{pending.map(item => <View key={item.id} style={s.pending}><View style={{flex: 1}}><Text variant="bodyLarge">{item.draft.title}</Text><Text style={s.muted}>{item.state === 'attention' ? '需要再看一下：' + item.error : item.state === 'sending' ? '正在同步…' : connection?.development ? '已保留，点同步后发送。' : '等连接恢复，再同步给 Wearing。'}</Text></View>{item.state === 'attention' && <Button onPress={async () => {await outbox.retry(item.scope, item.id); await local(connection!); synchronize(current.current, true);}}>再试一次</Button>}</View>)}</View>}
      <View style={[s.dayGrid, wide && s.dayGridWide]}><View style={[s.section, wide && s.dayPanel]}><Text variant="titleLarge">{new Date().toLocaleDateString('zh-CN', {month: 'long', day: 'numeric', weekday: 'long'})}</Text>{todayEvents.length ? todayEvents.map(row) : <Text style={s.empty}>今天还很空，先给一件小事留点时间。</Text>}<Button textColor={c.muted} style={{alignSelf: 'flex-start', marginLeft: -12}} onPress={() => {setForm(p => ({...p, kind: 'event'})); input.current?.focus();}}>安排一件小事</Button></View>
      <View style={[s.section, wide && s.dayPanel]}><Text variant="titleLarge">惦记着的事</Text>{records.some(r => r.kind === 'task' && !r.completed) ? records.filter(r => r.kind === 'task' && !r.completed).slice(0, 10).map(row) : <Text style={s.empty}>想起来的事先放这里，做完一件就轻一点。</Text>}</View>
      </View><View style={s.section}><Text variant="titleLarge">最近记下的</Text>{records.some(r => r.kind === 'note') ? records.filter(r => r.kind === 'note').slice(0, 5).map(row) : <Text style={s.empty}>一个还没成形的想法，也可以先留在这里。</Text>}</View>
    </>}
    {screen === 'tools' && <><Text style={s.heading}>更多</Text><MenuRow title="文件" icon={<Folder size={23} color={c.muted}/>} onPress={()=>openReviewTool('files')}/><MenuRow title="持续目标" icon={<Target size={23} color={c.muted}/>} onPress={()=>openReviewTool('goals')}/><MenuRow title="定时安排" icon={<Clock3 size={23} color={c.muted}/>} onPress={()=>openReviewTool('schedules')}/><MenuRow title="连接与身份" icon={<Settings size={23} color={c.muted}/>} onPress={()=>setScreen('settings')}/></>}
    {(screen === 'agenda' || screen === 'notes') && <><Text style={s.heading}>日历与笔记</Text><Text style={s.muted}>安排和想法，都在这里。</Text><View accessibilityRole="tablist" style={s.reviewTabs}>{([{view:'agenda',title:'日历'},{view:'notes',title:'笔记'}] as const).map(item=><TactilePressable key={item.view} accessibilityRole="tab" accessibilityState={{selected:screen===item.view}} onPress={()=>setScreen(item.view)} style={[s.reviewTab,screen===item.view&&s.reviewTabActive]}><Text style={[s.muted,screen===item.view&&{color:c.ink,fontWeight:'600'}]}>{item.title}</Text></TactilePressable>)}</View></>}
    {screen === 'agenda' && <><MonthCalendar selected={calendarDate} today={today} onSelect={setSelectedDate} eventCount={date => events.filter(item => eventOccursOn(item, date)).length}/><View style={s.section}>{calendarDate && <Text variant="titleMedium" accessibilityLiveRegion="polite">{calendarDate.month} 月 {calendarDate.day} 日</Text>}{selectedEvents.length ? selectedEvents.map(row) : calendarDate && <Text style={s.empty}>这一天还没有安排。告诉 Wearing 时间和事情，就可以在这里核对。</Text>}</View><Button disabled={!calendarDate} onPress={() => {if (!calendarDate) return;const start = localDateTime(calendarDate, 9);setForm(p => ({...p, kind: 'event', start: start.toISOString(), end: new Date(start.getTime() + 1800000).toISOString()}));setScreen('capture');}}>手动补充日程</Button></>}
    {screen === 'tasks' && <><Text style={s.heading}>任务</Text><Text style={s.muted}>交代的事，都在继续。</Text><View accessibilityRole="tablist" style={s.reviewTabs}>{([{id:'tasks',title:'任务'},{id:'schedules',title:'定时'}] as const).map(tab=><TactilePressable key={tab.id} accessibilityRole="tab" accessibilityState={{selected:taskTab===tab.id}} onPress={()=>setTaskTab(tab.id)} style={[s.reviewTab,taskTab===tab.id&&s.reviewTabActive]}><Text style={[s.muted,taskTab===tab.id&&{color:c.ink,fontWeight:'600'}]}>{tab.title}</Text></TactilePressable>)}</View>{taskTab==='tasks'?<View style={{gap:24}}>{connection&&<AgentTaskList connection={connection} onTask={openActivityTask} onGoals={()=>setTaskTab('goals')} onDraft={prepareMessage}/>}<View style={s.section}><Text style={s.reviewTitle}>待办</Text>{records.some(r=>r.kind==='task') ? records.filter(r=>r.kind==='task').map(row) : <Text style={s.empty}>交代具体要做的事，会记在这里。</Text>}</View></View>:connection?<OngoingPanel key={scopeOf(connection)+taskTab} connection={connection} kind={taskTab} onManage={()=>openReviewTool(taskTab)}/>:null}{taskTab==='schedules'&&<ScheduleSuggestions onDraft={prepareMessage}/>}</>}
    {screen === 'memory' && connection && <MemoryLibrary key={scopeOf(connection)} connection={connection} onFiles={()=>openReviewTool('files')} onChat={()=>setScreen('conversation')} onConnect={()=>setScreen('settings')}/>}
    {(screen === 'companion'||screen === 'settings') && <SettingsHub wardrobe={wardrobe} personal={screen === 'companion'} connection={connection} identity={name} connected={connected} onConnection={()=>setScreen('connection')} onFiles={()=>openReviewTool('files')} onNative={()=>setScreen('native')}/>}
    {screen === 'notes' && <><View style={s.section}>{records.some(r => r.kind === 'note') ? records.filter(r => r.kind === 'note').map(row) : <Text style={s.empty}>还没有笔记。Wearing 整理出的想法和资料会出现在这里。</Text>}</View></>}
    {screen === 'connection' && <><Text variant="headlineLarge" style={s.heading}>连接你的 Wearing。</Text><Text style={s.muted}>已有记录和未同步内容，会分别留在各自的身份里。</Text><View style={{gap: 20, marginTop: 24}}><TextInput mode="outlined" label="Wearing 地址" accessibilityLabel="Wearing 地址" value={address} onChangeText={setAddress} autoCapitalize="none" autoCorrect={false} keyboardType="url"/><TextInput mode="outlined" label="身份标识" accessibilityLabel="身份标识" value={identity} onChangeText={setIdentity} autoCapitalize="none"/>{identities.map(i => <Button key={i.id} mode={identity === i.id ? 'contained-tonal' : 'text'} onPress={() => setIdentity(i.id)}>{i.name}</Button>)}<Button mode="contained" onPress={connect} disabled={busy} loading={busy} contentStyle={s.buttonSize}>连接 Wearing</Button><Text style={s.muted}>{Platform.OS === 'web' ? '当前是手机客户端代码的网页预览，拍照和系统权限需在手机验收。' : '本机试用可通过 USB 连接电脑。远程使用需要你的私人 HTTPS 服务；公开云端登录尚未接入。'}</Text><Text style={s.muted}>离开应用时停止录音并尝试保存。已保存的原件留在应用私有目录；卸载或清除应用数据会移除未同步记录。</Text></View></>}
    {screen === 'detail' && detail && <><Button icon={() => <ChevronLeft size={20}/>} onPress={() => setScreen(detail.kind==='task'?'tasks':detail.kind==='event'?'agenda':'notes')} style={{alignSelf: 'flex-start'}}>回到记录</Button><Text variant="headlineSmall" style={s.heading}>{detail.title}</Text><Text style={s.muted}>{kinds[detail.kind]} · {detail.capture ? stages[detail.capture.state] : '与 Wearing 共用'}</Text><TextInput mode="outlined" multiline label="这条记录" accessibilityLabel="这条记录" value={edit} onChangeText={setEdit} style={{marginVertical: 24}} contentStyle={{minHeight: 180}}/><Button mode="contained" onPress={saveEdit} disabled={!connected}>保存修改</Button>{detail.capture && <View style={s.section}><Text variant="titleMedium">原话与原件</Text><Text style={{marginVertical: 12}}>{detail.capture.original_text}</Text>{connection && detail.capture.assets.map(a => <RemoteOriginal key={a.id} connection={connection} asset={a}/>)}</View>}<Button onPress={() => {setChatRecord(detail); setScreen('conversation');}}>接着和 Wearing 聊</Button></>}
  </ScrollView>;
  return <View style={{flex:1}}><AppBackdrop/><SafeAreaView style={{flex: 1, backgroundColor: 'transparent'}}><StatusBar style={mode === 'night' ? 'light' : 'dark'}/><KeyboardAvoidingView style={{flex: 1}} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
    {(screen==='conversation'||!primary||screen==='agenda'||screen==='notes')&&<View style={s.top}>
      {screen === 'conversation' && connection ? <ActivityReview key={scopeOf(connection)} compact outfit={wardrobe.state.outfit} identity={name} connection={connection} active={foreground} connected={connected} open={activityOpen} onOpenChange={setActivityOpen} onOpenTask={openActivityTask}/> : <IconButton label="返回" style={s.headerCircle} onPress={goBack}><ChevronLeft size={25} color={c.ink}/></IconButton>}
      <View style={{flex:1}}/>
      {screen==='conversation'&&<IconButton label="搜索对话" style={s.headerCircle} onPress={()=>{setReviewRequest({id:Date.now(),target:'search'});setScreen('conversation');}}><Search size={22} strokeWidth={1.7} color={c.ink}/></IconButton>}
      {screen==='conversation'&&<IconButton label="设置" style={s.headerCircle} onPress={()=>setScreen('settings')}><Settings size={22} strokeWidth={1.7} color={c.ink}/></IconButton>}
    </View>}
    {message ? <View style={s.feedback}><Text accessibilityLiveRegion="polite" style={[s.muted, {flex: 1, fontSize: 13}]}>{message}</Text><Pressable accessibilityLabel="收起提示" accessibilityRole="button" onPress={() => setMessage('')} style={s.dismiss}><X size={18} color={c.muted}/></Pressable></View> : null}
    <View style={s.body}>
      {connection ? <RetainedConversation key={scopeOf(connection)} active={foreground&&!activityOpen&&!menu&&!adding&&screen!=='capture'} visible={screen==='conversation'} inputScope={screen} connection={connection} record={chatRecord} reviewRequest={reviewRequest}
        onSend={()=>setScreen('conversation')}
        onCapture={()=>{setScreen('capture');void photo(true);}} onAdd={()=>setAdding(true)}
        navigation={<BottomNavigation outfit={wardrobe.state.outfit} selected={selectedTab} onSelect={selectTab}/>}
        content={<Animated.View key={screen} style={{flex:1,opacity:scene.interpolate({inputRange:[0,1],outputRange:[.55,1]}),transform:[{translateY:scene.interpolate({inputRange:[0,1],outputRange:[7,0]})}]}}>{content}</Animated.View>}/>
        : content}
    </View>
    <Sheet visible={menu} onDismiss={()=>setMenu(false)} title="更多">
      <MenuRow title="文件" detail="查看结果与原件" icon={<Folder size={23} color={c.muted}/>} onPress={()=>openReviewTool('files')}/>
      <MenuRow title="持续目标" detail="查看交给 Wearing 推进的事" icon={<Target size={23} color={c.muted}/>} onPress={()=>{setMenu(false);setTaskTab('goals');setScreen('tasks');}}/>
      <MenuRow title="定时安排" detail="到时会回来做的事" icon={<Clock3 size={23} color={c.muted}/>} onPress={()=>{setMenu(false);setTaskTab('schedules');setScreen('tasks');}}/>
      <MenuRow title="连接与身份" icon={<Settings size={23} color={c.muted}/>} onPress={()=>{setMenu(false);setScreen('settings');}}/>
      <MenuRow title={manualSync?'正在同步…':'同步记录'} icon={<RefreshCw size={23} color={c.muted}/>} onPress={()=>{if(!manualSync)void refresh();}}/>
    </Sheet>
    <Sheet visible={adding} onDismiss={()=>setAdding(false)} title="添加">
      <MenuRow title="拍一张" icon={<Camera size={23} color={c.muted}/>} onPress={()=>{setAdding(false);setScreen('capture');void photo(true);}}/>
      <MenuRow title="选择照片" icon={<ImageIcon size={23} color={c.muted}/>} onPress={()=>{setAdding(false);setScreen('capture');void photo(false);}}/>
      <MenuRow title="补记一条" icon={<FileText size={23} color={c.muted}/>} onPress={()=>{setAdding(false);setScreen('capture');}}/>
    </Sheet>
  </KeyboardAvoidingView></SafeAreaView></View>;
}
function ThemedApp() {
  const {colors: c, mode} = useAppTheme();
  const base = mode === 'night' ? MD3DarkTheme : MD3LightTheme;
  const theme = {...base, colors: {...base.colors, primary: c.accent, onPrimary: c.onAccent, primaryContainer: c.accentSoft, onPrimaryContainer: c.accentInk, secondary: c.accent, onSecondary: c.onAccent, secondaryContainer: c.accentSoft, onSecondaryContainer: c.accentInk, background: c.canvas, surface: c.surface, surfaceVariant: c.soft, onSurface: c.ink, onSurfaceVariant: c.muted, outline: c.line, outlineVariant: c.line, error: c.danger}, roundness: 6};
  return <PaperProvider theme={theme}><Mobile/></PaperProvider>;
}
export default function App() {return <SafeAreaProvider><AppThemeProvider><ThemedApp/></AppThemeProvider></SafeAreaProvider>;}
const makeStyles = (c: AppColors) => StyleSheet.create({
  reviewTabs:{flexDirection:"row",gap:4,padding:4,borderRadius:18,backgroundColor:c.soft,marginTop:24,marginBottom:20},
  reviewTab:{flex:1,minHeight:44,alignItems:"center",justifyContent:"center",borderRadius:14,paddingHorizontal:8},
  reviewTabActive:{backgroundColor:c.surface},
  reviewRow: {flexDirection:"row",alignItems:"center",gap:16,minHeight:78,borderBottomWidth:1,borderBottomColor:c.line,paddingVertical:16},
  reviewTitle: {fontSize:20,color:c.ink,fontWeight:"500"},
  reviewButton: {minHeight:44,flexDirection:"row",alignItems:"center",gap:8},
  headerCircle: {backgroundColor:c.surface,borderRadius:25,borderWidth:1,borderColor:c.line},
  top: {paddingHorizontal: 16, paddingTop: 6, paddingBottom: 10, minHeight: 64, gap:8, flexDirection: 'row', alignItems: 'center'},
  identityPill:{minHeight:44,flexDirection:'row',alignItems:'center',gap:9,paddingHorizontal:12,borderRadius:22,backgroundColor:c.surface},
  identityDot:{width:5,height:5,borderRadius:3,backgroundColor:c.accent}, identityText:{fontSize:14,fontWeight:'500',color:c.ink},
  headerTools: {flexDirection: 'row', alignItems: 'center', gap: 2}, statusDot: {width: 6, height: 6, borderRadius: 3},
  body: {flex: 1}, scroll: {padding: 16, paddingTop: 12, paddingBottom: 32},
  greeting: {flexDirection: 'row', alignItems: 'center', gap: 18, marginBottom: 28},
  heading: {color: c.ink, fontSize: 30, lineHeight: 41, letterSpacing: -.6, marginBottom: 8, fontWeight: '600'},
  muted: {color: c.muted, fontSize: 14, lineHeight: 23}, avatar: {width: 76, height: 76, resizeMode: 'contain'},
  composer: {backgroundColor: c.surface, borderWidth: 1, borderColor: c.line, borderRadius: 24, padding: 20},
  composerFocused: {borderColor: c.accent},
  input: {minHeight: 104, maxHeight: 240, fontSize: 17, lineHeight: 28, color: c.ink, textAlignVertical: 'top', outlineWidth: 0},
  actions: {flexDirection: 'row', flexWrap: 'wrap', marginVertical: 4, marginLeft: -10},
  segment: {flexDirection: 'row', alignSelf: 'flex-start', padding: 3, backgroundColor: c.soft, borderRadius: 14, marginTop: 12},
  kindItem: {paddingHorizontal: 18, minHeight: 40, alignItems: 'center', justifyContent: 'center', borderRadius: 12},
  kindSelected: {backgroundColor: c.surface}, kindText: {fontSize: 13, color: c.muted},
  captureMore: {borderTopWidth: 1, borderTopColor: c.line, paddingTop: 8}, moreButton: {width: 44, height: 44, borderRadius: 14, justifyContent: 'center', alignItems: 'center'},
  saveRow: {flexDirection: 'row', alignItems: 'center', gap: 12, marginTop: 18}, buttonSize: {minHeight: 48}, switchRow: {flexDirection: 'row', alignItems: 'center', gap: 12},
  dayGrid: {gap: 0}, dayGridWide: {flexDirection: 'row', gap: 20}, dayPanel: {flex: 1, minWidth: 0},
  section: {marginTop: 24, gap: 8, backgroundColor: c.surface, borderRadius: 24, padding: 20},
  empty: {color: c.muted, fontSize: 14, lineHeight: 25, paddingVertical: 18},
  row: {flexDirection: 'row', alignItems: 'center', borderBottomWidth: 1, borderBottomColor: c.line, paddingVertical: 8, gap: 6},
  recordBody: {flex: 1, minHeight: 52, borderRadius: 8, paddingVertical: 8},
  recordTitle: {color: c.ink, fontWeight: '500', lineHeight: 25, textAlign: 'left', fontSize: 16},
  recordMeta: {fontSize: 12, lineHeight: 20, marginTop: 3, color: c.muted}, excerpt: {color: c.muted, fontSize: 14, lineHeight: 23, marginTop: 6},
  pending: {flexDirection: 'row', alignItems: 'center', paddingVertical: 16, borderBottomWidth: 1, borderBottomColor: c.line},
  media: {flexDirection: 'row', alignItems: 'center', gap: 12, paddingVertical: 12}, thumbnail: {width: 56, height: 56, borderRadius: 12},
  feedback: {marginHorizontal: 24, marginBottom: 8, paddingHorizontal: 14, paddingVertical: 6, borderRadius: 16, backgroundColor: c.accentSoft, flexDirection: 'row', alignItems: 'center'},
  dismiss: {width: 44, height: 44, justifyContent: 'center', alignItems: 'center'},
  navigation: {flexDirection: 'row', gap: 4, borderTopWidth: 1, borderTopColor: c.line, paddingTop: 8, paddingBottom: 6, paddingHorizontal: 16, backgroundColor: c.canvas},
  navItem: {flex: 1, minHeight: 58, borderRadius: 16, justifyContent: 'center', alignItems: 'center', gap: 5},
  navSelected: {backgroundColor: c.accentSoft}, navText: {fontSize: 11, color: c.muted, lineHeight: 16},
  rail: {width: 190, padding: 18, paddingTop: 32, gap: 8, borderRightWidth: 1, borderRightColor: c.line, backgroundColor: c.soft},
  railItem: {flex: 0, flexDirection: 'row', justifyContent: 'flex-start', gap: 12, paddingHorizontal: 16, minHeight: 48, borderRadius: 14},
  railText: {fontSize: 14, lineHeight: 22}, pressed: {opacity: .65},
});
