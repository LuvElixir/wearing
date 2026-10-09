import {useCallback,useEffect,useRef,useState} from 'react';
import {AppState} from 'react-native';
import {scopeOf,type Connection} from './core';
import {storage} from './storage';
import {serviceFetch} from './transport';
import {NativeSyncClient} from './native-sync-client';
import {calendarSourceIndex,sourceIndexKey,type CalendarSourceIndex} from './calendar-sources';

export function useCalendarSources(connection:Connection,refreshKey:string,isCurrent:()=>boolean) {
  const [index,setIndex]=useState<CalendarSourceIndex|null>(null),[error,setError]=useState(''),[busy,setBusy]=useState(false),[stale,setStale]=useState(true);
  const [request,setRequest]=useState(0);const refresh=useCallback(()=>setRequest(v=>v+1),[]);
  const generation=useRef(0),scope=scopeOf(connection);
  useEffect(()=>{
    const ticket=++generation.current;let mounted=true,controller:AbortController|null=null,loads=0;
    const valid=()=>mounted&&ticket===generation.current&&isCurrent();
    const active=()=>valid()&&(AppState.currentState===null||AppState.currentState==='active');
    async function load(){
      ++loads;
      controller?.abort();controller=new AbortController();const own=controller;
      const current=()=>active()&&!own.signal.aborted;
      if(!current())return;setBusy(true);setError('');
      try{
        // index() never uses an installation key: the server scopes all display rows to the trusted owner.
        const result=await new NativeSyncClient(connection,'',serviceFetch,current,own.signal).index();
        if(!current())return;
        await storage.put(sourceIndexKey(scope),result);
        if(current()){setIndex(result);setStale(false);}
      }catch(e){if(current()){setError(e instanceof Error?e.message:'日历来源暂未更新。');setStale(true);}}
      finally{if(valid()&&own===controller)setBusy(false);}
    }
    async function start(){
      try{const saved=await storage.get<CalendarSourceIndex>(sourceIndexKey(scope));if(saved&&valid()&&loads===0){setIndex(calendarSourceIndex(saved));setStale(true);}}
      catch{if(valid())setError('本机来源缓存未能读取。');}
      if(valid())await load();
    }
    const app=AppState.addEventListener('change',state=>{controller?.abort();if(state==='active')void load();else if(valid()){setBusy(false);setStale(true);}});
    void start();return()=>{mounted=false;controller?.abort();app.remove();};
    // isCurrent closes over the connection owned by this mounted panel; the parent checks its current ref.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  },[connection,scope,refreshKey,request]);
  return {index,error,busy,stale,refresh};
}
