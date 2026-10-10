import {useEffect, useLayoutEffect, useRef, useState, type ReactNode} from 'react';
import {AppState, StyleSheet, Text, View} from 'react-native';
import {Check, Circle, Monitor, Server, Smartphone} from 'lucide-react-native';
import {useAppTheme, useThemedStyles, type AppColors} from './app-theme';
import {BrandWordmark} from './BrandWordmark';
import {type Connection} from './core';
import {accountWorkAllowed, registerAccountWork} from './account-work';
import {PrimaryButton, TactilePressable} from './experience/primitives';
import {ReadOnlyPoll, type ReadPollState} from './read-only-poll';
import {ProvisioningError, readProvisioning, type ProvisioningSnapshot} from './provisioning-client';
import {serviceFetch} from './transport';

type Props = {connection:Connection; isCurrent:()=>boolean; onReady:(snapshot:ProvisioningSnapshot)=>void; account:ReactNode};
const labels = {core:'Pajio 助手',linux:'你的 Linux 电脑',android:'你的 Android 手机'} as const;
const states = {pending:'等待准备',preparing:'正在准备',ready:'已准备好',needs_review:'需要核对'} as const;
/** This panel does not mount the Core, queue senders, or device viewers while delivery is unconfirmed. */
export function NativeProvisioningPanel({connection,isCurrent,onReady,account}: Props) {
  const {colors:c}=useAppTheme(), s=useThemedStyles(styles);
  const [snapshot,setSnapshot]=useState<ProvisioningSnapshot|null>(null), [error,setError]=useState(''), [expired,setExpired]=useState(false), [showAccount,setShowAccount]=useState(false);
  const [pollState,setPollState]=useState<ReadPollState>({busy:false,stopped:false,exhausted:false});
  const accountOpen=useRef(false);
  const callbacks=useRef({isCurrent,onReady});
  useLayoutEffect(()=>{callbacks.current={isCurrent,onReady};},[isCurrent,onReady]);
  const pollRef=useRef<ReadOnlyPoll<ProvisioningSnapshot>|null>(null);
  useEffect(()=>{
    let live=true;
    const current=()=>live&&callbacks.current.isCurrent()&&accountWorkAllowed(connection);
    const poll=new ReadOnlyPoll<ProvisioningSnapshot>({
      read:signal=>{if(!current())throw new ProvisioningError('unconfirmed');return readProvisioning(connection,signal,serviceFetch);},
      accept:value=>{
        if(!current())return null;
        setSnapshot(value);setError('');setExpired(false);
        if(value.state==='ready'){callbacks.current.onReady(value);return null;}
        return value.state==='needs_review'?null:value.retry_after*1000;
      },
      error:cause=>{
        if(!current())return true;
        const error=cause instanceof ProvisioningError?cause:new ProvisioningError('unconfirmed');
        setError(error.message);setExpired(error.code==='expired');return error.code==='expired';
      },change:state=>{if(current())setPollState(state);},limit:20,
    });
    pollRef.current=poll;
    const stop=registerAccountWork(connection,async()=>{poll.dispose();});
    const subscription=AppState.addEventListener('change',state=>poll.setForeground(state==='active'&&!accountOpen.current));
    poll.setForeground(AppState.currentState==='active');
    return()=>{live=false;poll.dispose();stop();subscription.remove();if(pollRef.current===poll)pollRef.current=null;};
  },[connection]);
  const review=snapshot?.state==='needs_review';
  return <View style={s.root}>
    <BrandWordmark width={56} color={c.ink}/>
    <Text accessibilityRole="header" style={s.title}>{expired?'重新确认登录':review?'准备需要核对':'正在准备你的 Pajio'}</Text>
    <Text style={s.lead}>{expired?'请重新验证账号。本机记录会保留。':review?'有一项准备需要处理。请联系邀请人，稍后再来核对。':'账号已登录。助手、独立电脑和手机准备好后，会在这里带你进入。'}</Text>
    <View style={s.members}>
      {(['core','linux','android'] as const).map(key=>{const status=snapshot?.members[key].state, Icon=key==='core'?Server:key==='linux'?Monitor:Smartphone;return <View key={key} style={s.member} accessibilityLabel={labels[key]+'，'+(status?states[status]:'正在核对')}>
        <Icon size={21} color={c.muted}/><Text style={s.label}>{labels[key]}</Text><Text style={[s.status,status==='needs_review'&&{color:c.danger}]}>{status?states[status]:'正在核对'}</Text>
        {status==='ready'?<Check size={18} color={c.accentInk}/>:<Circle size={14} color={c.line}/>}</View>;})}
    </View>
    {error?<Text accessibilityRole="alert" accessibilityLiveRegion="polite" style={s.error}>{error}</Text>:null}
    {!expired&&(pollState.exhausted||pollState.stopped)&&!review?<Text style={s.note}>自动核对已暂停。可以稍后刷新；准备工作不受影响。</Text>:null}
    <PrimaryButton label={pollState.busy?'正在核对…':'刷新准备状态'} loading={pollState.busy} disabled={pollState.busy||expired} onPress={()=>{if(callbacks.current.isCurrent())pollRef.current?.refresh();}}/>
    <Text style={s.note}>可以离开 App。回来后可继续核对，不会重复创建环境。</Text>
    <TactilePressable accessibilityLabel={showAccount?'收起账户选项':'重新登录或退出账户'} onPress={()=>{accountOpen.current=!accountOpen.current;pollRef.current?.setForeground(AppState.currentState==='active'&&!accountOpen.current);setShowAccount(accountOpen.current);}} style={s.accountButton}><Text style={s.accountLabel}>{showAccount?'收起账户选项':'重新登录或退出账户'}</Text></TactilePressable>
    {showAccount||expired?<View style={s.account}>{account}</View>:null}
  </View>;
}
const styles=(c:AppColors)=>StyleSheet.create({root:{width:'100%',maxWidth:440,alignSelf:'center',gap:18,paddingBottom:32},title:{fontSize:28,lineHeight:36,fontWeight:'700',color:c.ink,marginTop:54},lead:{fontSize:15,lineHeight:25,color:c.muted},members:{marginVertical:10,borderTopWidth:1,borderColor:c.line},member:{flexDirection:'row',alignItems:'center',gap:12,minHeight:68,borderBottomWidth:1,borderColor:c.line},label:{flex:1,fontSize:15,color:c.ink},status:{fontSize:12,color:c.muted},note:{fontSize:13,lineHeight:22,color:c.muted},error:{fontSize:13,lineHeight:22,color:c.danger},accountButton:{minHeight:44,alignItems:'center',justifyContent:'center'},accountLabel:{fontSize:14,color:c.accentInk},account:{borderTopWidth:1,borderColor:c.line,paddingTop:24}});
