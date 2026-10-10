import {StateSwitch,Choice, Segment} from './experience/selection';
import {ChatImportPanel} from './ChatImportPanel';
import {NativeNotificationSession, observeNotificationResponses} from './NativeNotificationsPanel';
import {CalendarSeriesClient} from './calendar-series-client';
import {accountWorkAllowed} from './account-work';
import {NotificationClient, notificationInstallation} from './notification-client';
import ArtifactPanel from './ArtifactPanel';
import NativeSearchPanel, {type SearchContext} from './NativeSearchPanel';
import CloudSessionPanel from './CloudSessionPanel';
import {persistNativeConnection, restoreNativeConnection} from './native-session';
import {assertNativeServiceAddress, initialConnection, PUBLIC_PAJIO_ENDPOINT, requiresNativeSignIn} from './connection-default';
import {developmentConnectionsEnabled} from './development-access';
import BriefPanel from './BriefPanel';
import type {OngoingCreateRequest} from './ongoing-management-forms';
import {AppThemeProvider, useAppTheme, useThemedStyles, type AppColors} from './app-theme';
/** MODE: Operate. THESIS: keep a thought, photo or voice clip first, even offline.
 * Near-neutral reading surfaces, a single cross star, and the pajama bear companion.
 * Native insets, keyboard and Back; canonical records; no invented cloud state.
 * FINISH: captured renders, independent finish verdict and implementation documentation.
 */
import {useEffect, useLayoutEffect, useRef, useState, type ReactNode} from 'react';
import {router, useLocalSearchParams} from 'expo-router';
import {AppState, BackHandler, Image, Keyboard, Pressable, KeyboardAvoidingView, Platform, ScrollView, StyleSheet, TextInput as Input, useWindowDimensions, View, type StyleProp, type ViewStyle} from 'react-native';
import {Button, MD3DarkTheme, MD3LightTheme, PaperProvider, Text, TextInput} from 'react-native-paper';
import {SafeAreaProvider, SafeAreaView, useSafeAreaInsets} from 'react-native-safe-area-context';
import {StatusBar} from 'expo-status-bar';
import * as Crypto from 'expo-crypto';
import * as Picker from 'expo-image-picker';
import * as DocumentPicker from 'expo-document-picker';
import {File} from 'expo-file-system';
import {ImageManipulator, SaveFormat} from 'expo-image-manipulator';
import {AudioModule, RecordingPresets, setAudioModeAsync, useAudioRecorder, useAudioRecorderState} from 'expo-audio';
import {Camera, Image as ImageIcon, ChevronLeft, Clock3, FileText, Folder, Inbox, Mic, Search, Plus, RefreshCw, Settings, Target, X} from 'lucide-react-native';
import {Connection, Kind, makeDraft, Media, Outbox, Pending, RecordItem, scopeOf, WearingApi, connectionEndpoint} from './core';
import {keepMedia, preview, storage} from './storage';
import {PickerRecovery, type PickedPhoto} from './picker-recovery';
import TimeField from './TimeField';
import RetainedConversation from './RetainedConversation';
import ActivityReview from './ActivityReview';
import type {ReviewRequest} from './conversationLink';
import RecordDetail from './RecordDetail';
import {RecordMutations, observeRecordMutations, projectRecordMutations, mutationLabel, type RecordMutation} from './record-mutations';
import {commitRecordReceipt, commitRecordSnapshot, localRecords} from './record-sync';
import {serviceFetch} from './transport';
import {observeDiagnosticError} from './diagnostics-client';
import {BottomNavigation, type BottomNavigationPage} from './experience/BottomNavigation';
import {IconButton, Sheet} from './experience/primitives';
import {MenuRow, OngoingPanel} from './PersonalPanels';
import {ConnectedCalendarPanel, ConnectedTodayPanel} from './ConnectedCalendarViews';
import {CalendarSeriesPanel} from './CalendarSeriesPanel';
import {isSeriesOccurrence, type SeriesOccurrence} from './calendar-series-model';
import {ScheduleSuggestions} from './TodayPanel';
import AgentTaskList from './AgentTaskList';
import TaskDetailPanel from './TaskDetailPanel';
import TaskListsPanel from './TaskListsPanel';
import {MemoryLibrary, SettingsHub} from './PersonalHub';
import {useWardrobe} from './useWardrobe';
import {NativeConnections} from './NativeConnections';
import {NativeActionPanel} from './NativeActionPanel';
import {NativeActionSession} from './NativeActionSession';
import {NativeSyncSession} from './NativeSyncSession';
import {NativeSyncPanel} from './NativeSyncPanel';
import {AppBackdrop} from './experience/AppBackdrop';
import {eventOccursOn, localDateTime, type CalendarDate} from './calendar';
import {useLocalDate} from './use-local-date';
import {feedbackAfterSynchronization, feedbackAfterSyncFailure, type MobileFeedback} from './mobile-sync-feedback';
import {ShareIntakePanel, useShareIntake} from './ShareIntakePanel';
import {SharedChatDrafts} from './share-chat-drafts';
import {createShareCaptureHandler} from './share-intake-delivery';
import {createShareBookmarkHandler} from './share-bookmarks';
import {BookmarksPanel, BookmarkDetailPanel} from './BookmarksPanel';
import ConversationSourcesPanel from './ConversationSourcesPanel';
import AccountDeletionPanel from './AccountDeletionPanel';
import {sameAccount} from './account-deletion-client';
import {clearDeletedAccountLocalData} from './account-cleanup-native';
import {startupDeletionDisposition} from './account-deletion-native';
import OnboardingPanel from './OnboardingPanel';
import {useOnboarding} from './useOnboarding';
import {shouldEnterOnboarding} from './onboarding-model';
import {TabScrollMemory} from './tab-scroll-memory';
import {NativeRemoteDevicePanel} from './NativeRemoteDevicePanel';

type Form = {id: string; text: string; kind: Kind; media: Media[]; organize: boolean; start: string; end: string};
type Screen = 'capture' | 'tools' | 'tasks' | 'agenda' | 'notes' | 'conversation' | 'settings' | 'detail' | 'memory' | 'companion' | 'today' | 'connection' | 'native' | 'trash' | 'briefing' | 'artifact' | 'search' | 'share-intake' | 'chat-import' | 'account-deletion' | 'task-detail' | 'calendar-series' | 'bookmarks' | 'conversation-sources' | 'onboarding' | 'remote-device';
function tabForScreen(screen: Screen): BottomNavigationPage | null {
  return screen==='conversation'?'now':screen==='today'||screen==='agenda'||screen==='notes'?'review':screen==='tasks'?'goals':screen==='memory'?'memory':screen==='companion'?'companion':null;
}
const blank = (): Form => {const start = new Date(); start.setMinutes(Math.ceil(start.getMinutes() / 30) * 30, 0, 0); return {id: Crypto.randomUUID(), text: '', kind: 'note', media: [], organize: true, start: start.toISOString(), end: new Date(start.getTime() + 1800000).toISOString()};};
const voiceOptions = {...RecordingPresets.HIGH_QUALITY, numberOfChannels: 1, bitRate: 64000, directory: 'document' as const};
const kinds = {note: '笔记', task: '任务', event: '日程'};
const stages: {[key: string]: string} = {queued: '等 Pajio 来整理', extracting: '正在读原件', organizing: 'Pajio 正在整理', done: 'Pajio 已整理', saved: '原话与原件已保存', failed: '原件已保存，整理可重试', paused: '原件已保存，整理暂停', conflict: '保留了你的编辑'};

function Original({media}: {media: Media}) {
  const {colors: c} = useAppTheme();
  const s = useThemedStyles(makeStyles);

  const [uri, setUri] = useState('');
  useEffect(() => {let live = true; preview(media.id).then(value => {if (live) setUri(value);}).catch(() => {}); return () => {live = false;};}, [media.id]);
  return <View style={s.media}>{media.mime.startsWith('image/') && uri ? <Image source={{uri}} style={s.thumbnail} accessibilityLabel={media.name}/> : <Mic size={22} color={c.muted}/>}<View style={{flex: 1}}><Text>{media.name}</Text><Text variant="bodySmall" style={s.muted}>原件已留在本机</Text></View></View>;
}

function ShareInboxNotice({connection, onOpen}: {connection: Connection; onOpen: () => void}) {
  const {items, error} = useShareIntake(connection);
  if (!items.length && !error) return null;
  return <Button icon="inbox-arrow-down-outline" onPress={onOpen} accessibilityLabel="打开分享收件箱">{items.length ? `${items.length} 份分享待处理` : '有一份分享需要查看'}</Button>;
}

