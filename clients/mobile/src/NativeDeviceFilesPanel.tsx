import {useCallback, useEffect, useMemo, useRef, useState} from 'react';
import {ActivityIndicator, AppState, StyleSheet, Text, TextInput, View} from 'react-native';
import * as Crypto from 'expo-crypto';
import {router} from 'expo-router';
import {type Connection, ApiError, scopeOf} from './core';
import {accountWorkAllowed, registerAccountWork} from './account-work';
import {useAppTheme, useThemedStyles, type AppColors} from './app-theme';
import {PrimaryButton, TactilePressable} from './experience/primitives';
import {deviceTransferStore} from './device-file-transfer-store';
import {serviceFetch} from './transport';
import {PersonalHubApi, mergeWorkspacePages, workspaceProgress, type WorkspaceFile, type WorkspacePage} from './personal-hub';
import {DeviceFilesApi, DeviceTransferJournal, deviceFileReason, transferLabel,
  type DeviceFile, type DeviceFilesCapability, type DeviceTransfer, type DeviceTransferRequest} from './device-file-transfer';

type Props = {connection: Connection; resource: string; name: string};
const issue = (cause: unknown) => cause instanceof ApiError ? cause.message : '暂时无法核对文件状态，请重新读取。';
const bytes = (size: number) => size < 1024 ? `${size} B` : size < 1048576 ? `${Math.ceil(size / 1024)} KB` : `${(size / 1048576).toFixed(1)} MB`;
const key = () => Crypto.randomUUID().replaceAll('-', '');
export function NativeDeviceFilesPanel(props: Props) {
  const [open, setOpen] = useState(false);
  return <View style={{gap: 10}}>
    <PrimaryButton label={open ? '收起文件传递' : '收发文件'} tone="quiet" onPress={() => setOpen(value => !value)}/>
    {open && <DeviceFilesContent key={scopeOf(props.connection) + '|' + (props.connection.session?.credentialId || 'local') + '|' + props.resource} {...props}/>}
  </View>;
}

