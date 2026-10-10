import {useCallback, useEffect, useMemo, useRef, useState} from 'react';
import {ActivityIndicator, AppState, StyleSheet, Switch, Text, TextInput, View} from 'react-native';
import {File} from 'expo-file-system';
import * as Crypto from 'expo-crypto';
import * as DocumentPicker from 'expo-document-picker';
import {Monitor, Smartphone} from 'lucide-react-native';
import {router} from 'expo-router';
import {NativeDeviceFilesPanel} from './NativeDeviceFilesPanel';
import {RemoteDeviceApi, remoteStatusCopy, type RemoteAccess} from './remote-device-model';
import {ApiError, Connection, scopeOf} from './core';
import {useAppTheme, useThemedStyles, type AppColors} from './app-theme';
import {PrimaryButton, TactilePressable} from './experience/primitives';
import {serviceFetch} from './transport';
import {storage} from './storage';
import {shareOriginalBytes} from './workspace-share';
import {DeviceManagementApi, approvalDescription, canDecide, deviceCapabilityLabels, deviceControlAction, deviceStatus, parseDeviceOffer, selectedDeviceOffer,
  type CloudDevice, type DeviceApproval, type DeviceReview, type InspectedResource, type LocalComputer,
  type LocalPhone, type PairingIntent, type PermissionIntent, type PermissionState} from './device-management';

type Props = {connection: Connection};
const uuid = () => Crypto.randomUUID().replaceAll('-', '');
const messageOf = (error: unknown) => error instanceof Error ? error.message : '这次未完成，请重新检测后再试。';
/** A keyed boundary discards pending UI state before a different identity can render it. */
export function NativeDevicePanel(props: Props) {return <DevicePanel key={scopeOf(props.connection)} {...props}/>;}

