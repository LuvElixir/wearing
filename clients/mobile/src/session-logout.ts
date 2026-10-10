import {type Connection} from './core';
type Options={registered:()=>Promise<string|null>;disable:(installation:string,signal:AbortSignal)=>Promise<unknown>;revoke:()=>Promise<void>;clear:()=>Promise<Connection>;timeoutMs?:number};
/** A Core notification failure must not block independent control-plane revocation. */
export async function logoutSession(options:Options):Promise<{connection:Connection;notificationsUnconfirmed:boolean}>{
 let notificationsUnconfirmed=false, installation:string|null=null;
 try{installation=await options.registered();}catch{notificationsUnconfirmed=true;}
 if(installation){
  const controller=new AbortController();let timer:ReturnType<typeof setTimeout>|undefined;
  try{
   const timeout=new Promise<never>((_,reject)=>{timer=setTimeout(()=>{controller.abort();reject(new Error('notification_disable_timeout'));},options.timeoutMs??2000);});
   await Promise.race([options.disable(installation,controller.signal),timeout]);
  }catch{notificationsUnconfirmed=true;}
  finally{if(timer)clearTimeout(timer);controller.abort();}
 }
 // No catch: an unknown revocation must retain the local credential for explicit recovery.
 await options.revoke();
 return {connection:await options.clear(),notificationsUnconfirmed};
}
