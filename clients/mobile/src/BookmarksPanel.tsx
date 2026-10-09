import {useEffect, useRef, useState} from 'react';
import {Text, View} from 'react-native';
import {TextInput} from 'react-native-paper';
import * as Crypto from 'expo-crypto';
import * as Linking from 'expo-linking';
import {ApiError, scopeOf, WearingApi, type Connection, type Outbox, type Pending, type RecordItem} from './core';
import {storage} from './storage';
import {serviceFetch} from './transport';
import {accountWorkAllowed, registerAccountWork} from './account-work';
import {PrimaryButton, TactilePressable} from './experience/primitives';
import {useAppTheme} from './app-theme';
import {localRecords, mergeRecordVersions, withRecordScope} from './record-sync';
import {RecordMutations, lifecycleMutation, projectRecordMutation, type RecordMutation} from './record-mutations';
import {BookmarkClient, bookmarkFetch} from './bookmark-client';
import {bookmarkDraft, bookmarkDraftKey, bookmarkEdit, bookmarkPending, openBookmark, withBookmarkDraft, type BookmarkEdit, type BookmarkRecord} from './bookmark-model';
import {isBookmarkUrl} from './bookmark-url';

type Props = {connection: Connection; outbox: Outbox; mutations?: RecordMutations; isCurrent?: () => boolean; onChanged?: () => void};
const sessionKey = (connection: Connection) => scopeOf(connection) + '|' + (connection.session?.credentialId || '') + '|' + (connection.session?.expiresAt || connection.development?.expiresAt || '');
function useBoundary(connection: Connection, isCurrent?: () => boolean) {
  const alive = useRef(false), abort = useRef<AbortController | null>(null);
  useEffect(() => {alive.current = true; const controller = new AbortController(); abort.current = controller; const stop = registerAccountWork(connection, async () => controller.abort()); return () => {alive.current = false; controller.abort(); stop();};
    // The owning screen is keyed by endpoint, identity and credential.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return {current: () => alive.current && accountWorkAllowed(connection) && !abort.current?.signal.aborted && (!isCurrent || isCurrent()), signal: () => abort.current?.signal};
}
export function BookmarksPanel(props: Props) {return <Bookmarks key={sessionKey(props.connection)} {...props}/>;}
function Bookmarks(props: Props) {
  const {connection, outbox, onChanged} = props, scope = scopeOf(connection), {colors: c} = useAppTheme(), boundary = useBoundary(connection, props.isCurrent);
  const [mutations] = useState(() => props.mutations || new RecordMutations(storage, Crypto.randomUUID));
  const [selected, setSelected] = useState<string | null>(null), [creating, setCreating] = useState(false), [items, setItems] = useState<BookmarkRecord[]>([]), [pending, setPending] = useState<Pending[]>([]), [query, setQuery] = useState(''), [applied, setApplied] = useState(''), [archived, setArchived] = useState(false), [cursor, setCursor] = useState<string | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState(''), [offline, setOffline] = useState(false);
  const sequence = useRef(0), locked = useRef(false);
  async function refresh(nextQuery = query, nextArchived = archived, more = false) {
    if (!boundary.current() || locked.current) return; locked.current = true; const token = ++sequence.current; setBusy(true); setError('');
    const current = () => boundary.current() && sequence.current === token;
    try {
      const page = await new BookmarkClient(connection, serviceFetch, current, boundary.signal()).page(nextQuery, nextArchived, more ? cursor || undefined : undefined);
      if (!current()) return;
      await withRecordScope(storage, scope, async () => {const prior = await storage.get<BookmarkRecord[]>(`receipts:${scope}`) || []; if (current()) await storage.put(`receipts:${scope}`, mergeRecordVersions(prior, page.items));});
      if (!current()) return;
      setItems(old => more ? mergeRecordVersions(old, page.items) as BookmarkRecord[] : page.items); setCursor(page.next_cursor); setApplied(page.query); setArchived(nextArchived); setOffline(false);
    } catch (e) {
      if (current()) {
        setError(e instanceof Error ? e.message : '收藏暂未读取。');
        if (!more) {let cache:RecordItem[]=[];try{cache=await localRecords(storage, scope);}catch{setError('收藏缓存暂时无法读取，请保留本机数据后重试。');} if (!current()) return; const q = nextQuery.trim().toLocaleLowerCase(); setItems(cache.filter(r => r.kind === 'note' && isBookmarkUrl(r.url) && !!r.deleted_at === nextArchived && [r.title,r.content,r.url].some(v => v!.toLocaleLowerCase().includes(q))).slice(0,30) as BookmarkRecord[]); setCursor(null); setApplied(nextQuery.trim()); setArchived(nextArchived); setOffline(true);}
      }
    } finally {locked.current = false; if (current()) {try{const entries = await outbox.items(scope); if (current()) setPending(entries.filter(e => e.draft.kind === 'note' && isBookmarkUrl(e.draft.url)));}catch{if(current())setError('待同步收藏暂时无法读取，请保留本机数据后重试。');}finally{if(current())setBusy(false);}}}
  }
  useEffect(() => {const generation=sequence, gate=locked;void refresh(); return () => {generation.current++;gate.current=false;};
    // This keyed screen belongs to one connection; explicit refresh/search own later reads.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  async function retry(entry: Pending) {if (locked.current || !boundary.current()) return; locked.current = true; setBusy(true); try {await outbox.retry(scope, entry.id); await outbox.flush(scope, new WearingApi(connection, bookmarkFetch(serviceFetch,boundary.current,boundary.signal())), boundary.current);} catch (e) {if(boundary.current())setError(e instanceof Error?e.message:'同步暂未完成。');} finally {locked.current=false;if(boundary.current()){setBusy(false);void refresh();onChanged?.();}}}
  if (creating || selected) return <BookmarkEditor key={selected || 'new'} {...props} mutations={mutations} recordId={selected || undefined} onBack={() => {setCreating(false);setSelected(null);void refresh();}}/>;
  return <View style={{gap:16}}>
    <Text accessibilityRole="header" style={{fontSize:28,fontWeight:'600',color:c.ink}}>链接收藏</Text>
    <Text style={{color:c.muted,lineHeight:22}}>留下值得再看的网页，也可以写下自己的备注。</Text>
    <PrimaryButton label="收藏新链接" onPress={() => setCreating(true)}/>
    <TextInput mode="outlined" label="搜索标题、网址或备注" value={query} maxLength={120} onChangeText={setQuery} onSubmitEditing={() => void refresh()} disabled={busy}/>
    <View style={{flexDirection:'row',gap:10}}>{[false,true].map(value => <TactilePressable key={String(value)} accessibilityRole="tab" accessibilityState={{selected:archived===value}} disabled={busy} onPress={() => void refresh(query,value)} style={{padding:12,borderRadius:16,backgroundColor:archived===value?c.soft:c.surface}}><Text style={{color:c.ink}}>{value?'已归档':'收藏'}</Text></TactilePressable>)}</View>
    <PrimaryButton label={busy?'读取中…':'搜索 / 刷新'} tone="quiet" disabled={busy} onPress={() => void refresh()}/>
    {!!error&&<Text accessibilityRole="alert" style={{color:c.danger}}>{error}</Text>}
    {offline&&<Text style={{color:c.muted}}>当前显示本机已看过的最多 30 条收藏，可能不是全部。连接恢复后请刷新。</Text>}
    {pending.map(entry => <View key={entry.id} style={{padding:16,gap:10,backgroundColor:c.surface,borderRadius:18}}><Text style={{color:c.ink}}>{entry.draft.title}</Text><Text style={{color:c.muted}}>{entry.error || '已保存在手机，等待同步到当前身份。'}</Text><PrimaryButton label="重试同步这条收藏" tone="quiet" disabled={busy} onPress={() => void retry(entry)}/></View>)}
    {items.map(item => <TactilePressable key={item.id} accessibilityRole="button" accessibilityLabel={`打开收藏 ${item.title}`} onPress={() => setSelected(item.id)} style={{padding:18,gap:8,backgroundColor:c.surface,borderWidth:1,borderColor:c.line,borderRadius:20}}><Text style={{fontSize:18,color:c.ink,fontWeight:'500'}}>{item.title}</Text><Text numberOfLines={2} style={{color:c.accent}}>{item.url}</Text>{!!item.content&&<Text numberOfLines={3} style={{color:c.muted,lineHeight:22}}>{item.content}</Text>}</TactilePressable>)}
    {!items.length&&!busy&&<Text style={{color:c.muted}}>{applied?'没有匹配的收藏。':archived?'归档的收藏会在这里。':'还没有收藏。也可以从浏览器分享链接到 Pajio。'}</Text>}
    {cursor&&items.length<300&&<PrimaryButton label="查看更多收藏" tone="quiet" disabled={busy} onPress={() => void refresh(applied,archived,true)}/>}
    {cursor&&items.length>=300&&<Text style={{color:c.muted}}>已显示 300 条，请搜索关键词缩小范围。</Text>}
  </View>;
}
export function BookmarkDetailPanel(props: Props & {recordId?: string; onBack: () => void}) {return <BookmarkEditor key={sessionKey(props.connection)+'|'+(props.recordId || 'new')} {...props}/>;}
function BookmarkEditor({connection,outbox,mutations:provided,isCurrent,onChanged,recordId,onBack}: Props & {recordId?: string; onBack: () => void}) {
  const {colors:c} = useAppTheme(), scope = scopeOf(connection), key = bookmarkDraftKey(scope,recordId), boundary = useBoundary(connection,isCurrent), locked = useRef(false);
  const [mutations] = useState(() => provided || new RecordMutations(storage,Crypto.randomUUID));
  const [form,setForm] = useState<BookmarkEdit | null>(null), [base,setBase] = useState<RecordItem | null>(null), [mutation,setMutation] = useState<RecordMutation | null>(null), [busy,setBusy] = useState(false), [error,setError] = useState(''), [notice,setNotice] = useState('');
  const api = () => new WearingApi(connection,bookmarkFetch(serviceFetch,boundary.current,boundary.signal()));
  const zone = () => Intl.DateTimeFormat().resolvedOptions().timeZone || 'Asia/Shanghai';
  useEffect(() => {let live=true; void (async () => {setBusy(true);try {
    const stored = await storage.get<unknown>(key), saved = stored ? bookmarkEdit(stored) : null;
    let record: RecordItem | null = null, row: RecordMutation | null = null;
    if(recordId){row=(await mutations.items(scope)).find(r=>r.id===recordId)||null;try{record=await api().record(recordId);if(record.kind!=='note')throw new Error('这条记录不是笔记收藏。');}catch(e){const cached=(await localRecords(storage,scope)).find(r=>r.id===recordId)||row?.base;if(!cached)throw e;record=cached;if(record.kind!=='note')throw new Error('这条记录不是笔记收藏。');if(boundary.current())setNotice('当前显示本机版本；保存时会核对服务端版本。');}}
    if(!live||!boundary.current())return;setBase(record);setMutation(row);
    const shown=record&&row&&!lifecycleMutation(row)?projectRecordMutation(row,record):record;const fields=shown?{title:shown.title,url:shown.url||'',notes:shown.content}:{title:'',url:'',notes:''};
    setForm(saved||{version:1,revision:record?.revision||0,requestId:Crypto.randomUUID(),...fields});
  }catch(e){if(live&&boundary.current())setError(e instanceof Error?e.message:'收藏暂未读取。');}finally{if(live&&boundary.current())setBusy(false);}})();return()=>{live=false;};
    // One editor is remounted per account credential and record. Draft loading must not rerun over typing.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  function change(field:'title'|'url'|'notes',value:string){if(!form||busy)return;const next={...form,[field]:value};setForm(next);void withBookmarkDraft(storage,key,async()=>{if(boundary.current())await storage.put(key,next);}).catch(e=>{if(boundary.current())setError(e instanceof Error?e.message:'草稿未保存在手机，请保留输入。');});}
  async function run(work:()=>Promise<void>){if(locked.current||!boundary.current())return;locked.current=true;setBusy(true);setError('');setNotice('');try{await work();}catch(e){if(boundary.current())setError(e instanceof Error?e.message:'保存暂未完成，输入仍保留。');}finally{locked.current=false;if(boundary.current()){setBusy(false);onChanged?.();}}}
  async function sync(preserveInput=false){await mutations.flush(scope,api(),boundary.current);if(!boundary.current()||!recordId)return;const row=(await mutations.items(scope)).find(r=>r.id===recordId)||null;if(!boundary.current())return;setMutation(row);if(row){setNotice(row.error||'修改已保存在手机，等待同步。');return;}const latest=await api().record(recordId);if(latest.kind!=='note')throw new Error('记录类型已有变化，请返回列表核对。');if(!boundary.current())return;setBase(latest);if(form)setForm({...form,...(preserveInput?{}:{title:latest.title,url:latest.url||'',notes:latest.content}),revision:latest.revision});setNotice(latest.deleted_at?'已归档；需要时可以恢复。':'已保存到当前身份。');}
  async function save(){if(!form)return;const captured=form, draft=bookmarkDraft(form,base?.timezone||zone());
    await withBookmarkDraft(storage,key,async()=>{if(!boundary.current())throw new ApiError('身份已切换。',409);await storage.put(key,captured);
      if(!recordId){await outbox.enqueue(bookmarkPending(scope,captured,zone()),[key,null]);}
      else{if(!base)throw new Error('请先读取收藏。');await mutations.enqueue(scope,{...base,revision:captured.revision},{title:draft.title,content:draft.content,url:draft.url});if(JSON.stringify(await storage.get(key))===JSON.stringify(captured))await storage.put(key,null);}
    });
    if(!boundary.current())return;
    if(!recordId){setForm({version:1,revision:0,requestId:Crypto.randomUUID(),title:'',url:'',notes:''});setNotice('收藏已加入同步队列。');await outbox.flush(scope,api(),boundary.current);if(boundary.current()){const rows=await outbox.items(scope);if(boundary.current())setNotice(rows.some(r=>r.id===captured.requestId)?'已保存在手机，等待联网同步。':'收藏已保存。可返回收藏列表查看。');}}
    else await sync();
  }
  async function lifecycle(){if(!base)return;await mutations.enqueueLifecycle(scope,base,base.deleted_at?'restore':'archive');await sync(true);}
  async function reconcile(keepLocal:boolean){if(!mutation||mutation.state!=='conflict'||!mutation.latest||!form)return;const latest=mutation.latest;if(latest.kind!=='note')throw new Error('记录类型已有变化，请返回列表核对。');
    if(lifecycleMutation(mutation))await mutations.resolveLifecycle(scope,mutation.id,mutation.generation,latest,keepLocal);
    else {const draft=keepLocal?bookmarkDraft(form,latest.timezone):null;await mutations.resolve(scope,mutation.id,mutation.generation,latest,keepLocal,draft?{title:draft.title,content:draft.content,url:draft.url}:undefined);}
    if(!boundary.current())return;setBase(latest);setForm({...form,revision:latest.revision});await storage.put(key,{...form,revision:latest.revision});await sync(!keepLocal);if(boundary.current()&&!keepLocal)setNotice('已采用最新版本状态；上方输入仍保留，点击保存才会重新提交。');
  }
  const blocked=busy||!form||!!base?.deleted_at||mutation?.state==='conflict'||lifecycleMutation(mutation);
  return <View style={{gap:16}}>
    <PrimaryButton label="返回收藏" tone="quiet" disabled={busy} onPress={onBack}/>
    <Text accessibilityRole="header" style={{fontSize:26,fontWeight:'600',color:c.ink}}>{recordId?'链接收藏':'收藏新链接'}</Text>
    <TextInput label="标题" mode="outlined" value={form?.title||''} maxLength={200} disabled={busy||!form||!!base?.deleted_at} onChangeText={v=>change('title',v)}/>
    <TextInput label="网页链接" mode="outlined" value={form?.url||''} maxLength={4096} autoCapitalize="none" autoCorrect={false} keyboardType="url" disabled={busy||!form||!!base?.deleted_at} onChangeText={v=>change('url',v)}/>
    <TextInput label="我的备注（可选）" mode="outlined" value={form?.notes||''} maxLength={12000} multiline disabled={busy||!form||!!base?.deleted_at} onChangeText={v=>change('notes',v)}/>
    <Text style={{color:c.muted,lineHeight:22}}>只保存链接和你写下的内容。点击“打开网页”后，由系统浏览器打开，不会自动读取网页。</Text>
    <PrimaryButton label="打开网页" tone="quiet" disabled={busy||!isBookmarkUrl(form?.url)} onPress={()=>void run(async()=>{await openBookmark(form?.url,Linking.openURL);})}/>
    <PrimaryButton label={recordId?'保存修改':'保存收藏'} disabled={blocked} onPress={()=>void run(save)}/>
    {mutation&&mutation.state!=='conflict'&&<PrimaryButton label="核对并重试上次同步" tone="quiet" disabled={busy} onPress={()=>void run(async()=>{await mutations.retry(scope,mutation.id);await sync();})}/>}
    {mutation?.state==='conflict'&&<View style={{padding:16,gap:12,backgroundColor:c.soft,borderRadius:18}}><Text style={{color:c.ink,fontWeight:'600'}}>这条收藏已有变化，你的输入仍在上方。</Text><Text selectable style={{color:c.muted,lineHeight:22}}>{mutation.latest?.deleted_at?'服务端已归档。\n':''}{mutation.latest?.title}{'\n'}{mutation.latest?.url}{'\n'}{mutation.latest?.content}</Text><PrimaryButton label="保留输入，采用最新版本状态" tone="quiet" disabled={busy||!mutation.latest} onPress={()=>void run(()=>reconcile(false))}/><PrimaryButton label={lifecycleMutation(mutation)?'确认继续这次归档 / 恢复':'核对后把我的修改保存到最新版本'} disabled={busy||!mutation.latest||!lifecycleMutation(mutation)&&!!mutation.latest.deleted_at} onPress={()=>void run(()=>reconcile(true))}/></View>}
    {base&&form&&form.revision!==base.revision&&<Text style={{color:c.muted}}>你的草稿来自较早版本。保存时会核对变化，原输入不会自动覆盖其他修改。</Text>}
    {base&&!mutation&&<PrimaryButton label={base.deleted_at?'恢复收藏':'归档收藏'} tone="quiet" disabled={busy} onPress={()=>void run(lifecycle)}/>}
    {!!notice&&<Text accessibilityLiveRegion="polite" style={{color:c.muted,lineHeight:22}}>{notice}</Text>}
    {!!error&&<Text accessibilityRole="alert" style={{color:c.danger,lineHeight:22}}>{error}</Text>}
  </View>;
}