function DevicePanel({connection}: Props) {
  const styles = useThemedStyles(makeStyles), {colors} = useAppTheme();
  const api = useMemo(() => new DeviceManagementApi(connection, serviceFetch), [connection]);
  const [deployment, setDeployment] = useState<'local' | 'cloud' | null>(null);
  const [devices, setDevices] = useState<CloudDevice[]>([]), [approvals, setApprovals] = useState<DeviceApproval[]>([]), [reviews, setReviews] = useState<DeviceReview[]>([]);
  const [computer, setComputer] = useState<LocalComputer | null>(null), [phone, setPhone] = useState<LocalPhone | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const [busy, setBusy] = useState(''), [error, setError] = useState(''), [notice, setNotice] = useState(''), [ready, setReady] = useState(false);
  const [offer, setOffer] = useState<InspectedResource[]>([]), [selected, setSelected] = useState<string[]>([]), [input, setInput] = useState<string[]>([]);
  const [pairing, setPairing] = useState<PairingIntent | null>(null), [permission, setPermission] = useState<PermissionIntent | null>(null), [permissionState, setPermissionState] = useState<PermissionState | null>(null);
  const alive = useRef(false), lock = useRef(false), loading = useRef(false), foreground = useRef(AppState.currentState === 'active');
  const mode = useRef<'local' | 'cloud' | null>(null), pendingPermission = useRef<PermissionIntent | null>(null);
  const stateKey = 'device-pairing:v1:' + scopeOf(connection), permissionKey = 'device-permission:v1:' + scopeOf(connection);
  const active = useCallback(() => alive.current, []);

  const refresh = useCallback(async (force = false) => {
    if (loading.current) return;
    loading.current = true;
    if (alive.current) setNow(Date.now());
    try {
      const currentMode = mode.current || await api.bootstrap();
      if (!alive.current) return;
      mode.current = currentMode; setDeployment(currentMode);
      if (currentMode === 'cloud') {
        const [inventory, decisions, checks] = await Promise.all([api.cloudDevices(), api.approvals(), api.reviews()]);
        if (!alive.current) return;
        setDevices(inventory); setApprovals(decisions); setReviews(checks);
        const intent = pendingPermission.current;
        if (intent) {
          try {const status = await api.permissionStatus(intent.request_id); if (alive.current) setPermissionState(status);}
          catch (cause) {if (alive.current) setError(messageOf(cause));}
        }
      } else {
        const [pc, mobile] = await Promise.allSettled([api.localComputer(force), api.localPhone()]);
        if (!alive.current) return;
        setComputer(pc.status === 'fulfilled' ? pc.value : null); setPhone(mobile.status === 'fulfilled' ? mobile.value : null);
        const failures = [pc, mobile].filter(result => result.status === 'rejected');
        if (failures.length) setError(failures.map(result => result.status === 'rejected' ? messageOf(result.reason) : '').join('\n'));
        if (failures.length === 2) {setReady(false); return;}
      }
      if (alive.current) setReady(true);
    } catch (cause) {if (alive.current) {setReady(false); setError(messageOf(cause));}}
    finally {loading.current = false;}
  }, [api]);

  useEffect(() => {
    alive.current = true;
    storage.get<PairingIntent>(stateKey).then(saved => {
      if (!alive.current || !saved || !/^[a-f0-9]{32}$/.test(saved.request_id) || !Number.isFinite(saved.createdAt)) return;
      try {setPairing({...saved, offer: parseDeviceOffer(saved.offer)});} catch {setError('上次设备清单未完整保存，请重新导入。');}
    }).catch(() => {if (alive.current) setError('上次配对记录未能读取，请重试打开此页。');});
    storage.get<PermissionIntent>(permissionKey).then(saved => {
      if (!alive.current || !saved || !/^[a-f0-9]{32}$/.test(saved.request_id)) return;
      pendingPermission.current = saved; setPermission(saved);
    }).catch(() => {if (alive.current) setError('上次权限请求未能读取，请重新检测设备权限。');});
    void refresh();
    const subscription = AppState.addEventListener('change', state => {foreground.current = state === 'active'; if (foreground.current && !lock.current) void refresh();});
    const timer = setInterval(() => {if (foreground.current && !lock.current) void refresh();}, 10000);
    return () => {alive.current = false; subscription.remove(); clearInterval(timer);};
  }, [refresh, stateKey, permissionKey]);

  async function run(label: string, work: () => Promise<void>) {
    if (lock.current) return;
    lock.current = true; setBusy(label); setError(''); setNotice('');
    try {await work();}
    catch (cause) {if (alive.current) setError(messageOf(cause));}
    finally {if (alive.current) {await refresh(); setBusy('');} lock.current = false;}
  }
  async function importOffer() {
    const picked = await DocumentPicker.getDocumentAsync({type: ['application/json', 'text/plain'], copyToCacheDirectory: true, multiple: false});
    if (picked.canceled || !alive.current) return;
    const item = picked.assets[0];
    if ((item.size ?? 0) > 32768) throw new Error('设备清单不能超过 32 KB，请选择连接器导出的清单文件。');
    const text = item.file ? await item.file.text() : await new File(item.uri).text();
    if (new TextEncoder().encode(text).length > 32768) throw new Error('设备清单不能超过 32 KB。');
    let value: unknown;
    try {value = JSON.parse(text);} catch {throw new Error('这不是有效的设备清单，请选择导出的 JSON 文件。');}
    const inspected = await api.inspect(parseDeviceOffer(value));
    if (!alive.current) return;
    setOffer(inspected); setSelected(inspected.filter(row => !row.already_paired).map(row => row.resource_id)); setInput([]);
  }
  async function createPairing() {
    const choice = selectedDeviceOffer(offer, selected, input);
    const intent = pairing && Date.now() - pairing.createdAt < 600000 && JSON.stringify(pairing.offer) === JSON.stringify(choice)
      ? pairing : {request_id: uuid(), offer: choice, createdAt: Date.now()};
    // Save the request before sending so lost responses can be recovered; never store its secret bundle.
    await storage.put(stateKey, intent);
    if (!alive.current) return;
    setPairing(intent); await api.pair(intent);
    if (alive.current) setNotice('配对文件已生成。请发送到这台设备的连接器完成接入；设备上线后会出现在列表里。');
  }
  async function changePermission(device: CloudDevice) {
    const mode = device.methods.includes('computer.input') ? 'observe' : 'input';
    const old = pendingPermission.current;
    const intent: PermissionIntent = old && old.resource_id === device.resource_id && old.revision === device.permission_revision && old.mode === mode
      && !['expired', 'superseded'].includes(permissionState?.state || '') ? old
      : {request_id: uuid(), resource_id: device.resource_id, revision: device.permission_revision, mode, delivery: 'connector'};
    await storage.put(permissionKey, intent);
    if (!alive.current) return;
    pendingPermission.current = intent; setPermission(intent); setPermissionState(null);
    await api.permission(intent);
    if (alive.current) setNotice('权限请求已发出，等待设备确认。');
  }
  const toggle = (values: string[], value: string) => values.includes(value) ? values.filter(item => item !== value) : [...values, value];
  const localControl = async (action: 'prepare' | 'permissions' | 'bind' | 'pause' | 'resume') => {
    await api.computerAction(action);
    const current = await api.localComputer(true);
    if (!alive.current) return;
    setComputer(current);
    if ((action === 'pause' && !current.held) || (action === 'resume' && current.held)) throw new Error('电脑尚未确认控制状态，请重新检测。');
    setNotice(action === 'permissions' ? '请在电脑上完成系统权限授权，然后点重新检测。' : action === 'prepare' ? '连接器正在准备，可稍后重新检测。' : action === 'bind' ? '电脑已接入。' : action === 'pause' ? '你已接管电脑。' : '电脑已交回助手。');
  };

  return <View style={styles.root}>
    <View style={styles.heading}><Text style={styles.title}>设备</Text>{<DeviceAction busy={busy} run={run} label={'重新检测'} work={async () => {await refresh(true);}}/>}</View>
    <Text style={styles.description}>管理接入的电脑和 Android 手机。你可以随时接管，也可以调整助手的操作权限。</Text>
    {!!error && <Text accessibilityRole="alert" style={styles.error}>{error}</Text>}
    {!!notice && <Text accessibilityLiveRegion="polite" style={styles.notice}>{notice}</Text>}
    {!deployment && !error && <ActivityIndicator color={colors.accent}/>}
    {deployment === 'local' && <>
      <Text style={styles.description}>这些设备连接在当前 Pajio 服务所在的电脑上。</Text>
      {computer && <View style={styles.card}>
        <View style={styles.row}><Monitor color={colors.ink} size={24}/><Text style={styles.title}>这台电脑</Text></View>
        <Text style={styles.body}>{computer.held ? '已由你接管' : computer.connector.enrolled && computer.ready ? '已接入 · 可以协助操作' : computer.ready ? '已就绪 · 等待接入' : computer.installed === null ? '暂时无法检测' : computer.installed ? '等待系统授权' : '连接器尚未准备'}</Text>
        {computer.installed && <Text style={styles.description}>辅助功能：{computer.accessibility ? '已允许' : '未允许'} · 屏幕录制：{computer.screen_recording ? '已允许' : '未允许'}</Text>}
        {!!(computer.error || computer.connector.error) && <Text style={styles.error}>{computer.error || computer.connector.error}</Text>}
        {computer.connector.phase === 'installing' ? <Text style={styles.description}>正在准备连接器…</Text>
          : computer.installed === false ? <DeviceAction busy={busy} run={run} label={'准备电脑连接器'} work={() => localControl('prepare')}/>
            : computer.installed === null ? <DeviceAction busy={busy} run={run} label={'重试电脑检测'} work={async () => {const value = await api.localComputer(true); if (alive.current) setComputer(value);}}/>
              : !computer.ready && computer.can_grant ? <DeviceAction busy={busy} run={run} label={'打开电脑系统授权'} work={() => localControl('permissions')}/>
                : computer.ready && !computer.connector.enrolled ? <DeviceAction busy={busy} run={run} label={'接入这台电脑'} work={() => localControl('bind')}/>
                  : computer.connector.enrolled ? <DeviceAction busy={busy} run={run} label={computer.held ? '交回助手' : '我来接管电脑'} work={() => localControl(computer.held ? 'resume' : 'pause')} disabled={false} danger={!computer.held}/> : null}
      </View>}
      {phone && <View style={styles.card}>
        <View style={styles.row}><Smartphone color={colors.ink} size={24}/><Text style={styles.title}>Android 手机</Text></View>
        {!phone.connector.installed && (phone.connector.phase === 'installing' ? <Text style={styles.body}>正在准备手机连接器…</Text> : <DeviceAction busy={busy} run={run} label={'准备手机连接器'} work={() => api.phoneAction('prepare')}/>)}
        {!!phone.connector.error && <Text style={styles.error}>{phone.connector.error}</Text>}
        {phone.resources.map(d => <View key={d.resource_id} style={styles.section}>
          <Text style={styles.body}>{d.name}</Text><Text style={styles.description}>{!d.enabled ? '已暂停' : d.online ? '在线' : '设备离线'}</Text>
          {<DeviceAction busy={busy} run={run} label={d.enabled ? `暂停 ${d.name}` : `恢复 ${d.name}`} work={async () => {
            await api.phoneAction(d.enabled ? 'pause' : 'resume', d.resource_id);
            if (alive.current && d.enabled) setNotice('已暂停新的手机操作；已发出的动作可能仍需片刻返回。');
          }} disabled={false} danger={d.enabled}/>}
        </View>)}
        {phone.devices.filter(d => !phone.resources.some(r => r.serial === d.serial)).map(d => <View key={d.serial} style={styles.section}>
          <Text style={styles.body}>{d.model}</Text>{d.state === 'device' ? <DeviceAction busy={busy} run={run} label={`接入 ${d.model}`} work={() => api.phoneAction('bind', d.serial)} disabled={!phone.connector.installed}/>
            : <Text style={styles.description}>{d.state === 'unauthorized' ? '请解锁手机，允许此电脑的 USB 调试连接，再重新检测。' : '手机连接未就绪，请检查 USB 连接。'}</Text>}
        </View>)}
        {!phone.resources.length && !phone.devices.length && <Text style={styles.description}>用 USB 把 Android 手机连接到服务所在电脑，开启 USB 调试并允许连接后，点重新检测。</Text>}
      </View>}
    </>}
    {deployment === 'cloud' && <>
      {devices.length === 0 && ready && <Text style={styles.body}>当前身份尚未接入设备。</Text>}
      {devices.map(d => <View key={d.resource_id} style={styles.card}>
        <View style={styles.row}>{d.kind === 'computer' ? <Monitor color={colors.ink} size={24}/> : <Smartphone color={colors.ink} size={24}/>}<Text style={styles.title}>{d.name}</Text></View>
        <Text style={styles.body}>{deviceStatus(d)}</Text>
        {!!deviceCapabilityLabels(d).length && <Text style={styles.description}>已授权能力 · {deviceCapabilityLabels(d).join('、')}</Text>}
        {!!d.last_seen_at && <Text style={styles.description}>最近连接 {new Date(d.last_seen_at).toLocaleString('zh-CN', {hour12: false})}</Text>}
        <RemoteDeviceEntry connection={connection} device={d} ready={ready} busy={busy} run={run} onControl={async paused => {
          await api.control(d, paused);
          if (alive.current) setNotice(paused ? '已阻止新的云端操作，等待设备确认暂停。' : '恢复请求已保存，等待设备确认。');
        }}/>
        <NativeDeviceFilesPanel connection={connection} resource={d.resource_id} name={d.name}/>
        {d.kind === 'computer' && <DeviceAction busy={busy} run={run} label={d.methods.includes('computer.input') ? '改为仅观察' : '允许确认后点击与输入'} work={() => changePermission(d)} disabled={!ready || d.needs_review}/>}
      </View>)}
      {permission && <View style={styles.card}><Text style={styles.body}>权限变更</Text>
        <Text style={styles.description}>{!permissionState ? '尚未取得回执，请重新检测或重试原请求。' : permissionState.state === 'pending' ? '等待设备接收并确认，当前权限尚未改变。'
          : permissionState.state === 'applied' ? permissionState.connected ? '权限已更新，设备已重新连接。' : '权限已更新，等待设备重新连接。'
            : permissionState.state === 'expired' ? '请求已过期，可重新选择设备权限。' : '权限已有后续变化，以设备当前显示为准。'}</Text>
        {!permissionState && <DeviceAction busy={busy} run={run} label={'重试原权限请求'} work={() => api.permission(permission)}/>}
      </View>}
      {approvals.filter(a => a.state === 'awaiting_user').map(a => <View key={a.approval_id + a.revision} style={styles.card}>
        <Text style={styles.title}>有一步需要你确认</Text><Text style={styles.body}>{a.reason}</Text><Text selectable style={styles.body}>{approvalDescription(a)}</Text>
        <Text style={styles.description}>{canDecide(a, now) ? '仅在有效期内执行本次选择。' : '这一步已变化或过期，请重新检测。'}</Text>
        {<DeviceAction busy={busy} run={run} label={'允许这一步'} work={() => api.decide(a, 'once')} disabled={!ready || !canDecide(a, now)}/>}
        {a.task_eligible && <><Text style={styles.description}>授权本次任务：同一任务的常规操作可继续，最多 30 分钟；付款、发布等承诺仍需单独确认。</Text>{<DeviceAction busy={busy} run={run} label={'授权本次任务'} work={() => api.decide(a, 'task')} disabled={!ready || !canDecide(a, now)}/>}</>}
        {<DeviceAction busy={busy} run={run} label={'不允许'} work={() => api.decide(a, 'deny')} disabled={!ready || !canDecide(a, now)} danger={true}/>}
      </View>)}
      {reviews.map(r => <ReviewCard key={r.command_id} value={r} busy={!!busy} ready={ready} submit={(note, checked) => run('保存设备核对', async () => {
        await api.review(r, note, checked); if (alive.current) setNotice('核对结果已保存，原动作不会重发。');
      })}/>)}
      <View style={styles.card}>
        <Text style={styles.title}>接入新的电脑或手机</Text>
        <Text style={styles.description}>从已安装连接器的电脑导入设备清单，选择允许的范围，再把一次性配对文件发送回该电脑。配对文件有效期为 10 分钟，只交给自己的设备。</Text>
        {<DeviceAction busy={busy} run={run} label={'导入设备清单'} work={importOffer} disabled={!ready}/>}
        {offer.map(d => <View key={d.resource_id} style={styles.section}>
          <View style={styles.between}><Text style={styles.body}>{d.name}{d.already_paired ? ' · 已接入' : ''}</Text><Switch accessibilityLabel={`选择 ${d.name}`} value={selected.includes(d.resource_id)}
            disabled={!!busy || d.already_paired} onValueChange={() => setSelected(current => toggle(current, d.resource_id))}/></View>
          {selected.includes(d.resource_id) && <View style={styles.between}><Text style={styles.description}>{d.kind === 'computer' ? '允许确认后点击与输入' : '允许读取、点击与输入'}</Text><Switch accessibilityLabel={`${d.name} 操作权限`} value={input.includes(d.resource_id)} disabled={!!busy}
            onValueChange={() => setInput(current => toggle(current, d.resource_id))}/></View>}
        </View>)}
        {!!offer.length && <DeviceAction busy={busy} run={run} label={'生成配对文件'} work={createPairing} disabled={!ready || !selected.length}/>}
        {pairing && <View style={styles.section}>
          <Text style={styles.description}>上次选择：{pairing.offer.resources.map(d => d.name).join('、')}</Text>
          {now - pairing.createdAt < 600000 ? <>
            {<DeviceAction busy={busy} run={run} label={'恢复上次配对请求'} work={() => api.pair(pairing)}/>}
            {<DeviceAction busy={busy} run={run} label={'分享配对文件到自己的电脑'} work={() => shareOriginalBytes(() => api.pairingBytes(pairing), 'pajio-pair.json', 'application/json', active)}/>}
          </> : <Text style={styles.description}>上次配对已过期，请重新导入清单生成。</Text>}
        </View>}
      </View>
      {!!devices.length && <DeviceAction busy={busy} run={run} label={'更新对话中的设备能力'} work={async () => {const message = await api.refreshTools(); if (alive.current) setNotice(message);}} disabled={!ready}/>}
    </>}
  </View>;
}

