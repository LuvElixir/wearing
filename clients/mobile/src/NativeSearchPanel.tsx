import {useCallback, useEffect, useMemo, useRef, useState} from 'react';
import {ActivityIndicator, Keyboard, StyleSheet, Text, TextInput, View} from 'react-native';
import {ArrowLeft, ChevronRight, FileSearch, Search} from 'lucide-react-native';
import {ApiError, Connection, scopeOf} from './core';
import {serviceFetch} from './transport';
import {useAppTheme, useThemedStyles, type AppColors} from './app-theme';
import {PrimaryButton, TactilePressable} from './experience/primitives';
import {NativeSearchApi, SearchItem, SearchKind, SearchMessage, mergeSearchPages, searchQuery} from './native-search';
import {ongoingTime} from './ongoing-management';

export type SearchContext = {draft: string; query: string; kind: SearchKind};
type Props = {connection: Connection; onTask: (id: string) => void; onRecord: (id: string) => void; onFiles: (query: string) => void; onBack?: () => void; onMessage?: (target: {taskId: string; messageId: number}) => void; initial?: SearchContext; onRemember?: (context: SearchContext) => void};
const filters: [SearchKind, string][] = [['all', '全部'], ['message', '聊天'], ['task', '任务'], ['record', '生活记录']];
const issue = (cause: unknown) => cause instanceof Error ? cause.message : '暂时没有完成，请重试。';
export default function NativeSearchPanel(props: Props) {return <SearchSession key={scopeOf(props.connection)} {...props}/>;}

