import {useEffect,useLayoutEffect,useRef,useState} from 'react';
import {ActivityIndicator,AppState,BackHandler,Linking,Platform,Text,View} from 'react-native';
import {CalendarDays,ChevronRight,Cloud,ArrowLeft} from 'lucide-react-native';
import {accountWorkAllowed} from './account-work';
import {useAppTheme} from './app-theme';
import {CloudAppsApi,officialFeishuUrl,type CloudState} from './cloud-apps-model';
import {scopeOf,type Connection} from './core';
import {PrimaryButton,TactilePressable} from './experience/primitives';
import {NativeSyncPanel} from './NativeSyncPanel';
import {serviceFetch} from './transport';
import {OnboardingActivity} from './onboarding-client';
import {onboardingCloudStatus} from './onboarding-connection-state';
import type {OnboardingValues} from './onboarding-model';
import {storage} from './storage';
import {syncKey,type SyncLocal} from './native-sync-model';
import {validateSyncLocal} from './native-sync-engine';

/** Reads saved settings and authorization metadata, never device or cloud content. */
export function OnboardingSourceSummary({connection,isCurrent,feishu}:{connection:Connection;isCurrent:()=>boolean;feishu:boolean}){
  const {colors:c}=useAppTheme();
  const [native,setNative]=useState('正在核对本机来源…'),[cloud,setCloud]=useState(feishu?'正在核对飞书连接…':'');
  const current=useRef(isCurrent);useLayoutEffect(()=>{current.current=isCurrent;},[isCurrent]);
  useEffect(()=>{let live=true;const active=()=>live&&current.current()&&accountWorkAllowed(connection);
    void storage.get<SyncLocal>(syncKey(scopeOf(connection))).then(raw=>{const value=validateSyncLocal(raw);if(active())setNative(value?.desired.enabled?`本机同步已启用 · ${value.desired.sources.length} 个所选列表${value.error?' · 需要检查连接':value.pending?' · 有更新待同步':''}`:'本机来源 · 未启用同步');}).catch(()=>{if(active())setNative('本机来源状态暂时无法读取');});
    if(feishu)void new CloudAppsApi(connection,async(url,init)=>{if(!active())throw new Error('连接已停止');return serviceFetch(url,init);}).list().then(value=>{const status=onboardingCloudStatus(value);if(active())setCloud(status==='revoking'?'飞书 · 原授权正在撤销':status==='connected'?'飞书 · 已授权，本次未读取正文':status==='authorizing'?'飞书 · 授权尚待完成':'飞书 · 尚未连接');}).catch(()=>{if(active())setCloud('飞书连接状态暂时无法读取');});
    return()=>{live=false;};
  },[connection,feishu]);
  return <View style={{gap:5}}><Text style={{fontSize:14,lineHeight:22,color:c.muted}}>{native}</Text>{cloud?<Text style={{fontSize:14,lineHeight:22,color:c.muted}}>{cloud}</Text>:null}</View>;
}

