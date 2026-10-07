import {AppearancePanel} from './AppearancePanel';
import {useAppTheme, useThemedStyles, type AppColors} from './app-theme';
import React, {ReactNode, useEffect, useMemo, useState} from 'react';
import {ActivityIndicator, Platform, StyleSheet, Text, View} from 'react-native';
import {router, useLocalSearchParams} from 'expo-router';
import {BookOpen, CalendarDays, Camera, ChevronLeft, ChevronRight, Cloud, FileText, Folder, Layers, Link2, MapPin, MessageCircle, Monitor, RefreshCw, ShieldCheck, Smartphone, Sparkles, WandSparkles} from 'lucide-react-native';
import Svg, {Circle, Defs, LinearGradient, Rect, Stop} from 'react-native-svg';
import {Connection, MemorySnapshot, scopeOf, WearingApi} from './core';
import {Entrance, TactilePressable} from './experience/primitives';
import {deviceCollectionState, HubIdentity, HubRuntime, memoryCollection, memoryObservationLabel, PersonalHubApi, textPreviewAllowed, WorkspaceFile, WorkspaceSnapshot, workspaceEntries} from './personal-hub';
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

export type MemoryLibraryProps = {connection: Connection; onFiles: () => void; onChat: () => void; onConnect: () => void};
/** The entries and file tree below are live data belonging to this connection's identity. */
export function MemoryLibrary(props: MemoryLibraryProps) {return <MemoryLibraryContent key={scopeOf(props.connection)} {...props}/>;}
function MemoryLibraryContent({connection, onFiles, onChat, onConnect}: MemoryLibraryProps) {
  const {colors: c} = useAppTheme();
  const s = useThemedStyles(makeStyles);

  const api = useMemo(() => new PersonalHubApi(connection, serviceFetch), [connection]);
  const memoryApi = useMemo(() => new WearingApi(connection, serviceFetch), [connection]);
  const params = useLocalSearchParams<{memoryPath?: string; memoryFile?: string; memorySection?: string}>();
  const directory = value(params.memoryPath), selectedPath = value(params.memoryFile), section = value(params.memorySection);
  const [data, setData] = useState<MemorySnapshot | null>(null), [workspace, setWorkspace] = useState<WorkspaceSnapshot | null>(null);
  const [memoryError, setMemoryError] = useState(''), [filesError, setFilesError] = useState(''), [loading, setLoading] = useState(true), [generation, setGeneration] = useState(0);
  useEffect(() => {
    let live = true;
    Promise.allSettled([memoryApi.memory(), api.workspace()]).then(([memory, files]) => {
      if (!live) return;
      if (memory.status === 'fulfilled') setData(memory.value); else setMemoryError(issue(memory.reason));
      if (files.status === 'fulfilled') setWorkspace(files.value); else setFilesError(issue(files.reason));
      setLoading(false);
    });
    return () => {live = false;};
  }, [api, memoryApi, generation]);
  const refresh = () => {setLoading(true); setData(null); setWorkspace(null); setMemoryError(''); setFilesError(''); setGeneration(current => current + 1);};
  const open = (next: {memoryPath?: string; memoryFile?: string; memorySection?: string}) => router.setParams({memoryPath: '', memoryFile: '', memorySection: '', ...next});
  const selectedFile = workspace?.files.find(file => file.path === selectedPath);
  const entries = workspaceEntries(workspace?.files || [], directory);
  const memoryKey = section === 'user' || section === 'memory' ? section : null;
  const target = memoryKey && data?.available ? data.targets?.[memoryKey] : null;
  const isLibrary = section === 'files' || !!directory;

  if (selectedPath) return <Entrance transitionKey={selectedPath} style={s.panel}>
    <BackLabel title="文件夹" onPress={() => open({memorySection: 'files', memoryPath: directory})}/>
    {loading ? <Loading label="正在读取文件"/> : selectedFile ? <FileReader key={selectedPath} api={api} file={selectedFile} onFiles={onFiles}/> : <Problem message={filesError || (workspace?.truncated ? '当前列表未包含这份文件，请到文件页查看。' : workspace ? '这份文件已经移动或不存在。' : '暂时无法读取文件列表。')} retry={refresh}/>}
  </Entrance>;
  if (memoryKey) return <Entrance transitionKey={memoryKey} style={s.panel}>
    <BackLabel title="记忆" onPress={() => open({})}/><Text style={s.title}>{memoryKey === 'user' ? '关于你' : '长期记忆'}</Text>
    <Text style={s.lead}>{memoryKey === 'user' ? '从日常交流里，慢慢了解你。' : '值得留住的经验，下次还用得上。'}</Text>
    {loading ? <Loading label="正在读取记忆"/> : target ? <View style={s.paper}>{!target.enabled ? <Text style={s.detail}>这部分记忆已暂停更新。</Text> : null}{target.entries.length ? target.entries.map((entry, index) => <Text key={index} selectable style={[s.body, index > 0 && s.entryDivider]}>{entry}</Text>) : <Text style={s.body}>这里还没有记下内容。</Text>}</View> : <Problem message={memoryError || data?.message || '暂时无法读取记忆。'} retry={refresh}/>}
    <HubRow title="补充或纠正记忆" detail="直接告诉我哪里需要修改" icon={<MessageCircle size={23} color={c.ink}/>} onPress={onChat} last/>
  </Entrance>;
  if (isLibrary) return <Entrance transitionKey={directory || 'files'} style={s.panel}>
    <BackLabel title={directory ? '上一级' : '记忆'} onPress={() => open(directory ? {memorySection: 'files', memoryPath: directory.split('/').slice(0, -1).join('/')} : {})}/>
    <Text style={s.title}>{directory ? directory.split('/').pop() : '文件夹'}</Text>
    <Text style={s.lead}>{directory || '当前身份的真实文件，打开就能读。'}</Text>
    {loading ? <Loading label="正在读取文件夹"/> : filesError || !workspace ? <Problem message={filesError || '暂时无法读取文件列表。'} retry={refresh}/> : entries.length ? <View style={s.grid}>{entries.map(entry => <FolderTile key={entry.path} title={entry.name} subtitle={entry.kind === 'folder' ? `${entry.count}${workspace.truncated ? '+' : ''} 份文件` : fileSize(entry.file!.size)} isFile={entry.kind === 'file'} onPress={() => open(entry.kind === 'folder' ? {memorySection: 'files', memoryPath: entry.path} : {memorySection: 'files', memoryPath: directory, memoryFile: entry.path})}/>)}</View> : workspace.truncated ? <Problem message="当前列表只包含部分文件，请到文件页查看这个文件夹。"/> : <View style={s.paper}><Folder size={30} color={c.muted}/><Text style={s.cardTitle}>这里还没有文件</Text><Text style={s.lead}>交给我整理的资料和生成的文件，会留在这里。</Text></View>}
    {workspace?.truncated ? <Text style={s.detail}>目前显示前 200 份文件，完整内容可以到文件页查看。</Text> : null}
    <HubRow title="打开文件页" icon={<Folder size={23} color={c.ink}/>} onPress={onFiles} last/>
  </Entrance>;

  const about = memoryCollection(data, 'user', loading), learned = memoryCollection(data, 'memory', loading);
  const readAt = memoryObservationLabel(data);
  return <View style={s.panel}>
    <View style={s.heading}><Text style={s.title}>记忆</Text><TactilePressable accessibilityLabel="刷新记忆" disabled={loading} onPress={refresh} style={s.circle}>{loading ? <ActivityIndicator color={c.muted}/> : <RefreshCw size={21} color={c.ink}/>}</TactilePressable></View>
    <View style={s.introCard}><Text style={s.cardTitle}>越了解你，越能帮到你。</Text><View style={s.introRows}>
      <HubRow title="带上你的资料" detail="文件、笔记和一起完成的结果" icon={<FileText size={24} color={c.ink}/>} onPress={onFiles}/>
      <HubRow title="连接常用应用" detail="让安排和信息连起来" icon={<Link2 size={24} color={c.ink}/>} onPress={onConnect}/>
      <HubRow title="聊聊你的近况" detail="习惯、偏好，或最近在忙的事" icon={<MessageCircle size={24} color={c.ink}/>} onPress={onChat} last/>
    </View></View>
    {loading ? <Loading label="正在整理记忆"/> : about.state === 'unavailable' ? <Problem message={memoryError || data?.message || '暂时无法读取记忆。'} retry={refresh}/> : <TactilePressable onPress={() => open({memorySection: 'user'})} accessibilityLabel="查看关于你的记忆" style={s.profileCard}>
      <Sparkles size={24} color={c.accent}/><Text style={s.cardTitle}>关于你</Text>
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

function fileSize(size: number) {return size < 1024 ? size + ' B' : size < 1048576 ? Math.ceil(size / 1024) + ' KB' : (size / 1048576).toFixed(1) + ' MB';}
function FolderTile({title, subtitle, isFile, onPress}: {title: string; subtitle: string; isFile?: boolean; onPress: () => void}) {
  const {colors: c} = useAppTheme();
  const s = useThemedStyles(makeStyles);

  return <TactilePressable accessibilityLabel={`${title}，${subtitle}`} onPress={onPress} style={s.folderTile}><View style={s.folderGlyph}>{isFile ? <FileText size={33} color={c.accent} strokeWidth={1.5}/> : <Folder size={36} color={c.accent} fill={c.soft} strokeWidth={1.3}/>}</View><Text numberOfLines={2} style={s.folderTitle}>{title}</Text><Text style={s.detail}>{subtitle}</Text></TactilePressable>;
}
function FileReader({api, file, onFiles}: {api: PersonalHubApi; file: WorkspaceFile; onFiles: () => void}) {
  const {colors: c} = useAppTheme();
  const s = useThemedStyles(makeStyles);

  const [text, setText] = useState(''), [error, setError] = useState(''), [loading, setLoading] = useState(true), [generation, setGeneration] = useState(0);
  const allowed = textPreviewAllowed(file);
  useEffect(() => {let live = true;
    if (!allowed) return;
    api.textFile(file).then(contents => {if (live) setText(contents);}).catch(cause => {if (live) setError(issue(cause));}).finally(() => {if (live) setLoading(false);});
    return () => {live = false;};
  }, [api, file, allowed, generation]);
  return <><Text style={s.title}>{file.path.split('/').pop()}</Text><Text style={s.detail}>{file.path} · {fileSize(file.size)}</Text>
    {!allowed ? <View style={s.paper}><FileText size={34} color={c.muted}/><Text style={s.cardTitle}>打开原文件查看</Text><Text style={s.lead}>这份文件不支持文字预览。</Text></View> : loading ? <Loading label="正在打开"/> : error ? <Problem message={error} retry={() => {setLoading(true); setText(''); setError(''); setGeneration(current => current + 1);}}/> : <View style={s.paper}><Text selectable style={s.body}>{text || '这份文件暂时没有内容。'}</Text></View>}
    <HubRow title="到文件页查看原件" icon={<FileText size={22} color={c.ink}/>} onPress={onFiles} last/>
  </>;
}

export type SettingsHubProps = {connection: Connection | null; identity: string; connected: boolean; wardrobe: WardrobeController; personal?: boolean; onConnection: () => void; onFiles: () => void; onNative: () => void};
export function SettingsHub(props: SettingsHubProps) {return <SettingsHubContent key={(props.connection ? scopeOf(props.connection) : 'disconnected') + '|' + props.connected} {...props}/>;}
function SettingsHubContent({connection, identity, connected, wardrobe, personal, onConnection, onFiles, onNative}: SettingsHubProps) {
  const {colors: c} = useAppTheme();
  const s = useThemedStyles(makeStyles);

  const {hubSection} = useLocalSearchParams<{hubSection?: string}>();
  const section = value(hubSection);
  const api = useMemo(() => connection ? new PersonalHubApi(connection, serviceFetch) : null, [connection]);
  const [runtime, setRuntime] = useState<HubRuntime | null>(null), [profile, setProfile] = useState<HubIdentity | null>(null), [loading, setLoading] = useState(!!api && connected), [error, setError] = useState(''), [generation, setGeneration] = useState(0);
  useEffect(() => {let live = true;
    if (!api || !connected) return;
    Promise.allSettled([api.runtime(), api.identity()]).then(([engine, user]) => {if (!live) return;
      if (engine.status === 'fulfilled') setRuntime(engine.value);
      if (user.status === 'fulfilled') setProfile(user.value);
      if (engine.status === 'rejected' || user.status === 'rejected') setError('部分连接状态暂时无法读取。');
      setLoading(false);
    }); return () => {live = false;};
  }, [api, connected, generation]);
  const refresh = () => {setRuntime(null); setProfile(null); setError(''); setLoading(!!api && connected); setGeneration(current => current + 1);};
  const open = (hubSection: string) => router.setParams({hubSection});
  const heading: Record<string, string> = {apps: '连接应用', devices: '设备', skills: '技能', messaging: '聊天工具'};
  const ready = (enabled?: boolean) => loading ? '读取中' : enabled === true ? '已接入' : enabled === false ? '未接入' : '未读取';
  const deviceState = deviceCollectionState(profile, loading);
  if (section === 'wardrobe') return <Wardrobe key={wardrobe.session.scope} wardrobe={wardrobe} onBack={() => open('')}/>;
  if (heading[section]) return <Entrance transitionKey={section} style={s.panel}>
    <BackLabel title="设置" onPress={() => open('')}/><Text style={s.title}>{heading[section]}</Text>
    {error ? <Problem message={error} retry={refresh}/> : null}
    {section === 'apps' ? <>
      <Text style={s.lead}>把信息带进来，让交代的事有着落。</Text>
      <SectionLabel>当前连接</SectionLabel><View style={s.group}>
        <HubRow title="文件空间" detail="查看你交给我的资料和生成的结果" icon={<Folder size={24} color={c.ink}/>} status={runtime ? runtime.files ? '已启用' : '未启用' : ready()} onPress={onFiles}/>
        <HubRow title="应用账号" detail={profile?.cloudAccountsConnected === true ? '当前身份已有应用授权' : profile?.cloudAccountsConnected === false ? '当前身份还没有接入云端应用账号' : '当前服务还未提供应用授权状态'} icon={<Cloud size={24} color={c.ink}/>} status={ready(profile?.cloudAccountsConnected ?? undefined)} last/>
      </View><SectionLabel>这台手机</SectionLabel><View style={s.group}>
        <HubRow title="照片" detail="由你选择本次分享的照片" icon={<Camera size={24} color={c.ink}/>} onPress={onNative}/>
        <HubRow title="系统日历" detail="查看权限与本机的日程安排" icon={<CalendarDays size={24} color={c.ink}/>} onPress={onNative}/>
        <HubRow title="位置" detail="需要时，再分享你的位置" icon={<MapPin size={24} color={c.ink}/>} onPress={onNative} last/>
      </View>
    </> : null}
    {section === 'devices' ? <>
      <Text style={s.lead}>你授权的设备，才会出现在这里。</Text>
      <View style={s.group}><HubRow title={Platform.OS === 'ios' ? '这台 iPhone' : Platform.OS === 'android' ? '这台手机' : '当前客户端'} detail="语音输入、查看结果与确认操作" icon={<Smartphone size={26} color={c.ink}/>} status={connected ? '已连接' : '未连接'} onPress={onConnection} last/></View>
      <SectionLabel>执行设备</SectionLabel>
      {deviceState === 'loading' ? <Loading label="正在读取设备"/> : deviceState === 'unavailable' ? <Problem message={connected ? '暂时无法读取执行设备，请重新读取。' : '连接后才能查看执行设备。'} retry={connected ? refresh : undefined}/> : deviceState === 'available' && profile ? <View style={s.group}>{profile.devices.map((device, index) => <HubRow key={device.id} title={device.name} detail={device.kind === 'computer' ? '已登记的电脑' : '已登记的手机'} icon={device.kind === 'computer' ? <Monitor size={25} color={c.ink}/> : <Smartphone size={25} color={c.ink}/>} status={device.online === true ? '在线' : device.online === false ? '离线' : '已登记'} last={index === profile.devices.length - 1}/>)}</View> : <View style={s.paper}><Monitor size={32} color={c.muted}/><Text style={s.cardTitle}>还没有执行设备</Text><Text style={s.lead}>在电脑上完成设备接入后，就可以在这里查看。</Text></View>}
      <Text style={s.footnote}>手机连接与设备操作权限分别管理。已登记不代表设备当前在线。</Text>
    </> : null}
    {section === 'skills' ? <>
      <Text style={s.lead}>完成事情的方法，也会逐步积累。</Text>{loading ? <Loading label="正在读取能力"/> : !runtime ? <Problem message={connected ? '暂时无法读取技能状态，请重新读取。' : '连接后才能查看当前身份的能力。'} retry={connected ? refresh : undefined}/> : <View style={s.paper}><WandSparkles size={32} color={c.ink}/><Text style={s.cardTitle}>{runtime.applied && runtime.running ? '技能能力已启用' : '技能能力尚未启用'}</Text><Text style={s.lead}>{runtime.applied && runtime.running ? '可以在聊天里交代要完成的事。技能目录和安装管理还没有接到手机端。' : '执行引擎启动后，再来查看当前身份的能力。'}</Text></View>}
      <HubRow title="查看已有文件" detail="技能相关的资料与交付结果" icon={<Folder size={23} color={c.ink}/>} onPress={onFiles} last/>
    </> : null}
    {section === 'messaging' ? <>
      <Text style={s.lead}>在你常用的地方继续聊。</Text><View style={s.paper}><MessageCircle size={32} color={c.ink}/><Text style={s.cardTitle}>聊天工具还未连接</Text><Text style={s.lead}>当前可以在 App 里交代事情、查看进展。外部聊天工具的授权入口还在接入中。</Text></View>
    </> : null}
  </Entrance>;

  return <View style={s.panel}>
    <Text style={s.title}>{personal ? '我的' : '设置'}</Text>
    <AppearancePanel/>
    <WardrobeEntry wardrobe={wardrobe} onPress={() => open('wardrobe')}/>
    <View style={s.membership}><View style={s.memberCard}>
      <View pointerEvents="none" style={StyleSheet.absoluteFill}><Svg width="100%" height="100%" preserveAspectRatio="none" viewBox="0 0 360 210"><Defs><LinearGradient id="personal-card" x1="0" y1="0" x2="1" y2="1"><Stop offset="0" stopColor={c.soft}/><Stop offset="0.52" stopColor={c.surface}/><Stop offset="1" stopColor={c.glow}/></LinearGradient></Defs><Rect width="360" height="210" fill="url(#personal-card)"/><Circle cx="316" cy="164" r="66" stroke={c.line} strokeWidth="1" fill="none" opacity=".72"/><Circle cx="316" cy="164" r="53" stroke={c.line} strokeWidth="1" strokeDasharray="1 7" fill="none"/><Circle cx="316" cy="164" r="10" fill={c.line}/></Svg></View>
      <View style={s.memberTop}><Text style={s.wordmark}>Wearing.</Text><Sparkles size={20} color={c.accent}/></View>
      <View style={s.memberBottom}><Text numberOfLines={1} style={s.memberName}>{identity}</Text><View style={s.planBadge}><Text style={s.planBadgeText}>{connection?.development ? '开发预览' : '个人空间'}</Text></View></View>
    </View><View style={s.memberSummary}><View><Text style={s.cardTitle}>{connection?.development ? '开发体验' : '个人空间'}</Text><Text style={s.detail}>{connected ? '已连接，继续你交代的事情。' : '连接后，带上你的记忆和安排。'}</Text></View><View style={[s.connectionDot, connected && s.connectionDotOn]}/></View>
      <View style={s.modelLine}><Text style={s.rowTitle}>模型服务</Text><Text style={s.modelValue}>{runtime?.provider || (loading ? '读取中' : !connected ? '连接后查看' : runtime ? '尚未确认' : '暂时无法读取')}</Text></View>
    </View>
    <SectionLabel>能力与连接</SectionLabel><View style={s.group}>
      <HubRow title="连接应用" detail="带上你的资料、安排和常用服务" icon={<Link2 size={24} color={c.ink}/>} onPress={() => open('apps')}/>
      <HubRow title="本机能力" detail="照片、系统日历与位置" icon={<Smartphone size={24} color={c.ink}/>} onPress={onNative}/>
      <HubRow title="设备" detail="手机、电脑与执行设备" icon={<Monitor size={24} color={c.ink}/>} onPress={() => open('devices')}/>
      <HubRow title="技能" detail="查看可用能力与方法" icon={<WandSparkles size={24} color={c.ink}/>} onPress={() => open('skills')}/>
      <HubRow title="聊天工具" detail="连接常用的沟通入口" icon={<MessageCircle size={24} color={c.ink}/>} onPress={() => open('messaging')} last/>
    </View>
    <SectionLabel>你的空间</SectionLabel><View style={s.group}>
      <HubRow title="连接与身份" detail="切换服务地址或当前身份" icon={<Layers size={24} color={c.ink}/>} onPress={onConnection}/>
      <HubRow title="资料与文件" detail="原件和完成的结果，都留在这里" icon={<BookOpen size={24} color={c.ink}/>} onPress={onFiles} last/>
    </View>
    <View style={s.privacy}><ShieldCheck size={15} color={c.muted}/><Text style={s.footnote}>由你选择分享什么，重要操作由你确认。</Text></View>
    {error ? <Problem message={error} retry={refresh}/> : null}
  </View>;
}

const makeStyles = (c: AppColors) => StyleSheet.create({
  panel: {gap: 16, paddingBottom: 20}, heading: {flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4},
  title: {fontSize: 34, lineHeight: 44, fontWeight: '500', letterSpacing: -.7, color: c.ink, flexShrink: 1}, lead: {fontSize: 15, lineHeight: 25, color: c.muted},
  cardTitle: {fontSize: 19, lineHeight: 28, color: c.ink, fontWeight: '500'}, detail: {fontSize: 12, lineHeight: 19, color: c.muted},
  circle: {width: 44, height: 44, borderRadius: 22, backgroundColor: c.surface, borderColor: c.line, borderWidth: 1, alignItems: 'center', justifyContent: 'center'},
  introCard: {backgroundColor: c.soft, borderRadius: 28, borderWidth: 1, borderColor: c.line, padding: 18, gap: 16},
  introRows: {borderRadius: 21, backgroundColor: c.surface, paddingHorizontal: 13},
  row: {minHeight: 78, paddingVertical: 15, flexDirection: 'row', alignItems: 'center', gap: 11}, rowDivider: {borderBottomColor: c.line, borderBottomWidth: StyleSheet.hairlineWidth},
  rowIcon: {width: 30, alignItems: 'center'}, rowWords: {flex: 1, gap: 4}, rowTitle: {fontSize: 16, lineHeight: 23, color: c.ink, fontWeight: '500'},
  status: {fontSize: 11, lineHeight: 18, color: c.muted, maxWidth: 58, textAlign: 'right'},
  profileCard: {padding: 22, borderRadius: 28, backgroundColor: c.surface, borderWidth: 1, borderColor: c.line, gap: 12},
  profileText: {fontSize: 15, lineHeight: 25, color: c.muted, marginTop: 2}, inline: {flexDirection: 'row', alignItems: 'center', gap: 4}, link: {color: c.accent, fontSize: 14, lineHeight: 23},
  sectionLabel: {fontSize: 16, lineHeight: 25, color: c.ink, fontWeight: '500', marginTop: 12, marginLeft: 5},
  grid: {flexDirection: 'row', flexWrap: 'wrap', gap: 10}, folderTile: {flexBasis: '48%', flexGrow: 1, maxWidth: '49%', minHeight: 153, padding: 18, borderRadius: 24, backgroundColor: c.surface, borderWidth: 1, borderColor: c.line, gap: 5},
  folderGlyph: {height: 47, justifyContent: 'center', marginBottom: 5}, folderTitle: {fontSize: 16, lineHeight: 23, color: c.ink, fontWeight: '500'},
  group: {paddingHorizontal: 18, borderRadius: 27, backgroundColor: c.surface, borderWidth: 1, borderColor: c.line},
  paper: {padding: 22, borderRadius: 27, backgroundColor: c.surface, borderWidth: 1, borderColor: c.line, gap: 15}, body: {fontSize: 16, lineHeight: 28, color: c.ink}, entryDivider: {paddingTop: 18, borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: c.line},
  back: {flexDirection: 'row', alignItems: 'center', alignSelf: 'flex-start', gap: 4, minHeight: 44}, backLabel: {fontSize: 14, lineHeight: 21, color: c.ink},
  loading: {paddingVertical: 28, gap: 10, alignItems: 'center'}, problem: {padding: 18, borderRadius: 22, backgroundColor: c.surface, gap: 10}, smallButton: {flexDirection: 'row', alignItems: 'center', alignSelf: 'flex-start', minHeight: 44, gap: 7},
  membership: {borderRadius: 28, padding: 17, backgroundColor: c.surface, borderWidth: 1, borderColor: c.line, gap: 24},
  memberCard: {minHeight: 198, padding: 20, borderRadius: 25, overflow: 'hidden', justifyContent: 'space-between', borderWidth: 1, borderColor: c.line}, memberTop: {flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center'},
  wordmark: {fontSize: 21, fontWeight: '600', color: c.ink, letterSpacing: -.7}, memberBottom: {flexDirection: 'row', alignItems: 'center', gap: 9}, memberName: {fontSize: 22, fontWeight: '500', color: c.ink, flexShrink: 1},
  planBadge: {paddingHorizontal: 10, paddingVertical: 3, borderRadius: 15, borderWidth: 1, borderColor: c.line}, planBadgeText: {fontSize: 11, color: c.muted},
  memberSummary: {flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 8}, connectionDot: {width: 7, height: 7, borderRadius: 4, backgroundColor: c.muted}, connectionDotOn: {backgroundColor: c.success},
  modelLine: {flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 12, paddingBottom: 3}, modelValue: {color: c.muted, fontSize: 14, lineHeight: 23, flexShrink: 1},
  footnote: {fontSize: 11, lineHeight: 19, color: c.muted}, privacy: {flexDirection: 'row', gap: 6, justifyContent: 'center', alignItems: 'center', marginTop: 5},
});
