import assert from 'node:assert/strict';
import {test} from 'node:test';
import {accountCleanupPlan, fencedWrite, fenceFor} from './account-cleanup-model';
import {scopeOf,type Connection,type Media,type Store} from './core';
import {PickerRecovery,PICKER_RECOVERY_KEY,type PickerIntent} from './picker-recovery';

const uuid = (n:number) => `00000000-0000-4000-8000-${String(n).padStart(12,'0')}`;
const account = (letter:string):Connection => ({endpoint:'https://pajio.example/',identity:'daily',session:{userId:'user_'+letter.repeat(32),tenantId:'tenant_fixture',credentialId:'c'.repeat(32),accessToken:'x'.repeat(64),expiresAt:'2099-10-08T00:00:00Z'}});
const a=account('a'),b=account('b'),scope=scopeOf(a),other=scopeOf(b);
const selected={canceled:false,assets:[{uri:'file:///synthetic/cache/ImagePicker/photo.jpg',fileName:'照片.jpg',mimeType:'image/jpeg',width:100,height:100,exif:{secret:'not persisted'},base64:'never persisted'}]};
const draft=()=>({id:uuid(90),text:'原来的文字',media:[] as Media[]});
function fixture(){
  const data=new Map<string,unknown>();let n=0;
  const storage:Store={get:async<T>(key:string)=>structuredClone(data.get(key)??null) as T|null,put:async(key,value)=>{data.set(key,structuredClone(value));},batch:async entries=>{for(const [key,value]of entries)data.set(key,structuredClone(value));},blob:async()=>new Blob()};
  const journal=()=>new PickerRecovery(storage,()=>uuid(++n));
  let copies=0;
  const save=async(asset:{mime:string;name:string},id:string)=>{copies++;return{id,name:asset.name,mime:asset.mime,size:20};};
  return{data,storage,journal,save,copies:()=>copies};
}
test('a recreated Android activity restores into the original draft and strips unrelated native data',async()=>{
  const h=fixture(),form=draft();await h.journal().begin(scope,form.id,async()=>null,()=>true);
  await h.journal().collectPending(async()=>selected);
  const packed=JSON.stringify(h.data.get(PICKER_RECOVERY_KEY));assert.equal(packed.includes('not persisted'),false);assert.equal(packed.includes('base64'),false);
  const restored=await h.journal().apply(scope,form,()=>true,h.save);
  assert.equal(restored.text,form.text);assert.equal(restored.media.length,1);assert.equal(h.copies(),1);
  assert.deepEqual(await h.storage.get('draft:'+scope),restored);assert.deepEqual(h.data.get(PICKER_RECOVERY_KEY),[]);
  assert.equal((await h.journal().apply(scope,restored,()=>true,h.save)).media.length,1);assert.equal(h.copies(),1);
});
test('same identity under another account cannot inherit the pending photo but can select its own',async()=>{
  const h=fixture(),form=draft();await h.journal().begin(scope,form.id,async()=>null,()=>true);
  await h.journal().collectPending(async()=>selected);
  assert.equal((await h.journal().apply(other,form,()=>true,h.save)).media.length,0);
  const own=await h.journal().begin(other,form.id,async()=>null,()=>true);await h.journal().accept(own,{...selected,assets:[{...selected.assets[0],fileName:'B.jpg'}]});
  assert.equal((await h.journal().apply(other,form,()=>true,h.save)).media[0].name,'B.jpg');
  assert.equal((await h.journal().apply(scope,form,()=>true,h.save)).media[0].name,'照片.jpg');
});
test('unattributed OS results never gain authority from the open account',async()=>{
  const h=fixture();await h.journal().collectPending(async()=>selected);
  assert.equal((await h.journal().apply(scope,draft(),()=>true,h.save)).media.length,0);assert.equal(h.copies(),0);
});
test('another draft in the same account cannot silently inherit a prior photo',async()=>{
  const h=fixture(),intent=await h.journal().begin(scope,draft().id,async()=>null,()=>true);await h.journal().accept(intent,selected);
  const next={...draft(),id:uuid(91)};assert.equal((await h.journal().apply(scope,next,()=>true,h.save)).media.length,0);
  assert.equal((await h.storage.get<PickerIntent[]>(PICKER_RECOVERY_KEY))!.length,1);
});
test('cancel removes the operation; a late callback cannot fill a newer operation',async()=>{
  const h=fixture(),j=h.journal();const intent=await j.begin(scope,draft().id,async()=>null,()=>true);await j.accept(intent,{canceled:true,assets:null});
  const next=await j.begin(scope,draft().id,async()=>null,()=>true);
  await assert.rejects(j.accept(intent,selected),/已经结束/);assert.equal((await h.storage.get<PickerIntent[]>(PICKER_RECOVERY_KEY))![0].id,next.id);
});
test('identity invalidation during copy prevents any draft commit',async()=>{
  const h=fixture(),j=h.journal(),form=draft();const intent=await j.begin(scope,form.id,async()=>null,()=>true);await j.accept(intent,selected);
  let live=true;await assert.rejects(j.apply(scope,form,()=>live,async(asset,id)=>{live=false;return h.save(asset,id);}),/账户已切换/);
  assert.equal(await h.storage.get('draft:'+scope),null);assert.equal((await h.storage.get<PickerIntent[]>(PICKER_RECOVERY_KEY))!.length,1);
});
test('a failed transaction retains the journal; reloaded draft IDs prevent duplicate media copies',async()=>{
  const h=fixture(),j=h.journal(),form=draft();const intent=await j.begin(scope,form.id,async()=>null,()=>true);await j.accept(intent,selected);
  const batch=h.storage.batch;h.storage.batch=async()=>{throw Error('synthetic disk full');};
  await assert.rejects(j.apply(scope,form,()=>true,h.save),/disk full/);assert.equal((await h.storage.get<PickerIntent[]>(PICKER_RECOVERY_KEY))!.length,1);
  h.storage.batch=batch;
  const existing={...form,media:[{id:intent.id,name:'照片.jpg',mime:'image/jpeg',size:20}]};
  const restored=await h.journal().apply(scope,existing,()=>true,h.save);assert.equal(restored.media.length,1);assert.equal(h.copies(),1);
});
test('pre-launch proof must persist before caller can open the system picker',async()=>{
  const h=fixture();h.storage.put=async()=>{throw Error('synthetic unavailable');};let launch=0;
  await assert.rejects((async()=>{await h.journal().begin(scope,draft().id,async()=>null,()=>true);launch++;})(),/unavailable/);assert.equal(launch,0);
});
test('account deletion removes only owned picker entries and rejects a late resurrection',async()=>{
  const h=fixture(),j=h.journal();const one=await j.begin(scope,draft().id,async()=>null,()=>true);await j.accept(one,selected);
  const two=await j.begin(other,draft().id,async()=>null,()=>true);await j.accept(two,selected);
  const original=await h.storage.get<PickerIntent[]>(PICKER_RECOVERY_KEY),plan=accountCleanupPlan(a,[{key:PICKER_RECOVERY_KEY,value:original}]);
  const retained=plan.replacements[0].value as PickerIntent[];
  assert.deepEqual(retained.map(r=>r.scope),[other]);assert.deepEqual(plan.originals,[one.id]);assert.deepEqual(plan.shareIds,[]);
  assert.equal(fencedWrite(PICKER_RECOVERY_KEY,original,[fenceFor(a)]),true);assert.equal(fencedWrite(PICKER_RECOVERY_KEY,retained,[fenceFor(a)]),false);
});
test('remote URI and malformed results are never copied or mistaken for cancellation',async()=>{
  const h=fixture(),j=h.journal(),intent=await j.begin(scope,draft().id,async()=>null,()=>true);
  await assert.rejects(j.accept(intent,{...selected,assets:[{...selected.assets[0],uri:'https://attacker.example/photo'}]}),/不完整/);
  await assert.rejects(j.accept(intent,{code:'native_failure'}),/完整图片/);assert.equal(h.copies(),0);
});
