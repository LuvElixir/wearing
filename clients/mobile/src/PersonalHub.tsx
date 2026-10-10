import {NativeNotificationsPanel} from './NativeNotificationsPanel';
import {UsagePanel} from './UsagePanel';
import {NativeDataPanel} from './NativeDataPanel';
import {NativeDiagnosticsPanel} from './NativeDiagnosticsPanel';
import {NativeCloudAppsPanel} from './NativeCloudAppsPanel';
import {MessagingPanel} from './MessagingPanel';
import {NativeDevicePanel} from './NativeDevicePanel';
import {MemoryEditor} from './MemoryEditor';
import {SkillsPanel} from './SkillsPanel';
import {WorkspaceImportButton} from './WorkspaceImportButton';
import WorkspaceTextEditor from './WorkspaceTextEditor';
import {editableDocument} from './workspace-text';
import {AppearancePanel} from './AppearancePanel';
import {BrandStar} from './BrandStar';
import {BrandWordmark} from './BrandWordmark';
import {useAppTheme, useThemedStyles, type AppColors} from './app-theme';
import React, {ReactNode, useEffect, useMemo, useRef, useState} from 'react';
import {ActivityIndicator, StyleSheet, Text, TextInput, View} from 'react-native';
import {router, useLocalSearchParams} from 'expo-router';
import {BookOpen, CalendarDays, Camera, ChevronLeft, ChevronRight, FileText, Folder, Layers, Link2, MapPin, MessageCircle, Monitor, RefreshCw, Search, Share2, ShieldCheck, SlidersHorizontal, Smartphone} from 'lucide-react-native';
import {Connection, MemorySnapshot, scopeOf, WearingApi} from './core';
import {Entrance, TactilePressable} from './experience/primitives';
import {HubRuntime, memoryCollection, memoryObservationLabel, mergeWorkspacePages, PersonalHubApi, safeWorkspacePath, textPreviewAllowed, WorkspaceFile, WorkspacePage, WorkspaceSnapshot, workspaceFileDraft, workspaceProgress, workspaceSearch, WORKSPACE_ORIGINAL_LIMIT} from './personal-hub';
import {shareWorkspaceFile} from './workspace-share';
import {serviceFetch} from './transport';
import {Wardrobe, WardrobeEntry} from './WardrobePanel';
import type {WardrobeController} from './useWardrobe';

const issue = (error: unknown) => error instanceof Error ? error.message : '暂时无法读取，请稍后再试。';
const value = (input?: string | string[]) => Array.isArray(input) ? input[0] || '' : input || '';

function HubRow({title, detail, icon, status, onPress, last = false}: {title: string; detail?: string; icon: ReactNode; status?: string; onPress?: () => void; last?: boolean}) {
  const {colors: c} = useAppTheme();
  const s = useThemedStyles(makeStyles);

  const contents = <><View style={s.rowIcon}>{icon}</View><View style={s.rowWords}><Text style={s.rowTitle}>{title}</Text>{detail ? <Text style={s.detail}>{detail}</Text> : null}</View>{status ? <Text style={s.status}>{status}</Text> : null}{onPress ? <ChevronRight size={17} color={c.muted}/> : null}</>;
  return onPress ? <TactilePressable accessibilityLabel={[title, status, detail].filter(Boolean).join('，')} onPress={onPress} style={[s.row, !last && s.rowDivider]}>{contents}</TactilePressable> : <View style={[s.row, !last && s.rowDivider]}>{contents}</View>;
}
function BackLabel({title, onPress}: {title: string; onPress: () => void}) {
  const {colors: c} = useAppTheme();
  const s = useThemedStyles(makeStyles);

  return <TactilePressable onPress={onPress} accessibilityLabel={'返回' + title} style={s.back}><ChevronLeft size={19} color={c.ink}/><Text style={s.backLabel}>{title}</Text></TactilePressable>;
}
function Loading({label}: {label: string}) {
  const {colors: c} = useAppTheme();
  const s = useThemedStyles(makeStyles);
return <View style={s.loading}><ActivityIndicator color={c.muted}/><Text style={s.detail}>{label}</Text></View>;}
function Problem({message, retry}: {message: string; retry?: () => void}) {
  const {colors: c} = useAppTheme();
  const s = useThemedStyles(makeStyles);
return <View style={s.problem}><Text accessibilityLiveRegion="polite" style={s.detail}>{message}</Text>{retry ? <TactilePressable onPress={retry} accessibilityLabel="重新读取" style={s.smallButton}><RefreshCw size={16} color={c.ink}/><Text style={s.backLabel}>重新读取</Text></TactilePressable> : null}</View>;}
function SectionLabel({children}: {children: ReactNode}) {
  const s = useThemedStyles(makeStyles);
return <Text style={s.sectionLabel}>{children}</Text>;}