/** Capability comes from this resource's authenticated access state, not deployment labels. */
function RemoteDeviceEntry({connection, device, ready, busy, run, onControl}: {
  connection: Connection; device: CloudDevice; ready: boolean; busy: string;
  run: (label: string, work: () => Promise<void>) => Promise<void>; onControl: (paused: boolean) => Promise<void>;
}) {
  const styles = useThemedStyles(makeStyles);
  const api = useMemo(() => new RemoteDeviceApi(connection, serviceFetch), [connection]);
  const [access, setAccess] = useState<RemoteAccess | null>(null), [failed, setFailed] = useState(false);
  const [revision, setRevision] = useState(0);
  const mounted = useRef(false);
  useEffect(() => {mounted.current = true; return () => {mounted.current = false;};}, []);
  useEffect(() => {
    let active = true, pending = false;
    const load = async () => {
      if (pending || AppState.currentState !== 'active') return;
      pending = true;
      try {const next = await api.status(device.resource_id); if (active) {setAccess(next); setFailed(false);}}
      catch {if (active) {setAccess(null); setFailed(true);}}
      finally {pending = false;}
    };
    void load(); const timer = setInterval(() => {void load();}, 10000);
    return () => {active = false; clearInterval(timer);};
  }, [api, device.resource_id, device.control_generation, revision]);
  function openRemote() {
    if (!mounted.current || AppState.currentState !== 'active') return;
    router.setParams({view: 'remote-device', resource: device.resource_id, deviceKind: device.kind, deviceName: device.name});
  }
  async function changeControl() {
    if (!mounted.current || AppState.currentState !== 'active' || !ready || busy || device.control_pending) return;
    if (!device.paused) {await onControl(true); return;}
    // Recheck on the explicit tap: the displayed inventory may predate another client's takeover.
    const current = await api.status(device.resource_id);
    if (!mounted.current || AppState.currentState !== 'active') return;
    setAccess(current); setFailed(false);
    const action = deviceControlAction(device, current);
    if (action === 'return') {openRemote(); return;}
    if (action !== 'resume') throw new ApiError('设备状态正在变化，请重新检测后再操作。', 409);
    await onControl(false);
  }
  const action = deviceControlAction(device, access);
  return <View style={{gap: 8}}>
    <Text style={styles.description}>{failed ? '暂时无法确认远程接管状态。' : remoteStatusCopy(access)}</Text>
    {access?.supported && <Text style={styles.description}>需要登录或验证时，可由你接管。设备确认后才连接画面，交还后 Pajio 才能继续操作。</Text>}
    {action === 'return' && <Text style={styles.description}>上次私密接管后，设备仍保持暂停。请先查看画面，再确认交还；不会直接恢复助手操作。</Text>}
    {access?.supported && <PrimaryButton label={action === 'return' ? `查看并交还 ${device.name}` : '查看画面与接管'} disabled={!!busy || !ready} onPress={openRemote}/>}
    {action !== 'return' && <DeviceAction busy={busy} run={run}
      label={action === 'check' ? '检查暂停状态' : action === 'wait' ? '等待设备确认' : device.paused ? `恢复 ${device.name}` : `暂停 ${device.name}`}
      work={changeControl} disabled={!ready || action === 'wait'} danger={!device.paused}/>}
    {failed && <PrimaryButton label="重新检查远程连接" tone="quiet" onPress={() => setRevision(v => v + 1)}/>}
  </View>;
}

