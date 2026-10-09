import {useEffect,useRef,useState} from 'react';
import {Platform,Text,View} from 'react-native';
import {useAppTheme} from './app-theme';
import {PrimaryButton,TactilePressable} from './experience/primitives';
import {scopeOf,type Connection} from './core';
import {storage} from './storage';
import {syncKey,sourceKey,type SyncLocal,type SyncSource} from './native-sync-model';
import {validateSyncLocal} from './native-sync-engine';
import {discoverNativeSyncSources,requestNativeSync,saveNativeSyncChoice} from './native-sync-runtime';

export function NativeSyncPanel({connection}:{connection:Connection}) {return <Content key={scopeOf(connection)} connection={connection}/>;}
function Content({connection}:{connection:Connection}) {
  const {colors:c}=useAppTheme(),scope=scopeOf(connection);
  const [state,setState]=useState<SyncLocal|null>(null),[sources,setSources]=useState<SyncSource[]>([]),[selected,setSelected]=useState<SyncSource[]>([]);
  const [ready,setReady]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState('');
  const alive=useRef(false),locked=useRef(false);
  const [unavailable,setUnavailable]=useState<string[]>([]);
  useEffect(()=>{alive.current=true;return()=>{alive.current=false;};},[]);
  useEffect(()=>{let live=true,first=true;
    const load=async()=>{try{const next=validateSyncLocal(await storage.get<SyncLocal>(syncKey(scope)));if(live){setState(next);setReady(true);if(first){setSelected(next?.desired.sources||[]);setSources(next?.desired.sources||[]);first=false;}}}catch{if(live)setError('无法读取同步设置，请返回后重试。');}};
    void load();const timer=setInterval(()=>void load(),1500);return()=>{live=false;clearInterval(timer);};
  },[scope]);
  const run=async(work:()=>Promise<void>)=>{if(locked.current||!alive.current)return;locked.current=true;setBusy(true);setError('');setNotice('');try{await work();}catch(e){if(alive.current)setError(e instanceof Error?e.message:'这次未完成。');}finally{locked.current=false;if(alive.current)setBusy(false);}};
  const discover=(kind:SyncSource['kind'])=>run(async()=>{const rows=await discoverNativeSyncSources(kind);if(!alive.current)return;
    const missing=selected.filter(s=>s.kind===kind&&!rows.some(row=>row.id===s.id));
    setSources(current=>[...current.filter(s=>s.kind!==kind),...rows,...missing]);
    setUnavailable(current=>[...current.filter(key=>!sources.filter(s=>s.kind===kind).some(s=>sourceKey(s)===key)),...missing.map(sourceKey)]);
    setNotice(missing.length?'部分已选来源暂时不可用，可取消勾选后保存。已有副本保留。':rows.length?'请勾选要同步的列表，再点启用。':'这个系统来源没有可用列表。');});
  const changed=JSON.stringify(selected)!==JSON.stringify(state?.desired.sources||[]);
  const save=(enabled:boolean)=>run(async()=>{const next=await saveNativeSyncChoice(connection,{enabled,sources:selected});if(!alive.current)return;setState(next);setNotice(enabled?'已保存选择，前台连接可用时开始同步。':'已在这台手机停止同步，已有副本保留。');});
  return <View style={{backgroundColor:c.surface,borderRadius:24,padding:20,gap:14}}>
    <Text style={{fontSize:20,fontWeight:'600',color:c.ink}}>同步到今天</Text>
    <Text style={{fontSize:14,lineHeight:23,color:c.muted}}>选择哪些日历和提醒列表出现在 Pajio。仅在 App 前台更新，日历范围为过去 7 天至未来 30 天；提醒事项每列表最多 500 条。</Text>
    <Text style={{fontSize:13,lineHeight:21,color:c.muted}}>这是单向副本，修改 Pajio 不会修改系统原件。你手动改过的副本会保留；系统删除、来源丢失或移出读取范围不会自动删除副本。</Text>
    <Text style={{fontSize:13,lineHeight:21,color:c.muted}}>副本保存在当前身份，沿用这个身份的可见范围。</Text>
    <PrimaryButton label="选择系统日历" tone="quiet" disabled={busy||!ready} onPress={()=>void discover('event')}/>
    {Platform.OS==='ios'&&<PrimaryButton label="选择提醒事项列表" tone="quiet" disabled={busy||!ready} onPress={()=>void discover('reminder')}/>}
    {sources.map(source=>{const checked=selected.some(s=>sourceKey(s)===sourceKey(source));return <TactilePressable key={sourceKey(source)} accessibilityRole="checkbox" accessibilityState={{checked}} disabled={busy} onPress={()=>setSelected(current=>checked?current.filter(s=>sourceKey(s)!==sourceKey(source)):[...current,source])} style={{paddingVertical:12,minHeight:44}}><Text style={{fontSize:16,color:c.ink}}>{checked?'✓  ':'○  '}{source.title}</Text><Text style={{fontSize:12,color:c.muted}}>{source.kind==='event'?'系统日历':'系统提醒事项'}{unavailable.includes(sourceKey(source))?' · 暂时不可用':''}</Text></TactilePressable>;})}
    <PrimaryButton label={state?.desired.enabled?'保存来源选择':'启用所选来源同步'} disabled={busy||!ready||!selected.length||(!!state?.desired.enabled&&!changed)} loading={busy} onPress={()=>void save(true)}/>
    {state?.desired.enabled&&<><PrimaryButton label="立即更新所选来源" tone="quiet" disabled={busy||changed} onPress={()=>{requestNativeSync(scope);setNotice('已请求重新读取所选来源。');}}/><PrimaryButton label="停止同步" tone="quiet" disabled={busy} onPress={()=>void save(false)}/></>}
    <Text accessibilityLiveRegion="polite" style={{fontSize:13,lineHeight:21,color:c.muted}}>{state?.desired.enabled?'已启用 · App 前台更新':'未启用同步'}{state?.pending?' · 有一批更新等待连接恢复':''}</Text>
    {state?.receipt&&<Text style={{fontSize:13,lineHeight:21,color:c.muted}}>上次更新 {new Date(state.receipt.observed_at).toLocaleString('zh-CN')} · 新增 {state.receipt.created} · 更新 {state.receipt.updated}{state.receipt.conflicts?` · ${state.receipt.conflicts} 条保留你的修改`:''}{state.receipt.unseen?` · ${state.receipt.unseen} 条本轮未看到，仍保留`:''}</Text>}
    {!!state?.receipt?.truncated&&<Text style={{fontSize:13,lineHeight:21,color:c.muted}}>本轮来源超过 500 条，只保存读取到的前 500 条；其余记录未作缺失判断。</Text>}
    {!!(error||state?.error)&&<Text accessibilityRole="alert" style={{color:c.danger,lineHeight:22}}>{error||state?.error}</Text>}
    {!!notice&&<Text accessibilityLiveRegion="polite" style={{color:c.success,lineHeight:22}}>{notice}</Text>}
  </View>;
}
