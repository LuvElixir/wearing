import {useEffect,useRef,useState} from 'react';
import {View} from 'react-native';
import {Button,Text} from 'react-native-paper';
import * as Crypto from 'expo-crypto';
import {scopeOf,type Connection} from './core';
import {storage} from './storage';
import {serviceFetch} from './transport';
import {useAppTheme} from './app-theme';
import {accountWorkAllowed,registerAccountWork} from './account-work';
import {Sheet} from './experience/primitives';
import {ConversationSourcesClient,adoptSourcePage,excludeConversation,mergeSourcePages,pendingSource,sourcePage,sourcePageKey,sourcePendingKey,type ConversationSource,type PendingSource,type SourcePage,type SourceRequest} from './conversation-sources';

type Props={connection:Connection};
export default function ConversationSourcesPanel(props:Props){return <Panel key={`${scopeOf(props.connection)}|${props.connection.session?.credentialId||''}`} {...props}/>;}
function Panel({connection}:Props){
  const {colors:c}=useAppTheme(),scope=scopeOf(connection),alive=useRef(false),lock=useRef(false),controller=useRef<AbortController|null>(null);
  const [page,setPage]=useState<SourcePage|null>(null),[waiting,setWaiting]=useState<PendingSource|null>(null),[selected,setSelected]=useState<ConversationSource|null>(null),[online,setOnline]=useState(false),[busy,setBusy]=useState(false),[notice,setNotice]=useState('');
  const active=()=>alive.current&&accountWorkAllowed(connection)&&!controller.current?.signal.aborted;
  const client=()=>new ConversationSourcesClient(connection,serviceFetch,active,controller.current?.signal);
  useEffect(()=>{alive.current=true;const abort=new AbortController();controller.current=abort;const stop=registerAccountWork(connection,async()=>abort.abort());
    const initialActive=()=>active()&&!abort.signal.aborted;
    const initialClient=new ConversationSourcesClient(connection,serviceFetch,initialActive,abort.signal);
    void(async()=>{try{const pending=pendingSource(await storage.get(sourcePendingKey(scope))),cache=await storage.get(sourcePageKey(scope));if(!initialActive())return;setWaiting(pending);if(cache)setPage(sourcePage(cache,connection.identity));const fresh=await initialClient.page();if(!initialActive())return;setPage(fresh);setOnline(true);await storage.put(sourcePageKey(scope),fresh);}catch(error){if(initialActive())setNotice(error instanceof Error?error.message:'来源列表暂未读取。');}})();
    return()=>{alive.current=false;abort.abort();stop();};
    // A changed credential/account remounts this scoped panel.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  },[]);
  async function run(work:()=>Promise<void>){if(lock.current||!active())return;lock.current=true;setBusy(true);setNotice('');try{await work();}catch(error){if(active())setNotice(error instanceof Error?error.message:'原操作已保留。');}finally{try{if(active())setWaiting(pendingSource(await storage.get(sourcePendingKey(scope))));}catch(error){if(active())setNotice(error instanceof Error?error.message:'本机回执暂未读取。');}finally{lock.current=false;if(active())setBusy(false);}}}
  async function submit(input?:SourceRequest){await excludeConversation(storage,scope,client(),input,active);if(!active())return;setSelected(null);setWaiting(null);setOnline(false);setNotice('已停止引用所选对话。后续消息将从新的会话上下文开始，历史仍可查看。');try{const fresh=await client().page();if(active()){setPage(fresh);setOnline(true);await storage.put(sourcePageKey(scope),fresh);}}catch{if(active())setNotice('排除设置已保存；当前列表暂未刷新，可稍后重新读取。');}}
  const disabled=busy||!!waiting||!online;
  return <View style={{gap:14,padding:20,paddingBottom:40}}>
    <Text variant="titleLarge" style={{color:c.ink}}>对话引用范围</Text>
    <Text style={{color:c.muted,lineHeight:23}}>选择哪些历史对话不再作为后续回答来源。每项是一整段连续会话，包含压缩后的后续内容。</Text>
    {!online&&page&&<Text style={{color:c.muted}}>当前显示上次读取的列表，请联网核对后操作。</Text>}
    {page?.items.map(row=><View key={row.source_id} style={{padding:18,borderRadius:22,gap:8,backgroundColor:c.surface}}>
      <Text numberOfLines={3} style={{color:c.ink,fontSize:16,fontWeight:'600'}}>{row.title||'对话'}</Text>
      <Text style={{color:c.muted,fontSize:12}}>{new Date(row.started_at).toLocaleString('zh-CN')} 起 · {row.message_count} 条消息</Text>
      <Text style={{color:c.muted,lineHeight:20}}>{row.excluded?'已停止作为历史来源 · 保留可查看的记录':'可被后续对话检索和引用'}</Text>
      {!row.excluded&&<Button disabled={disabled} onPress={()=>setSelected(row)}>不再引用这段对话…</Button>}
    </View>)}
    {page&&!page.items.length&&<Text style={{color:c.muted,lineHeight:24}}>还没有可核对归属的连续对话。新的聊天完成后会出现在这里；旧的共享记录不会被归到你的名下。</Text>}
    {page?.next_offset!==null&&page?.next_offset!==undefined&&<Button disabled={busy||!online} onPress={()=>void run(async()=>{if(!page||page.next_offset===null)return;const next=await client().page(page.next_offset,page.snapshot);if(active())setPage(mergeSourcePages(page,next,page.next_offset));})}>加载更多对话</Button>}
    {waiting&&<View style={{gap:8}}><Text style={{color:c.muted,lineHeight:22}}>{waiting.error||'上次操作还没有收到回执，已留在这个身份下。'}</Text>{waiting.phase==='pending'&&<Button disabled={busy} loading={busy} onPress={()=>void run(()=>submit())}>取回原操作回执</Button>}</View>}
    <Button disabled={busy||waiting?.phase==='pending'} onPress={()=>void run(async()=>{const fresh=await client().page();if(!active())return;await adoptSourcePage(storage,scope,fresh);if(active()){setPage(fresh);setWaiting(null);setSelected(null);setOnline(true);}})}>重新读取来源范围</Button>
    <Text style={{color:c.muted,fontSize:12,lineHeight:21}}>此设置只控制对话历史检索和续接。已保存的记忆、文件、目标及其他记录仍可使用，需要在各自页面管理。历史与备份不会被删除；这不代表彻底遗忘。目前排除后不提供恢复引用。</Text>
    {!!notice&&<Text accessibilityLiveRegion="polite" style={{color:c.muted,lineHeight:23}}>{notice}</Text>}
    <Sheet visible={!!selected} onDismiss={()=>{if(!busy)setSelected(null);}} title="以后不再引用这段对话" subtitle={selected?.title} footer={<Button mode="contained" disabled={disabled||!selected||!page} loading={busy} onPress={()=>void run(async()=>{if(!selected||!page)return;await submit({source_id:selected.source_id,source_revision:selected.source_revision,revision:page.revision,request_key:Crypto.randomUUID()});})}>确认停止引用</Button>}>
      <Text style={{color:c.ink,lineHeight:25}}>这会排除整段连续会话及其压缩后继，并让后续消息从新的上下文开始。已排队但尚未运行的消息也会使用新上下文。</Text>
      <Text style={{color:c.muted,lineHeight:23,marginTop:14}}>历史仍可查看。已保存的记忆、文件和目标不会删除；本页暂不提供恢复引用。若这个身份仍有运行中或待核对的任务，请先结束任务后再确认。</Text>
    </Sheet>
  </View>;
}
