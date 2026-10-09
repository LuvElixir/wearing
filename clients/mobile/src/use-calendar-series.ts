import {useCallback,useEffect,useRef,useState} from 'react';
import {AppState} from 'react-native';
import {scopeOf,type Connection} from './core';
import {storage} from './storage';
import {serviceFetch} from './transport';
import {accountWorkAllowed,registerAccountWork} from './account-work';
import {CalendarSeriesClient} from './calendar-series-client';
import {seriesQuery,seriesStorageKey,type SeriesQuery} from './calendar-series-model';
let change=0;const listeners=new Set<()=>void>();
export function calendarSeriesChanged(){++change;for(const listener of listeners)listener();}
export function useCalendarSeries(connection:Connection,start:string,end:string,isCurrent:()=>boolean){
  const [loaded,setLoaded]=useState<{value:SeriesQuery;key:string}|null>(null),[busy,setBusy]=useState(false),[stale,setStale]=useState(true),[error,setError]=useState(''),[tick,setTick]=useState(change);
  const refresh=useCallback(()=>setTick(v=>v+1),[]),epoch=useRef(0),scope=scopeOf(connection),zone=Intl.DateTimeFormat().resolvedOptions().timeZone||'Asia/Shanghai';
  const viewKey=JSON.stringify([scope,connection.session?.credentialId||'',start,end,zone]);
  const snapshot=loaded?.key===viewKey?loaded.value:null;
  useEffect(()=>{listeners.add(refresh);return()=>{listeners.delete(refresh);};},[refresh]);
  useEffect(()=>{
    const own=++epoch.current;let live=true,controller:AbortController|null=null,loads=0;
    const valid=()=>live&&own===epoch.current&&isCurrent()&&accountWorkAllowed(connection);
    const active=()=>valid()&&(AppState.currentState===null||AppState.currentState==='active');
    // Two bounded snapshots per account: today and the currently viewed calendar range.
    const key=seriesStorageKey(scope)+(Date.parse(end)-Date.parse(start)<=2*86400000?':today':':calendar');
    async function load(){
      ++loads;controller?.abort();controller=new AbortController();const handle=controller,current=()=>active()&&!handle.signal.aborted;
      if(!current())return;setBusy(true);setError('');
      try{const result=await new CalendarSeriesClient(connection,serviceFetch,current,handle.signal).query(start,end,zone);if(!current())return;await storage.put(key,result);if(current()){setLoaded({value:result,key:viewKey});setStale(false);}}
      catch(e){if(current()){setStale(true);setError(e instanceof Error?e.message:'重复日程暂未更新。');}}
      finally{if(valid()&&handle===controller)setBusy(false);}
    }
    async function begin(){setLoaded(null);setStale(true);try{const cache=await storage.get<SeriesQuery>(key);if(cache&&cache.start===start&&cache.end===end&&cache.timezone===zone&&valid()&&loads===0)setLoaded({value:seriesQuery(cache,connection.identity,start,end,zone),key:viewKey});}catch{if(valid())setError('重复日程缓存无法核对。');}if(valid())await load();}
    const app=AppState.addEventListener('change',state=>{controller?.abort();if(state==='active')void load();else if(valid()){setBusy(false);setStale(true);}});
    const stop=registerAccountWork(connection,async()=>{controller?.abort();});void begin();
    return()=>{live=false;controller?.abort();app.remove();stop();};
    // Parent current ref closes the React pending-unmount window.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  },[connection,scope,start,end,zone,viewKey,tick]);
  return {items:snapshot?.items||[],snapshot,busy,stale:stale||!snapshot,error:loaded&&loaded.key!==viewKey?'':error,refresh};
}
