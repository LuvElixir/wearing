import {useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState} from 'react';
import {ActivityIndicator, Animated, AppState, Easing, Platform, StyleSheet, Text, View} from 'react-native';
import {FileText, RefreshCw} from 'lucide-react-native';
import {type Connection, scopeOf} from './core';
import {registerAccountWork} from './account-work';
import {TaskDetailApi, type TaskControl, type TaskDetail} from './task-detail';
import {serviceFetch} from './transport';
import {refreshActivitySnapshot} from './use-activity-snapshot';
import {useAppTheme, useThemedStyles, type AppColors} from './app-theme';
import {IconButton, PrimaryButton, useReducedMotion} from './experience/primitives';
import {createTaskRequestQueue} from './task-request-queue';

type Props = {connection: Connection; taskId: string; isCurrent: () => boolean; onConversation: (id: string) => void; onArtifact: (id: string) => void};
export default function TaskDetailPanel(props: Props) {return <TaskSession key={scopeOf(props.connection) + '|' + (props.connection.session?.credentialId || '') + '|' + props.taskId} {...props}/>;}
function TaskSession({connection, taskId, isCurrent, onConversation, onArtifact}: Props) {
  const {colors: c} = useAppTheme(), s = useThemedStyles(styles);
  const api = useMemo(() => new TaskDetailApi(connection, serviceFetch), [connection]);
  useLayoutEffect(() => {api.setCurrent(isCurrent);}, [api, isCurrent]);
  const [task, setTask] = useState<TaskDetail | null>(null), [busy, setBusy] = useState(true), [error, setError] = useState(''), [notice, setNotice] = useState(''), [stale, setStale] = useState(false), [confirm, setConfirm] = useState<TaskControl | null>(null);
  const [showPrompt, setShowPrompt] = useState(false), [showEvents, setShowEvents] = useState(false);
  const session = useRef({live: true, queue: createTaskRequestQueue()});
  const load = useCallback(async (probe = false, quiet = false) => {
    const current = session.current;
    if (!current.live || current.queue.userPending) return;
    if (!quiet) {setBusy(true); setNotice('');}
    const read = async () => {
      try {
        const result = await (probe ? api.refresh(taskId) : api.read(taskId));
        if (current.live) {
          setTask(result); setStale(false); setError('');
          if (!quiet) {setConfirm(null); setNotice('进展已更新。');}
        }
      } catch (cause) {
        if (current.live) {setStale(true); if (!current.queue.userPending) setConfirm(null); setError(cause instanceof Error ? cause.message : '暂时读不到任务，请重试。');}
      }
    };
    let performed = false;
    try {performed = await (quiet ? current.queue.background(read) : current.queue.user(read));}
    finally {if (performed && current.live && !current.queue.userPending) setBusy(false);}
  }, [api, taskId]);
  useEffect(() => {
    api.activate();
    const current = {live: true, queue: createTaskRequestQueue()}; session.current = current;
    const close = () => {current.live = false; current.queue.close(); api.close();};
    const unregister = registerAccountWork(connection, async () => {close();});
    void Promise.resolve().then(() => load(false, true));
    const timer = setInterval(() => {if (AppState.currentState === 'active') void load(false, true);}, 8000);
    const foreground = AppState.addEventListener('change', state => {if (state === 'active') void load(false, true);});
    return () => {close(); clearInterval(timer); foreground.remove(); unregister();};
  }, [api, connection, load]);
  const attemptedReads = useRef(new Set<string>());
  useEffect(() => {
    const receipt = task?.receipt;
    if (!task || !receipt || stale || !isCurrent() || AppState.currentState !== 'active' || attemptedReads.current.has(receipt.version)) return;
    attemptedReads.current.add(receipt.version);
    // A rendered snapshot carries its exact version. Never fetch a newer
    // version merely to clear the badge after an old acknowledgement fails.
    void api.seen(task).then(seen => {if (seen && session.current.live && isCurrent()) void refreshActivitySnapshot(connection);}).catch(() => {});
  }, [api, task, stale, connection, isCurrent]);
  const control = async () => {
    const current = session.current;
    if (!task || !confirm || current.queue.userPending || !current.live || stale) return;
    const action = confirm; setBusy(true); setError(''); setNotice('');
    try {
      await current.queue.user(async () => {
        // TaskDetailApi rechecks the captured task/run before making a write.
        // A background read cannot silently consume this explicit confirmation.
        try {
          const next = await api.control(task, action);
          if (current.live) {
            setTask(next); setStale(false);
            setNotice(action === 'cancel-message' && next.status === 'stopped' ? '消息已撤回，原话仍保留。' : action === 'start' && ['starting', 'running'].includes(next.status) ? '已提交这一次请求，请查看最新进展。' : next.status === 'stopped' ? '已确认停止。' : next.status === 'stopping' ? '停止请求已送达，等待原运行确认结束。' : '已取得最新任务状态，请查看上方进展。');
            void refreshActivitySnapshot(connection);
          }
        } catch (cause) {
          if (current.live) {setStale(true); setError(cause instanceof Error ? cause.message : '操作结果尚未确认，请重新读取原任务。');}
        }
      });
    } finally {if (current.live) {setBusy(false); setConfirm(null);}}
  };
  const stamp = (value: string) => new Date(value).toLocaleString('zh-CN', {month:'numeric', day:'numeric', hour:'2-digit', minute:'2-digit'});
  return <View style={s.root}>
    <View style={s.row}><Text accessibilityRole="header" style={s.heading}>任务进展</Text><IconButton label="刷新任务进展" disabled={busy} onPress={() => {void load(true);}}>{busy ? <ActivityIndicator color={c.accent}/> : <RefreshCw size={20} color={c.ink}/>}</IconButton></View>
    {!task && busy && !error && <View style={s.loading} accessibilityLiveRegion="polite"><Text style={s.subheading}>正在找回这件事…</Text><Text style={s.caption}>进展和已经返回的内容会一起显示。</Text></View>}
    {!!error && <View style={s.card}><Text accessibilityRole="alert" style={s.error}>{error}</Text>{task && <Text style={s.caption}>已读到的内容仍保留在下方。</Text>}<PrimaryButton label="重新读取原任务" tone="quiet" loading={busy} onPress={() => {void load();}}/></View>}
    {task && busy && !confirm && <Text accessibilityLiveRegion="polite" style={s.caption}>正在更新进展，已读内容会保留。</Text>}
    {!!notice && <Text accessibilityLiveRegion="polite" style={s.caption}>{notice}</Text>}
    {task && <>
      <View style={s.card}><TaskStatus label={task.label} stale={stale}/><Text style={s.title}>{task.title}</Text><Text style={s.caption}>更新于 {stamp(task.updatedAt)}</Text>
        {task.status === 'stopping' && <Text style={s.body}>正在等待停止回执。确认结束前，原运行可能仍在进行。</Text>}
        {['connection_lost','ambiguous'].includes(task.status) && <Text style={s.body}>原任务可能仍在执行。先刷新进展，避免重复交代同一件事。</Text>}
        {task.status === 'failed' && <Text style={s.body}>{task.failureReason || '这次任务没有完成。已返回的内容会保留，可以回到对话补充情况。'}</Text>}
        {task.status === 'waiting_for_approval' && <PrimaryButton label="回到对话查看这一步" onPress={() => onConversation(task.id)}/>}
      </View>
      <View style={s.card}>
        <Text style={s.subheading}>进展记录{stale ? ' · 上次读取' : ''}</Text>
        {task.events.length ? (showEvents ? task.events : task.events.slice(-3)).map((event, index, shown) => <View key={`${event.at}-${index}`} style={s.timelineRow}>
          <View style={s.timelineRail}><View style={[s.timelineDot, index===shown.length-1&&s.timelineCurrent]}/>{index<shown.length-1&&<View style={s.timelineLine}/>}</View>
          <View style={s.timelineWords}><Text style={s.body}>{event.label}</Text><Text style={s.caption}>{stamp(event.at)}</Text></View>
        </View>) : <Text style={s.caption}>还没有可展示的状态回执。有新进展会更新在这里。</Text>}
        {task.events.length>3&&<PrimaryButton label={showEvents?'收起较早记录':`查看全部 ${task.events.length} 条记录`} tone="quiet" onPress={()=>setShowEvents(value=>!value)}/>}
        {task.eventsTruncated&&<Text style={s.caption}>这里保留最近 100 条可识别的状态变化。</Text>}
      </View>
      {!!task.output && <View style={s.card}><Text style={s.subheading}>{task.status === 'completed_unverified' || task.status === 'verified' ? '返回的结果' : '当前已返回的内容'}</Text><Text selectable style={s.body}>{task.output}</Text></View>}
      {!!task.artifacts.length && <View style={s.card}><Text style={s.subheading}>图文与文件结果</Text>{task.artifacts.map(item => <PrimaryButton key={item.id} tone="quiet" leading={<FileText size={18} color={c.ink}/>} label={item.title} onPress={() => onArtifact(item.id)}/>)}{task.artifactsTruncated && <Text style={s.caption}>这里显示最近 100 份，较早结果可从资料与文件查看。</Text>}</View>}
      {!!task.blockedReason && <View style={s.card}><Text style={s.subheading}>暂时还不能开始</Text><Text style={s.body}>{task.blockedReason}</Text></View>}
      {task.queued && <Text style={s.caption}>会在前面的任务结束后继续；现在撤回不会中断其他任务。</Text>}
      {!confirm && task.canRetry && <PrimaryButton label={task.recovery ? '重新核对' : '继续这条消息'} disabled={busy || stale} onPress={() => setConfirm('start')}/>}
      {!confirm && (task.canStop || task.canCancel) && <PrimaryButton label={task.canCancel ? (task.queued ? '撤回排队消息' : '撤回这次请求') : '停止这次任务'} tone="quiet" disabled={busy || stale} onPress={() => setConfirm(task.canCancel ? 'cancel-message' : 'stop')}/>}
      {confirm && <View style={s.card}><Text style={s.subheading}>{confirm === 'stop' ? '停止这次任务？' : confirm === 'start' ? (task.recovery ? '重新核对这件事？' : '继续这条消息？') : '撤回这次请求？'}</Text><Text style={s.body}>{confirm === 'stop' ? '将请求结束当前运行，已生成的内容会保留。已经完成的外部操作不会撤销。' : confirm === 'start' ? (task.recovery ? '先核对当前情况。需要操作时会重新请你确认，之前的批准不会沿用。' : '将这条已保存的消息交给 Pajio 处理。') : '撤回后这条消息不会开始执行，原话仍保留。'}</Text><PrimaryButton label={confirm === 'stop' ? '确认停止' : confirm === 'start' ? (task.recovery ? '确认重新核对' : '确认继续') : '确认撤回'} loading={busy} onPress={() => {void control();}}/><PrimaryButton label="暂不操作" tone="quiet" disabled={busy} onPress={() => setConfirm(null)}/></View>}
      <PrimaryButton label="回到原对话" tone="quiet" onPress={() => onConversation(task.id)}/>
      <PrimaryButton label={showPrompt ? '收起原话' : '查看最初交代的事'} tone="quiet" onPress={() => setShowPrompt(value => !value)}/>
      {showPrompt && <View style={s.card}><Text selectable style={s.body}>{task.prompt}</Text></View>}
    </>}
  </View>;
}
/** Only the changed status fades; the result text and confirmation remain mounted. */
function TaskStatus({label, stale}: {label: string; stale: boolean}) {
  const s = useThemedStyles(styles), reduced = useReducedMotion();
  const [opacity] = useState(() => new Animated.Value(1));
  const previous = useRef(label);
  useEffect(() => {
    const changed = previous.current !== label;
    previous.current = label;
    opacity.stopAnimation();
    if (reduced || !changed) {opacity.setValue(1); return;}
    opacity.setValue(0.45);
    const transition = Animated.timing(opacity, {toValue: 1, duration: 180, easing: Easing.out(Easing.cubic), useNativeDriver: Platform.OS !== 'web', isInteraction: false});
    transition.start();
    return () => transition.stop();
  }, [label, reduced, opacity]);
  return <Animated.Text accessibilityLiveRegion="polite" style={[s.status, {opacity}]}>{stale ? '上次状态 · ' : ''}{label}</Animated.Text>;
}
const styles = (c: AppColors) => StyleSheet.create({root:{gap:16}, loading:{paddingVertical:24,paddingHorizontal:19,gap:10}, row:{flexDirection:'row',alignItems:'center',justifyContent:'space-between',gap:10}, heading:{fontSize:26,fontWeight:'600',color:c.ink,flex:1}, title:{fontSize:22,lineHeight:32,fontWeight:'600',color:c.ink}, subheading:{fontSize:17,lineHeight:25,fontWeight:'600',color:c.ink}, body:{fontSize:16,lineHeight:27,color:c.ink,flexShrink:1}, caption:{fontSize:13,lineHeight:21,color:c.muted}, status:{fontSize:14,lineHeight:23,color:c.accentInk}, error:{fontSize:14,lineHeight:23,color:c.danger},card:{backgroundColor:c.surface,borderRadius:22,padding:19,gap:14},timelineRow:{flexDirection:'row',gap:12},timelineRail:{width:12,alignItems:'center',paddingTop:9},timelineDot:{width:8,height:8,borderRadius:4,backgroundColor:c.outline},timelineCurrent:{backgroundColor:c.accent},timelineLine:{width:1,flex:1,minHeight:20,marginTop:5,backgroundColor:c.line},timelineWords:{flex:1,gap:2}});
