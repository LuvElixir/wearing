import {test} from 'node:test';
import assert from 'node:assert/strict';
import {randomBytes} from 'node:crypto';
import {EnrollmentFlow} from './enrollment-client';
import {accountCredentials, base64urlBytes, enrollmentResult, recoveryRecord} from './enrollment-model';
import {PUBLIC_PAJIO_ENDPOINT} from './connection-default';
import {sessionReceipt, type Vault} from './session-protocol';

const now = Date.parse('2026-10-10T12:00:00Z'), expires_at = new Date(now + 900_000).toISOString();
const operation_id = 'a'.repeat(32), receipt = 'r'.repeat(43), verifier = 'v'.repeat(64), state = 's'.repeat(48), challenge = 'c'.repeat(43);
const code = 'pajio_' + 'i'.repeat(43), password = 'synthetic-only-测试🙂';
const record = () => ({origin: PUBLIC_PAJIO_ENDPOINT, operation_id, receipt, verifier, state, expires_at});
const reply = (status = 'verified', extra = {}) => ({operation_id, state, status, expires_at, ...extra});
const completed = () => reply('completed', {next_action: 'exchange', handoff: {code: 'h'.repeat(43), state}});
class Memory implements Vault {
  values = new Map<string, string>();
  async get(key: string) {return this.values.get(key) ?? null;}
  async put(key: string, value: string) {this.values.set(key, value);}
  async remove(key: string) {this.values.delete(key);}
}
function fixture() {
  const vault = new Memory(), calls: {path: string; body: Record<string, unknown>; init?: RequestInit}[] = [];
  let respond: (path: string, body: Record<string, unknown>) => Promise<Response> = async () => Response.json(reply());
  let exchanges = 0;
  const create = () => new EnrollmentFlow({vault, now: () => now, proof: async () => ({operation_id, receipt, verifier, state, challenge}),
    fetcher: async (url, init) => {const path = new URL(String(url)).pathname, body = JSON.parse(String(init?.body)); calls.push({path, body, init}); return respond(path, body);},
    finish: async () => {exchanges++; return sessionReceipt(PUBLIC_PAJIO_ENDPOINT, {token_type: 'Bearer', access_token: 't'.repeat(64), expires_at: new Date(Date.now() + 3600000).toISOString(), user_id: 'user_' + 'u'.replace('u','a').repeat(32), tenant_id: 'synthetic'}, 'x'.repeat(32));},
  });
  return {flow: create(), create, vault, calls, respond: (value: typeof respond) => {respond = value;}, exchanges: () => exchanges};
}
test('native credential rules count Unicode points, preserve password whitespace, reject lone surrogates and controls', () => {
  assert.equal(accountCredentials('  Name_1 ', password).username, 'name_1');
  assert.equal(accountCredentials('name', ' ' + '密'.repeat(10) + '🙂 ').password, ' ' + '密'.repeat(10) + '🙂 ');
  assert.doesNotThrow(() => accountCredentials('name', '🙂'.repeat(128)));
  for (const bad of ['🙂'.repeat(129), 'x'.repeat(11), 'x'.repeat(12) + '\n', 'x'.repeat(12) + '\u0080', 'x'.repeat(12) + '\ud800']) assert.throws(() => accountCredentials('name', bad));
  assert.throws(() => accountCredentials('0bad', password));
});
test('random recovery proof base64url matches standard encoding without padding', () => {
  for (const length of [0, 1, 2, 3, 24, 32, 64]) {const bytes = randomBytes(length); assert.equal(base64urlBytes(bytes), bytes.toString('base64url'));}
});
test('record and server receipts bind exact official origin, operation and PKCE state', () => {
  assert.deepEqual(recoveryRecord(record(), PUBLIC_PAJIO_ENDPOINT), record());
  for (const patch of [{origin: 'https://other.invalid/'}, {password}, {receipt: 'x'}, {expires_at: 'invalid'}]) assert.throws(() => recoveryRecord({...record(), ...patch}, PUBLIC_PAJIO_ENDPOINT));
  for (const patch of [{operation_id: 'b'.repeat(32)}, {state: 'b'.repeat(48)}, {status: 'logged_in'}, {expires_at: new Date(now + 86400000).toISOString()}, {next_action: 'https://other.invalid/'}, {attempts_remaining: 20}]) assert.throws(() => enrollmentResult({...reply(), ...patch}, record(), now));
  assert.doesNotThrow(() => enrollmentResult(completed(), record(), now));
  assert.throws(() => enrollmentResult(reply('pending', {handoff: {code: 'h'.repeat(43), state}}), record(), now));
});
test('verify saves only private recovery proof before dispatch; passwords, invitation and bearer are never persisted', async () => {
  const f = fixture(); f.respond(async () => {assert.equal(f.vault.values.size, 1); return Response.json(reply());});
  await f.flow.verify(code);
  const saved = [...f.vault.values.values()].join(); assert.equal(saved.includes(password), false); assert.equal(saved.includes(code), false);
  assert.deepEqual(Object.keys(JSON.parse(saved)).sort(), ['expires_at','operation_id','origin','receipt','state','verifier']);
  assert.equal(f.calls[0].init?.credentials, 'omit'); assert.equal(f.calls[0].init?.redirect, 'error');
  assert.deepEqual(f.calls[0].init?.headers, {'Content-Type':'application/json'});
  assert.deepEqual(f.calls[0].body, {operation_id, receipt, code, challenge, state});
});
test('secure storage refusal prevents any verify request', async () => {
  const f = fixture(); f.vault.put = async () => {throw Error('synthetic locked');};
  await assert.rejects(f.flow.verify(code)); assert.equal(f.calls.length, 0);
});
test('invalid invitation is the sole definitive verify failure that safely clears the retained operation', async () => {
  const f = fixture(); f.respond(async () => Response.json({code:'invitation_unavailable'}, {status:422}));
  await assert.rejects(f.flow.verify(code)); assert.equal(f.vault.values.size, 0); assert.equal(f.flow.current().recovery, null);
  f.respond(async () => Response.json(reply())); await f.flow.verify(code); assert.equal(f.calls.length, 2);
});
test('lost register response survives restart; 404 and authorization errors preserve the original operation', async () => {
  const f = fixture(); await f.flow.verify(code);
  f.respond(async () => {throw Error(password);}); await assert.rejects(f.flow.register('name', password), error => !String(error).includes(password));
  await assert.rejects(f.flow.register('name', password)); assert.equal(f.calls.length, 2);
  f.flow.dispose(); const resumed = f.create(); await resumed.restore();
  assert.equal(resumed.current().recovery?.operation_id, operation_id); assert.equal(resumed.current().result, null);
  await assert.rejects(resumed.register('name', password)); await assert.rejects(resumed.verify(code)); assert.equal(f.calls.length, 2);
  for (const status of [403, 404, 503]) {f.respond(async () => Response.json({code:'operation_unavailable'}, {status})); await assert.rejects(resumed.status()); assert.equal(f.vault.values.size, 1);}
  assert.equal(f.calls.filter(call => call.path.endsWith('/register')).length, 1);
  assert.equal(f.calls.slice(2).every(call => call.path.endsWith('/status') && !('password' in call.body)), true);
});
test('definitively undispatched registration keeps the same operation and allows only explicit retry', async () => {
  const f=fixture(); await f.flow.verify(code);
  f.respond(async()=>Response.json(reply('verified',{code:'registration_unavailable',next_action:'register',attempts_remaining:5})));
  await f.flow.register('name', password); assert.equal(f.calls.length,2); assert.equal(f.flow.current().result?.status,'verified');
  f.respond(async()=>Response.json(completed())); await f.flow.register('name', password);
  assert.equal(f.calls.length,3); assert.equal(f.calls[1].body.operation_id,f.calls[2].body.operation_id);
});
test('cancel start-over receipt is recognized without treating cancellation as successful sign-in',async()=>{
  const f=fixture();await f.flow.verify(code);f.respond(async()=>Response.json(reply('cancelled',{cancel_requested:true,next_action:'start_over'})));
  await f.flow.cancel();assert.equal(f.flow.current().result?.status,'cancelled');assert.equal(f.exchanges(),0);
  await f.flow.forget();assert.equal(f.vault.values.size,0);
});
test('a double press while a registration is in flight dispatches exactly one request',async()=>{
  const f=fixture();await f.flow.verify(code);let resolve!:(response:Response)=>void;
  f.respond(()=>new Promise(done=>{resolve=done;}));const first=f.flow.register('name',password);
  await assert.rejects(f.flow.register('name',password));assert.equal(f.calls.length,2);
  resolve(Response.json(reply('pending'),{status:202}));await first;assert.equal(f.calls.length,2);
});
test('credential rejection requires explicit correction, while pending forbids any new register', async () => {
  const f = fixture(); await f.flow.verify(code); f.respond(async () => Response.json(reply('rejected', {code:'username_unavailable', next_action:'register'})));
  await f.flow.register('name', password); f.respond(async () => Response.json(reply('pending', {next_action:'check_status',retry_after:2}), {status:202}));
  await f.flow.register('other', password); await assert.rejects(f.flow.register('other', password));
  assert.equal(f.calls.filter(call => call.path.endsWith('/register')).length, 2);
});
test('completed registration is not a logged-in session; exchange runs once before clearing recovery', async () => {
  const f = fixture(); await f.flow.verify(code); f.respond(async () => Response.json(completed())); await f.flow.register('name', password);
  assert.equal(f.exchanges(), 0); assert.equal(f.vault.values.size, 1);
  const connection = await f.flow.finish(); assert.ok(connection.session?.accessToken); assert.equal(f.exchanges(), 1); assert.equal(f.vault.values.size, 0);
  await assert.rejects(f.flow.finish()); assert.equal(f.exchanges(), 1);
});
test('lost exchange cannot reuse an old handoff even if status repeats it', async () => {
  const f = fixture(); let attempts = 0;
  const flow = new EnrollmentFlow({vault:f.vault,now:()=>now,proof:async()=>({operation_id,receipt,verifier,state,challenge}),fetcher:async()=>Response.json(completed()),finish:async()=>{attempts++;throw Error('synthetic response loss');}});
  await flow.verify(code); await assert.rejects(flow.finish()); await flow.status(); await assert.rejects(flow.finish());
  assert.equal(attempts,1); assert.equal(flow.current().result?.next_action,'existing_login'); assert.equal(f.vault.values.size,1);
});
test('late response after leaving cannot grant input or rewrite a newer recovery expiry', async () => {
  const f=fixture(); let resolve!: (response:Response)=>void;
  f.respond(()=>new Promise(done=>{resolve=done;})); const pending=f.flow.verify(code);
  while(!resolve) await new Promise(done=>setImmediate(done)); f.flow.dispose();
  const before=[...f.vault.values.values()]; resolve(Response.json({...reply(),expires_at:new Date(now+850000).toISOString()}));
  await assert.rejects(pending); assert.deepEqual([...f.vault.values.values()],before); assert.equal(f.flow.current().result,null);
});
test('forget is explicit and checked; refused deletion never claims a cleared operation',async()=>{
  const f=fixture();await f.flow.verify(code);f.vault.remove=async()=>{};
  await assert.rejects(f.flow.forget());assert.ok(f.flow.current().recovery);assert.equal(f.vault.values.size,1);
});
test('cancelled response clears nothing until the user explicitly forgets, and pending cancellation stays pending',async()=>{
  const f=fixture();await f.flow.verify(code);f.respond(async()=>Response.json(reply('pending',{cancel_requested:true,next_action:'check_status'}),{status:202}));
  await f.flow.cancel();assert.equal(f.flow.current().result?.status,'pending');assert.equal(f.vault.values.size,1);
  await f.flow.forget();assert.equal(f.vault.values.size,0);assert.equal(f.calls.filter(call=>call.path.endsWith('/cancel')).length,1);
});
test('a cancelled foreground status read preserves proof and rejects a late completed result without exchange',async()=>{
 const f=fixture();await f.flow.verify(code);
 f.respond(async()=>Response.json(reply('pending',{retry_after:5})));await f.flow.register('name',password);
 const abort=new AbortController();let resolve!:(value:Response)=>void;
 f.respond(async()=>new Promise<Response>(r=>{resolve=r;}));const read=f.flow.status(abort.signal);abort.abort();resolve(Response.json(completed()));
 await assert.rejects(read);assert.equal(f.flow.current().result?.status,'pending');assert.equal(f.exchanges(),0);assert.equal(f.vault.values.size,1);
 assert.equal(f.calls.filter(call=>call.path.endsWith('/register')).length,1);
 assert.equal(f.calls.at(-1)?.path,'/auth/mobile/enrollment/status');assert.equal('password' in f.calls.at(-1)!.body,false);
});
test('foreground polling uses only status after unknown registration and completion never auto-exchanges',async()=>{
 const {ReadOnlyPoll}=await import('./read-only-poll');const f=fixture();await f.flow.verify(code);
 f.respond(async()=>{throw Error('synthetic lost reply');});await assert.rejects(f.flow.register('name',password));
 const jobs=new Map<number,()=>void>();let id=0;const accepted:string[]=[];
 f.respond(async()=>Response.json(reply('pending',{retry_after:5})));
 const poll=new ReadOnlyPoll({read:signal=>f.flow.status(signal),accept:value=>{accepted.push(value.result!.status);return value.result?.status==='pending'?5000:null;},error:()=>false,schedule:fn=>{jobs.set(++id,fn);return id;},cancel:key=>{jobs.delete(key as number);}});
 const step=async()=>{const entry=jobs.entries().next().value!;jobs.delete(entry[0]);entry[1]();await new Promise<void>(resolve=>setImmediate(resolve));};
 poll.setForeground(true);await step();f.respond(async()=>Response.json(completed()));await step();
 assert.deepEqual(accepted,['pending','completed']);assert.equal(jobs.size,0);assert.equal(f.exchanges(),0);
 assert.equal(f.calls.filter(call=>call.path.endsWith('/register')).length,1);assert.equal(f.calls.slice(2).every(call=>call.path.endsWith('/status')&&!('password'in call.body)),true);poll.dispose();
});