function DeviceFilesContent({connection, resource, name}: Props) {
  const s = useThemedStyles(styles), {colors} = useAppTheme();
  const api = useMemo(() => new DeviceFilesApi(connection, resource, serviceFetch), [connection, resource]);
  const journal = useMemo(() => new DeviceTransferJournal(deviceTransferStore(connection), api), [api, connection]);
  const workspace = useMemo(() => new PersonalHubApi(connection, serviceFetch), [connection]);
  const alive = useRef(false), foreground = useRef(AppState.currentState === 'active'), lock = useRef(false), refreshing = useRef(false);
  const pendingRef = useRef<DeviceTransferRequest | null>(null);
  const [capability, setCapability] = useState<DeviceFilesCapability | null>(null), [pending, setPending] = useState<DeviceTransferRequest | null>(null);
  const [ready, setReady] = useState(false), [history, setHistory] = useState<DeviceTransfer[]>([]), [busy, setBusy] = useState('');
  const [error, setError] = useState(''), [reading, setReading] = useState(true), [choosing, setChoosing] = useState(false);
  const [choice, setChoice] = useState<{direction: 'to_device' | 'from_device'; source: DeviceFile} | null>(null);
  const [results, setResults] = useState<{files: DeviceFile[]; truncated: boolean} | null>(null);
  const [missingChecks, setMissingChecks] = useState(0), [confirmStop, setConfirmStop] = useState(false), [notice, setNotice] = useState('');
  const active = useCallback(() => alive.current && foreground.current && accountWorkAllowed(connection), [connection]);
  useEffect(() => {pendingRef.current = pending;}, [pending]);
  const apply = useCallback((receipt: DeviceTransfer) => {
    if (!alive.current) return;
    setHistory(rows => [receipt, ...rows.filter(row => row.request_id !== receipt.request_id)].slice(0, 50));
    if (receipt.state === 'completed' && receipt.direction === 'list') setResults({files: receipt.files!, truncated: receipt.truncated!});
  }, []);
  const refresh = useCallback(async () => {
    if (refreshing.current || lock.current || !active()) return;
    refreshing.current = true;
    try {
      const original = await journal.pending();
      if (!active()) return;
      setPending(original); setReady(true);
      const [status, records] = await Promise.allSettled([api.capability(), api.history()]);
      if (!active()) return;
      setCapability(status.status === 'fulfilled' ? status.value : null);
      if (records.status === 'fulfilled') {
        setHistory(records.value);
        const previous = records.value.find(row => row.direction === 'list' && row.state === 'completed');
        if (previous) setResults({files: previous.files!, truncated: previous.truncated!});
      }
      if (status.status === 'rejected') setError(issue(status.reason));
      else if (records.status === 'rejected' && status.value.supported) setError(issue(records.reason));
      if (original) {
        const receipt = await journal.check(active);
        if (!active()) return;
        if (receipt) {apply(receipt); setMissingChecks(0);}
        const remaining = await journal.pending();
        if (active()) setPending(remaining);
      }
    } catch (cause) {
      if (alive.current) {
        setError(issue(cause));
        if (cause instanceof ApiError && cause.status === 404) setMissingChecks(value => value + 1);
        try {const original = await journal.pending(); if (alive.current) setPending(original);}
        catch {if (alive.current) setReady(false);}
      }
    } finally {refreshing.current = false; if (alive.current) setReading(false);}
  }, [active, api, journal, apply]);

  useEffect(() => {
    alive.current = true;
    const initial = setTimeout(() => {void refresh();}, 0);
    const unregister = registerAccountWork(connection, async () => {
      alive.current = false; pendingRef.current = null;
      setPending(null); setChoice(null); setResults(null); setHistory([]); setCapability(null); setReady(false); setError(''); setNotice('');
    });
    const subscription = AppState.addEventListener('change', state => {
      foreground.current = state === 'active';
      if (foreground.current) {setReading(true); setError(''); void refresh();}
    });
    const timer = setInterval(() => {if (pendingRef.current) void refresh();}, 5000);
    return () => {alive.current = false; clearTimeout(initial); subscription.remove(); unregister(); clearInterval(timer);};
  }, [connection, refresh]);

  async function run(label: string, action: () => Promise<void>) {
    if (lock.current || refreshing.current || !ready || !active()) return;
    lock.current = true; setBusy(label); setError(''); setNotice('');
    try {await action();}
    catch (cause) {if (alive.current) setError(issue(cause));}
    finally {
      try {const original = await journal.pending(); if (alive.current) setPending(original);}
      catch {if (alive.current) {setReady(false); setError('待核对请求未能读取，暂不发起新传递。');}}
      lock.current = false; if (alive.current) setBusy('');
    }
  }
  async function submit(request: DeviceTransferRequest) {
    if (!capability?.available || pending) return;
    const receipt = await journal.create(request, active);
    if (!alive.current) return;
    apply(receipt); setChoice(null); setChoosing(false); setMissingChecks(0); setConfirmStop(false);
  }
  async function stopWaiting() {
    if (!pending || !confirmStop) return;
    await run('正在停止本机等待', async () => {
      await journal.stopWaiting(pending, true, active);
      if (active()) {setPending(null); setChoice(null); setChoosing(false); setConfirmStop(false); setMissingChecks(0); setNotice('已停止本机等待。原请求仍可能完成，可重新读取服务历史。再次传递需重新选择文件。');}
    });
  }
  async function selectFile(file: WorkspaceFile) {
    await run('正在准备文件', async () => {
      const source = await api.source(file.path, active);
      if (active()) {setChoice({direction: 'to_device', source}); setChoosing(false);}
    });
  }
  const unavailable = !!busy || reading || !ready || !capability?.available || !!pending;
  const latest = pending ? history.find(row => row.request_id === pending.request_id) : null;
  return <View style={s.panel}>
    <Text style={s.heading}>{name} · 文件传递</Text>
    <Text style={s.detail}>发到收件箱，或把结果取回工作区。不会自动打开文件或安装应用。</Text>
    {reading && <ActivityIndicator color={colors.accent}/>}
    {capability && !capability.available ? <Text style={s.detail}>{capability.reason ? deviceFileReason(capability.reason) : capability.supported ? '文件传递暂不可用，请重新检查设备。' : '这台设备暂不支持文件传递。'}</Text> : null}
    {error && <Text accessibilityLiveRegion="polite" style={s.error}>{error}</Text>}
    {notice && <Text accessibilityLiveRegion="polite" style={s.detail}>{notice}</Text>}
    <PrimaryButton label="重新核对文件状态" tone="quiet" disabled={!!busy || reading} onPress={() => {setReading(true); setError(''); void refresh();}}/>
    {pending && <View style={s.box}>
      <Text accessibilityLiveRegion="polite" style={s.body}>{latest ? transferLabel(latest) : '原请求结果尚未确认'}</Text>
      {pending.source && <Text style={s.detail}>{pending.source.name} · {bytes(pending.source.size)}</Text>}
      <Text style={s.detail}>正在查询原回执。收起页面不会取消已发出的请求，也不会重新发送文件。</Text>
      {(latest?.state === 'unknown' || missingChecks >= 2) && (confirmStop ? <>
        <Text style={s.detail}>这不会取消设备上的传递，原请求仍可能完成。只停止这台手机的等待；重新发送需重新选择文件并确认。</Text>
        <PrimaryButton label="确认停止本机等待" tone="danger" disabled={!!busy || reading} onPress={() => void stopWaiting()}/>
        <PrimaryButton label="继续核对原请求" tone="quiet" disabled={!!busy} onPress={() => setConfirmStop(false)}/>
      </> : <PrimaryButton label="停止在本机等待" tone="quiet" disabled={!!busy || reading} onPress={() => setConfirmStop(true)}/>)}
    </View>}
    {capability?.supported && <>
      <PrimaryButton label="从工作区选择文件" tone="quiet" disabled={unavailable} onPress={() => {setChoice(null); setChoosing(value => !value);}}/>
      {choosing && <WorkspaceFilePicker connection={connection} api={workspace} disabled={unavailable} limit={capability.max_bytes} onSelect={file => void selectFile(file)}/>}
      <PrimaryButton label="读取设备结果目录" tone="quiet" loading={busy === '正在读取结果目录'} disabled={unavailable}
        onPress={() => void run('正在读取结果目录', () => submit({request_id: key(), direction: 'list'}))}/>
      <Text style={s.detail}>设备结果请保存到 {capability.outbox_label}。只读取这个目录。</Text>
      {results && <View style={s.box}>
        <Text style={s.body}>上次读取的结果</Text>
        {!results.files.length && <Text style={s.detail}>{results.truncated ? '本次返回范围里没有可取回的文件。' : '上次读取时，结果目录里没有文件。'}</Text>}
        {results.files.map(file => <TactilePressable key={file.file_id} disabled={unavailable} style={s.file} accessibilityLabel={`取回 ${file.name}，${bytes(file.size)}`}
          onPress={() => {setChoosing(false); setChoice({direction: 'from_device', source: file});}}>
          <Text style={s.body}>{file.name}</Text><Text style={s.detail}>{bytes(file.size)} · 选择取回</Text>
        </TactilePressable>)}
        {results.truncated && <Text style={s.detail}>目录较大，本次列表未包含全部文件。</Text>}
      </View>}
      {choice && <View style={s.box}>
        <Text style={s.body}>{choice.source.name}</Text><Text style={s.detail}>{bytes(choice.source.size)}</Text>
        <Text style={s.detail}>{choice.direction === 'to_device' ? `已准备文件快照。确认后送到 ${capability.inbox_label}。` : '确认后将这份结果复制到当前身份的工作区。'}</Text>
        <PrimaryButton label={choice.direction === 'to_device' ? '确认发送到设备' : '确认取回工作区'} disabled={unavailable} loading={busy === '正在提交传递'}
          onPress={() => void run('正在提交传递', () => submit({request_id: key(), ...choice}))}/>
        <PrimaryButton label="重新选择" tone="quiet" disabled={!!busy || !!pending} onPress={() => setChoice(null)}/>
      </View>}
    </>}
    {!!history.filter(row => row.direction !== 'list').length && <View style={s.box}>
      <Text style={s.body}>最近传递</Text>
      {history.filter(row => row.direction !== 'list').slice(0, 8).map(row => <View key={row.request_id} style={s.file}>
        <Text style={s.body}>{row.source?.name}</Text><Text style={s.detail}>{transferLabel(row)}</Text>
        {row.state === 'failed' && <Text style={s.detail}>{deviceFileReason(row.error)}</Text>}
        {row.state === 'completed' && row.workspace_file && <PrimaryButton label="在工作区查看" tone="quiet" onPress={() => router.setParams({view: 'memory', memorySection: 'files', memoryFile: row.workspace_file!.path, memoryPath: ''})}/>}
      </View>)}
    </View>}
  </View>;
}

