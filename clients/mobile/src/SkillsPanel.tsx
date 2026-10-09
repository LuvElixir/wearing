import {useCallback, useEffect, useMemo, useRef, useState} from 'react';
import {ActivityIndicator, StyleSheet, Text, TextInput, View} from 'react-native';
import {ArrowLeft, BookOpen, Check, ChevronRight, Download, RefreshCw} from 'lucide-react-native';
import {ApiError, Connection, scopeOf} from './core';
import {useAppTheme, useThemedStyles, AppColors} from './app-theme';
import {PrimaryButton, TactilePressable} from './experience/primitives';
import {SkillDetail, SkillRemoval, SkillSnapshot, SkillsApi, SkillSource} from './skills-model';

function SkillsContent({connection, fetcher}: {connection: Connection; fetcher?: typeof fetch}) {
  const {colors: c} = useAppTheme(), s = useThemedStyles(styles);
  const api = useMemo(() => new SkillsApi(connection, fetcher), [connection, fetcher]);
  const [data, setData] = useState<SkillSnapshot | null>(null), [detail, setDetail] = useState<SkillDetail | null>(null);
  const [section, setSection] = useState<SkillSource>('installed'), [query, setQuery] = useState('');
  const [busy, setBusy] = useState('load'), [error, setError] = useState(''), [notice, setNotice] = useState('');
  const [removal, setRemoval] = useState<SkillRemoval | null>(null);
  const active = useRef(true), operation = useRef(false), sequence = useRef(0);
  const refresh = useCallback(async () => {
    const ticket = ++sequence.current;
    setBusy('load'); setError('');
    try {const snapshot = await api.list(); if (active.current && ticket === sequence.current) setData(snapshot);}
    catch (error) {if (active.current && ticket === sequence.current) setError(error instanceof ApiError ? error.message : '技能目录暂时无法读取。');}
    finally {if (active.current && ticket === sequence.current) setBusy('');}
  }, [api]);
  useEffect(() => {active.current = true; void Promise.resolve().then(() => {if (active.current) return refresh();}); return () => {active.current = false;};}, [refresh]);
  async function open(id: string) {
    if (operation.current || busy) return;
    operation.current = true; setBusy(id); setError(''); setNotice('');
    try {const result = await api.detail(section, id); if (active.current) setDetail(result);}
    catch (error) {if (active.current) setError(error instanceof ApiError ? error.message : '技能说明暂时无法读取。');}
    finally {operation.current = false; if (active.current) setBusy('');}
  }
  async function apply() {
    if (!detail || !data || operation.current || busy) return;
    operation.current = true; setBusy('save'); setError(''); setNotice('');
    try {
      const snapshot = detail.source === 'catalog' ? await api.install(detail.id, detail.revision) : await api.enabled(detail.id, !detail.enabled, data.revision);
      if (!active.current) return;
      setData(snapshot);
      const installed = snapshot.installed.find(item => item.name === detail.name);
      if (installed) setDetail({...detail, ...installed, source: 'installed'});
      setNotice(detail.source === 'catalog' ? installed?.enabled ? '已安装并启用，可以在对话中使用这项技能。' : '已安装，保留之前的停用设置。点启用后，后续任务才会使用它。' : detail.enabled ? '已停用，后续技能调用将不再使用它。' : '已启用，后续技能调用可以使用它。');
    } catch (error) {if (active.current) setError(error instanceof ApiError ? error.message : '这次操作未完成。');}
    finally {operation.current = false; if (active.current) setBusy('');}
  }
  async function prepareRemoval() {
    if (!detail || detail.source !== 'installed' || detail.essential || operation.current || busy) return;
    operation.current = true; setBusy('removal'); setError(''); setNotice('');
    try {const preview = await api.removal(detail.id); if (active.current) setRemoval(preview);}
    catch (error) {if (active.current) setError(error instanceof ApiError ? error.message : '暂时无法移除这项技能。');}
    finally {operation.current = false; if (active.current) setBusy('');}
  }
  async function remove() {
    if (!removal || operation.current || busy) return;
    operation.current = true; setBusy('remove'); setError('');
    try {
      const receipt = await api.remove(removal);
      if (!active.current) return;
      setData(receipt.snapshot); setDetail(null); setRemoval(null); setSection('installed');
      setNotice(`已移除 ${removal.name}。恢复副本已保留；聊天、记忆和其他身份不受影响。`);
    } catch (error) {if (active.current) setError(error instanceof ApiError ? error.message : '尚未确认移除结果，请重试或刷新目录核对。');}
    finally {operation.current = false; if (active.current) setBusy('');}
  }
  const items = data?.[section].filter(item => `${item.name} ${item.description} ${item.category}`.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase())) || [];
  return <View style={s.panel}>
    {detail ? <>
      <TactilePressable accessibilityLabel="返回技能目录" disabled={!!busy} onPress={() => {setDetail(null); setRemoval(null); setNotice(''); setError('');}} style={s.back}><ArrowLeft size={18} color={c.ink}/><Text style={s.link}>技能目录</Text></TactilePressable>
      <View style={s.card}><BookOpen size={27} color={c.accent}/><Text style={s.title}>{detail.name}</Text><Text style={s.copy}>{detail.description}</Text>
        <Text style={s.muted}>{detail.source === 'installed' ? detail.enabled ? '已安装 · 已启用' : '已安装 · 已停用' : '运行时技能目录'}{!detail.compatible ? ' · 当前执行设备不支持' : ''}</Text>
        {detail.requirements.length ? <Text style={s.muted}>需要配置：{detail.requirements.join('、')}。安装技能不会自动连接这些账号。</Text> : null}
        {detail.essential ? <Text style={s.muted}>运行必需技能，保持启用。</Text> : !removal ? <><PrimaryButton label={detail.source === 'catalog' ? '安装技能' : detail.enabled ? '停用技能' : '启用技能'} loading={busy === 'save'} disabled={!!busy || (detail.source === 'catalog' && !detail.compatible)} tone={detail.source === 'installed' && detail.enabled ? 'quiet' : undefined} onPress={() => {void apply();}} leading={detail.source === 'catalog' ? <Download size={17} color={c.ink}/> : undefined}/>{detail.source === 'installed' ? <PrimaryButton label="移除技能" tone="quiet" disabled={!!busy} onPress={() => {void prepareRemoval();}}/> : null}</> : null}
      </View>
      {removal ? <View style={s.card}><Text style={s.section}>移除 {removal.name}？</Text><Text style={s.copy}>这项技能将从当前身份移除，后续任务不再使用。原文件会保留恢复副本，聊天、记忆和其他身份不会被删除。技能目录里的原版仍可重新安装。</Text><Text style={s.muted}>有正在执行或排队的任务时，需要先结束任务。</Text><PrimaryButton label="确认移除" tone="danger" loading={busy === 'remove'} disabled={!!busy} onPress={() => {void remove();}}/><PrimaryButton label="保留技能" tone="quiet" disabled={!!busy} onPress={() => {setRemoval(null); setError('');}}/></View> : null}
    </> : <>
      <View style={s.heading}><View style={s.words}><Text style={s.title}>技能</Text><Text style={s.muted}>按需要开启，Pajio 会在做事时使用。</Text></View><TactilePressable accessibilityLabel="刷新技能目录" disabled={!!busy} onPress={() => {void refresh();}} style={s.refresh}><RefreshCw size={20} color={c.ink}/></TactilePressable></View>
      <View style={s.tabs}>{([['installed', '已安装'], ['catalog', '添加技能']] as const).map(([key, label]) => <TactilePressable key={key} accessibilityRole="tab" accessibilityState={{selected: section === key}} disabled={!!busy} onPress={() => {setSection(key); setQuery(''); setError('');}} style={[s.tab, section === key && s.selected]}><Text style={s.link}>{label}{data ? ` · ${data[key].length}` : ''}</Text></TactilePressable>)}</View>
      <TextInput value={query} onChangeText={setQuery} accessibilityLabel="搜索技能" placeholder="搜索名称或用途" placeholderTextColor={c.muted} style={s.search} clearButtonMode="while-editing"/>
    </>}
    {busy ? <View style={s.loading}><ActivityIndicator color={c.accent}/><Text style={s.muted}>{busy === 'save' ? '正在保存…' : busy === 'remove' ? '正在移除…' : '正在读取…'}</Text></View> : null}
    {error ? <View style={s.card}><Text accessibilityLiveRegion="polite" style={s.error}>{error}</Text><PrimaryButton label="刷新目录" tone="quiet" disabled={!!busy} onPress={() => {setDetail(null); setRemoval(null); void refresh();}}/></View> : null}
    {notice ? <View style={s.notice}><Check size={17} color={c.accent}/><Text accessibilityLiveRegion="polite" style={s.muted}>{notice}</Text></View> : null}
    {detail ? <View style={s.card}><Text style={s.section}>技能说明</Text><Text selectable style={s.document}>{detail.content}</Text></View> : data ? <>
      {items.length ? items.map(item => <TactilePressable key={item.id} disabled={!!busy} onPress={() => {void open(item.id);}} accessibilityLabel={`查看技能 ${item.name}`} style={s.row}><View style={s.words}><Text style={s.name}>{item.name}</Text><Text numberOfLines={2} style={s.muted}>{item.description}</Text><Text style={s.state}>{section === 'installed' ? item.enabled ? '已启用' : '已停用' : item.installed ? '已安装' : item.compatible ? '可安装' : '当前设备不支持'}</Text></View><ChevronRight size={18} color={c.muted}/></TactilePressable>) : <Text style={s.copy}>{query ? '没有找到匹配的技能。' : section === 'installed' ? '还没有安装技能，到“添加技能”选一个。' : '当前运行时还没有可安装目录。'}</Text>}
    </> : null}
  </View>;
}

