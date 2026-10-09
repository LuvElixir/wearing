import {useEffect,useLayoutEffect,useRef,useState} from 'react';
import {accountWorkAllowed} from './account-work';
import type {Connection} from './core';
import {OnboardingApi} from './onboarding-client';
import type {OnboardingSnapshot} from './onboarding-model';
import {serviceFetch} from './transport';

/** A read-only gate. Unavailable or older servers never block an existing account. */
export function useOnboarding(connection:Connection|null,enabled:boolean){
  const [result,setResult]=useState<{connection:Connection;snapshot:OnboardingSnapshot}|null>(null);
  const current=useRef(connection);useLayoutEffect(()=>{current.current=connection;},[connection]);
  useEffect(()=>{
    if(!connection||!enabled||!connection.session?.accessToken)return;
    let live=true;const abort=new AbortController();
    const active=()=>live&&current.current===connection&&accountWorkAllowed(connection);
    void new OnboardingApi(connection,serviceFetch,active,abort.signal).load().then(snapshot=>{if(active())setResult({connection,snapshot});}).catch(()=>{});
    return()=>{live=false;abort.abort();};
  },[connection,enabled]);
  return result?.connection===connection?result.snapshot:null;
}
