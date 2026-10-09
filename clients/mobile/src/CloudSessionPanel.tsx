import {useEffect, useRef, useState} from 'react';
import {Platform, Text, View} from 'react-native';
import {Connection, scopeOf} from './core';
import {signIn, signOut} from './native-session';
import {useAppTheme} from './app-theme';
import {PrimaryButton} from './experience/primitives';

type Props = {connection: Connection | null; address: string; disabled?: boolean; onConnected: (connection: Connection) => Promise<void>};
export default function CloudSessionPanel(props: Props) {return <AccountSession key={props.connection ? scopeOf(props.connection) : 'signed-out'} {...props}/>;}
function AccountSession({connection,address,disabled,onConnected}: Props) {
  const {colors:c}=useAppTheme(), [busy,setBusy]=useState(false), [error,setError]=useState(''), [now,setNow]=useState(Date.now);
  const live=useRef(true), lock=useRef(false);
  useEffect(()=>{const timer=setInterval(()=>setNow(Date.now()),1000);return()=>{live.current=false;clearInterval(timer);};},[]);
  async function act(logout=false) {
    if(lock.current||disabled)return;
    lock.current=true;setBusy(true);setError('');
    try {const result=logout&&connection?await signOut(connection):await signIn(address);if(result&&live.current)await onConnected(result);}
    catch(error){if(live.current)setError(error instanceof Error?error.message:'这次登录没有完成，请重试。');}
    finally{lock.current=false;if(live.current)setBusy(false);}
  }
  if(Platform.OS==='web')return null;
  const session=connection?.session, signedIn=!!session?.accessToken&&Date.parse(session.expiresAt)>now;
  return <View style={{gap:14}}>
    <Text style={{color:c.ink,fontSize:18,fontWeight:'600'}}>{signedIn?'你的账户':'登录 Pajio'}</Text>
    <Text style={{color:c.muted,fontSize:14,lineHeight:23}}>{signedIn?'任务和结果保存在你的私人空间。退出后本机草稿仍会保留。':'填入邀请中的服务地址，通过系统浏览器登录。账户验证完成后会自动回到这里。'}</Text>
    {session?<Text style={{color:c.muted,fontSize:13}}>私人空间 · {session.tenantId}</Text>:null}
    {error?<Text accessibilityLiveRegion="polite" style={{color:c.danger,lineHeight:22}}>{error}</Text>:null}
    <PrimaryButton label={signedIn?'重新登录或更换账户':'登录我的账户'} disabled={!!disabled||busy} loading={busy} onPress={()=>{void act();}}/>
    {session?.accessToken?<PrimaryButton tone="quiet" label="退出此账户" disabled={!!disabled||busy} onPress={()=>{void act(true);}}/>:null}
  </View>;
}
