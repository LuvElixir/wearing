import {useEffect, useMemo, useRef, useState} from 'react';
import {ActivityIndicator, Platform, Pressable, ScrollView, StyleSheet, Text, View} from 'react-native';
import Constants from 'expo-constants';
import * as Network from 'expo-network';
import {LifeBuoy} from 'lucide-react-native';
import {Connection} from './core';
import HealthHistoryPanel from './HealthHistoryPanel';
import {AppColors, useAppTheme, useThemedStyles} from './app-theme';
import {PrimaryButton} from './experience/primitives';
import {shareOriginalBytes} from './workspace-share';
import {DiagnosticLocal, DiagnosticReport, DiagnosticSnapshot, DiagnosticsClient, FeedbackKind, diagnosticFindings, feedbackKinds, makeDiagnosticReport, observeDiagnosticError, recentDiagnosticErrors, shareDiagnosticReport} from './diagnostics-client';

export type NativeDiagnosticsProps = {connection: Connection; fetcher?: typeof fetch; onTasks?: () => void; onDevices?: () => void; onReconnect?: () => void};

function DiagnosticsContent({connection, fetcher, onTasks, onDevices, onReconnect}: NativeDiagnosticsProps) {
  const {colors} = useAppTheme(), s = useThemedStyles(styles), api = useMemo(() => new DiagnosticsClient(connection, fetcher), [connection, fetcher]);
  const [category, setCategory] = useState<FeedbackKind>('general'), [report, setReport] = useState<DiagnosticReport | null>(null), [busy, setBusy] = useState<'load' | 'share' | null>(null), [notice, setNotice] = useState(''), [preview, setPreview] = useState(false);
  const active = useRef(true), work = useRef(false), request = useRef<AbortController | null>(null);
  useEffect(() => {active.current = true; return () => {active.current = false; request.current?.abort();};}, []);
  async function collect() {
    if (work.current) return;
    work.current = true; setBusy('load'); setNotice(''); setPreview(false);
    const controller = new AbortController(); request.current = controller;
    try {
      let network: unknown = null, server: DiagnosticSnapshot | null = null;
      let networkTimer: ReturnType<typeof setTimeout> | undefined;
      // A network interface is not proof that the service or engine is reachable.
      await Promise.all([
        Promise.race([Promise.resolve().then(() => Network.getNetworkStateAsync()).catch(() => null), new Promise<null>(resolve => {networkTimer = setTimeout(() => resolve(null), 5000);})])
          .then(value => {network = value;}).finally(() => {if (networkTimer) clearTimeout(networkTimer);}),
        api.snapshot(controller.signal).then(value => {server = value;}, error => {if (active.current) observeDiagnosticError(connection, 'diagnostics', error);}),
      ]);
      if (!active.current || controller.signal.aborted) return;
      const local: DiagnosticLocal = {app_version: Constants.expoConfig?.version, native_build: Platform.OS === 'ios' ? Constants.platform?.ios?.buildNumber : Platform.OS === 'android' ? Constants.platform?.android?.versionCode : null,
        platform: Platform.OS, os_version: Platform.Version, network};
      setReport(makeDiagnosticReport(connection, local, server, category, recentDiagnosticErrors(connection)));
      setNotice('诊断已在本机整理。可以先预览，再自行选择保存或发送给支持人员。');
    } catch {if (active.current) setNotice('这次没能整理诊断，请重试。');}
    finally {work.current = false; if (active.current) setBusy(null);}
  }
  async function share() {
    if (!report || work.current) return;
    work.current = true; setBusy('share'); setNotice('');
    try {
      const opened = await shareDiagnosticReport(report, () => active.current, bytes => shareOriginalBytes(async () => bytes, `pajio-diagnostics-${report.captured_at.slice(0, 10)}.json`, 'application/json', () => active.current));
      if (opened) setNotice('分享面板已关闭。请在目标 App 确认是否保存或发送成功；Pajio 没有自动提交反馈。');
    } catch {if (active.current) setNotice('没能打开分享面板，诊断仍保留在此页，可以重试。');}
    finally {work.current = false; if (active.current) setBusy(null);}
  }
  function select(value: FeedbackKind) {setCategory(value); setReport(current => current ? {...current, feedback: {category: value}} : null);}
  return <View style={s.panel}>
    <View style={s.line}><LifeBuoy size={24} color={colors.accent}/><Text style={s.title}>诊断与反馈</Text></View>
    <Text style={s.copy}>遇到问题时，整理一份可阅读的诊断文件。包含版本、连接类型、任务编号和状态，帮助支持人员定位。</Text>
    <View style={s.card}><Text style={s.name}>哪里遇到了问题</Text><View style={s.choices}>{(Object.keys(feedbackKinds) as FeedbackKind[]).map(key => <Pressable key={key} accessibilityRole="radio" accessibilityState={{checked: key === category, disabled: !!busy}} disabled={!!busy} onPress={() => select(key)} style={[s.choice, key === category && s.selected]}><Text style={key === category ? s.selectedText : s.copy}>{feedbackKinds[key]}</Text></Pressable>)}</View><Text style={s.copy}>不会收集对话、任务正文、文件路径、账号地址、密钥或运行日志。你可以完整预览导出内容。</Text><PrimaryButton label={report ? '重新检查并更新诊断' : '生成诊断'} disabled={!!busy} onPress={() => {void collect();}}/></View>
    {busy ? <View style={s.line}><ActivityIndicator color={colors.accent}/><Text style={s.copy}>{busy === 'load' ? '正在读取实际状态…' : '正在打开分享面板…'}</Text></View> : null}
    {report ? <View style={s.card}><Text style={s.name}>本次检查</Text><Text style={s.copy}>{new Date(report.captured_at).toLocaleString('zh-CN')} · App {report.app.manifest_version || '版本未知'}{report.app.native_build ? ` · 构建 ${report.app.native_build}` : ''}</Text>
      {diagnosticFindings(report.server).map(text => <Text key={text} style={s.copy}>{text}</Text>)}
      {report.network.connected === false ? <Text style={s.copy}>手机系统报告当前没有网络连接。</Text> : null}
      {report.server ? <Text style={s.copy}>本次包含 {report.server.tasks.items.length} 个近期任务{report.server.tasks.truncated ? '（还有更早任务未包含）' : ''}。任务状态变化时间和服务读取时间分别记录。</Text> : null}
      <PrimaryButton label={preview ? '收起完整内容' : '预览完整诊断'} tone="quiet" onPress={() => setPreview(value => !value)}/>
      {preview ? <ScrollView style={s.preview} nestedScrollEnabled><Text selectable style={s.code}>{JSON.stringify(report, null, 2)}</Text></ScrollView> : null}
      <PrimaryButton label="保存或分享诊断文件" disabled={!!busy} onPress={() => {void share();}}/>
    </View> : null}
    {notice ? <Text style={s.copy} accessibilityLiveRegion="polite">{notice}</Text> : null}
    <HealthHistoryPanel connection={connection}/>
    <View style={s.card}><Text style={s.name}>继续处理</Text>{onTasks ? <PrimaryButton label="打开任务，核对进展" tone="quiet" onPress={onTasks}/> : null}{onDevices ? <PrimaryButton label="检查执行设备" tone="quiet" onPress={onDevices}/> : null}{onReconnect ? <PrimaryButton label="检查当前连接" tone="quiet" onPress={onReconnect}/> : null}<Text style={s.copy}>检查只读取当前状态，不会重发任务或重新执行设备操作。</Text></View>
    <Text style={s.foot}>诊断是这次检查的快照，不是后台心跳。最近错误只包含本次打开 App 后已观测到的类别。分享文件可能包含可关联到任务的编号，请自行选择接收人。</Text>
  </View>;
}
export function NativeDiagnosticsPanel(props: NativeDiagnosticsProps) {return <DiagnosticsContent key={`${props.connection.endpoint}-${props.connection.identity}-${props.connection.session?.credentialId || props.connection.development?.expiresAt || ''}`} {...props}/>;}
const styles = (c: AppColors) => StyleSheet.create({panel: {gap: 16}, line: {flexDirection: 'row', alignItems: 'center', gap: 12}, title: {color: c.ink, fontSize: 23, fontWeight: '600', flex: 1}, card: {backgroundColor: c.surface, borderRadius: 24, padding: 20, gap: 12}, name: {color: c.ink, fontSize: 17, fontWeight: '600'}, copy: {color: c.muted, fontSize: 14, lineHeight: 22}, choices: {flexDirection: 'row', flexWrap: 'wrap', gap: 8}, choice: {borderWidth: 1, borderColor: c.line, borderRadius: 16, paddingHorizontal: 14, paddingVertical: 10}, selected: {backgroundColor: c.accentSoft, borderColor: c.accent}, selectedText: {color: c.accent, fontSize: 14, lineHeight: 22}, preview: {maxHeight: 300, borderRadius: 12, padding: 12, backgroundColor: c.canvas}, code: {color: c.ink, fontSize: 11, lineHeight: 17, fontFamily: Platform.OS === 'ios' ? 'Menlo' : 'monospace'}, foot: {color: c.muted, fontSize: 12, lineHeight: 20}});
