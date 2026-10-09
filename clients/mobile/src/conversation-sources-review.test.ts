import {test} from 'node:test';
import assert from 'node:assert/strict';
import {ConversationSourcesClient} from './conversation-sources';
import {ApiError,type Connection} from './core';

const connection:Connection={endpoint:'https://fixture.invalid/',identity:'daily',session:{userId:'user_'+'a'.repeat(32),tenantId:'synthetic',credentialId:'c'.repeat(32),accessToken:'s'.repeat(64),expiresAt:'2099-01-01T00:00:00Z'}};
const payload={identity_id:'daily',revision:0,snapshot:'b'.repeat(64),items:[],next_offset:null};

for(const cancellation of ['identity','abort'] as const)test(`source page rejects ${cancellation} change while body is arriving`,async()=>{
  let current=true;const controller=new AbortController();
  const fetcher:typeof fetch=async()=>{const response=new Response('{}',{status:200});response.json=async()=>{
    if(cancellation==='identity')current=false;else controller.abort();
    return payload;
  };return response;};
  const client=new ConversationSourcesClient(connection,fetcher,()=>current,controller.signal);
  await assert.rejects(client.page(),(error:unknown)=>error instanceof ApiError&&error.status===0);
});
