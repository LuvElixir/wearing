import {test} from 'node:test';
import assert from 'node:assert/strict';
import {DatabaseSync} from 'node:sqlite';
import {commitNativeConnection} from './native-connection-commit';
import {type Connection} from './core';
import {type StateDatabase} from './sqlite-store';
import {credentialsKey} from './account-cleanup-state';
const prior:Connection={endpoint:'https://pajio.luckyloading.com/',identity:'daily',session:{userId:'user_'+'a'.repeat(32),tenantId:'prior',credentialId:'a'.repeat(32),accessToken:'o'.repeat(64),expiresAt:new Date(Date.now()+3600000).toISOString()}};
const next:Connection={...prior,session:{...prior.session!,userId:'user_'+'b'.repeat(32),tenantId:'next',credentialId:'b'.repeat(32),accessToken:'n'.repeat(64)}};
for(const phase of ['upsert','commit'] as const)test(`cancellation during final ${phase} preserves old account and removes only new credential`,async()=>{
 const sql=new DatabaseSync(':memory:');sql.exec('CREATE TABLE local_state(key TEXT PRIMARY KEY,value TEXT)');
 const metadata={...prior,session:{...prior.session,accessToken:undefined}};sql.prepare('INSERT INTO local_state VALUES(?,?)').run('connection',JSON.stringify(metadata));
 let current=true;
 const db:StateDatabase={execAsync:async command=>{sql.exec(command);if(command==='COMMIT'&&phase==='commit')current=false;},runAsync:async(command,...args)=>{const result=sql.prepare(command).run(...args);if(args[0]==='connection'&&phase==='upsert')current=false;return result;},getFirstAsync:async<T>(command:string,...args:string[])=>sql.prepare(command).get(...args) as T,closeAsync:async()=>sql.close()};
 const secrets=new Map([['pajio.session.'+prior.session!.credentialId,prior.session!.accessToken!]]);
 await assert.rejects(commitNativeConnection(db,{get:async k=>secrets.get(k)||null,put:async(k,v)=>{secrets.set(k,v)},remove:async k=>{secrets.delete(k)}},next,()=>current));
 assert.deepEqual(JSON.parse((sql.prepare('SELECT value FROM local_state WHERE key=?').get('connection') as {value:string}).value),JSON.parse(JSON.stringify(metadata)));
 assert.equal(sql.prepare('SELECT value FROM local_state WHERE key=?').get(credentialsKey(next)),undefined);
 assert.deepEqual([...secrets], [['pajio.session.'+prior.session!.credentialId,prior.session!.accessToken]]);sql.close();
});
test('successful native commit saves account metadata without a bearer and preserves the previous credential',async()=>{
 const sql=new DatabaseSync(':memory:');sql.exec('CREATE TABLE local_state(key TEXT PRIMARY KEY,value TEXT)');
 const db:StateDatabase={execAsync:async command=>sql.exec(command),runAsync:async(command,...args)=>sql.prepare(command).run(...args),getFirstAsync:async<T>(command:string,...args:string[])=>sql.prepare(command).get(...args) as T,closeAsync:async()=>sql.close()};
 const secrets=new Map([['pajio.session.'+prior.session!.credentialId,prior.session!.accessToken!]]);
 await commitNativeConnection(db,{get:async k=>secrets.get(k)||null,put:async(k,v)=>{secrets.set(k,v)},remove:async k=>{secrets.delete(k)}},next,()=>true);
 const raw=(sql.prepare('SELECT value FROM local_state WHERE key=?').get('connection') as {value:string}).value;
 assert.equal(JSON.parse(raw).session.credentialId,next.session!.credentialId);assert.ok(!raw.includes(next.session!.accessToken!));
 assert.equal(secrets.get('pajio.session.'+prior.session!.credentialId),prior.session!.accessToken);assert.equal(secrets.get('pajio.session.'+next.session!.credentialId),next.session!.accessToken);sql.close();
});