export function SkillsPanel(props: {connection: Connection; fetcher?: typeof fetch}) {
  return <SkillsContent key={`${scopeOf(props.connection)}|${props.connection.session?.credentialId || ''}|${props.connection.session?.expiresAt || props.connection.development?.expiresAt || ''}`} {...props}/>;
}
const styles = (c: AppColors) => StyleSheet.create({
  panel: {gap: 16}, heading: {flexDirection: 'row', alignItems: 'center', gap: 12}, words: {flex: 1, gap: 6}, title: {fontSize: 28, lineHeight: 37, fontWeight: '600', color: c.ink},
  copy: {fontSize: 16, lineHeight: 25, color: c.ink}, muted: {fontSize: 13, lineHeight: 21, color: c.muted}, link: {fontSize: 14, color: c.ink},
  tabs: {flexDirection: 'row', padding: 4, gap: 6, backgroundColor: c.soft, borderRadius: 18}, tab: {flex: 1, minHeight: 44, alignItems: 'center', justifyContent: 'center', borderRadius: 14}, selected: {backgroundColor: c.surface},
  search: {fontSize: 16, color: c.ink, minHeight: 48, paddingHorizontal: 16, backgroundColor: c.surface, borderWidth: 1, borderColor: c.line, borderRadius: 18},
  card: {padding: 20, borderRadius: 24, backgroundColor: c.surface, borderWidth: 1, borderColor: c.line, gap: 14}, row: {padding: 18, borderRadius: 22, backgroundColor: c.surface, borderWidth: 1, borderColor: c.line, flexDirection: 'row', alignItems: 'center', gap: 14},
  name: {fontSize: 18, lineHeight: 25, fontWeight: '500', color: c.ink}, state: {fontSize: 12, lineHeight: 20, color: c.accent}, back: {flexDirection: 'row', alignItems: 'center', gap: 8, minHeight: 44}, refresh: {height: 46, width: 46, alignItems: 'center', justifyContent: 'center', borderRadius: 23, backgroundColor: c.surface},
  loading: {flexDirection: 'row', gap: 10, alignItems: 'center'}, error: {fontSize: 14, lineHeight: 22, color: c.danger}, notice: {flexDirection: 'row', alignItems: 'center', gap: 8}, section: {fontSize: 17, fontWeight: '500', color: c.ink}, document: {fontSize: 14, lineHeight: 23, color: c.ink},
});