export type MemoryLibraryProps = {connection: Connection; onFiles: () => void; onChat: (draft?: string) => void; onConnect: () => void; onSources?: () => void};
/** The entries and file tree below are live data belonging to this connection's identity. */
export function MemoryLibrary(props: MemoryLibraryProps) {return <MemoryLibraryContent key={scopeOf(props.connection)} {...props}/>;}
function MemoryLibraryContent({connection, onFiles, onChat, onConnect, onSources}: MemoryLibraryProps) {
  const {colors: c} = useAppTheme();
  const s = useThemedStyles(makeStyles);

  const api = useMemo(() => new PersonalHubApi(connection, serviceFetch), [connection]);
  const memoryApi = useMemo(() => new WearingApi(connection, serviceFetch), [connection]);
  const params = useLocalSearchParams<{memoryPath?: string; memoryFile?: string; memorySection?: string; memoryQuery?: string}>();
  const directory = value(params.memoryPath), selectedPath = value(params.memoryFile), section = value(params.memorySection);
  const [data, setData] = useState<MemorySnapshot | null>(null), [workspace, setWorkspace] = useState<WorkspaceSnapshot | null>(null);
  const [memoryError, setMemoryError] = useState(''), [filesError, setFilesError] = useState(''), [memoryLoading, setMemoryLoading] = useState(true), [filesLoading, setFilesLoading] = useState(true), [generation, setGeneration] = useState(0);
  const loading = memoryLoading || filesLoading;
  useEffect(() => {
    let live = true;
    void memoryApi.memory().then(result => {if (live) setData(result);}).catch(cause => {if (live) setMemoryError(issue(cause));}).finally(() => {if (live) setMemoryLoading(false);});
    void api.workspacePage().then(result => {if (live) setWorkspace(result);}).catch(cause => {if (live) setFilesError(issue(cause));}).finally(() => {if (live) setFilesLoading(false);});
    return () => {live = false;};
  }, [api, memoryApi, generation]);
  const refresh = () => {setMemoryLoading(true); setFilesLoading(true); setData(null); setWorkspace(null); setMemoryError(''); setFilesError(''); setGeneration(current => current + 1);};
  const open = (next: {memoryPath?: string; memoryFile?: string; memorySection?: string}) => {router.setParams({memoryPath: '', memoryFile: '', memorySection: '', memoryQuery: '', ...next});};
  const memoryKey = section === 'user' || section === 'memory' ? section : null;
  const target = memoryKey && data?.available ? data.targets?.[memoryKey] : null;
  const isLibrary = section === 'files' || !!directory;

  if (directory && !safeWorkspacePath(directory) || selectedPath && !safeWorkspacePath(selectedPath)) return <View style={s.panel}><BackLabel title="文件夹" onPress={() => open({memorySection: 'files'})}/><Problem message="文件路径不正确，请返回文件夹重新选择。"/></View>;
  if (selectedPath) return <Entrance transitionKey={selectedPath} style={s.panel}>
    <BackLabel title="文件夹" onPress={() => open({memorySection: 'files', memoryPath: directory})}/>
    <WorkspaceFileView key={selectedPath} connection={connection} api={api} path={selectedPath} onChat={onChat} onOpen={path => open({memorySection: 'files', memoryFile: path, memoryPath: path.split('/').slice(0, -1).join('/')})}/>
  </Entrance>;
  if (memoryKey) return <Entrance transitionKey={memoryKey} style={s.panel}>
    <BackLabel title="记忆" onPress={() => open({})}/><View style={s.heading}><Text style={s.title}>{memoryKey === 'user' ? '关于你' : '长期记忆'}</Text><TactilePressable accessibilityLabel="刷新当前记忆" disabled={loading} onPress={refresh} style={s.circle}><RefreshCw size={20} color={c.ink}/></TactilePressable></View>
    <Text style={s.lead}>{memoryKey === 'user' ? '从日常交流里，慢慢了解你。' : '值得留住的经验，下次还用得上。'}</Text>
    {memoryLoading ? <Loading label="正在读取记忆"/> : target && data ? <MemoryEditor key={memoryKey} connection={connection} target={memoryKey} data={data} onChanged={setData} onRefresh={refresh}/> : <Problem message={memoryError || data?.message || '暂时无法读取记忆。'} retry={refresh}/>}
  </Entrance>;
  if (isLibrary) return <WorkspaceBrowser key={(directory || 'files') + '|' + value(params.memoryQuery)} connection={connection} api={api} directory={directory} initialQuery={value(params.memoryQuery).slice(0, 120)} open={open} onChat={onChat}/>;

  const about = memoryCollection(data, 'user', memoryLoading), learned = memoryCollection(data, 'memory', memoryLoading);
  const readAt = memoryObservationLabel(data);
  return <View style={s.panel}>
    <View style={s.heading}><Text style={s.title}>记忆</Text><TactilePressable accessibilityLabel="刷新记忆" disabled={loading} onPress={refresh} style={s.circle}>{loading ? <ActivityIndicator color={c.muted}/> : <RefreshCw size={21} color={c.ink}/>}</TactilePressable></View>
    <View style={s.introCard}><Text style={s.cardTitle}>越了解你，越能帮到你。</Text><View style={s.introRows}>
      <HubRow title="带上你的资料" detail="文件、笔记和一起完成的结果" icon={<FileText size={24} color={c.ink}/>} onPress={onFiles}/>
      {onSources ? <HubRow title="对话引用范围" detail="选择哪些历史对话不再作为后续回答来源" icon={<ShieldCheck size={24} color={c.ink}/>} onPress={onSources}/> : null}
      <HubRow title="连接常用应用" detail="让安排和信息连起来" icon={<Link2 size={24} color={c.ink}/>} onPress={onConnect}/>
      <HubRow title="聊聊你的近况" detail="习惯、偏好，或最近在忙的事" icon={<MessageCircle size={24} color={c.ink}/>} onPress={() => onChat()} last/>
    </View></View>
    {memoryLoading ? <Loading label="正在整理记忆"/> : about.state === 'unavailable' ? <Problem message={memoryError || data?.message || '暂时无法读取记忆。'} retry={refresh}/> : <TactilePressable onPress={() => open({memorySection: 'user'})} accessibilityLabel="查看关于你的记忆" style={s.profileCard}>
      <BookOpen size={24} color={c.accent}/><Text style={s.cardTitle}>关于你</Text>
      {readAt ? <Text style={s.detail}>{readAt}</Text> : null}
      <Text numberOfLines={5} style={s.profileText}>{about.entries?.length ? about.entries.join('\n\n') : '你的习惯和偏好，会在一次次交流中慢慢清晰。'}</Text>
      <View style={s.inline}><Text style={s.link}>查看记忆</Text><ChevronRight size={16} color={c.accent}/></View>
    </TactilePressable>}
    <SectionLabel>全部</SectionLabel>
    <View style={s.grid}>
      <FolderTile title="关于你" subtitle={about.countLabel} onPress={() => open({memorySection: 'user'})}/>
      <FolderTile title="长期记忆" subtitle={learned.countLabel} onPress={() => open({memorySection: 'memory'})}/>
      <FolderTile title="文件夹" subtitle={workspace ? `${workspace.files.length}${workspace.truncated ? '+' : ''} 份文件` : loading ? '正在读取' : '稍后重试'} onPress={() => open({memorySection: 'files'})}/>
    </View>
    {filesError ? <Problem message={filesError} retry={refresh}/> : null}
  </View>;
}

