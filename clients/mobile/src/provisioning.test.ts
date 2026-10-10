import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {type Connection} from './core';
import {needsProvisioning,ProvisioningGate,provisioningSnapshot,readProvisioning,ProvisioningError,type ProvisioningSnapshot} from './provisioning-client';
import {PUBLIC_PAJIO_ENDPOINT} from './connection-default';
const connection=():Connection=>({endpoint:PUBLIC_PAJIO_ENDPOINT,identity:'daily',session:{accessToken:'t'.repeat(64),expiresAt:new Date(Date.now()+3600000).toISOString(),userId:'user_'+'a'.repeat(32),tenantId:'synthetic_only',credentialId:'c'.repeat(32)}});
const receipt=(state:ProvisioningSnapshot['state']='preparing'):ProvisioningSnapshot=>({state,members:{core:{state:'ready'},linux:{state:state==='ready'?'ready':'preparing'},android:{state:state==='ready'?'ready':'pending'}},updated_at:1791600000,reason:null,retry_after:7});
test('ready requires server overall ready and a complete consistent member receipt, never inferred from members',()=>{
 const gate=new ProvisioningGate(),a=connection();gate.activate(a);
 for(const state of ['reserved','preparing','installing','pairing','needs_review'] as const){assert.equal(gate.accept(a,{...receipt('ready'),state}),false);assert.equal(gate.allows(a),false);}
 for(const bad of [{...receipt('ready'),members:{core:{state:'ready'}}},{...receipt(),state:'ready'},{...receipt(),retry_after:0},{...receipt(),retry_after:31},{...receipt(),updated_at:'today'},{...receipt(),reason:'private detail'},{...receipt(),state:'unknown'}])assert.throws(()=>provisioningSnapshot(bad));
 assert.equal(gate.accept(a,receipt('ready')),true);assert.equal(gate.allows(a),true);
});
test('new activation, credential or account never inherits an old in-memory readiness grant',()=>{
 const a=connection(),b={...connection(),session:{...connection().session!,tenantId:'other'}};const gate=new ProvisioningGate();gate.activate(a);gate.accept(a,receipt('ready'));gate.activate(b);
 assert.equal(gate.accept(a,receipt('ready')),false);assert.equal(gate.allows(b),false);assert.equal(gate.allows(a),false);
 assert.equal(gate.accept(b,receipt('ready')),true);gate.activate(b);assert.equal(gate.allows(b),false);
 assert.equal(needsProvisioning(a),true);assert.equal(needsProvisioning({endpoint:'http://127.0.0.1:8878/',identity:'daily'}),false);
 assert.equal(gate.allows({endpoint:'http://127.0.0.1:8878/',identity:'daily'}),true);
});
test('actual status fetch is authenticated control GET without Core bootstrap, body, cookie, mutation or token URL',async()=>{
 const a=connection(),calls:{url:string;init?:RequestInit}[]=[];
 const value=await readProvisioning(a,new AbortController().signal,async(url,init)=>{calls.push({url:String(url),init});return Response.json(receipt());});
 assert.equal(value.state,'preparing');assert.equal(calls.length,1);assert.equal(calls[0].url,PUBLIC_PAJIO_ENDPOINT+'auth/provisioning');
 assert.deepEqual(calls[0].init?.headers,{Authorization:'Bearer '+a.session!.accessToken,'X-Pajio-Expected-Tenant':'synthetic_only'});
 for(const [field,expected]of Object.entries({method:'GET',body:undefined,credentials:'omit',redirect:'error',cache:'no-store'}))assert.equal((calls[0].init as Record<string,unknown>)[field],expected);
});
test('404, invalid, 401 and network errors are fixed safe messages; none yields ready or leaks a response',async()=>{
 for(const [status,code]of [[404,'unavailable'],[401,'expired'],[503,'unconfirmed']]as const)await assert.rejects(readProvisioning(connection(),new AbortController().signal,async()=>new Response('synthetic secret',{status})),error=>error instanceof ProvisioningError&&error.code===code&&!error.message.includes('secret'));
 await assert.rejects(readProvisioning(connection(),new AbortController().signal,async()=>Response.json({...receipt(),state:'ready'})),ProvisioningError);
 await assert.rejects(readProvisioning(connection(),new AbortController().signal,async()=>{throw Error('synthetic secret');}),error=>error instanceof ProvisioningError&&!error.message.includes('secret'));
});
test('background/disposal abort suppresses ready even when fetch ignores abort',async()=>{
 const controller=new AbortController();let resolve!:(value:Response)=>void;const operation=readProvisioning(connection(),controller.signal,async()=>new Promise<Response>(r=>{resolve=r;}));controller.abort();resolve(Response.json(receipt('ready')));await assert.rejects(operation,ProvisioningError);
 let calls=0;await assert.rejects(readProvisioning(connection(),controller.signal,async()=>{calls++;return Response.json(receipt('ready'));}));assert.equal(calls,0);
});
test('production Mobile orders the gate before Core requests and before any side-effectful native/viewer mount',()=>{
 const source=readFileSync(new URL('./Mobile.tsx',import.meta.url),'utf8');const sync=source.slice(source.indexOf('async function synchronize'),source.indexOf('async function activateConnection'));
 assert.ok(sync.indexOf('provisioningGate.current.allows(connection)')<sync.indexOf('api.bootstrap()'));
 const render=source.slice(source.indexOf("if (deletionFrozen && screen !== 'connection')"));
 assert.ok(render.indexOf('<NativeProvisioningPanel')<render.indexOf('<NativeRemoteDevicePanel'));
 assert.ok(render.indexOf('<NativeProvisioningPanel')<render.indexOf('<NativeSyncSession'));
 assert.ok(render.indexOf('<NativeProvisioningPanel')<render.indexOf('<NativeActionSession'));
 assert.ok(render.indexOf('<NativeProvisioningPanel')<render.indexOf('<RetainedConversation'));
});
