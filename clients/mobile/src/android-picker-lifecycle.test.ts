import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {test} from 'node:test';
import {runInNewContext} from 'node:vm';
import * as ts from 'typescript';
import {scopeOf,type Connection,type Media,type Store} from './core';
import {PickerRecovery,PICKER_RECOVERY_KEY} from './picker-recovery';

const id=(n:number)=>`00000000-0000-4000-8000-${String(n).padStart(12,'0')}`;
const connection:Connection={endpoint:'https://pajio.example/',identity:'daily'};
const selected={canceled:false,assets:[{uri:'file:///synthetic/photo.jpg',fileName:'选图.jpg',mimeType:'image/jpeg',width:100,height:100}]};
function code(file:string,names:string[],inside?:string){
  const source=ts.createSourceFile(file,readFileSync(new URL('./'+file,import.meta.url),'utf8'),ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
  const statements=inside?(source.statements.find(s=>ts.isFunctionDeclaration(s)&&s.name?.text===inside) as ts.FunctionDeclaration).body!.statements:source.statements;
  const functions=statements.filter(s=>ts.isFunctionDeclaration(s)&&names.includes(s.name!.text));assert.equal(functions.length,names.length);
  return ts.transpileModule(functions.map(s=>ts.createPrinter().printNode(ts.EmitHint.Unspecified,s,source)).join('\n').replaceAll('export async function','async function'),{compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText;
}
function shell(){
  const data=new Map<string,unknown>();let sequence=0,copies=0,launches=0;
  const storage:Store={get:async<T>(key:string)=>structuredClone(data.get(key)??null) as T|null,put:async(key,value)=>{data.set(key,structuredClone(value));},batch:async entries=>{for(const[key,value]of entries)data.set(key,structuredClone(value));},blob:async()=>new Blob()};
  const form={id:id(90),text:'原草稿',media:[] as Media[]};
  const state={locked:false,message:'',screen:''};
  const h={Error,Promise,Date,clearTimeout,Platform:{OS:'android'},storage,scopeOf,
    current:{current:connection as Connection|null},formRef:{current:form},captureWriting:{current:false},draftTimer:{current:null},
    voiceBusy:{current:false},voiceStop:{current:null},voiceRecovery:{current:null},recorder:{isRecording:false},stopVoice:async()=>true,
    setCaptureLocked:(v:boolean)=>{state.locked=v;},setForm:(v:typeof form)=>{h.formRef.current=v;},setMessage:(v:string)=>{state.message=v;},setScreen:(v:string)=>{state.screen=v;},
    accountWorkAllowed:()=>true,pickerRecovery:new PickerRecovery(storage,()=>id(++sequence)),
    keepMedia:async(_uri:string,media:Media,target:Connection,recover:boolean)=>{assert.equal(target,connection);assert.equal(recover,true);copies++;return{...media,size:20};},
    Picker:{getPendingResultAsync:async():Promise<unknown>=>null,launchImageLibraryAsync:async()=>{launches++;const journal=await storage.get<{scope:string}[]>(PICKER_RECOVERY_KEY);assert.equal(journal![0].scope,scopeOf(connection));return selected;}},
    copies:()=>copies,launches:()=>launches,state,data};
  runInNewContext(code('Mobile.tsx',['beginCaptureWrite','photo','recoverPicker'],'Mobile'),h);
  return h as typeof h&{photo:(camera:boolean)=>Promise<void>;recoverPicker:(connection:Connection)=>Promise<void>};
}
test('actual Android photo handler persists intent before launch and restores only to its captured draft',async()=>{
  const h=shell();await h.photo(false);assert.equal(h.launches(),1);assert.equal(h.copies(),1);assert.equal(h.formRef.current.media.length,1);assert.equal(h.state.locked,false);
  assert.equal(h.state.screen,'capture');assert.deepEqual(h.data.get(PICKER_RECOVERY_KEY),[]);
});
test('actual cold-start recovery uses pre-existing proof without opening another picker',async()=>{
  const h=shell();await h.pickerRecovery.begin(scopeOf(connection),h.formRef.current.id,async()=>null,()=>true);h.Picker.getPendingResultAsync=async()=>selected;
  await h.recoverPicker(connection);assert.equal(h.launches(),0);assert.equal(h.formRef.current.media.length,1);assert.equal(h.state.message.includes('尚未发送'),true);
});
test('actual handler cannot open a picker after proof persistence failed',async()=>{
  const h=shell(),put=h.storage.put;h.storage.put=async(key,value)=>{if(key===PICKER_RECOVERY_KEY)throw Error('synthetic journal full');await put(key,value);};
  await h.photo(false);assert.equal(h.launches(),0);assert.equal(h.copies(),0);assert.equal(h.state.locked,false);assert.match(h.state.message,/journal full/);
});
test('actual account-change callback keeps the old result unattached and does not copy for a new user',async()=>{
  const h=shell();h.Picker.launchImageLibraryAsync=async()=>{h.current.current={...connection,identity:'work'};return selected;};await h.photo(false);
  assert.equal(h.formRef.current.media.length,0);assert.equal(h.copies(),0);assert.equal(h.state.locked,false);
  assert.equal((h.data.get(PICKER_RECOVERY_KEY) as {scope:string}[])[0].scope,scopeOf(connection));
});
test('recoverCopy repairs a nonempty partial file under the same account write fence',async()=>{
  const files=new Map<string,string>([['source','whole-photo'],['originals/'+id(1),'partial']]);let fenced=false,copies=0;
  class File {uri:string;constructor(...parts:(string|{uri:string})[]){this.uri=parts.map(p=>typeof p==='string'?p:p.uri).join('/');}get exists(){return files.has(this.uri);}get size(){return files.get(this.uri)?.length||0;}get md5(){return files.get(this.uri)||null;}async copy(destination:File,options?:{overwrite:boolean}){assert.equal(options?.overwrite,true);copies++;files.set(destination.uri,files.get(this.uri)!);}}
  class Directory {uri:string;constructor(_root:unknown,name:string){this.uri=name;}create(){}}
  const target={...connection,session:{userId:'user_'+'a'.repeat(32),tenantId:'t',credentialId:'c'.repeat(32),expiresAt:'2099-01-01',accessToken:'x'.repeat(64)}};
  const context={Error,Promise,JSON,File,Directory,Paths:{document:{uri:'file:///private'},cache:{uri:'file:///cache'}},scopeOf,managedRecordingUri:()=>false,upsertState:async()=>{},assertAccountWritable:async()=>{if(fenced)throw Error('account frozen');},withNativeState:async(operation:(db:unknown)=>Promise<unknown>)=>operation({getFirstAsync:async()=>null})};
  runInNewContext(code('storage.ts',['keepMedia']),context);
  const keep=(context as typeof context&{keepMedia:(uri:string,media:Media,connection:Connection,recover:boolean)=>Promise<Media>}).keepMedia;
  const media={id:id(1),name:'照片.jpg',mime:'image/jpeg',size:0};await keep('source',media,target,true);assert.equal(copies,1);assert.equal(files.get('originals/'+id(1)),'whole-photo');
  await keep('source',media,target,true);assert.equal(copies,1);
  fenced=true;files.set('originals/'+id(1),'bad');await assert.rejects(keep('source',media,target,true),/frozen/);assert.equal(copies,1);
});