function WorkspaceFileView({connection, api, path, onChat, onOpen}: {connection: Connection; api: PersonalHubApi; path: string; onChat: (draft?: string) => void; onOpen: (path: string) => void}) {
  const [file, setFile] = useState<WorkspaceFile | null>(null), [error, setError] = useState(''), [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let live = true;
    const cancel = new AbortController();
    void api.workspaceMetadata(path, cancel.signal).then(next => {if (live) setFile(next);}).catch(cause => {if (live) setError(issue(cause));});
    return () => {live = false; cancel.abort();};
  }, [api, path, attempt]);
  return file ? <FileReader connection={connection} api={api} file={file} onChat={onChat} onOpen={onOpen} onSaved={() => setAttempt(x => x + 1)}/> : error ? <Problem message={error} retry={() => {setError(''); setAttempt(x => x + 1);}}/> : <Loading label="正在读取文件"/>;
}

function WorkspaceBrowser({connection, api, directory, initialQuery = '', open, onChat}: {
  connection: Connection; api: PersonalHubApi; directory: string; initialQuery?: string;
  open: (next: {memoryPath?: string; memoryFile?: string; memorySection?: string}) => void; onChat: (draft?: string) => void;
}) {
  const {colors: c} = useAppTheme(), s = useThemedStyles(makeStyles);
  const [query, setQuery] = useState(initialQuery), [search, setSearch] = useState(initialQuery.trim()), [attempt, setAttempt] = useState(0);
  const [page, setPage] = useState<WorkspacePage | null>(null), [error, setError] = useState(''), [loading, setLoading] = useState(true);
  const generation = useRef(0), busy = useRef(false), moreAbort = useRef<AbortController | null>(null);
  useEffect(() => {
    const timer = setTimeout(() => {if (query.trim() !== search) {setPage(null); setError(''); setLoading(true); setSearch(query.trim());}}, 350);
    return () => clearTimeout(timer);
  }, [query, search]);
  useEffect(() => {
    const current = ++generation.current, cancel = new AbortController();
    busy.current = true;
    moreAbort.current?.abort();
    void api.workspacePage({directory, query: search}, cancel.signal).then(result => {if (current === generation.current) setPage(result);})
      .catch(cause => {if (current === generation.current) setError(issue(cause));})
      .finally(() => {if (current === generation.current) {busy.current = false; setLoading(false);}});
    return () => {generation.current = current + 1; cancel.abort(); moreAbort.current?.abort();};
  }, [api, directory, search, attempt]);
  const refresh = () => {setPage(null); setError(''); setLoading(true); setAttempt(x => x + 1);};
  const submitSearch = () => {if (query.trim() !== search) {setPage(null); setError(''); setLoading(true); setSearch(query.trim());}};
  const more = async () => {
    if (!page?.next_cursor || busy.current || query.trim() !== search) return;
    const current = generation.current, cancel = new AbortController();
    moreAbort.current = cancel; busy.current = true; setLoading(true); setError('');
    try {
      const next = await api.workspacePage({directory, query: search, cursor: page.next_cursor}, cancel.signal);
      if (current === generation.current) setPage(mergeWorkspacePages(page, next));
    } catch (cause) {
      if (current === generation.current) {
        setError(issue(cause));
        if (cause instanceof Error && 'status' in cause && (cause.status === 409 || cause.status === 422)) setPage(null);
      }
    } finally {if (current === generation.current) {busy.current = false; setLoading(false);}}
  };
  const waiting = query.trim() !== search;
  const entries = workspaceSearch(page?.files || [], directory, search);
  return <Entrance transitionKey={directory || 'files'} style={s.panel}>
    <BackLabel title={directory ? '上一级' : '记忆'} onPress={() => open(directory ? {memorySection: 'files', memoryPath: directory.split('/').slice(0, -1).join('/')} : {})}/>
    <Text style={s.title}>{directory ? directory.split('/').pop() : '文件夹'}</Text>
    <Text style={s.lead}>{directory || '当前身份的真实文件，打开就能读。'}</Text>
    <WorkspaceImportButton connection={connection} onImported={file => open({memorySection: 'files', memoryFile: file.path, memoryPath: file.path.split('/').slice(0, -1).join('/')})}/>
    <View style={s.search}><Search size={18} color={c.muted}/><TextInput accessibilityLabel="搜索当前文件夹及子文件夹" placeholder="搜索文件名" placeholderTextColor={c.muted} value={query} maxLength={200} onChangeText={setQuery} onSubmitEditing={submitSearch} style={s.searchInput} returnKeyType="search" clearButtonMode="while-editing"/></View>
    {waiting || loading && !page ? <Loading label={query ? '正在查找文件' : '正在读取文件夹'}/> : <>
      {entries.length ? <View style={s.grid}>{entries.map(entry => <FolderTile key={entry.path} title={entry.name} subtitle={entry.kind === 'folder' ? `${entry.count}${page?.truncated ? '+' : ''} 份文件` : fileSize(entry.file!.size)} isFile={entry.kind === 'file'} onPress={() => open(entry.kind === 'folder' ? {memorySection: 'files', memoryPath: entry.path} : {memorySection: 'files', memoryPath: directory, memoryFile: entry.path})}/>)}</View> : page?.complete ? <View style={s.paper}><Folder size={30} color={c.muted}/><Text style={s.cardTitle}>{search ? '没有找到匹配的文件' : '这里还没有文件'}</Text><Text style={s.lead}>{search ? '试试其他文件名。' : '交给我整理的资料和生成的文件，会留在这里。'}</Text></View> : page ? <Text style={s.lead}>已检查的文件里还没有匹配项，可以继续查找。</Text> : null}
      {page ? <Text accessibilityLiveRegion="polite" style={s.detail}>{workspaceProgress(page)}</Text> : null}
      {error ? <Problem message={error} retry={page?.next_cursor ? () => void more() : refresh}/> : null}
      {page?.next_cursor ? <TactilePressable disabled={loading} accessibilityLabel={search ? '继续查找更多文件' : '加载更多文件'} onPress={() => void more()} style={s.smallButton}>{loading ? <ActivityIndicator color={c.ink}/> : <RefreshCw size={17} color={c.ink}/>}<Text style={s.backLabel}>{loading ? '正在读取…' : search ? '继续查找' : '加载更多'}</Text></TactilePressable> : null}
    </>}
    <View style={s.group}><HubRow title="重新读取文件列表" icon={<RefreshCw size={23} color={c.ink}/>} onPress={refresh}/><HubRow title="按内容查找文件" detail="让 Pajio 阅读资料后帮你找" icon={<Search size={23} color={c.ink}/>} onPress={() => onChat(`请在当前身份的文件空间里查找${query.trim() ? '与「' + query.trim() + '」相关的文件' : '这份文件'}：\n`)} last/></View>
  </Entrance>;
}