function SearchSession({connection, onTask, onRecord, onFiles, onBack, onMessage, initial, onRemember}: Props) {
  const {colors: c} = useAppTheme(), s = useThemedStyles(makeStyles);
  const api = useMemo(() => new NativeSearchApi(connection, serviceFetch), [connection]);
  const [draft, setDraft] = useState(initial?.draft || ''), [query, setQuery] = useState(initial?.query || ''), [kind, setKind] = useState<SearchKind>(initial?.kind || 'all');
  const [revision, setRevision] = useState(0), [items, setItems] = useState<SearchItem[]>([]), [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(!!initial?.query), [loaded, setLoaded] = useState(false), [error, setError] = useState(''), [restart, setRestart] = useState(false);
  const [selected, setSelected] = useState<SearchItem | null>(null);
  const request = useRef<{generation: number; controller?: AbortController}>({generation: 0});
  const loadPage = useCallback((next: string | null) => {
    const generation = ++request.current.generation;
    request.current.controller?.abort();
    const controller = new AbortController(); request.current.controller = controller;
    return api.page(query, kind, next, controller.signal).then(page => {
      if (generation !== request.current.generation) return;
      setItems(previous => next ? mergeSearchPages(previous, page.items) : page.items);
      setCursor(page.next_cursor); setLoaded(true);
    }).catch(cause => {
      if (generation !== request.current.generation) return;
      setError(issue(cause)); setRestart(cause instanceof ApiError && cause.status === 409);
    }).finally(() => {if (generation === request.current.generation) setLoading(false);});
  }, [api, query, kind]);
  useEffect(() => {
    const current = request.current;
    if (query) void loadPage(null);
    return () => {current.generation += 1; current.controller?.abort();};
  }, [query, loadPage, revision]);
  const markLoading = () => {setLoading(true); setError(''); setRestart(false);};
  const clearResults = () => {request.current.generation += 1; request.current.controller?.abort(); setItems([]); setCursor(null); setLoaded(false); setSelected(null); setError('');};
  const submit = () => {try {const next = searchQuery(draft); clearResults(); markLoading(); setQuery(next); onRemember?.({draft, query: next, kind}); setRevision(value => value + 1); Keyboard.dismiss();} catch (cause) {setError(issue(cause));}};
  if (selected?.target.kind === 'message') return <MessageResult key={selected.key} api={api} item={selected} onBack={() => setSelected(null)} onTask={onTask} onMessage={onMessage}/>;
  return <View style={s.stack}>
    {onBack ? <TactilePressable accessibilityLabel="返回" onPress={onBack} style={s.back}><ArrowLeft size={18} color={c.ink}/><Text style={s.link}>返回</Text></TactilePressable> : null}
    <Text accessibilityRole="header" style={s.title}>搜索</Text>
    <View style={s.search}><Search size={19} color={c.muted}/><TextInput autoFocus={!initial?.query} accessibilityLabel="搜索关键词" value={draft} onChangeText={value => {setDraft(value); onRemember?.({draft: value, query, kind});}} maxLength={240} returnKeyType="search" onSubmitEditing={submit} placeholder="找聊过的事、任务和生活记录" placeholderTextColor={c.muted} style={s.input}/><TactilePressable accessibilityLabel="搜索" disabled={!draft.trim()} onPress={submit} style={s.searchButton}><Text style={s.link}>搜索</Text></TactilePressable></View>
    <View style={s.filters}>{filters.map(([value, label]) => <TactilePressable key={value} accessibilityRole="radio" accessibilityState={{checked: value === kind}} accessibilityLabel={`搜索${label}`} onPress={() => {if (value !== kind) {clearResults(); if (query) markLoading(); setKind(value); onRemember?.({draft, query, kind: value});}}} style={[s.filter, value === kind && s.active]}><Text style={[s.filterText, value === kind && {color: c.ink}]}>{label}</Text></TactilePressable>)}</View>
    {query ? <Text style={s.caption}>“{query}” · 按保存时间排序。搜索期间的新内容与修改会在重新搜索后显示。</Text> : <Text style={s.secondary}>输入你记得的几个字，从当前身份保存的内容里找。</Text>}
    {error ? <View style={s.stack}><Text accessibilityLiveRegion="polite" style={s.error}>{error}</Text>{query ? <PrimaryButton label={restart ? '重新搜索' : '重试搜索'} tone="quiet" disabled={loading} onPress={() => {markLoading(); if (restart) {clearResults(); setRevision(value => value + 1);} else void loadPage(cursor);}}/> : null}</View> : null}
    {items.map(item => <TactilePressable key={item.key} accessibilityLabel={`打开${item.kind === 'message' ? '聊天' : item.kind === 'task' ? '任务' : '生活记录'}：${item.title}`} onPress={() => {
      if (item.target.kind === 'record') onRecord(item.target.record_id);
      else if (item.target.kind === 'task') onTask(item.target.task_id);
      else setSelected(item);
    }} style={s.card}><View style={s.row}><Text style={s.caption}>{item.kind === 'message' ? '聊天' : item.kind === 'task' ? '任务' : item.record_kind === 'event' ? '日程' : item.record_kind === 'task' ? '待办' : '笔记'} · {ongoingTime(item.created_at)}</Text><ChevronRight size={17} color={c.muted}/></View><Text style={s.heading}>{item.title}</Text><Text style={s.body}>{item.snippet}</Text>{item.matched_field === 'output' ? <Text style={s.caption}>匹配到 Pajio 的回复</Text> : null}</TactilePressable>)}
    {loading ? <View style={s.row}><ActivityIndicator color={c.accent}/><Text style={s.secondary}>正在搜索…</Text></View> : null}
    {query && loaded && !items.length && !loading ? <Text style={s.secondary}>没有找到匹配内容，试试另一个关键词。</Text> : null}
    {cursor && !error ? <PrimaryButton label="加载更多结果" tone="quiet" loading={loading} onPress={() => {if (!loading) {markLoading(); void loadPage(cursor);}}}/> : null}
    {loaded && items.length > 0 && !cursor ? <Text style={s.caption}>已显示这次搜索的全部结果。</Text> : null}
    <TactilePressable accessibilityLabel="前往文件名搜索" onPress={() => onFiles([...draft.trim()].slice(0, 120).join(''))} style={s.file}><FileSearch size={22} color={c.accent}/><View style={s.words}><Text style={s.heading}>找文件</Text><Text style={s.caption}>前往文件页搜索文件名；这里不包含文件正文。</Text></View><ChevronRight size={18} color={c.muted}/></TactilePressable>
  </View>;
}

function MessageResult({api, item, onBack, onTask, onMessage}: {api: NativeSearchApi; item: SearchItem; onBack: () => void; onTask: (id: string) => void; onMessage?: Props['onMessage']}) {
  const {colors: c} = useAppTheme(), s = useThemedStyles(makeStyles);
  const [detail, setDetail] = useState<SearchMessage | null>(null), [loading, setLoading] = useState(true), [error, setError] = useState(''), [revision, setRevision] = useState(0);
  useEffect(() => {
    let live = true; const controller = new AbortController();
    if (item.target.kind === 'message') api.message(item.target.message_id, item.target.task_id, controller.signal).then(value => {if (live) setDetail(value);}).catch(cause => {if (live) setError(issue(cause));}).finally(() => {if (live) setLoading(false);});
    return () => {live = false; controller.abort();};
  }, [api, item, revision]);
  return <View style={s.stack}>
    <TactilePressable accessibilityLabel="返回搜索结果" onPress={onBack} style={s.back}><ArrowLeft size={18} color={c.ink}/><Text style={s.link}>搜索结果</Text></TactilePressable>
    <Text accessibilityRole="header" style={s.title}>这段对话</Text>
    {loading ? <ActivityIndicator color={c.accent}/> : null}
    {error ? <><Text style={s.error}>{error}</Text><PrimaryButton label="重新读取对话" tone="quiet" onPress={() => {setLoading(true); setError(''); setDetail(null); setRevision(value => value + 1);}}/></> : null}
    {detail ? <><Text style={s.caption}>{ongoingTime(detail.created_at)}</Text><View style={s.card}><Text style={s.caption}>你说</Text><Text selectable style={s.body}>{detail.content}</Text></View><View style={s.card}><Text style={s.caption}>Pajio</Text><Text selectable style={s.body}>{detail.output || '这条消息还没有保存回复，可以查看任务进展。'}</Text></View><PrimaryButton label="查看这条消息的任务与进展" tone="quiet" onPress={() => onTask(detail.task_id)}/>{onMessage ? <PrimaryButton label="定位原对话" tone="quiet" onPress={() => onMessage({taskId: detail.task_id, messageId: detail.id})}/> : null}</> : null}
  </View>;
}
const makeStyles = (c: AppColors) => StyleSheet.create({
  stack: {gap: 16}, row: {flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 10},
  title: {fontSize: 28, lineHeight: 39, fontWeight: '500', color: c.ink}, heading: {fontSize: 16, lineHeight: 25, fontWeight: '500', color: c.ink},
  body: {fontSize: 15, lineHeight: 26, color: c.ink}, secondary: {fontSize: 14, lineHeight: 24, color: c.muted}, caption: {fontSize: 12, lineHeight: 20, color: c.muted},
  card: {backgroundColor: c.surface, borderColor: c.line, borderWidth: 1, borderRadius: 18, padding: 17, gap: 9},
  search: {flexDirection: 'row', alignItems: 'center', gap: 10, paddingHorizontal: 14, borderColor: c.line, borderWidth: 1, borderRadius: 16, backgroundColor: c.surface},
  input: {flex: 1, color: c.ink, minHeight: 52, fontSize: 16}, searchButton: {minHeight: 44, paddingLeft: 6, justifyContent: 'center'},
  filters: {flexDirection: 'row', flexWrap: 'wrap', gap: 6}, filter: {minHeight: 44, paddingHorizontal: 14, justifyContent: 'center', borderRadius: 22}, active: {backgroundColor: c.surface}, filterText: {fontSize: 14, color: c.muted},
  back: {minHeight: 44, flexDirection: 'row', alignItems: 'center', gap: 8}, link: {fontSize: 14, color: c.accent}, error: {fontSize: 14, lineHeight: 23, color: c.danger},
  file: {flexDirection: 'row', alignItems: 'center', gap: 12, paddingVertical: 18, borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: c.line}, words: {flex: 1, gap: 5},
});
