import {useEffect, useLayoutEffect, useRef} from 'react';
import {AppState} from 'react-native';
import {scopeOf, type Connection} from './core';
import {observeNativeSync, performNativeSync} from './native-sync-runtime';

/** Foreground only, independent of the visible tab. No OS background scheduling claim. */
export function NativeSyncSession({connection,onRecordsChanged,isCurrent}:{connection:Connection;onRecordsChanged:()=>void;isCurrent:()=>boolean}) {
  const latest = useRef(onRecordsChanged);
  useLayoutEffect(()=>{latest.current=onRecordsChanged;},[onRecordsChanged]);
  const scope=scopeOf(connection), credential=connection.session?.accessToken || connection.development?.accessToken || '';
  useEffect(()=>{
    let mounted=true,running=false,pending=false,controller:AbortController|null=null,timer:ReturnType<typeof setTimeout>|undefined;
    const active=()=>mounted && isCurrent() && AppState.currentState==='active';
    const stop=()=>{controller?.abort();if(timer)clearTimeout(timer);};
    async function tick() {
      if(!active())return;
      if(running){pending=true;return;}
      running=true;controller=new AbortController();
      try {await performNativeSync(connection,active,controller.signal,()=>{if(active())latest.current();});} catch { /* Scoped status is shown in the source panel; keep foreground retry bounded. */ }
      finally {running=false;if(active()){const delay=pending?0:60000;pending=false;timer=setTimeout(()=>void tick(),delay);}}
    }
    const app=AppState.addEventListener('change',state=>{stop();if(state==='active')void tick();});
    const changed=observeNativeSync(value=>{if(value.scope!==scope)return;stop();if(value.run)void tick();});
    void tick();
    return()=>{mounted=false;stop();app.remove();changed();};
    // The immutable credential and canonical scope own this foreground reader.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  },[connection,scope,credential]);
  return null;
}