function fileSize(size: number) {return size < 1024 ? size + ' B' : size < 1048576 ? Math.ceil(size / 1024) + ' KB' : (size / 1048576).toFixed(1) + ' MB';}
function FolderTile({title, subtitle, isFile, onPress}: {title: string; subtitle: string; isFile?: boolean; onPress: () => void}) {
  const {colors: c} = useAppTheme();
  const s = useThemedStyles(makeStyles);

  return <TactilePressable accessibilityLabel={`${title}，${subtitle}`} onPress={onPress} style={s.folderTile}><View style={s.folderGlyph}>{isFile ? <FileText size={33} color={c.accent} strokeWidth={1.5}/> : <Folder size={36} color={c.accent} fill={c.soft} strokeWidth={1.3}/>}</View><Text numberOfLines={2} style={s.folderTitle}>{title}</Text><Text style={s.detail}>{subtitle}</Text></TactilePressable>;
}
function FileReader({connection, api, file, onChat, onOpen, onSaved}: {connection: Connection; api: PersonalHubApi; file: WorkspaceFile; onChat: (draft?: string) => void; onOpen: (path: string) => void; onSaved: () => void}) {
  const {colors: c} = useAppTheme();
  const s = useThemedStyles(makeStyles);
  const live = useRef(true), exportBusy = useRef(false);
  const [text, setText] = useState(''), [error, setError] = useState(''), [loading, setLoading] = useState(true), [generation, setGeneration] = useState(0);
  const [sharing, setSharing] = useState(false), [shareError, setShareError] = useState('');
  const [editing, setEditing] = useState(false);
  const allowed = textPreviewAllowed(file);
  useEffect(() => {live.current = true; return () => {live.current = false;};}, []);
  useEffect(() => {let current = true;
    if (!allowed) return;
    api.textFile(file).then(contents => {if (current) setText(contents);}).catch(cause => {if (current) setError(issue(cause));}).finally(() => {if (current) setLoading(false);});
    return () => {current = false;};
  }, [api, file, allowed, generation]);
  const share = async () => {
    if (exportBusy.current) return;
    exportBusy.current = true; setSharing(true); setShareError('');
    try {await shareWorkspaceFile(api, file, () => live.current);}
    catch (cause) {if (live.current) setShareError(issue(cause));}
    finally {exportBusy.current = false; if (live.current) setSharing(false);}
  };
  return <><Text style={s.title}>{file.path.split('/').pop()}</Text><Text style={s.detail}>{file.path} · {fileSize(file.size)}</Text>
    {editing ? <WorkspaceTextEditor connection={connection} path={file.path} onClose={() => setEditing(false)} onSaved={onSaved} onOpen={onOpen}/> : editableDocument(file.path, file.size) ? <HubRow title={file.path.startsWith('imports/') ? '编辑可用副本' : '编辑这份文档'} detail={file.path.startsWith('imports/') ? '保留导入原件，修改后另存文本文档' : '保留本机草稿，核对版本后写回'} icon={<FileText size={22} color={c.ink}/>} onPress={() => setEditing(true)} last/> : null}
    {!allowed ? <View style={s.paper}><FileText size={34} color={c.muted}/><Text style={s.cardTitle}>打开原件查看</Text><Text style={s.lead}>照片、PDF 和其他文档可保存到文件，或用手机上的应用打开。</Text></View> : loading ? <Loading label="正在打开"/> : error ? <Problem message={error} retry={() => {setLoading(true); setText(''); setError(''); setGeneration(current => current + 1);}}/> : <View style={s.paper}><Text selectable style={s.body}>{text || '这份文件暂时没有内容。'}</Text></View>}
    {file.size <= WORKSPACE_ORIGINAL_LIMIT ? <TactilePressable disabled={sharing} onPress={() => {void share();}} accessibilityLabel="打开或分享原件" style={s.shareButton}>{sharing ? <ActivityIndicator color={c.ink}/> : <Share2 size={20} color={c.ink}/>}<Text style={s.rowTitle}>{sharing ? '正在准备原件…' : '打开或分享原件'}</Text></TactilePressable> : <Text style={s.detail}>原件超过 20 MB，请在电脑上打开。</Text>}
    {shareError ? <Problem message={shareError} retry={() => {void share();}}/> : null}
    <HubRow title="让 Pajio 读这份文件" detail="把文件路径带到对话，再补充你的要求" icon={<MessageCircle size={22} color={c.ink}/>} onPress={() => onChat(workspaceFileDraft(file.path))} last/>
  </>;
}

