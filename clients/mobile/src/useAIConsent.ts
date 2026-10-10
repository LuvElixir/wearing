import {useCallback,useEffect,useLayoutEffect,useRef,useState} from 'react';
import {AppState} from 'react-native';
import * as Crypto from 'expo-crypto';
import {accountWorkAllowed,registerAccountWork} from './account-work';
import {AIConsentClient,AIConsentGate,needsAIConsent,type AIConsentAction,type AIConsentSnapshot} from './ai-consent-client';
import type {Connection} from './core';
import {serviceFetch} from './transport';

type State={connection:Connection|null;snapshot:AIConsentSnapshot|null;busy:boolean;error:string};
const empty:State={connection:null,snapshot:null,busy:false,error:''};
export function useAIConsent(connection:Connection|null, enabled:boolean) {
  const gate=useRef(new AIConsentGate()), active=useRef(connection), request=useRef<AbortController|null>(null);
  const [state,setState]=useState<State>(empty);
  // Invalidate synchronously with the activation; old UI state is also filtered by connection below.
  useLayoutEffect(()=>{active.current=connection;gate.current.activate(connection);request.current?.abort();request.current=null;},[connection]);
  const perform=useCallback(async(action?:AIConsentAction, prior?:AIConsentSnapshot)=>{
    if(!connection||active.current!==connection||!enabled||!needsAIConsent(connection)||!accountWorkAllowed(connection)||AppState.currentState!=='active'||request.current)return;
    const controller=new AbortController();request.current=controller;gate.current.invalidate(connection);
    setState(previous=>({...((previous.connection===connection)?previous:empty),connection,busy:true,error:''}));
    const current=()=>active.current===connection&&request.current===controller&&!controller.signal.aborted&&accountWorkAllowed(connection);
    try{
      const client=new AIConsentClient(connection,serviceFetch);
      const value=action&&prior?await client.change(action,prior,Crypto.randomUUID().replace(/-/g,''),controller.signal):await client.read(controller.signal);
      if(current()){gate.current.observe(connection,value);setState({connection,snapshot:value,busy:false,error:''});}
    }catch(cause){if(current())setState({connection,snapshot:null,busy:false,error:cause instanceof Error?cause.message:'暂时无法确认授权状态，请刷新核对。'});}
    finally{if(request.current===controller)request.current=null;}
  },[connection,enabled]);
  useEffect(()=>{
    if(!connection||!enabled||!needsAIConsent(connection))return;
    let live=true;
    void Promise.resolve().then(()=>{if(live)void perform();});
    const invalidate=()=>{request.current?.abort();request.current=null;gate.current.invalidate(connection);};
    const stop=()=>{invalidate();if(live&&active.current===connection)setState(previous=>({...previous,busy:false}));};
    const subscription=AppState.addEventListener('change',value=>{if(value==='active')void perform();else stop();});
    const unregister=registerAccountWork(connection,async()=>{stop();});
    return()=>{live=false;subscription.remove();unregister();invalidate();};
  },[connection,enabled,perform]);
  const shown=state.connection===connection?state:empty;
  return {...shown,allows:(candidate:Connection)=>gate.current.allows(candidate),refresh:()=>perform(),change:(action:AIConsentAction)=>shown.snapshot?perform(action,shown.snapshot):Promise.resolve()};
}