/** Selects metadata only; file content is snapshotted by the service after an explicit tap. */
function WorkspaceFilePicker({connection, api, disabled, limit, onSelect}: {
  connection: Connection; api: PersonalHubApi; disabled: boolean; limit: number; onSelect: (file: WorkspaceFile) => void;
}) {
  const s = useThemedStyles(styles), {colors} = useAppTheme();
  const [query, setQuery] = useState(''), [search, setSearch] = useState(''), [revision, setRevision] = useState(0);
  const [page, setPage] = useState<WorkspacePage | null>(null), [error, setError] = useState(''), [loading, setLoading] = useState(true);
  const generation = useRef(0), moreLock = useRef(false), moreAbort = useRef<AbortController | null>(null);
  useEffect(() => {
    const current = ++generation.current, cancel = new AbortController();
    moreAbort.current?.abort();
    void api.workspacePage({query: search}, cancel.signal).then(next => {if (generation.current === current) setPage(next);})
      .catch(cause => {if (generation.current === current) setError(issue(cause));})
      .finally(() => {if (generation.current === current) setLoading(false);});
    return () => {generation.current = current + 1; cancel.abort(); moreAbort.current?.abort();};
  }, [api, search, revision]);
  function find() {
    setPage(null); setError(''); setLoading(true);
    if (search === query.trim()) setRevision(value => value + 1); else setSearch(query.trim());
  }
  async function more() {
    if (!page?.next_cursor || moreLock.current || loading) return;
    const current = generation.current, cancel = new AbortController(); moreAbort.current = cancel; moreLock.current = true; setLoading(true); setError('');
    try {
      const next = await api.workspacePage({query: search, cursor: page.next_cursor}, cancel.signal);
      if (generation.current === current) setPage(mergeWorkspacePages(page, next));
    } catch (cause) {if (generation.current === current) {setError(issue(cause)); if (cause instanceof ApiError && [409, 422].includes(cause.status)) setPage(null);}}
    finally {moreLock.current = false; if (generation.current === current) setLoading(false);}
  }
  return <View style={s.box}>
    <Text style={s.body}>工作区文件</Text>
    <TextInput accessibilityLabel="搜索要发送的工作区文件" placeholder="搜索文件名" placeholderTextColor={colors.muted} value={query} maxLength={200} onChangeText={setQuery}
      onSubmitEditing={find} returnKeyType="search" style={s.input}/>
    <PrimaryButton label="查找文件" tone="quiet" disabled={disabled || loading} onPress={find}/>
    {page?.files.map(file => <TactilePressable key={file.path} style={s.file} disabled={disabled || file.size === 0 || file.size > limit || !accountWorkAllowed(connection)}
      accessibilityLabel={`选择 ${file.path}，${bytes(file.size)}`} onPress={() => onSelect(file)}>
      <Text style={s.body}>{file.path.split('/').pop()}</Text><Text numberOfLines={2} style={s.detail}>{file.path} · {bytes(file.size)}{file.size > limit ? ' · 超出传递大小限制' : file.size === 0 ? ' · 空文件暂不支持传递' : ''}</Text>
    </TactilePressable>)}
    {loading && <ActivityIndicator color={colors.accent}/>}
    {page && <Text style={s.detail}>{workspaceProgress(page)}</Text>}
    {page?.complete && !page.files.length && <Text style={s.detail}>没有找到文件。可先在“记忆 → 文件夹”导入资料。</Text>}
    {error && <Text style={s.error}>{error}</Text>}
    {page?.next_cursor ? <PrimaryButton label="继续查找" tone="quiet" disabled={disabled || loading} onPress={() => void more()}/> : error ? <PrimaryButton label="重新读取列表" tone="quiet" disabled={disabled || loading} onPress={find}/> : null}
  </View>;
}

const styles = (c: AppColors) => StyleSheet.create({
  panel: {gap: 12, paddingTop: 8}, heading: {fontSize: 17, fontWeight: '600', color: c.ink},
  body: {fontSize: 15, color: c.ink, lineHeight: 22}, detail: {fontSize: 13, color: c.muted, lineHeight: 20},
  error: {fontSize: 14, color: c.danger, lineHeight: 21}, box: {backgroundColor: c.soft, borderRadius: 14, padding: 12, gap: 10},
  file: {minHeight: 48, paddingVertical: 10, gap: 4, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: c.line},
  input: {minHeight: 44, paddingHorizontal: 12, borderRadius: 12, color: c.ink, backgroundColor: c.surface, fontSize: 15},
});