export type SettingsHubProps = {connection: Connection | null; identity: string; connected: boolean; wardrobe: WardrobeController; personal?: boolean; onConnection: () => void; onFiles: () => void; onNative: () => void; onChat: (text: string) => void; onAccountDeletion?: () => void; onOnboarding?: () => void; onBookmarks?: () => void; onSync?: () => void; pendingCount?: number; syncing?: boolean};
export function SettingsHub(props: SettingsHubProps) {return <SettingsHubContent key={(props.connection ? scopeOf(props.connection) : 'disconnected') + '|' + props.connected} {...props}/>;}
function SettingsHubContent({connection, identity, connected, wardrobe, personal, onConnection, onFiles, onNative, onAccountDeletion, onOnboarding, onBookmarks, onSync, pendingCount = 0, syncing = false}: SettingsHubProps) {
  const {colors: c} = useAppTheme();
  const s = useThemedStyles(makeStyles);

  const {hubSection} = useLocalSearchParams<{hubSection?: string}>();
  const section = value(hubSection);
  const api = useMemo(() => connection ? new PersonalHubApi(connection, serviceFetch) : null, [connection]);
  const [runtime, setRuntime] = useState<HubRuntime | null>(null), [loading, setLoading] = useState(!!api && connected), [error, setError] = useState(''), [generation, setGeneration] = useState(0);
  useEffect(() => {let live = true;
    if (!api || !connected) return;
    api.runtime().then(engine=>{if(live)setRuntime(engine);}).catch(()=>{if(live)setError('连接状态暂时无法读取。');}).finally(()=>{if(live)setLoading(false);}); return () => {live = false;};
  }, [api, connected, generation]);
  const refresh = () => {setRuntime(null); setError(''); setLoading(!!api && connected); setGeneration(current => current + 1);};
  const open = (hubSection: string) => router.setParams({hubSection});
  const heading: Record<string, string> = {apps: '连接应用', devices: '设备', skills: '技能', messaging: '聊天工具', notifications:'通知', usage:'用量与试用额度', data:'带走我的数据', diagnostics:'连接与运行诊断'};
  const ready = (enabled?: boolean) => loading ? '读取中' : enabled === true ? '已接入' : enabled === false ? '未接入' : '未读取';
  if (section === 'wardrobe') return <Wardrobe key={wardrobe.session.scope} wardrobe={wardrobe} onBack={() => open('appearance')}/>;
  if (section === 'appearance') return <Entrance transitionKey="appearance" style={s.panel}>
    <BackLabel title={personal ? '我的' : '设置'} onPress={() => open('')}/>
    <Text style={s.title}>外观与个性化</Text>
    <AppearancePanel/>
    <WardrobeEntry wardrobe={wardrobe} onPress={() => open('wardrobe')}/>
  </Entrance>;
  if (heading[section]) return <Entrance transitionKey={section} style={s.panel}>
    <BackLabel title={personal ? '我的' : '设置'} onPress={() => open('')}/><Text style={s.title}>{heading[section]}</Text>
    {error ? <Problem message={error} retry={refresh}/> : null}
    {section === 'apps' ? <>
      <Text style={s.lead}>把信息带进来，让交代的事有着落。</Text>
      <SectionLabel>当前连接</SectionLabel><View style={s.group}>
        <HubRow title="文件空间" detail="查看你交给我的资料和生成的结果" icon={<Folder size={24} color={c.ink}/>} status={runtime ? runtime.files ? '已启用' : '未启用' : ready()} onPress={onFiles}/>
      </View>{connection?<NativeCloudAppsPanel connection={connection} fetcher={serviceFetch}/>:<Problem message="登录后即可管理云端应用。"/>}<SectionLabel>这台手机</SectionLabel><View style={s.group}>
        <HubRow title="照片" detail="由你选择本次分享的照片" icon={<Camera size={24} color={c.ink}/>} onPress={onNative}/>
        <HubRow title="系统日历" detail="查看权限与本机的日程安排" icon={<CalendarDays size={24} color={c.ink}/>} onPress={onNative}/>
        <HubRow title="位置" detail="需要时，再分享你的位置" icon={<MapPin size={24} color={c.ink}/>} onPress={onNative} last/>
      </View>
    </> : null}
    {section === 'notifications' ? connection ? <NativeNotificationsPanel connection={connection}/> : <Problem message="登录后即可设置通知。"/> : null}
    {section === 'usage' ? connection ? <UsagePanel connection={connection} fetcher={serviceFetch}/> : <Problem message="登录后即可查看用量。"/> : null}
    {section === 'data' ? connection ? <NativeDataPanel connection={connection} fetcher={serviceFetch} pendingCount={pendingCount} onSync={onSync} onFiles={onFiles}/> : <Problem message="登录后即可导出已保存的数据。"/> : null}
    {section === 'diagnostics' ? connection ? <NativeDiagnosticsPanel connection={connection} fetcher={serviceFetch} onDevices={()=>open('devices')} onReconnect={onConnection}/> : <Problem message="添加连接后即可查看诊断。"/> : null}
    {section === 'devices' ? connection ? <NativeDevicePanel connection={connection}/> : <Problem message="连接后即可管理设备。"/> : null}
    {section === 'skills' ? connection ? <SkillsPanel connection={connection} fetcher={serviceFetch}/> : <Problem message="连接后即可管理技能。"/> : null}
    {section === 'messaging' ? connection ? <MessagingPanel connection={connection} fetcher={serviceFetch}/> : <Problem message="连接后即可管理聊天工具。"/> : null}
  </Entrance>;

  return <View style={s.panel}>
    <Text style={s.title}>{personal ? '我的' : '设置'}</Text>
    <View style={s.accountSummary}>
      <View style={s.accountTop}><BrandWordmark width={76} color={c.ink}/><BrandStar size={22} color={c.ink}/></View>
      <View style={s.accountIdentity}><Text numberOfLines={1} style={s.memberName}>{identity}</Text><Text style={s.accountKind}>{connection?.development ? '开发预览' : '个人空间'}</Text></View>
      <View style={s.serviceLine}><View style={s.connectionState}><View style={[s.connectionDot, connected && s.connectionDotOn]}/><Text style={s.serviceText}>{connected ? '已连接' : '未连接'}</Text></View><Text style={s.modelValue}>模型服务 · {runtime?.provider || (loading ? '读取中' : !connected ? '连接后查看' : runtime ? '尚未确认' : '暂时无法读取')}</Text></View>
    </View>
    <SectionLabel>能力与连接</SectionLabel><View style={s.group}>
      <HubRow title="连接应用" detail="带上你的资料、安排和常用服务" icon={<Link2 size={24} color={c.ink}/>} onPress={() => open('apps')}/>
      <HubRow title="本机能力" detail="照片、系统日历与位置" icon={<Smartphone size={24} color={c.ink}/>} onPress={onNative}/>
      <HubRow title="设备" detail="手机、电脑与执行设备" icon={<Monitor size={24} color={c.ink}/>} onPress={() => open('devices')}/>
      <HubRow title="技能" detail="查看可用能力与方法" icon={<Layers size={24} color={c.ink}/>} onPress={() => open('skills')}/>
      <HubRow title="聊天工具" detail="连接常用的沟通入口" icon={<MessageCircle size={24} color={c.ink}/>} onPress={() => open('messaging')} last/>
    </View>
    <SectionLabel>数据与身份</SectionLabel><View style={s.group}>
      <HubRow title="账户与身份" detail="管理登录状态与当前身份" icon={<Layers size={24} color={c.ink}/>} onPress={onConnection}/>
      {onBookmarks ? <HubRow title="收藏链接" detail="保存网页、备注，需要时再打开" icon={<Link2 size={24} color={c.ink}/>} onPress={onBookmarks}/> : null}
      <HubRow title="资料与文件" detail="原件和完成的结果，都留在这里" icon={<BookOpen size={24} color={c.ink}/>} onPress={onFiles} last={!onSync}/>{onSync ? <HubRow title="同步记录" detail={syncing ? '正在同步本机记录…' : pendingCount > 0 ? `${pendingCount} 条本机记录待同步，点按重试` : '本机没有等待同步的记录，点按检查'} icon={<RefreshCw size={24} color={c.ink}/>} onPress={syncing ? undefined : onSync} status={syncing ? '同步中' : pendingCount > 0 ? '待同步' : undefined} last/> : null}
    </View>
    <HubRow title="用量与试用额度" detail="已使用的模型与语音服务" icon={<Layers size={24} color={c.ink}/>} onPress={()=>open('usage')}/>
    <HubRow title="带走我的数据" detail="导出当前身份的记录、记忆和原件" icon={<Share2 size={24} color={c.ink}/>} onPress={()=>open('data')}/>
    {onAccountDeletion ? <HubRow title="注销账户" detail="核对清理范围、验证身份与查看处理进度" icon={<ShieldCheck size={24} color={c.ink}/>} onPress={onAccountDeletion}/> : null}
    <HubRow title="连接与运行诊断" detail="查看状态或分享不含正文的故障报告" icon={<ShieldCheck size={24} color={c.ink}/>} onPress={()=>open('diagnostics')}/>
    <SectionLabel>偏好设置</SectionLabel><View style={s.group}>
      {onOnboarding ? <HubRow title="初始偏好" detail="日常角色、常用应用与回答方式" icon={<SlidersHorizontal size={24} color={c.ink}/>} onPress={onOnboarding}/> : null}
      <HubRow title="通知" detail="任务结果与待确认事项" icon={<MessageCircle size={24} color={c.ink}/>} onPress={()=>open('notifications')}/>
      <HubRow title="外观与个性化" detail="显示模式与睡衣衣橱" icon={<SlidersHorizontal size={24} color={c.ink}/>} onPress={() => open('appearance')} last/>
    </View>
    <View style={s.privacy}><ShieldCheck size={15} color={c.muted}/><Text style={s.footnote}>由你选择分享什么，重要操作由你确认。</Text></View>
    {error ? <Problem message={error} retry={refresh}/> : null}
  </View>;
}

