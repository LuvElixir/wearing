import {useCallback, useEffect, useMemo, useRef, useState} from 'react';
import {ActivityIndicator, StyleSheet, Text, View} from 'react-native';
import * as Crypto from 'expo-crypto';
import {FileArchive} from 'lucide-react-native';
import {ApiError, Connection} from './core';
import {AppColors, useAppTheme, useThemedStyles} from './app-theme';
import {PrimaryButton} from './experience/primitives';
import {DataExport, DataExportApi, handoffDataExport} from './data-export';
import {shareOriginalBytes} from './workspace-share';

function DataContent({connection, fetcher, pendingCount = 0, onSync, onFiles}: {connection: Connection; fetcher?: typeof fetch; pendingCount?: number; onSync?: () => void; onFiles?: () => void}) {
  const {colors} = useAppTheme(), s = useThemedStyles(styles), api = useMemo(() => new DataExportApi(connection, fetcher), [connection, fetcher]);
  const [item, setItem] = useState<DataExport | null>(null), [busy, setBusy] = useState<'load' | 'create' | 'share' | null>(null), [error, setError] = useState(''), [notice, setNotice] = useState('');
  const active = useRef(true), key = useRef(Crypto.randomUUID()), generatedKey = useRef<string | null>(null), working = useRef(false);
  const generation = useRef(0);
  const refresh = useCallback(async () => {
    const ticket = ++generation.current; working.current = true; setBusy('load'); setError('');
    try {const latest = await api.latest(); if (active.current && generation.current === ticket) {setItem(latest); if (latest) generatedKey.current = key.current;}}
    catch (cause) {if (active.current && generation.current === ticket) setError(cause instanceof Error ? cause.message : '暂时无法读取已有副本。');}
    finally {if (generation.current === ticket) {working.current = false; if (active.current) setBusy(null);}}
  }, [api]);
  useEffect(() => {const sequence = generation; active.current = true; void Promise.resolve().then(() => {if (active.current) return refresh();}); return () => {active.current = false; sequence.current++;};}, [refresh]);
  async function create(fresh = false) {
    if (working.current) return;
    if (fresh && key.current === generatedKey.current) key.current = Crypto.randomUUID();
    working.current = true; setBusy('create'); setError(''); setNotice('');
    try {const value = await api.create(key.current); if (active.current) {generatedKey.current = key.current; setItem(value);}}
    catch (cause) {if (active.current) setError(cause instanceof Error ? cause.message : '导出没有完成，请重试。');}
    finally {working.current = false; if (active.current) setBusy(null);}
  }
  async function share() {
    if (!item || working.current) return;
    working.current = true; setBusy('share'); setError(''); setNotice('');
    try {
      const opened = await handoffDataExport(api, item, () => active.current, async bytes => {
        const digest = await Crypto.digest(Crypto.CryptoDigestAlgorithm.SHA256, new Uint8Array(bytes).buffer);
        return Array.from(new Uint8Array(digest)).map(value => value.toString(16).padStart(2, '0')).join('');
      }, bytes => shareOriginalBytes(async () => bytes, item.filename, 'application/zip', () => active.current));
      if (opened) setNotice('分享面板已关闭。请在你选择的 App 中确认是否保存成功；也可以再次打开。');
    } catch (cause) {
      if (active.current) {setError(cause instanceof Error ? cause.message : '未能打开分享面板，可重试同一份导出。'); if (cause instanceof ApiError && cause.status === 410) setNotice('请点击“生成最新副本”。');}
    } finally {working.current = false; if (active.current) setBusy(null);}
  }
  return <View style={s.panel}><View style={s.line}><FileArchive color={colors.accent} size={25}/><Text style={s.title}>带走我的数据</Text></View><Text style={s.copy}>导出当前身份在运行服务上保存的内容，打包为可阅读的 ZIP 文件。原数据会保留。</Text>
    {pendingCount ? <View style={s.card}><Text style={s.name}>还有 {pendingCount} 项留在手机上</Text><Text style={s.copy}>这份导出只包含已同步到服务的内容。请先完成同步，再生成最新副本。</Text>{onSync ? <PrimaryButton label="先同步本机记录" tone="quiet" onPress={onSync}/> : null}</View> : null}
    <View style={s.card}><Text style={s.name}>包含哪些内容</Text><Text style={s.copy}>对话和任务、目标与安排、生活记录、两份个人记忆，以及大小允许的图片、录音和已发布结果原件。</Text><Text style={s.copy}>工作区提供文件清单，原件请在文件页逐份取回。未包含项目会列在 manifest.json。记录和文件的取样时间也会注明。</Text><Text style={s.copy}>不会打包账号密钥、服务配置、运行日志或其他身份。每份导出最多 15 MB，下载有效期为 30 分钟。</Text>{onFiles ? <PrimaryButton label="打开文件页，逐份取回原件" tone="quiet" onPress={onFiles}/> : null}</View>
    {item ? <View style={s.card}><Text style={s.name}>副本已准备好</Text><Text style={s.copy}>{item.counts.conversation || 0} 条对话 · {item.counts.tasks || 0} 个任务 · {item.counts.life || 0} 条生活记录</Text><Text style={s.copy}>{(item.size / 1024 / 1024).toFixed(2)} MB · {new Date(item.expires_at * 1000).toLocaleTimeString('zh-CN')} 前可取回</Text>{item.omitted.length ? <><Text style={s.name}>有 {item.omitted.length} 项未包含说明</Text>{item.omitted.slice(0, 4).map((row, index) => <Text style={s.copy} key={index}>{row.path ? row.path + '：' : ''}{row.reason}</Text>)}{item.omitted.length > 4 ? <Text style={s.copy}>完整说明保存在包内的 manifest.json。</Text> : null}</> : null}<PrimaryButton label="保存或分享副本" disabled={!!busy} onPress={() => {void share();}}/><PrimaryButton label="生成最新副本" tone="quiet" disabled={!!busy} onPress={() => {void create(true);}}/></View> : <PrimaryButton label={error ? '重试生成副本' : '生成当前身份副本'} disabled={!!busy} onPress={() => {void create();}}/>}
    {busy ? <View style={s.line}><ActivityIndicator color={colors.accent}/><Text style={s.copy}>{busy === 'create' ? '正在整理当前身份的数据…' : busy === 'load' ? '正在读取已有副本…' : '正在取回并核对文件…'}</Text></View> : null}{error ? <><Text style={s.error} accessibilityLiveRegion="polite">{error}</Text><PrimaryButton label="刷新已有副本" tone="quiet" disabled={!!busy} onPress={() => {void refresh();}}/></> : null}{notice ? <Text style={s.copy} accessibilityLiveRegion="polite">{notice}</Text> : null}<Text style={s.foot}>副本包含你的个人内容，请自行选择合适的保存位置。完成分享面板操作，不代表目标 App 已保存成功。</Text>
  </View>;
}
export function NativeDataPanel(props: {connection: Connection; fetcher?: typeof fetch; pendingCount?: number; onSync?: () => void; onFiles?: () => void}) {return <DataContent key={`${props.connection.endpoint}-${props.connection.identity}-${props.connection.session?.credentialId || props.connection.development?.expiresAt || ''}`} {...props}/>;}
const styles = (c: AppColors) => StyleSheet.create({panel: {gap: 16}, line: {flexDirection: 'row', alignItems: 'center', gap: 12}, title: {color: c.ink, fontSize: 23, fontWeight: '600', flex: 1}, card: {backgroundColor: c.surface, borderRadius: 24, padding: 20, gap: 12}, name: {color: c.ink, fontSize: 17, fontWeight: '600'}, copy: {color: c.muted, fontSize: 14, lineHeight: 22}, error: {color: c.danger, fontSize: 14, lineHeight: 22}, foot: {color: c.muted, fontSize: 12, lineHeight: 20}});
