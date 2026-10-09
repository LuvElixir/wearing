import assert from 'node:assert/strict';
import test from 'node:test';
import fs from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';
import * as core from './core';
import * as cleanupModel from './account-cleanup-model';
import * as cleanupState from './account-cleanup-state';
import * as parser from './chat-import-parser';
import {chatImportDraftKey, chatImportPendingKey} from './chat-import-client';
const source = fs.readFileSync(new URL('./chat-import-native.ts', import.meta.url), 'utf8');
const ID = 'aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee', ID2 = 'bbbbbbbb-bbbb-4ccc-8ddd-eeeeeeeeeeee';
const connection: core.Connection = {endpoint:'https://pajio.test', identity:'personal', session:{userId:'user_'+'a'.repeat(32),tenantId:'tenant_a',credentialId:'x'.repeat(32),expiresAt:'2099-01-01T00:00:00Z'}};
function fixture() {
  const rows = new Map<string, unknown>(), files = new Set<string>([ID, ID2]); let failFile = false;
  const db = {async getFirstAsync() {return {rows:JSON.stringify([...rows].map(([key,value])=>({key,value:JSON.stringify(value)})))};},async runAsync(_sql:string,key:string,value:string) {rows.set(key,JSON.parse(value));}};
  class Directory {id:string;constructor(_root:unknown,_folder:string,id:string) {this.id=id;}get exists(){return files.has(this.id);}delete(){if(failFile)throw Error('synthetic locked file');files.delete(this.id);}}
  const dependencies: Record<string,unknown> = {'expo-crypto':{},'expo-file-system':{Directory,Paths:{document:{uri:'file:///private/docs/'}}},'./core':core,'./account-cleanup-model':cleanupModel,'./account-cleanup-state':cleanupState,'./chat-import-parser':parser,'./storage':{withNativeState:async(work:(db:unknown)=>unknown)=>work(db)}};
  const exports:Record<string,unknown>={};
  vm.runInNewContext(ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,{exports,require:(name:string)=>{if(!(name in dependencies))throw Error(name);return dependencies[name];},Uint8Array,WeakSet,Set,JSON,Error,setTimeout});
  return {rows,files,setFailFile:(fail:boolean)=>{failFile=fail;},api:exports as {clearChatImportPrivateDrafts(c:core.Connection):Promise<void>;chatImportWorkAllowed(c:core.Connection):boolean}};
}
const share = (scope:string,id=ID) => ({id,scope,action:'chat-import',state:'pending',text:'synthetic selected chat',files:[{path:'0.zip',uri:`file:///private/docs/share-intake/${id}/0.zip`}]});
test('logout clears private drafts and bodies from all own identities, preserving other accounts',async()=>{
  const f=fixture(),scope=core.scopeOf(connection),work=core.scopeOf({...connection,identity:'work'}),other=core.scopeOf({...connection,session:{...connection.session!,userId:'user_'+'b'.repeat(32)}});
  f.rows.set(chatImportDraftKey(scope),{shareId:ID,preview:{messages:['private synthetic']}});f.rows.set(chatImportDraftKey(work),{preview:{messages:['private work']}});f.rows.set(chatImportDraftKey(other),{preview:{messages:['retained other']}});
  f.rows.set(chatImportPendingKey(scope),{version:1,key:'synthetic-request-key',request:{messages:['private']},shareId:ID});f.rows.set('share-intake:v1',[share(scope),share(other,ID2)]);
  await f.api.clearChatImportPrivateDrafts(connection);
  assert.equal(f.api.chatImportWorkAllowed(connection),false);assert.equal(f.rows.get(chatImportDraftKey(scope)),null);assert.equal(f.rows.get(chatImportDraftKey(work)),null);assert.notEqual(f.rows.get(chatImportDraftKey(other)),null);
  assert.deepEqual(f.rows.get(chatImportPendingKey(scope)),{version:1,key:'synthetic-request-key',request:null});assert.equal(f.files.has(ID),false);assert.equal(f.files.has(ID2),true);
});
test('claimed share without a draft is removed on logout after a parse interruption',async()=>{
  const f=fixture();f.rows.set('share-intake:v1',[share(core.scopeOf(connection))]);await f.api.clearChatImportPrivateDrafts(connection);
  assert.equal(f.files.has(ID),false);const rows=f.rows.get('share-intake:v1') as {state:string;files:unknown[]}[];assert.equal(rows[0].state,'cancelled');assert.equal(rows[0].files.length,0);
});
test('failed local file removal retains its inventory and succeeds on logout retry',async()=>{
  const f=fixture();f.rows.set(chatImportDraftKey(core.scopeOf(connection)),{shareId:ID});f.rows.set('share-intake:v1',[share(core.scopeOf(connection))]);f.setFailFile(true);
  await assert.rejects(f.api.clearChatImportPrivateDrafts(connection),/locked/);assert.equal(f.files.has(ID),true);assert.equal((f.rows.get('share-intake:v1') as {files:unknown[]}[])[0].files.length,1);
  f.setFailFile(false);await f.api.clearChatImportPrivateDrafts(connection);assert.equal(f.files.has(ID),false);assert.equal((f.rows.get('share-intake:v1') as {files:unknown[]}[])[0].files.length,0);
});