const makeStyles = (c: AppColors) => StyleSheet.create({
  search: {flexDirection: 'row', alignItems: 'center', gap: 10, paddingHorizontal: 14, borderRadius: 16, borderWidth: 1, borderColor: c.line, backgroundColor: c.surface}, searchInput: {flex: 1, minHeight: 48, color: c.ink, fontSize: 16},
  shareButton: {minHeight: 52, paddingHorizontal: 18, borderRadius: 16, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 10, backgroundColor: c.soft},
  panel: {gap: 16, paddingBottom: 20}, heading: {flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4},
  title: {fontSize: 34, lineHeight: 44, fontWeight: '500', letterSpacing: -.7, color: c.ink, flexShrink: 1}, lead: {fontSize: 15, lineHeight: 25, color: c.muted},
  cardTitle: {fontSize: 19, lineHeight: 28, color: c.ink, fontWeight: '500'}, detail: {fontSize: 12, lineHeight: 19, color: c.muted},
  circle: {width: 44, height: 44, borderRadius: 22, backgroundColor: c.surface, borderColor: c.line, borderWidth: 1, alignItems: 'center', justifyContent: 'center'},
  introCard: {backgroundColor: c.soft, borderRadius: 20, borderWidth: 1, borderColor: c.line, padding: 18, gap: 16},
  introRows: {borderRadius: 16, backgroundColor: c.surface, paddingHorizontal: 13},
  row: {minHeight: 68, paddingVertical: 13, flexDirection: 'row', alignItems: 'center', gap: 11}, rowDivider: {borderBottomColor: c.line, borderBottomWidth: StyleSheet.hairlineWidth},
  rowIcon: {width: 30, alignItems: 'center'}, rowWords: {flex: 1, gap: 4}, rowTitle: {fontSize: 16, lineHeight: 23, color: c.ink, fontWeight: '500'},
  status: {fontSize: 11, lineHeight: 18, color: c.muted, maxWidth: 58, textAlign: 'right'},
  profileCard: {padding: 22, borderRadius: 20, backgroundColor: c.surface, borderWidth: 1, borderColor: c.line, gap: 12},
  profileText: {fontSize: 15, lineHeight: 25, color: c.muted, marginTop: 2}, inline: {flexDirection: 'row', alignItems: 'center', gap: 4}, link: {color: c.accent, fontSize: 14, lineHeight: 23},
  sectionLabel: {fontSize: 16, lineHeight: 25, color: c.ink, fontWeight: '500', marginTop: 12, marginLeft: 5},
  grid: {flexDirection: 'row', flexWrap: 'wrap', gap: 10}, folderTile: {flexBasis: '48%', flexGrow: 1, maxWidth: '49%', minHeight: 153, padding: 18, borderRadius: 18, backgroundColor: c.surface, borderWidth: 1, borderColor: c.line, gap: 5},
  folderGlyph: {height: 47, justifyContent: 'center', marginBottom: 5}, folderTitle: {fontSize: 16, lineHeight: 23, color: c.ink, fontWeight: '500'},
  group: {paddingHorizontal: 18, borderRadius: 18, backgroundColor: c.surface, borderWidth: 1, borderColor: c.line},
  paper: {padding: 22, borderRadius: 18, backgroundColor: c.surface, borderWidth: 1, borderColor: c.line, gap: 15}, body: {fontSize: 16, lineHeight: 28, color: c.ink}, entryDivider: {paddingTop: 18, borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: c.line},
  back: {flexDirection: 'row', alignItems: 'center', alignSelf: 'flex-start', gap: 4, minHeight: 44}, backLabel: {fontSize: 14, lineHeight: 21, color: c.ink},
  loading: {paddingVertical: 28, gap: 10, alignItems: 'center'}, problem: {padding: 18, borderRadius: 22, backgroundColor: c.surface, gap: 10}, smallButton: {flexDirection: 'row', alignItems: 'center', alignSelf: 'flex-start', minHeight: 44, gap: 7},
  accountSummary: {minHeight: 128, padding: 18, borderRadius: 18, backgroundColor: c.surface, borderWidth: StyleSheet.hairlineWidth, borderColor: c.line, gap: 13},
  accountTop: {flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center'}, wordmark: {fontSize: 17, lineHeight: 23, fontWeight: '600', color: c.ink, letterSpacing: -.4},
  accountIdentity: {flexDirection: 'row', alignItems: 'baseline', gap: 10}, memberName: {fontSize: 22, lineHeight: 28, fontWeight: '500', color: c.ink, flexShrink: 1}, accountKind: {fontSize: 12, lineHeight: 19, color: c.muted},
  serviceLine: {flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between', gap: 8}, connectionState: {flexDirection: 'row', alignItems: 'center', gap: 6}, serviceText: {fontSize: 12, lineHeight: 20, color: c.muted},
  connectionDot: {width: 6, height: 6, borderRadius: 3, backgroundColor: c.muted}, connectionDotOn: {backgroundColor: c.success}, modelValue: {color: c.muted, fontSize: 12, lineHeight: 20, flexShrink: 1},
  footnote: {fontSize: 11, lineHeight: 19, color: c.muted}, privacy: {flexDirection: 'row', gap: 6, justifyContent: 'center', alignItems: 'center', marginTop: 5},
});