function DeviceAction({label, work, disabled = false, danger = false, busy, run}: {
  label: string; work: () => Promise<void>; disabled?: boolean; danger?: boolean; busy: string;
  run: (label: string, work: () => Promise<void>) => Promise<void>;
}) {
  return <PrimaryButton label={label} loading={busy === label} disabled={!!busy || disabled}
    tone={danger ? 'danger' : 'quiet'} onPress={() => void run(label, work)}/>;
}

function ReviewCard({value, busy, ready, submit}: {value: DeviceReview; busy: boolean; ready: boolean; submit: (note: string, checked: boolean) => Promise<void>}) {
  const styles = useThemedStyles(makeStyles), {colors} = useAppTheme();
  const [note, setNote] = useState(''), [checkedRevision, setCheckedRevision] = useState('');
  const checked = checkedRevision === value.revision;
  return <View style={styles.card}>
    <Text style={styles.title}>{value.name} · 旧动作待核对</Text>
    <Text style={styles.description}>请查看设备上的实际结果。核对后只恢复后续操作，不重发旧动作，也不会把任务标为成功。</Text>
    <TextInput value={note} onChangeText={setNote} style={styles.input} multiline maxLength={2000} editable={!busy}
      accessibilityLabel="设备操作的实际结果" placeholder="写下实际看到的结果，至少五个字" placeholderTextColor={colors.muted}/>
    <TactilePressable style={styles.row} accessibilityRole="checkbox" accessibilityState={{checked}} disabled={busy || !value.can_review}
      onPress={() => setCheckedRevision(checked ? '' : value.revision)}><Text style={styles.body}>{checked ? '☑' : '☐'} 我已查看设备，确认旧动作已结束</Text></TactilePressable>
    {!value.can_review && <Text style={styles.description}>等待旧动作结束、设备重新在线后才能提交。</Text>}
    <PrimaryButton label="保存核对结果" disabled={busy || !ready || !value.can_review || !checked || note.trim().length < 5} onPress={() => void submit(note, checked)}/>
  </View>;
}

const makeStyles = (c: AppColors) => StyleSheet.create({
  root: {gap: 16}, heading: {flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', gap: 12},
  title: {fontSize: 19, lineHeight: 27, fontWeight: '600', color: c.ink, flexShrink: 1},
  body: {fontSize: 16, lineHeight: 25, color: c.ink, flexShrink: 1}, description: {fontSize: 14, lineHeight: 23, color: c.muted, flexShrink: 1},
  card: {backgroundColor: c.surface, borderRadius: 24, padding: 20, gap: 14}, row: {flexDirection: 'row', alignItems: 'center', gap: 10, minHeight: 44},
  between: {flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 14},
  section: {gap: 12, borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: c.line, paddingTop: 16},
  input: {fontSize: 16, lineHeight: 24, color: c.ink, backgroundColor: c.soft, minHeight: 110, borderRadius: 14, padding: 14, textAlignVertical: 'top'},
  error: {fontSize: 14, lineHeight: 22, color: c.danger}, notice: {fontSize: 14, lineHeight: 22, color: c.success},
});
