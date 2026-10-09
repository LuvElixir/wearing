import {test} from 'node:test';
import assert from 'node:assert/strict';
import {DatabaseSync} from 'node:sqlite';
import {scopeOf, type Connection} from './core';
import {ACCOUNT_FENCES_KEY, accountCleanupPlan, fenceFor, fencedWrite, keyScope, type LocalRow} from './account-cleanup-model';
import {accountFences, assertAccountWritable, credentialsKey, prepareAccountCleanup, registerAccountCredential, upsertState} from './account-cleanup-state';
import {createSqliteStore, type StateDatabase} from './sqlite-store';
import {memoryDraftKey} from './memory-drafts';
const a:Connection={endpoint:'https://pajio.example/',identity:'daily',session:{userId:'user_'+'a'.repeat(32),tenantId:'home',credentialId:'d'.repeat(32),expiresAt:'2030-01-01T00:00:00Z'}};
const b:Connection={...a,session:{...a.session!,userId:'user_'+'b'.repeat(32)}};
const otherTenant={...a,identity:'work',session:{...a.session!,tenantId:'team'}};
const id=(n:string)=>n.repeat(8)+'-'+n.repeat(4)+'-'+n.repeat(4)+'-'+n.repeat(4)+'-'+n.repeat(12);
function fixture(t:{after(callback:()=>void):void}){
 const sql=new DatabaseSync(':memory:');sql.exec('CREATE TABLE local_state(key TEXT PRIMARY KEY,value TEXT NOT NULL)');t.after(()=>sql.close());
 const db:StateDatabase={async execAsync(q){sql.exec(q);},async runAsync(q,...p){return sql.prepare(q).run(...p);},async getFirstAsync<T>(q:string,...p:string[]){return(sql.prepare(q).get(...p)||null)as T|null;},async closeAsync(){}};
 const get=(key:string)=>{const row=sql.prepare('SELECT value FROM local_state WHERE key=?').get(key);return row?JSON.parse(String(row.value)):null;};return{db,sql,get};
}
test('every scoped feature key matches exact full account scope, including future namespace',()=>{
 for(const key of [`workspace-import:${scopeOf(a)}`,`ongoing-create:${scopeOf(a)}|goal`,`decision:${scopeOf(a)}:task:approval`,`share-delivery:v1:${scopeOf(a)}:${id('1')}`]){assert.equal(keyScope(key),scopeOf(a));assert.equal(fencedWrite(key,null,[fenceFor(a)]),true);}
 assert.equal(fencedWrite(`draft:${scopeOf(b)}`,{},[fenceFor(a)]),false);assert.equal(fencedWrite(`draft:${scopeOf({...a,endpoint:'https://other.example/'})}`,{},[fenceFor(a)]),false);
});
test('all target tenants clear while another account and unbound shares protect their media',()=>{
 const unbound={id:id('4'),scope:null,files:[{uri:'file:///share/unbound.pdf'}]},foreign={id:id('5'),scope:scopeOf(b)};
 const rows:LocalRow[]=[{key:'draft:'+scopeOf(a),value:{media:[{id:id('1')},{id:id('2')},{mediaId:id('3')}]}},{key:'snapshot:'+scopeOf(otherTenant),value:{title:'remove'}},{key:'draft:'+scopeOf(b),value:{mediaId:id('2')}},{key:'share-intake:v1',value:[unbound,foreign,{id:id('6'),scope:scopeOf(a)}]},{key:'appearance:v1',value:'dark'}];
 const p=accountCleanupPlan(a,rows);assert.deepEqual(p.remove,['draft:'+scopeOf(a),'snapshot:'+scopeOf(otherTenant)]);assert.ok(p.originals.includes(id('1')));assert.ok(p.originals.includes(id('3')));assert.ok(!p.originals.includes(id('2')));assert.deepEqual(p.replacements,[{key:'share-intake:v1',value:[unbound,foreign]}]);assert.deepEqual(p.shareIds,[id('6')]);
});
test('ambiguous share ownership and legacy memory stay retained; new memory keys separate users',()=>{
 const legacy=`memory-edit:v1:${encodeURIComponent(a.endpoint)}:daily:memory`,p=accountCleanupPlan(a,[{key:legacy,value:{text:'unknown owner'}},{key:'share-intake:v1',value:[{id:id('4'),scope:scopeOf(a)},{id:id('4'),scope:null}]}]);assert.equal(p.unownedLegacy,1);assert.deepEqual(p.shareIds,[]);assert.deepEqual(p.remove,[]);assert.notEqual(memoryDraftKey(a,'memory'),memoryDraftKey(b,'memory'));
});
test('atomic cleanup and durable fence reject old single/batch saves without touching switched account',async t=>{
 const{db,get}=fixture(t);await upsertState(db,'draft:'+scopeOf(a),{private:'remove'});await upsertState(db,'draft:'+scopeOf(b),{private:'keep'});await upsertState(db,'connection',b);await registerAccountCredential(db,a);await registerAccountCredential(db,otherTenant);
 const result=await prepareAccountCleanup(db,a);assert.equal(result.rowsRemoved,1);assert.equal(get('draft:'+scopeOf(a)),null);assert.deepEqual(get('draft:'+scopeOf(b)),{private:'keep'});assert.deepEqual(get('connection'),b);assert.deepEqual(get(ACCOUNT_FENCES_KEY),[fenceFor(a)]);assert.ok(result.scopes.includes(scopeOf(otherTenant)));assert.equal(get(credentialsKey(a)),null);
 const restored=createSqliteStore(async()=>db,undefined,async(handle,key,value)=>{if(fencedWrite(key,JSON.parse(value),await accountFences(handle)))throw new Error('frozen');});
 await assert.rejects(restored.put('draft:'+scopeOf(a),{late:true}),/frozen/);await assert.rejects(restored.batch([['draft:'+scopeOf(b),{mustRollback:true}],['voice-input:'+scopeOf(a),{late:true}]]),/frozen/);assert.deepEqual(get('draft:'+scopeOf(b)),{private:'keep'});await assert.rejects(registerAccountCredential(db,a),/正在注销/);await assertAccountWritable(db,b);
});
test('crash recovery retains file inventory and respects references acquired by retained account',async t=>{
 const{db,get}=fixture(t);await upsertState(db,'outbox:'+scopeOf(a),{media:{id:id('1')},uri:'file:///voice/a.wav'});const first=await prepareAccountCleanup(db,a);assert.ok(first.originals.includes(id('1')));const retry=await prepareAccountCleanup(db,a);assert.deepEqual(retry.originals,first.originals);await upsertState(db,'draft:'+scopeOf(b),{mediaId:id('1'),uri:'file:///voice/a.wav'});const retained=await prepareAccountCleanup(db,a);assert.deepEqual(retained.originals,[]);assert.deepEqual(retained.uris,[]);assert.equal(get('outbox:'+scopeOf(a)),null);
});
test('corrupt foreign row aborts atomically, never mistaken for no references',async t=>{
 const{db,sql,get}=fixture(t);await upsertState(db,'draft:'+scopeOf(a),{preserve:true});sql.prepare('INSERT INTO local_state VALUES(?,?)').run('draft:'+scopeOf(b),'broken-json');await assert.rejects(prepareAccountCleanup(db,a));assert.deepEqual(get('draft:'+scopeOf(a)),{preserve:true});assert.equal(get(ACCOUNT_FENCES_KEY),null);
});
test('stale intake index cannot restore frozen account; unbound and foreign intake stay writable',()=>{
 assert.equal(fencedWrite('share-intake:v1',[{id:id('1'),scope:scopeOf(a)}],[fenceFor(a)]),true);assert.equal(fencedWrite('share-intake:v1',[{id:id('1'),scope:null},{id:id('2'),scope:scopeOf(b)}],[fenceFor(a)]),false);
});

