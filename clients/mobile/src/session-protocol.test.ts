import {test} from 'node:test';
import assert from 'node:assert/strict';
import {AuthorizationFlow, authorizationCode, authorizationURL, forgetSession, loadConnection, saveConnection, sessionReceipt, Vault} from './session-protocol';
import {connectionEndpoint, connectionHeaders, scopeOf, Store} from './core';
import {initialConnection, PUBLIC_PAJIO_ENDPOINT} from './connection-default';
const state='s'.repeat(48),code='c'.repeat(43),verifier='v'.repeat(64), token='t'.repeat(64);
const callback='pajio://auth?code='+code+'&state='+state;
const receipt = () => ({token_type:'Bearer',access_token:token,expires_at:new Date(Date.now()+3600000).toISOString(),user_id:'user_'+'a'.repeat(32),tenant_id:'tenant-a'});
const connection=()=>sessionReceipt('https://pajio.example',receipt(),'d'.repeat(32));
class Memory implements Pick<Store,'get'|'put'>, Vault {
 data=new Map<string,unknown>();
 async get<T=string>(key:string){return structuredClone(this.data.get(key)??null) as T|null;}
 async put(key:string,value:unknown){this.data.set(key,structuredClone(value));}
 async remove(key:string){this.data.delete(key);}
}
test('callback binds exact origin, single code and state, without extra fields',()=>{
 assert.equal(authorizationCode(callback,state),code);
 for(const url of [callback.replace('pajio:','https:'),callback.replace('//auth','//auth.evil'),callback.replace('//auth','//u@auth'),callback.replace('?','/?'),callback+'&state='+state,callback+'&code='+code,callback+'#x',callback+'&token=x',callback.replace(state,'x'.repeat(48))]) assert.throws(()=>authorizationCode(url,state));
 assert.throws(()=>authorizationURL('http://127.0.0.1','a'.repeat(43),state));
 assert.equal(new URL(authorizationURL('https://pajio.example','a'.repeat(43),state)).pathname,'/auth/mobile/start');
});
test('invite entry carries only its fixed selector alongside PKCE; account login remains compatible',()=>{
 const origin='https://pajio.luckyloading.com/',challenge='a'.repeat(43);
 const invite=new URL(authorizationURL(origin,challenge,state,'invite'));
 assert.equal(invite.origin,'https://pajio.luckyloading.com');assert.equal(invite.pathname,'/auth/mobile/start');
 assert.deepEqual([...invite.searchParams], [['challenge',challenge],['state',state],['entry','invite']]);
 const account=new URL(authorizationURL(origin,challenge,state,'account'));
 assert.equal(account.searchParams.has('entry'),false);assert.equal(account.searchParams.has('return'),false);
 assert.throws(()=>authorizationURL(origin,challenge,state,'https://other.invalid/' as 'invite'));
});
test('receipt validates token, identity, expiry and HTTPS before exposing a session',()=>{
 for(const patch of [{token_type:'Basic'},{access_token:'bad'},{expires_at:'bad'},{expires_at:new Date(0).toISOString()},{expires_at:new Date(Date.now()+86400000).toISOString()},{user_id:'user_?'},{tenant_id:'a/b'}]) assert.throws(()=>sessionReceipt('https://pajio.example',{...receipt(),...patch},'d'.repeat(32)));
 assert.throws(()=>sessionReceipt('http://127.0.0.1',receipt(),'d'.repeat(32)));
 assert.equal(connectionHeaders(connection()).Authorization,'Bearer '+token);
 assert.equal(connectionHeaders(connection())['X-Pajio-Expected-Tenant'],connection().session?.tenantId);
});
test('SQLite holds metadata, token restores securely, logout retains drafts',async()=>{
 const db=new Memory(),vault=new Memory(),con=connection();await db.put('draft:'+scopeOf(con),{text:'private draft'});
 await saveConnection(con,db,vault);assert.equal(JSON.stringify([...db.data]).includes(token),false);assert.deepEqual(await loadConnection(db,vault),con);
 const out=await forgetSession(con,db,vault);assert.equal(out.session?.accessToken,undefined);assert.equal((await loadConnection(db,vault))?.session?.accessToken,undefined);
 assert.deepEqual(await db.get('draft:'+scopeOf(con)),{text:'private draft'});assert.equal(scopeOf(con),scopeOf(out));assert.throws(()=>connectionEndpoint(out));assert.equal(connectionEndpoint(out,true),con.endpoint);
});
test('native production restore rejects a retired origin before reading its bearer and preserves isolated drafts',async()=>{
 const db=new Memory(),vault=new Memory(),retired=connection();
 await saveConnection(retired,db,vault);await db.put('draft:'+scopeOf(retired),{text:'原服务未同步草稿'});
 let vaultReads=0;const read=vault.get.bind(vault);vault.get=async<T=string>(key:string)=>{vaultReads++;return read<T>(key);};
 const restored=await loadConnection(db,vault,stored=>initialConnection(stored,'ios'));
 assert.deepEqual(restored,{endpoint:PUBLIC_PAJIO_ENDPOINT,identity:'daily'});assert.equal(vaultReads,0);
 assert.deepEqual(await db.get('draft:'+scopeOf(retired)),{text:'原服务未同步草稿'});
 assert.equal(await db.get('draft:'+scopeOf(restored!)),null);
 assert.equal(vault.data.size,1);assert.equal((await db.get<{endpoint:string}>('connection'))?.endpoint,retired.endpoint);
});
test('scopes separate accounts and tenants while refresh preserves scope',()=>{
 const con=connection();for(const patch of [{userId:'user_'+'b'.repeat(32)},{tenantId:'tenant-b'}]) assert.notEqual(scopeOf(con),scopeOf({...con,session:{...con.session!,...patch}}));
 assert.equal(scopeOf(con),scopeOf({...con,session:{...con.session!,credentialId:'e'.repeat(32),accessToken:'x'.repeat(64)}}));
});
test('secure-store failure cannot publish an unusable descriptor',async()=>{
 const db=new Memory(),vault=new Memory();vault.put=async()=>{throw new Error('locked');};await assert.rejects(saveConnection(connection(),db,vault));assert.equal(await db.get('connection'),null);
});
test('PKCE survives restart and duplicate browser/Router callbacks exchange once',async()=>{
 const vault=new Memory();let calls=0,writes=0;
 const exchange=async(p:{verifier:string},c:string)=>{assert.equal(p.verifier,verifier);assert.equal(c,code);calls++;await new Promise(r=>setTimeout(r,10));return connection();};const persist=async()=>{writes++;};
 await new AuthorizationFlow(vault,exchange,persist).begin({address:'https://pajio.example',verifier,state,createdAt:0});const restored=new AuthorizationFlow(vault,exchange,persist);
 const [a,b]=await Promise.all([restored.complete(callback),restored.complete(callback)]);assert.deepEqual(a,b);assert.equal(calls,1);assert.equal(writes,1);
 await restored.cancel();await assert.rejects(restored.complete(callback));assert.equal(calls,1);
});
test('foreign callback preserves pending login; expiry prevents exchange',async()=>{
 const vault=new Memory();let now=100,calls=0;const flow=new AuthorizationFlow(vault,async()=>{calls++;return connection();},async()=>{},()=>now);
 await flow.begin({address:'https://pajio.example',verifier,state,createdAt:0});await assert.rejects(flow.complete(callback.replace(state,'z'.repeat(48))));await flow.complete(callback);assert.equal(calls,1);
 await flow.begin({address:'https://pajio.example',verifier,state,createdAt:0});now+=600001;await assert.rejects(flow.complete(callback));assert.equal(calls,1);
});
test('ambiguous exchange cannot blindly repeat a consumed authorization',async()=>{
 const vault=new Memory();let calls=0;const flow=new AuthorizationFlow(vault,async()=>{calls++;throw new Error('response lost');},async()=>{});
 await flow.begin({address:'https://pajio.example',verifier,state,createdAt:0});await assert.rejects(flow.complete(callback));await assert.rejects(flow.complete(callback));assert.equal(calls,1);
});
test('previous cancellation cannot erase a newer pending authorization',async()=>{
 const vault=new Memory();let calls=0;const flow=new AuthorizationFlow(vault,async()=>{calls++;return connection();},async()=>{});
 await flow.begin({address:'https://pajio.example',verifier,state,createdAt:0});await flow.cancel('old'.repeat(16));await flow.complete(callback);assert.equal(calls,1);
});