function ReadingScrollView({memory, rememberKey, children, contentContainerStyle}: {
  memory: TabScrollMemory; rememberKey: string | null; children: ReactNode; contentContainerStyle: StyleProp<ViewStyle>;
}) {
  const scroll = useRef<ScrollView>(null), visit = useRef(0);
  const frame = useRef<ReturnType<typeof requestAnimationFrame> | null>(null);
  const clamp = useRef(false);
  function restorePosition() {
    if (frame.current !== null) cancelAnimationFrame(frame.current);
    const intended = visit.current;
    frame.current = requestAnimationFrame(() => {
      frame.current = null;
      const offset = memory.restore(intended, clamp.current);
      if (offset !== null) scroll.current?.scrollTo({y: offset, animated: false});
    });
  }
  useLayoutEffect(() => {
    const id = memory.begin(rememberKey); visit.current = id; clamp.current = false;
    // Give panels time to replace their loading state. Shorter results still
    // recover a valid position; any user touch cancels the pending restoration.
    const timer = setTimeout(() => {clamp.current = true; restorePosition();}, 1500);
    return () => {
      clearTimeout(timer); if (frame.current !== null) cancelAnimationFrame(frame.current);
      frame.current = null; memory.end(id);
    };
    // This effect establishes one visit; native size events drive restoration.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [memory, rememberKey]);
  return <ScrollView ref={scroll} keyboardShouldPersistTaps="handled" keyboardDismissMode="on-drag"
    maximumZoomScale={1} minimumZoomScale={1} pinchGestureEnabled={false}
    contentContainerStyle={contentContainerStyle} scrollEventThrottle={32}
    onLayout={event => {memory.viewport(visit.current, event.nativeEvent.layout.height); restorePosition();}}
    onContentSizeChange={(_, height) => {memory.content(visit.current, height); restorePosition();}}
    onTouchStart={() => memory.interact(visit.current)} onScrollBeginDrag={() => memory.interact(visit.current)}
    onScroll={event => memory.record(visit.current, event.nativeEvent.contentOffset.y)}>{children}</ScrollView>;
}

function Mobile() {
  const safeInsets = useSafeAreaInsets();
  const {colors: c, mode} = useAppTheme();
  const s = useThemedStyles(makeStyles);

  const wide = useWindowDimensions().width >= 840;
  const [connection, setConnection] = useState<Connection | null>(null); const current = useRef<Connection | null>(null);
  const [deletionFrozen, setDeletionFrozen] = useState(false);
  const wardrobe = useWardrobe(connection);
  const [identities, setIdentities] = useState<{id: string; name: string}[]>([]);
  const {view,memoryPath,memoryFile,memorySection,hubSection,artifact,authDone,authError,resource,deviceKind,deviceName} = useLocalSearchParams<{view?: string;memoryPath?:string;memoryFile?:string;memorySection?:string;hubSection?:string;artifact?:string;authDone?:string;authError?:string;resource?:string;deviceKind?:string;deviceName?:string}>();
  const screen: Screen = ['capture','tools','tasks','agenda','notes','conversation','settings','detail','memory','companion','today','connection','native','trash','briefing','artifact','search','share-intake','chat-import','account-deletion','task-detail','calendar-series','bookmarks','conversation-sources','onboarding','remote-device'].includes(view || '') ? view as Screen : 'conversation';
  const [menu, setMenu] = useState(false), [adding, setAdding] = useState(false);
  const [taskTab, setTaskTab] = useState<'tasks' | 'goals' | 'schedules' | 'lists'>('tasks');
  const [readingPositions] = useState(() => new TabScrollMemory());
  const artifactId = /^art_[a-f0-9]{1,64}$/.test(artifact || '') ? artifact! : '';
  const [chatImportShareId, setChatImportShareId] = useState<string | undefined>();
  const [briefingIntro, setBriefingIntro] = useState(false);
  function openChatImport(id?: string) {setChatImportShareId(id); setScreen('chat-import');}
  const onboardingReturn = useRef<Screen>('conversation');
  const onboardingSeen = useRef<Connection|null>(null);
  const artifactReturn = useRef<Screen>('conversation'), detailReturn = useRef<Screen>('today'), taskReturn = useRef<Screen>('tasks');
  const [openedTask,setOpenedTask] = useState<string | null>(null);
  const seriesReturn=useRef<Screen>('agenda');
  const [seriesTarget,setSeriesTarget]=useState<{seriesId?:string;occurrence?:SeriesOccurrence;initialDay?:CalendarDate}>({});
  function openSeries(target:typeof seriesTarget){if(screen!=='calendar-series')seriesReturn.current=screen;setSeriesTarget(target);setScreen('calendar-series');}
  const searchContext = useRef<{scope: string; value: SearchContext} | null>(null);
  const openArtifact = (id: string) => {if (screen !== 'artifact') artifactReturn.current = screen; router.setParams({view:'artifact',artifact:id});};
  const [taskCreate,setTaskCreate] = useState<OngoingCreateRequest>();
  const [lastTab, setLastTab] = useState<BottomNavigationPage>(()=>tabForScreen(screen)||'now');
  const [lastReview,setLastReview] = useState<'agenda'|'tasks'|'notes'>('agenda');
  const today = useLocalDate();
  const [selectedDate, setSelectedDate] = useState<CalendarDate | null>(null);
  const calendarDate = selectedDate || today;
  const setScreen = (next: Screen) => {if(next==='agenda'||next==='tasks'||next==='notes')setLastReview(next);const tab=tabForScreen(next);if(tab)setLastTab(tab);router.setParams({view:next,memoryPath:'',memoryFile:'',memorySection:'',memoryQuery:'',hubSection:'',artifact:''});};
  const primary = ['conversation','today','agenda','tasks','notes','memory','companion'].includes(screen);
  const selectedTab = tabForScreen(screen)||lastTab;
  function selectTab(tab: BottomNavigationPage) {Keyboard.dismiss();setLastTab(tab);setReviewRequest(null);setScreen(tab==='now'?'conversation':tab==='review'?'today':tab==='goals'?'tasks':tab);}
  function goBack(){
    if(screen==='remote-device'){router.setParams({view:'settings',hubSection:'devices',resource:'',deviceKind:'',deviceName:''});return;}
    if((screen==='settings'||screen==='companion')&&hubSection){router.setParams({hubSection:hubSection==='wardrobe'?'appearance':''});return;}
    if(screen==='memory'&&memoryFile){router.setParams({memoryFile:''});return;}
    if(screen==='memory'&&memoryPath){router.setParams({memoryPath:memoryPath.split('/').slice(0,-1).join('/')});return;}
    if(screen==='memory'&&memorySection){router.setParams({memorySection:''});return;}
    if(screen==='agenda'||screen==='notes'){setScreen('today');return;}
    if(screen==='artifact'){setScreen(artifactReturn.current);return;}
    if(screen==='detail'){setScreen(detailReturn.current);return;}
    if(screen==='task-detail'){setScreen(taskReturn.current);return;}
    if(screen==='calendar-series'){setScreen(seriesReturn.current);return;}
    if(screen==='onboarding'){onboardingSeen.current=connection;setScreen(onboardingReturn.current);return;}
    if(screen==='briefing'){setScreen('today');return;}
    if(screen==='trash'){setScreen('settings');return;}
    if(screen==='chat-import'){setScreen('settings');return;}
    if(screen==='bookmarks'){setScreen('settings');return;}
    if(screen==='conversation-sources'){setScreen('memory');return;}
    if(screen==='native'||screen==='connection'){setScreen('settings');return;}
    setScreen(primary?'conversation':screen==='capture'?lastReview:lastTab==='now'?'conversation':lastTab==='review'?'today':lastTab==='goals'?'tasks':lastTab);
  }
  const [reviewRequest,setReviewRequest] = useState<ReviewRequest | null>(null);
  const [activityOpen, setActivityOpen] = useState(false);
  function prepareMessage(text:string){setReviewRequest({id:Date.now(),target:'draft',text});setScreen('conversation');}
  function openFiles(query = ''){setScreen('memory');router.setParams({memorySection:'files',memoryQuery:query});}
  function openReviewTool(target:'files'|'goals'|'schedules'){setMenu(false);if(target==='files'){openFiles();return;}setReviewRequest({id:Date.now(),target});setScreen('conversation');}
  function openTaskConversation(taskId: string) {setActivityOpen(false); setChatRecord(null); setReviewRequest({id:Date.now(),target:'activity',taskId});setScreen('conversation');}
  function openActivityTask(taskId: string) {if(screen!=='task-detail')taskReturn.current=screen;setActivityOpen(false);setOpenedTask(taskId);setScreen('task-detail');}
  const screenRef = useRef(screen);
  useLayoutEffect(() => {screenRef.current = screen;}, [screen]);
  const [form, setForm] = useState<Form>(blank); const formRef = useRef(form);
  const [pickerRecovery] = useState(() => new PickerRecovery(storage, () => Crypto.randomUUID()));
  useLayoutEffect(() => {formRef.current = form;}, [form]);
  const draftTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const captureWriting = useRef(false); const [captureLocked, setCaptureLocked] = useState(false);
  // Acquire synchronously: a second tap or native callback can precede React's render.
  function beginCaptureWrite() {
    if (captureWriting.current) return null;
    captureWriting.current = true; setCaptureLocked(true);
    if (draftTimer.current) {clearTimeout(draftTimer.current); draftTimer.current = null;}
    return () => {captureWriting.current = false; setCaptureLocked(false);};
  }
  function changeForm(change: (previous: Form) => Form) {
    if (captureWriting.current) return;
    const next = change(formRef.current); formRef.current = next; setForm(next);
  }
  const [records, setRecords] = useState<RecordItem[]>([]); const [pending, setPending] = useState<Pending[]>([]);
  const [pendingMutations, setPendingMutations] = useState<RecordMutation[]>([]); const localRead = useRef(0);
  const [feedback, setFeedback] = useState<MobileFeedback>({text: '', source: 'action'});
  const message = feedback.text;
  function setMessage(text: string) {setFeedback({text, source: 'action'});}
  const [connected, setConnected] = useState(false);
  const [busy, setBusy] = useState(false); const syncBusy = useRef(false); const [saving, setSaving] = useState(false); const [ready, setReady] = useState(false);
  const [address, setAddress] = useState(PUBLIC_PAJIO_ENDPOINT); const [identity, setIdentity] = useState('daily');
  const [advancedConnection, setAdvancedConnection] = useState(false);
  const [foreground, setForeground] = useState(AppState.currentState === 'active');
  const [chatRecord, setChatRecord] = useState<RecordItem | null>(null);
  const [detail, setDetail] = useState<RecordItem | null>(null);
  const recordWrites = useRef(new Set<string>()); const [writingRecords, setWritingRecords] = useState<string[]>([]);
  const activationEpoch = useRef(0);
  const connectionWrite = useRef(false); const [startupAttempt, setStartupAttempt] = useState(0);
  const recorder = useAudioRecorder(voiceOptions); const voice = useAudioRecorderState(recorder, 250); const voiceBusy = useRef(false);
  const voiceConnection = useRef<Connection | null>(null); const voiceStop = useRef<Promise<boolean> | null>(null);
  const voiceRecovery = useRef<{uri: string; connection: Connection | null} | null>(null);
  const input = useRef<Input>(null); const [outbox] = useState(() => new Outbox(storage));
  const [mutations] = useState(() => new RecordMutations(storage, () => Crypto.randomUUID()));
  const [manualSync, setManualSync] = useState(false);
  const onboarding = useOnboarding(connection, ready && connected && !deletionFrozen);
  useEffect(() => {
    if (!connection || !onboarding || onboardingSeen.current===connection || deletionFrozen || !shouldEnterOnboarding(onboarding,screen,!!connection.session?.accessToken)) return;
    onboardingSeen.current=connection; onboardingReturn.current='conversation'; setScreen('onboarding');
  }, [connection,onboarding,screen,deletionFrozen]);
  const [moreCapture, setMoreCapture] = useState(false);
  const [inputFocused, setInputFocused] = useState(false);
  async function refresh() {setManualSync(true);try {await synchronize(current.current, true);} finally {setManualSync(false);}}
  const handlers = useRef({activateConnection, synchronize, stopVoice, goBack, openActivityTask, local, open});
  useLayoutEffect(() => {handlers.current = {activateConnection, synchronize, stopVoice, goBack, openActivityTask, local, open};});
  async function local(connection: Connection) {
    if (current.current !== connection) return;
    const scope = scopeOf(connection), ticket = ++localRead.current;
    const [canonical, items, edits] = await Promise.all([localRecords(storage, scope), outbox.items(scope), mutations.items(scope)]);
    if (current.current !== connection || localRead.current !== ticket) return;
    setRecords(projectRecordMutations(canonical, edits)); setPending(items); setPendingMutations(edits);
  }
  useEffect(() => {
    if (!connection) return;
    return observeRecordMutations(scopeOf(connection), () => {void handlers.current.local(connection).catch(error => {if (current.current === connection) setMessage(error instanceof Error ? error.message : '本机修改暂时无法读取。');});});
  }, [connection]);
  async function synchronize(connection = current.current, allowPending = !connection?.development) {
    if (!connection || syncBusy.current || AppState.currentState !== 'active') return;
    if (requiresNativeSignIn(connection, Platform.OS)) {setConnected(false); await local(connection); return;}
    if(connection.session && (!connection.session.accessToken || Date.parse(connection.session.expiresAt)<=Date.now())){setConnected(false);await local(connection);return;}
    syncBusy.current = true; setBusy(true);
    try {
      const api = new WearingApi(connection, serviceFetch); const data = await api.bootstrap();
      if (current.current !== connection) return;
      setIdentities(data.identities);
      // Opening a short-term development pairing must not send an existing queue.
      let sent = allowPending ? await outbox.flush(scopeOf(connection), api, () => current.current === connection && AppState.currentState === 'active') : 0;
      if (allowPending) sent += await mutations.flush(scopeOf(connection), api, () => current.current === connection && AppState.currentState === 'active', Date.now(), error => observeDiagnosticError(connection, 'record', error));
      const snapshot = await api.snapshot(); await commitRecordSnapshot(storage, scopeOf(connection), snapshot);
      if (current.current === connection) {
        setConnected(true);
        setFeedback(previous => feedbackAfterSynchronization(previous, sent));
      }
    } catch (error) {observeDiagnosticError(connection, 'sync', error); if (current.current === connection) {setConnected(false); setFeedback(previous => feedbackAfterSyncFailure(previous, error instanceof Error ? error.message : '暂时没连上，原件仍在本机。'));}}
    finally {
      try {await local(connection);}
      catch {if (current.current === connection) setMessage('暂时没能读到本机记录，请检查存储空间后再同步。');}
      finally {syncBusy.current = false; setBusy(false); if (current.current && current.current !== connection) void synchronize(current.current);}
    }
  }
  async function activateConnection(connection: Connection) {
    if (Platform.OS !== 'web') assertNativeServiceAddress(connection.endpoint);
    const release = beginCaptureWrite();
    if (!release) throw new Error('输入或原件正在保存，请稍后再切换。');
    const ticket = ++activationEpoch.current;
    const assertActivation = () => {if (ticket !== activationEpoch.current) throw new Error('账户状态已变化，请重新登录或查看注销进度。');};
    try {
      if (voiceBusy.current && !voiceStop.current) throw new Error('麦克风正在准备，请稍后再切换。');
      if ((recorder.isRecording || voiceStop.current || voiceRecovery.current) && !await stopVoice()) throw new Error('录音还没保存好，暂时没有切换身份。');
      assertActivation();
      if (draftTimer.current) clearTimeout(draftTimer.current);
      if (current.current) await storage.put(`draft:${scopeOf(current.current)}`, formRef.current);
      assertActivation();
      // Resolve the new draft before exposing its identity to autosave or capture.
      const saved = await storage.get<Form>(`draft:${scopeOf(connection)}`);
      assertActivation();
      const next = saved ? {...saved, id: saved.id || Crypto.randomUUID()} : blank();
      const frozen = await startupDeletionDisposition(connection) === 'review';
      assertActivation();
      if (!frozen) await persistNativeConnection(connection);
      assertActivation();
      current.current = connection; formRef.current = next; setForm(next);
      setDeletionFrozen(frozen);
      setConnection(connection); setConnected(false); setRecords([]); setPending([]); setPendingMutations([]); setDetail(null); setChatRecord(null); setReviewRequest(null); setActivityOpen(false); setLastReview('agenda');
      router.setParams({memoryPath:'',memoryFile:'',memorySection:'',memoryQuery:'',hubSection:''});
      setAddress(connection.endpoint); setIdentity(connection.identity);
      if (frozen) {current.current = null; const {accessToken: _removed, ...session} = connection.session!; setConnection({...connection, session}); formRef.current = blank(); setForm(formRef.current); setScreen('account-deletion');}
      else {
        await local(connection); void synchronize(connection);
        if (Platform.OS === 'android') try {await recoverPicker(connection);} catch (error) {if (current.current === connection) setMessage(error instanceof Error ? error.message : '上次选图还未恢复，请重新打开草稿。');}
      }
    } finally {release();}
  }
  useEffect(() => {
    let active = true;
    (async () => {try {
      const stored = await restoreNativeConnection();
      const connection = initialConnection(stored, Platform.OS, Platform.OS === 'web' ? window.location.origin : undefined);
      connection.endpoint = connectionEndpoint(connection, true); if (!active) return;
      await handlers.current.activateConnection(connection); setReady(true); if(!stored&&Platform.OS!=='web')setScreen('connection');
    } catch (error) {setMessage(error instanceof Error ? error.message : '本机存储暂时无法打开，尚未保存新记录。请检查存储空间后重试。');}})();
    return () => {active = false;};
  }, [startupAttempt,authDone]);
  useEffect(()=>{if(authError)setMessage('登录没有完成，请重新登录。');},[authError]);
  useEffect(() => {
    if (!connection || !ready || !connected || (connection.session && !connection.session.accessToken)) return;
    let live = true;
    const stop = observeNotificationResponses(async target => {
      const original = current.current;
      if (!original || !live) return false;
      const data = await new WearingApi(original, serviceFetch).bootstrap();
      if (!data.identities.some(item => item.id === target.identity_id) || !live || current.current !== original) return false;
      const destination = {...original, identity:target.identity_id};
      const client = new NotificationClient(destination, await notificationInstallation(storage,()=>Crypto.randomUUID()), serviceFetch);
      const resolved = await client.resolve(target);
      if (!live || current.current !== original) return false;
      let record: RecordItem | null = null;
      if (resolved.type === 'record') {
        if (resolved.seriesId && resolved.occurrenceKey) record = (await new CalendarSeriesClient(destination, serviceFetch, () => live && current.current === original && accountWorkAllowed(original)).get(resolved.seriesId, resolved.occurrenceKey)).selected ?? null;
        else record = await new WearingApi(destination, serviceFetch).record(resolved.recordId);
        if (!record || record.id !== resolved.recordId || (record as RecordItem & {identity_id?: string}).identity_id !== destination.identity || record.deleted_at) throw new Error('这项安排已取消或改变，请在日历与待办中查看最新状态。');
      }
      if (!live || current.current !== original || !accountWorkAllowed(original)) return false;
      const expected = destination.identity !== original.identity ? destination : original;
      if (expected === destination) await handlers.current.activateConnection(destination);
      if (current.current !== expected || !accountWorkAllowed(expected)) return false;
      if (resolved.type === 'record' && record) handlers.current.open(record);
      else if (resolved.type === 'task') handlers.current.openActivityTask(resolved.taskId);
      return true;
    }, message => {if(live)setMessage(message);});
    return () => {live = false; stop();};
  }, [connection,ready,connected]);
  useEffect(() => {
    if (!connection || !ready || captureLocked || deletionFrozen) return;
    draftTimer.current = setTimeout(() => {storage.put(`draft:${scopeOf(connection)}`, form).catch(() => setMessage('草稿还没保存好，请保留输入并检查存储空间。'));}, 150);
    return () => {if (draftTimer.current) clearTimeout(draftTimer.current);};
  }, [form, connection, ready, captureLocked, deletionFrozen]);
  useEffect(() => {
    const timer = setInterval(() => {handlers.current.synchronize();}, 15000);
    const listener = AppState.addEventListener('change', state => {setForeground(state === 'active'); if (state === 'active') handlers.current.synchronize(); else handlers.current.stopVoice();});
    const back = BackHandler.addEventListener('hardwareBackPress', () => {if (screenRef.current !== 'conversation') {handlers.current.goBack(); return true;} return false;});
    return () => {clearInterval(timer); listener.remove(); back.remove();};
  }, []);
  useEffect(() => {if(screen!=='capture')void handlers.current.stopVoice();},[screen]);
  useEffect(() => {if (voice.isRecording && voice.durationMillis >= 180000) handlers.current.stopVoice();}, [voice.durationMillis, voice.isRecording]);
  async function addOriginal(uri: string, name: string, mime: string, connection = current.current) {
    if (!connection || current.current !== connection) throw new Error('身份已切换，原件没有加入新身份。');
    if (formRef.current.media.length >= 4) throw new Error('一次最多放四份原件。');
    const media = await keepMedia(uri, {id: Crypto.randomUUID(), name, mime, size: 0}, connection);
    if (media.size > 15 * 1024 * 1024) throw new Error('这份原件超过 15 MB，请选一份较小的。');
    if (current.current !== connection) {setMessage('身份已切换，这份原件未加入新身份。'); return;}
    const next = {...formRef.current, media: [...formRef.current.media, media]};
    await storage.put(`draft:${scopeOf(connection)}`, next);
    if (current.current !== connection) return;
    formRef.current = next; setForm(next); setMessage('原件已留在本机，可以再补一句。');
  }
  async function recoverPicker(connection: Connection) {
    if (current.current !== connection || !accountWorkAllowed(connection)) return;
    await pickerRecovery.collectPending(() => Picker.getPendingResultAsync());
    const prior = formRef.current;
    const next = await pickerRecovery.apply(scopeOf(connection), prior, () => current.current === connection && accountWorkAllowed(connection), async (asset: PickedPhoto, id: string) => {
      let {uri,mime,name} = asset;
      if (!['image/jpeg','image/png','image/webp'].includes(mime) || asset.width * asset.height > 24000000) {
        const context = ImageManipulator.manipulate(uri); if (asset.width > 2400) context.resize({width:2400});
        const image = await (await context.renderAsync()).saveAsync({format:SaveFormat.JPEG,compress:.85});
        uri = image.uri; mime = 'image/jpeg'; name = name.replace(/\.[^.]+$/, '') + '.jpg';
      }
      if (current.current !== connection || !accountWorkAllowed(connection)) throw Error('账户已切换，照片没有加入其他身份。');
      return keepMedia(uri,{id,name,mime,size:0},connection,true);
    });
    if (current.current === connection && accountWorkAllowed(connection) && next !== prior) {
      formRef.current = next; setForm(next); setScreen('capture'); setMessage('上次选取的照片已恢复到原来的草稿，尚未发送。');
    }
  }
  async function photo(camera: boolean) {
    const release = beginCaptureWrite(); if (!release) return;
    const intended = current.current;
    try {
      if (voiceBusy.current && !voiceStop.current) throw new Error('麦克风正在准备，请稍后再选图。');
      if ((recorder.isRecording || voiceStop.current || voiceRecovery.current) && !await stopVoice()) throw new Error('先把这段录音保存好，再选图。');
      if (intended) await storage.put(`draft:${scopeOf(intended)}`, formRef.current);
      if (camera && !(await Picker.requestCameraPermissionsAsync()).granted) throw new Error('还没有相机权限，可以先选一张图片。');
      if (Platform.OS === 'android') {
        if (!intended || current.current !== intended || !accountWorkAllowed(intended)) throw Error('请先连接账户再选图。');
        await recoverPicker(intended);
        if (formRef.current.media.length >= 4) throw Error('一次最多放四份原件。');
        const intent = await pickerRecovery.begin(scopeOf(intended),formRef.current.id,() => Picker.getPendingResultAsync(),() => current.current === intended && accountWorkAllowed(intended));
        if (current.current !== intended || !accountWorkAllowed(intended)) throw Error('账户已切换，没有打开选图。');
        const result = camera ? await Picker.launchCameraAsync({mediaTypes:['images'],quality:.8}) : await Picker.launchImageLibraryAsync({mediaTypes:['images'],quality:1,selectionLimit:1});
        await pickerRecovery.accept(intent,result);
        await recoverPicker(intended); return;
      }
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
    finally {release();}
  }
  async function pickAudio() {
    const release=beginCaptureWrite();if(!release)return;
    const intended=current.current;
    try {
      if(voiceBusy.current&&!voiceStop.current)throw new Error('麦克风正在准备，请稍后再选录音。');
      if((recorder.isRecording||voiceStop.current||voiceRecovery.current)&&!await stopVoice())throw new Error('先把这段录音保存好，再选文件。');
      const result=await DocumentPicker.getDocumentAsync({type:'audio/*',copyToCacheDirectory:true,multiple:false});
      if(result.canceled)return;
      const asset=result.assets[0];if(asset.size&&asset.size>15*1024*1024)throw new Error('录音超过15 MB，请选择较小的文件。');
      await addOriginal(asset.uri,asset.name,asset.mimeType||'audio/mp4',intended);
    }catch(error){if(current.current===intended)setMessage(error instanceof Error?error.message:'录音没有保存好，请重新选择。');}
    finally{release();}
  }
  async function stopVoice(): Promise<boolean> {
    if (voiceStop.current) return voiceStop.current;
    if (!recorder.isRecording && !voiceRecovery.current) return !voiceBusy.current;
    const release = captureWriting.current ? null : beginCaptureWrite();
    const intended = voiceRecovery.current?.connection || voiceConnection.current; voiceBusy.current = true;
    voiceStop.current = (async () => {
      try {if (recorder.isRecording) {await recorder.stop(); if (recorder.uri) voiceRecovery.current = {uri: recorder.uri, connection: intended};}
        if (!voiceRecovery.current) throw new Error('录音文件尚未生成。');
        await addOriginal(voiceRecovery.current.uri, Platform.OS === 'web' ? '随口说的.webm' : '随口说的.m4a', Platform.OS === 'web' ? 'audio/webm' : 'audio/mp4', intended); voiceRecovery.current = null; return true;}
      catch {setMessage('录音暂时没保存好，请保留页面，再点「说一句」重试。'); return false;}
      finally {voiceBusy.current = false; voiceConnection.current = null; voiceStop.current = null; release?.();}
    })();
    return voiceStop.current;
  }
  async function recordVoice() {
    if (captureWriting.current) return;
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
    if (!connection || saving || !ready) return;
    const release = beginCaptureWrite(); if (!release) return;
    setSaving(true);
    try {
      if (voiceBusy.current && !voiceStop.current) throw new Error('麦克风正在准备，请稍后再保存。');
      if ((recorder.isRecording || voiceStop.current || voiceRecovery.current) && !await stopVoice()) throw new Error('录音还没保存好，输入保留在这里。');
      const connection = current.current!; const form = formRef.current;
      const text = form.text.trim() || (form.media.some(m => m.mime.startsWith('image/')) ? '随手拍下的' : form.media.length ? '保存的录音' : '');
      const draft = makeDraft(text, form.kind, new Date(form.start), new Date(form.end));
      if (draftTimer.current) clearTimeout(draftTimer.current);
      const empty = blank();
      // The outbox may be waiting on a slow upload; retain this accepted text first.
      await storage.put(`draft:${scopeOf(connection)}`, form);
      await outbox.enqueue({id: form.id, scope: scopeOf(connection), draft, media: form.media, uploaded: [], organize: form.organize, state: 'pending', attempts: 0, nextAt: 0, createdAt: new Date().toISOString()}, [`draft:${scopeOf(connection)}`, empty]);
      if (current.current !== connection) return;
      formRef.current = empty; setForm(empty);
      setFeedback({text: '已留在本机。连接后会同步给 Pajio。', source: 'sync'}); await local(connection); synchronize(connection, true);
    } catch (error) {setMessage(error instanceof Error ? error.message : '没有保存成功，输入仍在这里。');}
    finally {setSaving(false); release();}
  }
  async function connect() {
    if (!developmentConnectionsEnabled()) return;
    if(connectionWrite.current)return;connectionWrite.current=true;
    try {
      const prior = current.current;
      const connection: Connection = {endpoint: address, identity, ...(prior?.session && address.trim().replace(/\/$/,'')===prior.endpoint.replace(/\/$/,'') ? {session:prior.session}:{}), ...(prior?.development && address.trim().replace(/\/$/, '') === prior.endpoint.replace(/\/$/, '') && identity === prior.identity ? {development: prior.development} : {})};
      connection.endpoint = connectionEndpoint(connection); setBusy(true);
      const data = await new WearingApi(connection, serviceFetch).bootstrap(); setIdentities(data.identities);
      await activateConnection(connection); setReady(true); setScreen('conversation'); setMessage('已连接，可以继续说。');
    } catch (error) {setMessage(error instanceof Error ? error.message : '连接没有成功，原连接仍在。');}
    finally {connectionWrite.current=false;setBusy(false);}
  }
  async function toggle(item: RecordItem) {
    const intended = current.current;
    if (!intended) {setMessage('请先选择记录所属的身份。'); return;}
    const scope = scopeOf(intended), key = scope + item.id;
    if (recordWrites.current.has(key)) return;
    recordWrites.current.add(key); setWritingRecords([...recordWrites.current]);
    try {
      await mutations.enqueue(scope, item, {completed: !item.completed});
      if (current.current !== intended) return;
      await local(intended); setMessage('完成状态已留在本机，连接后会同步。');
      void mutations.flush(scope, new WearingApi(intended, serviceFetch), () => current.current === intended && AppState.currentState === 'active', Date.now(), error => observeDiagnosticError(intended, 'record', error)).then(() => local(intended)).catch(error => {if (current.current === intended) setMessage(error instanceof Error ? error.message : '修改仍在本机，稍后可重试。');});
    } catch (error) {observeDiagnosticError(intended, 'record', error); if (current.current === intended) setMessage(error instanceof Error ? error.message : '本机保存未完成，请重试。');}
    finally {recordWrites.current.delete(key); setWritingRecords([...recordWrites.current]);}
  }
  function recordChanged(item: RecordItem, intended: Connection) {
    if (current.current !== intended) return;
    void commitRecordReceipt(storage, scopeOf(intended), item).then(() => local(intended)).catch(error => {if (current.current === intended) setMessage(error instanceof Error ? error.message : '回执暂未更新，请同步核对。');});
  }
  function open(item: RecordItem) {if(isSeriesOccurrence(item)){openSeries({occurrence:item});return;}detailReturn.current = screen; setDetail(item);setScreen('detail');}
  const searchOpen = useRef(0);
  async function openSearchRecord(id: string) {
    const intended = current.current, ticket = ++searchOpen.current;
    if (!intended) return;
    try {
      const item = await new WearingApi(intended, serviceFetch).record(id);
      if (current.current === intended && screenRef.current === 'search' && ticket === searchOpen.current) open(item);
    } catch (error) {
      observeDiagnosticError(intended, 'record', error);
      if (current.current === intended && screenRef.current === 'search' && ticket === searchOpen.current) setMessage(error instanceof Error ? error.message : '记录未能打开，请重试。');
    }
  }
  async function retryPending(item: Pending) {
    const intended=current.current;if(!intended||manualSync||syncBusy.current)return;
    setManualSync(true);
    try {await outbox.retry(scopeOf(intended),item.id);if(current.current===intended)await synchronize(intended,true);}
    catch(error){if(current.current===intended)setMessage(error instanceof Error?error.message:'同步未完成，原件保留在本机。');}
    finally{setManualSync(false);}
  }
  async function freezeAccount(target: Connection) {
    // Invalidate even an activation of this account that has not become visible.
    activationEpoch.current++;
    const matches = !!current.current?.session && sameAccount(current.current, target);
    const recordingUris: string[] = [];
    if (matches) {
      // Invalidate every captured business operation before awaiting disk or OS work.
      current.current = null; localRead.current++; searchOpen.current++;
      if (draftTimer.current) {clearTimeout(draftTimer.current); draftTimer.current = null;}
      const {accessToken: _removed, ...session} = connection!.session!;
      setConnection({...connection!, session}); setDeletionFrozen(true); setConnected(false);
      setRecords([]); setPending([]); setPendingMutations([]); setDetail(null); setChatRecord(null);
      setReviewRequest(null); setActivityOpen(false); setMenu(false); setAdding(false); searchContext.current = null;
      formRef.current = blank(); setForm(formRef.current); setScreen('account-deletion');
      const recordingOwner = voiceConnection.current;
      const recovery = voiceRecovery.current;
      if (recorder.isRecording) await recorder.stop().catch(() => {});
      if (recordingOwner?.session && sameAccount(recordingOwner, target) && recorder.uri) recordingUris.push(recorder.uri);
      if (recovery?.connection?.session && sameAccount(recovery.connection, target)) recordingUris.push(recovery.uri);
      if (voiceStop.current) await voiceStop.current.catch(() => false);
      voiceRecovery.current = null; voiceConnection.current = null;
    }
    const report = await clearDeletedAccountLocalData(target, {recordingUris});
    if (matches && !current.current) setMessage(report.pendingFiles || report.unownedLegacy
      ? '账户已停止使用；部分本机副本尚需核对，可刷新清理进度重试。'
      : '已清理能确认归属的本机副本。云端数据以注销进度为准；旧版未登记的凭据仍需核对。');
    if (report.pendingFiles) throw new Error('部分本机副本尚未清理，请刷新注销进度重试。');
  }
  const deletionPanel = <AccountDeletionPanel key={connection?.session ? connection.endpoint + '|' + connection.session.userId : 'no-account'} connection={connection}
    onReauthenticated={async next => {if (!current.current?.session || !sameAccount(current.current, next)) throw new Error('账户已切换，请重新打开注销页面。'); await activateConnection(next);}}
    onFrozen={freezeAccount}
    isCurrent={() => !!connection?.session && (current.current?.session ? sameAccount(current.current, connection) : deletionFrozen)}/>;
  const name = identities.find(i => i.id === connection?.identity)?.name || '日常';
  const accountPanel = <CloudSessionPanel connection={connection} disabled={!ready||busy||captureLocked} onConnected={async next=>{
    await activateConnection(next); setReady(true); setAdvancedConnection(false);
    if (next.session?.accessToken) {setScreen('conversation');setMessage('登录已完成。');}
    else {setScreen('connection');setMessage('已退出账户，本机草稿仍保留。');}
  }}/>;
  const visibleRecords=records.filter(r=>!r.deleted_at);
  const events = visibleRecords.filter(r => r.kind === 'event').sort((a, b) => (a.start_at || '').localeCompare(b.start_at || ''));
  const todayEvents = today ? events.filter(r => eventOccursOn(r, today)) : [];
  function row(item: RecordItem) {const edit = pendingMutations.find(value => value.id === item.id);return <View key={item.id} style={s.row}>{item.kind === 'task' && !item.deleted_at && <Choice multiple style={{width:44,minHeight:44,paddingHorizontal:0,paddingVertical:0,justifyContent:'center'}} disabled={!!connection&&writingRecords.includes(scopeOf(connection)+item.id)||!!edit&&!!edit.action&&edit.action!=='edit'} selected={!!item.completed} onPress={() => toggle(item)} accessibilityLabel={(item.completed ? '重开：' : '完成：') + item.title}/>}<Pressable accessibilityRole="button" accessibilityLabel={item.title} onPress={() => open(item)} style={({pressed}) => [s.recordBody, pressed && s.pressed]}><Text numberOfLines={2} style={[s.recordTitle, item.completed && {textDecorationLine: 'line-through', color: c.muted}]}>{item.title}</Text><Text style={s.recordMeta}>{item.kind === 'event' ? (/^\d{4}-\d{2}-\d{2}$/.test(item.start_at || '') ? `${Number(item.start_at!.slice(5,7))}月${Number(item.start_at!.slice(8,10))}日 · 全天` : new Date(item.start_at!).toLocaleString('zh-CN', {month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit'})) : item.capture ? stages[item.capture.state] || '原件已保存' : kinds[item.kind]}</Text>{edit && <Text style={s.recordMeta}>{mutationLabel(edit)}</Text>}{item.content !== item.title && <Text numberOfLines={2} style={s.excerpt}>{item.content}</Text>}</Pressable></View>;}


  const readingKey = connection && (screen === 'today' || screen === 'tasks' || (screen === 'memory' && !memoryPath && !memoryFile && !memorySection) || (screen === 'companion' && !hubSection))
    ? `${scopeOf(connection)}|${screen}|${screen === 'tasks' ? taskTab : ''}` : null;
  const content = <ReadingScrollView key={readingKey || screen} memory={readingPositions} rememberKey={readingKey} contentContainerStyle={[s.scroll, wide && {maxWidth: 980, alignSelf: 'center', width: '100%'}]}>
    {screen === 'account-deletion' && deletionPanel}
    {screen === 'chat-import' && connection && <ChatImportPanel connection={connection} identityName={name} shareId={chatImportShareId} isCurrent={() => current.current === connection} onShareConsumed={() => setChatImportShareId(undefined)}/>}
    {screen === 'share-intake' && connection && <ShareIntakePanel onChatImport={openChatImport} connection={connection} identityName={name} onChooseIdentity={() => setScreen('connection')}
      onBookmark={async submission => {const receipt = await createShareBookmarkHandler(connection, {store:storage,outbox,isCurrent:()=>current.current===connection})(submission);if(current.current===connection){await local(connection);void synchronize(connection,true);}return receipt;}}
      onCapture={async submission => {const receipt = await createShareCaptureHandler(connection, {store: storage, outbox, readFile: async uri => new File(uri), fetcher: serviceFetch, isCurrent: () => current.current === connection})(submission); if (current.current === connection) {await local(connection); void synchronize(connection, true);} return receipt;}}
      onDraft={async submission => {if (current.current !== connection || submission.scope !== scopeOf(connection)) throw new Error('身份已切换，请回到原身份处理这份分享。'); return new SharedChatDrafts(storage).save(submission);}}
      onChanged={() => {if (current.current === connection) setScreen('conversation');}}/>}
    {screen === 'search' && connection && <NativeSearchPanel connection={connection} initial={searchContext.current?.scope === scopeOf(connection) ? searchContext.current.value : undefined} onRemember={value => {searchContext.current = {scope: scopeOf(connection), value};}} onTask={openActivityTask} onRecord={id=>void openSearchRecord(id)} onFiles={openFiles}/>}
    {screen === 'today' && connection && <ConnectedTodayPanel isCurrent={()=>current.current===connection} key={scopeOf(connection)} connection={connection} records={visibleRecords} connected={connected} onRefreshRecords={()=>synchronize(current.current,false)} onBriefing={()=>setScreen('briefing')} onCalendar={()=>setScreen('agenda')} onRecord={open} onTask={openActivityTask} onDraft={prepareMessage}/>}
    {screen === 'artifact' && connection && artifactId && <ArtifactPanel connection={connection} artifactId={artifactId} onBack={goBack} onTask={openActivityTask} onArtifact={openArtifact}/>}
    {(screen === 'briefing'||(screen==='artifact'&&!artifactId)) && connection && <BriefPanel connection={connection} isCurrent={() => current.current === connection} firstRun={briefingIntro} onTask={openActivityTask} onArtifact={openArtifact}/>}
    {screen === 'native' && <View style={{gap:24}}>{connection && <><NativeActionPanel connection={connection}/><NativeSyncPanel connection={connection}/></>}<NativeConnections scope={connection?scopeOf(connection):'disconnected'} key={connection?scopeOf(connection):'disconnected'} onDraft={prepareMessage} onPhoto={()=>{setScreen('capture');void photo(false);}}/></View>}
    {screen === 'capture' && <>
      <View style={s.greeting}><View style={{flex: 1}}><Text variant="headlineLarge" style={s.heading}>补记记录</Text><Text variant="bodyLarge" style={s.muted}>也可以直接补充或修改记录。</Text></View></View>
      <View pointerEvents={captureLocked ? 'none' : 'auto'} style={[s.composer, inputFocused && s.composerFocused]}><Input ref={input} editable={!captureLocked} multiline value={form.text} onChangeText={text => changeForm(p => ({...p, text}))} placeholder="一个念头、一件小事…" placeholderTextColor={c.muted} accessibilityLabel="随手记一下" maxLength={12000} style={s.input} onFocus={() => setInputFocused(true)} onBlur={() => setInputFocused(false)} selectionColor={c.accent}/>
        {form.media.map(media => <View key={media.id} style={{flexDirection: 'row', alignItems: 'center'}}><View style={{flex: 1}}><Original media={media}/></View><Button accessibilityLabel={'从草稿移除：' + media.name} onPress={() => changeForm(p => ({...p, media: p.media.filter(m => m.id !== media.id)}))}><X size={20} color={c.muted}/></Button></View>)}
        {moreCapture && <View style={s.captureMore}>
        <View style={s.actions}><Button icon={() => <Camera size={20} color={c.accent}/>} onPress={() => photo(true)}>拍一下</Button><Button icon={() => <Mic size={20} color={voice.isRecording ? c.danger : c.accent}/>} onPress={recordVoice}>{voice.isRecording ? '说完了 ' + Math.floor(voice.durationMillis / 1000) + 's' : '说一句'}</Button><Button onPress={() => photo(false)}>选图</Button></View>
        <View style={s.segment}>{(Object.keys(kinds) as Kind[]).map(kind => <Choice variant="chip" key={kind} selected={form.kind === kind} onPress={() => {changeForm(p => ({...p, kind})); if (!voice.isRecording) setMoreCapture(false);}} style={[s.kindItem, form.kind === kind && s.kindSelected]}><Text style={[s.kindText, form.kind === kind && {color: c.ink, fontWeight: '600'}]}>{kinds[kind]}</Text></Choice>)}</View>
</View>}
        {form.kind === 'event' && <View style={{gap: 16, marginVertical: 16}}><TimeField label="开始" value={new Date(form.start)} onChange={date => changeForm(p => ({...p, start: date.toISOString()}))}/><TimeField label="结束" value={new Date(form.end)} onChange={date => changeForm(p => ({...p, end: date.toISOString()}))}/></View>}
        {form.media.length > 0 && <View style={s.switchRow}><Text style={{flex: 1}}>让 Pajio 整理原件</Text><StateSwitch value={form.organize} onValueChange={organize => changeForm(p => ({...p, organize}))} accessibilityLabel="让 Pajio 整理原件"/></View>}
        <View style={s.saveRow}><Pressable accessibilityRole="button" accessibilityLabel="添加照片、语音或选择记录类型" accessibilityState={{expanded: moreCapture}} onPress={() => setMoreCapture(value => voice.isRecording || !value)} style={({pressed}) => [s.moreButton, moreCapture && s.navSelected, pressed && s.pressed]}><Plus size={22} strokeWidth={1.7} color={c.muted}/></Pressable><Text style={[s.muted, {flex: 1, fontSize: 12}]}>{form.kind === 'note' ? '先留住，不必想清楚。' : kinds[form.kind]}</Text><Button mode="contained" onPress={save} loading={saving} disabled={captureLocked || !ready} contentStyle={s.buttonSize}>记下</Button></View>
      </View>
      {pending.length > 0 && <View style={s.section}><Text variant="titleMedium">{pending.length} 条已留在本机</Text>{pending.map(item => <View key={item.id} style={s.pending}><View style={{flex: 1}}><Text variant="bodyLarge">{item.draft.title}</Text><Text style={s.muted}>{item.state === 'attention' ? '需要再看一下：' + item.error : item.state === 'sending' ? '正在同步…' : connection?.development ? '已保留，点同步后发送。' : '等连接恢复，再同步给 Pajio。'}</Text></View>{item.state === 'attention' && <Button disabled={manualSync||busy} onPress={()=>void retryPending(item)}>再试一次</Button>}</View>)}</View>}
      <View style={[s.dayGrid, wide && s.dayGridWide]}><View style={[s.section, wide && s.dayPanel]}><Text variant="titleLarge">{new Date().toLocaleDateString('zh-CN', {month: 'long', day: 'numeric', weekday: 'long'})}</Text>{todayEvents.length ? todayEvents.map(row) : <Text style={s.empty}>今天还很空，先给一件小事留点时间。</Text>}<Button textColor={c.muted} style={{alignSelf: 'flex-start', marginLeft: -12}} onPress={() => {changeForm(p => ({...p, kind: 'event'})); input.current?.focus();}}>安排一件小事</Button></View>
      <View style={[s.section, wide && s.dayPanel]}><Text variant="titleLarge">惦记着的事</Text>{visibleRecords.some(r => r.kind === 'task' && !r.completed) ? visibleRecords.filter(r => r.kind === 'task' && !r.completed).slice(0, 10).map(row) : <Text style={s.empty}>想起来的事先放这里，做完一件就轻一点。</Text>}</View>
      </View><View style={s.section}><Text variant="titleLarge">最近记下的</Text>{visibleRecords.some(r => r.kind === 'note') ? visibleRecords.filter(r => r.kind === 'note').slice(0, 5).map(row) : <Text style={s.empty}>一个还没成形的想法，也可以先留在这里。</Text>}</View>
    </>}
    {screen === 'tools' && <><Text style={s.heading}>更多</Text><MenuRow title="文件" icon={<Folder size={23} color={c.muted}/>} onPress={()=>openReviewTool('files')}/><MenuRow title="持续目标" icon={<Target size={23} color={c.muted}/>} onPress={()=>openReviewTool('goals')}/><MenuRow title="定时安排" icon={<Clock3 size={23} color={c.muted}/>} onPress={()=>openReviewTool('schedules')}/><MenuRow title="连接与身份" icon={<Settings size={23} color={c.muted}/>} onPress={()=>setScreen('settings')}/></>}
    {(screen === 'agenda' || screen === 'notes') && <><Text style={s.heading}>日历与笔记</Text><Text style={s.muted}>安排和想法，都在这里。</Text><View accessibilityRole="tablist" style={s.reviewTabs}>{([{view:'agenda',title:'日历'},{view:'notes',title:'笔记'}] as const).map(item=><Segment key={item.view}  selected={screen===item.view} onPress={()=>setScreen(item.view)} style={[s.reviewTab,screen===item.view&&s.reviewTabActive]}><Text style={[s.muted,screen===item.view&&{color:c.ink,fontWeight:'600'}]}>{item.title}</Text></Segment>)}</View></>}
    {screen === 'agenda' && connection && <ConnectedCalendarPanel onSeriesCreate={day=>openSeries({initialDay:day})} connection={connection} records={visibleRecords} selected={calendarDate} today={today} isCurrent={()=>current.current===connection} onSelect={setSelectedDate} onRecord={open} onNative={()=>setScreen('native')} onCreate={day=>{const start=localDateTime(day,9);changeForm(p=>({...p,kind:'event',start:start.toISOString(),end:new Date(start.getTime()+1800000).toISOString()}));setScreen('capture');}}/>}
    {screen === 'tasks' && <><Text style={s.heading}>任务</Text><Text style={s.muted}>查看进展、结果和定时安排。</Text><View accessibilityRole="tablist" style={s.reviewTabs}>{([{id:'tasks',title:'任务'},{id:'lists',title:'清单'},{id:'schedules',title:'定时'}] as const).map(tab=><Segment key={tab.id}  selected={taskTab===tab.id} onPress={()=>setTaskTab(tab.id)} style={[s.reviewTab,taskTab===tab.id&&s.reviewTabActive]}><Text style={[s.muted,taskTab===tab.id&&{color:c.ink,fontWeight:'600'}]}>{tab.title}</Text></Segment>)}</View>{taskTab==='tasks'?<View style={{gap:24}}>{connection&&<AgentTaskList connection={connection} onTask={openActivityTask} onGoals={()=>setTaskTab('goals')} onDraft={prepareMessage}/>}</View>:taskTab==='lists'?connection?<TaskListsPanel connection={connection} onRecord={open} onChanged={()=>void synchronize(current.current,false)}/>:null:connection?<OngoingPanel key={scopeOf(connection)+taskTab} connection={connection} kind={taskTab} createRequest={taskCreate} onManage={()=>prepareMessage(taskTab==='goals'?'我想交代一个持续目标：':'请帮我安排：')} onTask={openActivityTask}/>:null}{taskTab==='schedules'&&<ScheduleSuggestions onCreate={request=>{setTaskCreate({...request,id:Crypto.randomUUID()});setTaskTab('schedules');}}/>}</>}
    {screen === 'calendar-series' && connection && <CalendarSeriesPanel connection={connection} {...seriesTarget} isCurrent={()=>current.current===connection} onOpenSeries={seriesId=>openSeries({seriesId})} onChanged={result=>{if(!seriesTarget.seriesId&&!seriesTarget.occurrence)openSeries({seriesId:result.id});}}/>}
    {screen === 'task-detail' && connection && openedTask && <TaskDetailPanel connection={connection} taskId={openedTask} isCurrent={()=>current.current===connection} onConversation={openTaskConversation} onArtifact={openArtifact}/>}
    {screen === 'bookmarks' && connection && <BookmarksPanel connection={connection} outbox={outbox} mutations={mutations} isCurrent={()=>current.current===connection} onChanged={()=>{void synchronize(current.current,false);}}/>}
    {screen === 'conversation-sources' && connection && <ConversationSourcesPanel connection={connection}/>}
    {screen === 'memory' && connection && <MemoryLibrary key={scopeOf(connection)} connection={connection} onSources={()=>setScreen('conversation-sources')} onFiles={()=>openReviewTool('files')} onChat={text=>text?prepareMessage(text):setScreen('conversation')} onConnect={()=>setScreen('settings')}/>}
    {(screen === 'companion'||screen === 'settings') && <SettingsHub key={connection?scopeOf(connection):'disconnected'} onOnboarding={connection?()=>{onboardingReturn.current=screen;onboardingSeen.current=connection;setScreen('onboarding');}:undefined} onAccountDeletion={()=>setScreen('account-deletion')} onBookmarks={()=>setScreen('bookmarks')} onChat={prepareMessage} onSync={()=>void refresh()} pendingCount={pending.length+pendingMutations.length} syncing={busy||manualSync} wardrobe={wardrobe} personal={screen === 'companion'} connection={connection} identity={name} connected={connected} onConnection={()=>setScreen('connection')} onFiles={()=>openReviewTool('files')} onNative={()=>setScreen('native')}/>}
    {screen === 'notes' && <><View style={s.section}>{visibleRecords.some(r => r.kind === 'note') ? visibleRecords.filter(r => r.kind === 'note').map(row) : <Text style={s.empty}>还没有笔记。Pajio 整理出的想法和资料会出现在这里。</Text>}</View></>}
    {screen === 'connection' && <>
      <Text variant="headlineLarge" style={s.heading}>账户与身份</Text>
      <Text style={s.muted}>已有记录和未同步内容，会分别留在各自的身份里。</Text>
      <View style={{gap: 20, marginTop: 24}}>
        {accountPanel}
        {connection?.session?.accessToken && identities.length > 1 ? <View style={{gap:8}}><Text style={s.muted}>当前身份</Text>{identities.map(item => <Choice key={item.id} label={item.name} selected={connection.identity===item.id} disabled={busy||captureLocked} onPress={()=>{void activateConnection({...connection, identity:item.id}).catch(error=>setMessage(error instanceof Error?error.message:'身份暂时无法切换。'));}}/>)}</View> : null}
        {developmentConnectionsEnabled() ? <View style={{borderTopWidth: 1, borderTopColor: c.line, paddingTop: 8, gap: 14}}>
          <Button icon={advancedConnection ? 'chevron-up' : 'chevron-down'} accessibilityLabel="开发连接" accessibilityState={{expanded: advancedConnection}} onPress={() => setAdvancedConnection(value => !value)}>开发连接</Button>
          {advancedConnection ? <View style={{gap: 16}}>
            <Text style={s.muted}>仅供已启用开发连接的开发版验收，不会迁移其他服务的账户或草稿。</Text>
            <TextInput mode="outlined" label="开发服务地址" accessibilityLabel="开发服务地址" value={address} onChangeText={setAddress} autoCapitalize="none" autoCorrect={false} keyboardType="url"/>
            <TextInput mode="outlined" label="身份标识" accessibilityLabel="身份标识" value={identity} onChangeText={setIdentity} autoCapitalize="none"/>
            {identities.map(i => <Choice key={i.id} selected={identity === i.id} label={i.name} onPress={() => setIdentity(i.id)}/>)}
            <Button mode="contained-tonal" onPress={connect} disabled={busy || captureLocked} loading={busy} contentStyle={s.buttonSize}>连接 Pajio</Button>
          </View> : null}
        </View> : null}
        {Platform.OS === 'web' ? <Text style={s.muted}>当前是手机客户端代码的网页预览，拍照和系统权限需在手机验收。</Text> : null}
        <Text style={s.muted}>离开应用时停止录音并尝试保存。已保存的原件留在应用私有目录；卸载或清除应用数据会移除未同步记录。</Text>
      </View>
    </>}
    {screen === 'trash' && <><Text style={s.heading}>最近删除</Text><Text style={s.muted}>移除的记录保留在这里，点开可以恢复。</Text><Button disabled={busy} onPress={()=>void synchronize(current.current,false)}>刷新记录</Button>{records.filter(r=>r.deleted_at).map(row)}{!records.some(r=>r.deleted_at)&&<Text style={s.empty}>没有已删除的记录。</Text>}</>}
    {screen === 'detail' && detail && connection && (detail.kind==='note'&&detail.url?<BookmarkDetailPanel connection={connection} recordId={detail.id} outbox={outbox} mutations={mutations} isCurrent={()=>current.current===connection} onBack={goBack} onChanged={()=>{void synchronize(current.current,false);}}/>:<RecordDetail key={scopeOf(connection)+detail.id} record={detail} connection={connection} onChanged={item=>recordChanged(item,connection)} onChat={item=>{setChatRecord(item);setScreen('conversation');}}/>)}
    {(screen==='settings'||screen==='companion')&&!hubSection&&<><Button onPress={()=>openChatImport()}>导入选定聊天</Button><Button onPress={()=>setScreen('share-intake')}>分享收件箱</Button><Button onPress={()=>setScreen('trash')}>最近删除</Button></>}

  </ReadingScrollView>;
  if (deletionFrozen && screen !== 'connection') return <SafeAreaView style={{flex: 1, backgroundColor: c.canvas}}><StatusBar style={mode === 'night' ? 'light' : 'dark'}/><ScrollView contentContainerStyle={s.scroll}>{deletionPanel}{message ? <Text accessibilityLiveRegion="polite" style={s.muted}>{message}</Text> : null}<Button onPress={() => setScreen('connection')}>重新登录或切换账户</Button></ScrollView></SafeAreaView>;
  if (requiresNativeSignIn(connection, Platform.OS) && !(developmentConnectionsEnabled() && screen==='connection' && advancedConnection)) return <SafeAreaView style={{flex:1,backgroundColor:c.canvas}}><StatusBar style={mode==='night'?'light':'dark'}/><KeyboardAvoidingView style={{flex:1}} behavior={Platform.OS==='ios'?'padding':undefined}><ScrollView automaticallyAdjustKeyboardInsets={false} keyboardDismissMode={Platform.OS==='ios'?'interactive':'on-drag'} keyboardShouldPersistTaps="handled" contentContainerStyle={[s.scroll,{flexGrow:1,justifyContent:'flex-start',maxWidth:480,width:'100%',alignSelf:'center',gap:16,paddingHorizontal:28,paddingTop:Math.max(8,64-safeInsets.top),paddingBottom:24}]}>
    {accountPanel}
    {message?<Text accessibilityLiveRegion="polite" style={s.muted}>{message}</Text>:null}
    {!ready?<Button onPress={()=>setStartupAttempt(value=>value+1)}>重新读取本机记录</Button>:null}
    {developmentConnectionsEnabled()?<Button onPress={()=>{setAdvancedConnection(true);setScreen('connection');}}>开发连接</Button>:null}
  </ScrollView></KeyboardAvoidingView></SafeAreaView>;
  if(screen==='remote-device' && connection && !deletionFrozen) return <SafeAreaView style={{flex:1,backgroundColor:c.canvas}}><StatusBar style={mode==='night'?'light':'dark'}/><KeyboardAvoidingView style={{flex:1}} behavior={Platform.OS==='ios'?'padding':undefined}><NativeRemoteDevicePanel key={scopeOf(connection)+'|'+(connection.session?.credentialId||'local')+'|'+resource} connection={connection} resource={resource||''} name={(deviceName||'').slice(0,100)} kind={deviceKind==='android'?'android':'computer'} onBack={goBack}/></KeyboardAvoidingView></SafeAreaView>;
  if(screen==='onboarding' && connection && !deletionFrozen) return <View style={{flex:1}}><AppBackdrop/><NativeSyncSession connection={connection} isCurrent={()=>current.current===connection} onRecordsChanged={()=>{void synchronize(current.current,false);}}/><SafeAreaView style={{flex:1,backgroundColor:'transparent'}}><StatusBar style={mode==='night'?'light':'dark'}/><OnboardingPanel key={scopeOf(connection)+'|'+(connection.session?.credentialId||'local')} connection={connection} outfit={wardrobe.state.outfit} isCurrent={()=>current.current===connection&&!deletionFrozen} onComplete={destination=>{if(current.current===connection){onboardingSeen.current=connection;setBriefingIntro(destination==='briefing');setScreen(destination||'today');}}} onClose={()=>{if(current.current===connection){onboardingSeen.current=connection;setScreen(onboardingReturn.current);}}}/></SafeAreaView></View>;
  return <View style={{flex:1}}><AppBackdrop/>
    {connection && !deletionFrozen && <><NativeActionSession connection={connection}/><NativeSyncSession connection={connection} isCurrent={()=>current.current===connection} onRecordsChanged={()=>{void synchronize(current.current,false);}}/></>}
    {connection&&connected?<NativeNotificationSession connection={connection}/>:null}
    <SafeAreaView style={{flex: 1, backgroundColor: 'transparent'}}><StatusBar style={mode === 'night' ? 'light' : 'dark'}/><KeyboardAvoidingView style={{flex: 1}} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
    {screen!=='artifact'&&(screen==='conversation'||!primary||screen==='agenda'||screen==='notes')&&<View style={s.top}>
      {screen === 'conversation' && connection ? <ActivityReview key={scopeOf(connection)} compact outfit={wardrobe.state.outfit} identity={name} connection={connection} active={foreground} connected={connected} open={activityOpen} onOpenChange={setActivityOpen} onOpenTask={openActivityTask}/> : <IconButton label="返回" style={s.headerCircle} onPress={goBack}><ChevronLeft size={25} color={c.ink}/></IconButton>}
      {!(screen === 'conversation' && connection) && <View style={{flex:1}}/>}
      {screen==='conversation'&&<IconButton label="搜索聊天、任务和记录" style={s.headerCircle} onPress={()=>setScreen('search')}><Search size={22} strokeWidth={1.7} color={c.ink}/></IconButton>}
      {screen==='conversation'&&<IconButton label="设置" style={s.headerCircle} onPress={()=>setScreen('settings')}><Settings size={22} strokeWidth={1.7} color={c.ink}/></IconButton>}
    </View>}
    {!ready&&<View style={s.feedback}><Text style={[s.muted,{flex:1}]}>本机记录尚未就绪</Text><Button onPress={()=>setStartupAttempt(value=>value+1)}>重新读取</Button><Button onPress={()=>setScreen('connection')}>连接设置</Button></View>}
    {message ? <View style={s.feedback}><Text accessibilityLiveRegion="polite" style={[s.muted, {flex: 1, fontSize: 13}]}>{message}</Text><Pressable accessibilityLabel="收起提示" accessibilityRole="button" onPress={() => setMessage('')} style={s.dismiss}><X size={18} color={c.muted}/></Pressable></View> : null}
    {connection && !deletionFrozen && screen !== 'share-intake' ? <ShareInboxNotice key={scopeOf(connection)} connection={connection} onOpen={() => setScreen('share-intake')}/> : null}
    <View style={s.body}>
      {connection && !deletionFrozen ? <RetainedConversation key={scopeOf(connection)} active={foreground&&!activityOpen&&!menu&&!adding&&screen!=='capture'&&screen!=='account-deletion'} visible={screen==='conversation'} inputScope={screen} showComposer={!['settings','companion','native','connection','capture','trash','detail','search','share-intake','chat-import','account-deletion','task-detail','calendar-series','bookmarks','conversation-sources'].includes(screen)} compactComposer={screen!=='conversation'} connection={connection} record={chatRecord} reviewRequest={reviewRequest}
        onSend={()=>setScreen('conversation')} onOpenChat={()=>setScreen('conversation')} onArtifact={openArtifact}
        onCapture={()=>{setScreen('capture');void photo(true);}} onAdd={()=>setAdding(true)}
        navigation={<BottomNavigation outfit={wardrobe.state.outfit} selected={selectedTab} onSelect={selectTab}/>}
        content={<View key={screen} style={{flex:1}}>{content}</View>}/>
        : content}
    </View>
    <Sheet visible={menu} onDismiss={()=>setMenu(false)} title="更多">
      <MenuRow title="文件" detail="查看结果与原件" icon={<Folder size={23} color={c.muted}/>} onPress={()=>openReviewTool('files')}/>
      <MenuRow title="持续目标" detail="查看交给 Pajio 推进的事" icon={<Target size={23} color={c.muted}/>} onPress={()=>{setMenu(false);setTaskTab('goals');setScreen('tasks');}}/>
      <MenuRow title="定时安排" detail="到时会回来做的事" icon={<Clock3 size={23} color={c.muted}/>} onPress={()=>{setMenu(false);setTaskTab('schedules');setScreen('tasks');}}/>
      <MenuRow title="连接与身份" icon={<Settings size={23} color={c.muted}/>} onPress={()=>{setMenu(false);setScreen('settings');}}/>
      <MenuRow title={manualSync?'正在同步…':'同步记录'} icon={<RefreshCw size={23} color={c.muted}/>} onPress={()=>{if(!manualSync)void refresh();}}/>
    </Sheet>
    <Sheet visible={adding} onDismiss={()=>setAdding(false)} title="添加">
      <MenuRow title="导入选定聊天" detail="先预览微信聊天，再决定交给 Pajio" icon={<FileText size={23} color={c.muted}/>} onPress={()=>{setAdding(false);openChatImport();}}/>
      <MenuRow title="分享收件箱" detail="处理其他 App 分享来的文字和文件" icon={<Inbox size={23} color={c.muted}/>} onPress={()=>{setAdding(false);setScreen('share-intake');}}/>
      <MenuRow title="拍一张" icon={<Camera size={23} color={c.muted}/>} onPress={()=>{setAdding(false);setScreen('capture');void photo(true);}}/>
      <MenuRow title="选择照片" icon={<ImageIcon size={23} color={c.muted}/>} onPress={()=>{setAdding(false);setScreen('capture');void photo(false);}}/>
      <MenuRow title="选择录音文件" icon={<Mic size={23} color={c.muted}/>} onPress={()=>{setAdding(false);setScreen('capture');void pickAudio();}}/>
      <MenuRow title="补记一条" icon={<FileText size={23} color={c.muted}/>} onPress={()=>{setAdding(false);setScreen('capture');}}/>
    </Sheet>
  </KeyboardAvoidingView></SafeAreaView></View>;
}
function ThemedApp() {
  const {colors: c, mode} = useAppTheme();
  const base = mode === 'night' ? MD3DarkTheme : MD3LightTheme;
  const theme = {...base, colors: {...base.colors, primary: c.action, onPrimary: c.onAction, primaryContainer: c.accentSoft, onPrimaryContainer: c.accentInk, secondary: c.accent, onSecondary: c.onAccent, secondaryContainer: c.accentSoft, onSecondaryContainer: c.accentInk, background: c.canvas, surface: c.surface, surfaceVariant: c.soft, onSurface: c.ink, onSurfaceVariant: c.muted, outline: c.line, outlineVariant: c.line, error: c.danger}, roundness: 6};
  return <PaperProvider theme={theme}><Mobile/></PaperProvider>;
}
export default function App() {return <SafeAreaProvider><AppThemeProvider><ThemedApp/></AppThemeProvider></SafeAreaProvider>;}
const makeStyles = (c: AppColors) => StyleSheet.create({
  reviewTabs:{flexDirection:"row",gap:4,borderBottomWidth:1,borderBottomColor:c.line,marginTop:24,marginBottom:20},
  reviewTab:{flex:1,minHeight:44,alignItems:"center",justifyContent:"center",borderRadius:14,paddingHorizontal:8},
  reviewTabActive:{backgroundColor:c.surface},
  reviewRow: {flexDirection:"row",alignItems:"center",gap:16,minHeight:78,borderBottomWidth:1,borderBottomColor:c.line,paddingVertical:16},
  reviewTitle: {fontSize:20,color:c.ink,fontWeight:"500"},
  reviewButton: {minHeight:44,flexDirection:"row",alignItems:"center",gap:8},
  headerCircle: {backgroundColor:'transparent',borderRadius:16},
  top: {paddingHorizontal: 16, paddingTop: 6, paddingBottom: 10, minHeight: 64, gap:8, flexDirection: 'row', alignItems: 'center'},
  identityPill:{minHeight:44,flexDirection:'row',alignItems:'center',gap:9,paddingHorizontal:12,borderRadius:22,backgroundColor:c.surface},
  identityDot:{width:5,height:5,borderRadius:3,backgroundColor:c.accent}, identityText:{fontSize:14,fontWeight:'500',color:c.ink},
  headerTools: {flexDirection: 'row', alignItems: 'center', gap: 2}, statusDot: {width: 6, height: 6, borderRadius: 3},
  body: {flex: 1}, scroll: {padding: 24, paddingTop: 16, paddingBottom: 32},
  greeting: {flexDirection: 'row', alignItems: 'center', gap: 18, marginBottom: 28},
  heading: {color: c.ink, fontSize: 30, lineHeight: 38, letterSpacing: 0, marginBottom: 8, fontWeight: '600'},
  muted: {color: c.muted, fontSize: 14, lineHeight: 23}, avatar: {width: 76, height: 76, resizeMode: 'contain'},
  composer: {backgroundColor: c.surface, borderWidth: 1, borderColor: c.line, borderRadius: 24, padding: 20},
  composerFocused: {borderColor: c.accent},
  input: {minHeight: 104, maxHeight: 240, fontSize: 17, lineHeight: 28, color: c.ink, textAlignVertical: 'top', outlineWidth: 0},
  actions: {flexDirection: 'row', flexWrap: 'wrap', marginVertical: 4, marginLeft: -10},
  segment: {flexDirection: 'row', flexWrap:'wrap', gap:8, marginTop: 12},
  kindItem: {paddingHorizontal: 18, minHeight: 44, alignItems: 'center', justifyContent: 'center', borderRadius: 12},
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