test('foreign raw file URI protects owned original and share folder without a media object',()=>{
 const p=accountCleanupPlan(a,[{key:'draft:'+scopeOf(a),value:{id:id('1')}},{key:'draft:'+scopeOf(b),value:{uri:'file:///originals/'+id('1'),other:'file:///share-intake/'+id('2')+'/0.pdf'}},{key:'share-intake:v1',value:[{id:id('2'),scope:scopeOf(a)}]}]);
 assert.deepEqual(p.originals,[]);assert.deepEqual(p.shareIds,[]);
});

test('known recorder paths allow exact App recordings while rejecting directory traversal and user originals',async()=>{
 const {managedRecordingUri}=await import('./account-media');
 const doc='file:///app/Documents/',cache='file:///app/Cache/';
 assert.equal(managedRecordingUri(doc+'voice-takes/voice-'+id('a')+'.wav',doc,cache),true);
 assert.equal(managedRecordingUri(doc+'ExpoAudio/recording-'+id('a').toUpperCase()+'.m4a',doc,cache),true);
 assert.equal(managedRecordingUri(cache+'Audio/recording-'+id('a')+'.m4a',doc,cache),true);
 for(const uri of [doc+'private.pdf',doc+'ExpoAudio/../secret',doc+'voice-takes/evil.wav','ph://'+id('a'),'file:///other/ExpoAudio/recording-'+id('a')+'.m4a'])assert.equal(managedRecordingUri(uri,doc,cache),false);
});
test('account work freeze waits for original account microphone and never stops another account',async()=>{
 const {accountWorkAllowed,registerAccountWork,stopDeletedAccountWork}=await import('./account-work');
 let resolve!:()=>void,aStopped=false,bStopped=false;const gate=new Promise<void>(done=>{resolve=done;});
 const removeA=registerAccountWork(a,async()=>{await gate;aStopped=true;}),removeB=registerAccountWork(b,async()=>{bStopped=true;});
 const work=stopDeletedAccountWork(a);assert.equal(accountWorkAllowed(a),false);assert.equal(accountWorkAllowed(b),true);assert.equal(aStopped,false);resolve();await work;assert.equal(aStopped,true);assert.equal(bStopped,false);removeA();removeB();
});

test('corrupt cleanup journal cannot use a relative share path to escape a managed directory',async t=>{
 const {db}=fixture(t),key='account-cleanup:v1:'+a.endpoint+'|'+a.session!.userId;
 await upsertState(db,key,{version:1,originals:[],shareIds:['../../private'],uris:['file:///app/Documents/share-intake/../../private/0.pdf'],scopes:[],credentialIds:[],rowsRemoved:0,unownedLegacy:0});
 await assert.rejects(prepareAccountCleanup(db,a),/无法核对/);
});
