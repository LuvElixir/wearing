import {test} from 'node:test';
import assert from 'node:assert/strict';
import {type Connection,type Store} from './core';
import {NotificationClient} from './notification-client';
import {logoutSession} from './session-logout';
import {registeredNotificationInstallation,notificationRegistrationKey} from './notification-registration';
import {accountCleanupPlan} from './account-cleanup-model';
const connection:Connection={endpoint:'https://pajio.luckyloading.com/',identity:'daily',session:{accessToken:'t'.repeat(64),expiresAt:'2099-01-01T00:00:00Z',userId:'user_'+'a'.repeat(32),tenantId:'synthetic',credentialId:'c'.repeat(32)}};
const installation='synthetic-installation',project='12345678-abcd-1234-abcd-123456789abc';
const receipt=(enabled=true)=>({identity_id:'daily',installation_id:installation,server_id:'a'.repeat(32),configured:true,project_id:project,enabled,reason:null,provider_status:'unverified',provider_error:null,counts:{}});
const token='ExpoPushToken[syntheticToken12345]';
const bootstrap={version:'0.2.0',token:'csrf',identities:[{id:'daily'}]};
const unsigned:Connection={endpoint:connection.endpoint,identity:'daily'};
function memory(){const data=new Map<string,unknown>();const store:Pick<Store,'get'|'put'>={get:async<T>(key:string)=>(data.get(key)??null)as T|null,put:async(key,value)=>{data.set(key,value);}};return{data,store};}
test('only actual validated register acknowledgement persists a session-bound receipt without a push token',async()=>{
 const {data,store}=memory();data.set('notification-installation:v1',installation);
 assert.equal(await registeredNotificationInstallation(store,connection),null);
 let enabled=false;const api=new NotificationClient(connection,installation,async url=>Response.json(String(url).endsWith('/api/bootstrap')?bootstrap:receipt(enabled)),store);
 await assert.rejects(api.register(token,project,'ios'));assert.equal(await registeredNotificationInstallation(store,connection),null);
 enabled=true;await api.register(token,project,'ios');assert.equal(await registeredNotificationInstallation(store,connection),installation);
 assert.equal(JSON.stringify([...data.values()]).includes(token),false);
 assert.equal(await registeredNotificationInstallation(store,{...connection,session:{...connection.session!,credentialId:'d'.repeat(32)}}),null);
 assert.equal(await registeredNotificationInstallation(store,{...connection,session:{...connection.session!,tenantId:'other'}}),null);
 assert.equal(await registeredNotificationInstallation(store,{...connection,identity:'work'}),installation);
 assert.ok(accountCleanupPlan(connection,[...data].map(([key,value])=>({key,value}))).remove.includes(notificationRegistrationKey(connection)));
});
test('fresh prepared session makes zero Core requests and clears credentials only after control-plane revocation',async()=>{
 const calls:string[]=[];const result=await logoutSession({registered:async()=>null,disable:async()=>{calls.push('core');},revoke:async()=>{calls.push('control');},clear:async()=>{calls.push('clear');return unsigned;}});
 assert.deepEqual(calls,['control','clear']);assert.equal(result.notificationsUnconfirmed,false);assert.equal(result.connection,unsigned);
});
test('Core offline failure never prevents control logout; revocation uncertainty must retain credentials',async()=>{
 const calls:string[]=[];const base={registered:async()=>installation,disable:async()=>{calls.push('core');throw Error('offline');},revoke:async()=>{calls.push('control');},clear:async()=>{calls.push('clear');return unsigned;}};
 const result=await logoutSession(base);assert.equal(result.notificationsUnconfirmed,true);assert.deepEqual(calls,['core','control','clear']);calls.length=0;
 await assert.rejects(logoutSession({...base,revoke:async()=>{calls.push('control');throw Error('response unknown');}}));assert.deepEqual(calls,['core','control']);
});
test('two-second policy is cancellable and bounded even if Core fetch never settles; late bootstrap cannot dispatch disable',async()=>{
 let release!:(value:Response)=>void, aborted=false;const paths:string[]=[];
 const api=new NotificationClient(connection,installation,async(url,init)=>{paths.push(new URL(String(url)).pathname);init!.signal!.addEventListener('abort',()=>{aborted=true;});return new Promise<Response>(r=>{release=r;});});
 const events:string[]=[];const result=await logoutSession({registered:async()=>installation,disable:(_,signal)=>api.disableInstallation(signal),timeoutMs:5,revoke:async()=>{events.push('control');},clear:async()=>{events.push('clear');return unsigned;}});
 assert.equal(result.notificationsUnconfirmed,true);assert.equal(aborted,true);assert.deepEqual(events,['control','clear']);assert.deepEqual(paths,['/api/bootstrap']);
 release(Response.json(bootstrap));await new Promise<void>(resolve=>setImmediate(resolve));assert.deepEqual(paths,['/api/bootstrap']);
});
test('matched installation disable acknowledges false before dropping only its exact receipt',async()=>{
 const{store}=memory();const api=new NotificationClient(connection,installation,async url=>Response.json(String(url).endsWith('/api/bootstrap')?bootstrap:receipt(!String(url).endsWith('/disable-installation'))),store);
 await api.register(token,project,'ios');const result=await logoutSession({registered:()=>registeredNotificationInstallation(store,connection),disable:(_,signal)=>api.disableInstallation(signal),revoke:async()=>{},clear:async()=>unsigned});
 assert.equal(result.notificationsUnconfirmed,false);assert.equal(await registeredNotificationInstallation(store,connection),null);
});