export function OnboardingConnections({connection,values,isCurrent,onBranchChange}:{connection:Connection;values:OnboardingValues;isCurrent:()=>boolean;onBranchChange?:(open:boolean)=>void}){
  const {colors:c}=useAppTheme();
  const [branch,setBranch]=useState<'calendar'|'feishu'|null>(null);
  const [cloud,setCloud]=useState<CloudState|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState('');
  const locked=useRef(false);
  const [session]=useState(()=>new OnboardingActivity(()=>isCurrent()&&accountWorkAllowed(connection)));
  const allowed=session.active;
  const [api]=useState(()=>new CloudAppsApi(connection,async(url,init)=>{if(!allowed())throw new Error('连接已停止');return serviceFetch(url,init);}));
  useLayoutEffect(()=>{session.update(()=>isCurrent()&&accountWorkAllowed(connection));},[session,isCurrent,connection]);
  const load=async()=>{if(locked.current||!allowed())return;locked.current=true;setBusy(true);setError('');try{const next=await api.list();if(allowed())setCloud(next);}catch{if(allowed())setError('暂时无法读取飞书连接，可以稍后再来。');}finally{locked.current=false;if(allowed())setBusy(false);}};
  useEffect(()=>{session.mount();return()=>{session.stop();};},[session]);
  const openBranch=(next:typeof branch)=>{setBranch(next);onBranchChange?.(!!next);if(next==='feishu')void load();};
  const openAuthorization=async(url:string)=>{if(!allowed()||!officialFeishuUrl(url))return;try{await Linking.openURL(url);}catch{if(allowed())setError('授权页面暂时无法打开，请重试。');}};
  const authorize=async()=>{if(!cloud?.configured||!cloud.revision||cloud.revocation_pending||locked.current||!allowed())return;locked.current=true;setBusy(true);setError('');try{const next=await api.authorize(cloud.revision);if(allowed()){setCloud(next);if(next.authorization)await openAuthorization(next.authorization.url);}}catch{if(allowed())setError('授权尚未完成，请重试或稍后设置。');}finally{locked.current=false;if(allowed())setBusy(false);}};
  const checkAuthorization=async()=>{if(!cloud?.authorization||locked.current||!allowed())return;locked.current=true;setBusy(true);setError('');try{const next=await api.poll(cloud.authorization.id);if(allowed())setCloud(next);}catch{if(allowed())setError('还没能确认授权结果，请重试。');}finally{locked.current=false;if(allowed())setBusy(false);}};
  const refreshRef=useRef(()=>{});useLayoutEffect(()=>{refreshRef.current=()=>{if(cloud?.authorization)void checkAuthorization();else void load();};});
  useEffect(()=>{if(!branch)return;const back=BackHandler.addEventListener('hardwareBackPress',()=>{setBranch(null);onBranchChange?.(false);return true;});return()=>back.remove();},[branch,onBranchChange]);
  useEffect(()=>{if(branch!=='feishu')return;const listener=AppState.addEventListener('change',state=>{if(state==='active')refreshRef.current();});const timer=cloud?.authorization?setInterval(()=>{if(AppState.currentState==='active')refreshRef.current();},Math.max(5,cloud.authorization.interval)*1000):null;return()=>{listener.remove();if(timer)clearInterval(timer);};},[branch,cloud?.authorization]);
  const copy={fontSize:14,lineHeight:23,color:c.muted};
  const row={backgroundColor:c.surface,borderWidth:1,borderColor:c.line,borderRadius:22,padding:20,gap:14};
  const cloudStatus=cloud?onboardingCloudStatus(cloud):null;
  if(branch)return <View style={{gap:18}}>
    <TactilePressable accessibilityLabel="返回资料选择" onPress={()=>openBranch(null)} style={{minHeight:44,flexDirection:'row',alignItems:'center',gap:8}}><ArrowLeft size={20} color={c.ink}/><Text style={{color:c.ink,fontSize:15}}>返回资料选择</Text></TactilePressable>
    {branch==='calendar'?<NativeSyncPanel connection={connection}/>:<View style={row}>
      <Text style={{fontSize:20,fontWeight:'600',color:c.ink}}>飞书资料与日程</Text>
      {busy?<ActivityIndicator color={c.accent}/>:null}
      {cloud?<>
        <Text style={copy}>{cloudStatus==='revoking'?'原授权正在撤销，请完成后再连接。':cloudStatus==='connected'?'已授权。可访问的范围以飞书权限为准，完成引导不会自动读取文档。':cloud.configured?'允许 Pajio 访问你授权范围内的飞书资料。请先在授权页核对权限。':'这个服务尚未准备好飞书授权。你可以直接继续，之后在设置中连接。'}</Text>
        {cloudStatus==='authorizing'&&cloud.authorization?<>
          <Text style={copy}>需要时使用确认码：{cloud.authorization.user_code}</Text>
          <PrimaryButton label="打开飞书授权页" disabled={busy} onPress={()=>void openAuthorization(cloud.authorization!.url)}/>
          <PrimaryButton label="我已授权，检查结果" disabled={busy} tone="quiet" onPress={()=>void checkAuthorization()}/>
        </>:cloudStatus==='available'?<PrimaryButton label="前往飞书授权" disabled={busy} onPress={()=>void authorize()}/>:null}
        {cloudStatus==='connected'?<Text style={{...copy,color:c.success}}>飞书连接已建立 · 本次未读取正文</Text>:null}
      </>:!busy?<PrimaryButton label="重试读取连接状态" onPress={()=>void load()} tone="quiet"/>:null}
      {error?<Text accessibilityRole="alert" style={{...copy,color:c.danger}}>{error}</Text>:null}
    </View>}
  </View>;
  return <View style={{gap:14}}>
    <Text style={copy}>有现成的安排，可以少解释一些。每一项都由你决定，暂时不连接也可以继续。</Text>
    {Platform.OS!=='web'?<TactilePressable accessibilityLabel="选择日历与提醒事项资料" onPress={()=>openBranch('calendar')} style={{...row,flexDirection:'row',alignItems:'center'}}>
      <CalendarDays size={27} color={c.accent}/><View style={{flex:1,gap:5}}><Text style={{fontSize:17,fontWeight:'500',color:c.ink}}>{Platform.OS==='ios'?'日历与提醒事项':'系统日历'}</Text><Text style={copy}>由你选择要同步的列表，让安排出现在「今天」。</Text></View><ChevronRight size={19} color={c.muted}/>
    </TactilePressable>:<Text style={copy}>本机日历与提醒事项，请在手机 App 中连接。</Text>}
    {values.apps.includes('feishu')?<TactilePressable accessibilityLabel="查看飞书是否可以授权" onPress={()=>openBranch('feishu')} style={{...row,flexDirection:'row',alignItems:'center'}}>
      <Cloud size={27} color={c.accent}/><View style={{flex:1,gap:5}}><Text style={{fontSize:17,fontWeight:'500',color:c.ink}}>飞书</Text><Text style={copy}>查看当前服务是否已准备好资料与日历授权。</Text></View><ChevronRight size={19} color={c.muted}/>
    </TactilePressable>:null}
    <Text style={copy}>微信、抖音和小红书的历史不会因为选择了应用而被读取。之后可以把需要处理的链接或截图分享给 Pajio。</Text>
  </View>;
}
