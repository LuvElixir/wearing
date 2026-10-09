import type {Store} from './core';
import {withRecordDraft} from './record-editor';
import {NativeDriverError} from './native-action-driver';
import {isNativeWrite, matchNativeRequest, nativeOutcome, nativeRequest, sameNativeValue, validateNativeDispatch, type NativeDevice, type NativeOutcome, type NativeRequest} from './native-action-model';

type Client = {claim(r: NativeRequest, approve: boolean): Promise<NativeRequest>; finish(r: NativeRequest, o: NativeOutcome): Promise<NativeRequest>};
type Driver = {execute(r: NativeRequest, device: NativeDevice): Promise<Record<string, unknown>>};
type Entry = {request: NativeRequest; phase: 'prepared' | 'admitted' | 'receipt'; outcome?: NativeOutcome};
const interrupted = (write: boolean): NativeOutcome => ({status:write ? 'unknown':'cancelled',code:'interrupted',data:{}});

/** Journal admission before dispatch; recovery submits a receipt, never an action. */
export class NativeActionRunner {
  readonly key: string;
  constructor(private readonly store: Pick<Store,'get'|'put'>, scope: string, private readonly client: Client, private readonly driver: Driver, private readonly active: () => boolean, private readonly now: () => number = Date.now) {this.key = 'native-actions-journal:v1:' + scope;}
  private async load(): Promise<Entry | null> {
    const entry = await this.store.get<Entry>(this.key);
    if (!entry) return null;
    if (!entry.request || !['prepared','admitted','receipt'].includes(entry.phase)) throw new Error('手机执行记录无法读取，请保留此页并重试。');
    nativeRequest(entry.request,entry.request.identity_id,entry.request.installation_id);
    if (entry.phase === 'receipt' && !entry.outcome) throw new Error('手机原始回执未完整保留，请先核对系统记录。');
    if (entry.outcome) nativeOutcome(entry.outcome);
    return entry;
  }
  async recover(): Promise<void> {
    return withRecordDraft(this.key, async () => {
      const saved = await this.load();
      if (!saved) return;
      if (saved.phase === 'prepared') {
        // We cannot know whether a lost claim response admitted the command.
        // No native call was made before the durable admitted phase; nonetheless
        // return uncertainty to the original command instead of replaying it.
        saved.outcome = interrupted(isNativeWrite(saved.request.command.method));
      }
      const outcome = saved.outcome || interrupted(isNativeWrite(saved.request.command.method));
      try {this.receipt(await this.client.finish(saved.request,outcome),saved.request,outcome);}
      catch (error) {
        // A rejected old read/prepared command has no side effect to recover.
        if (!(error instanceof Error && 'status' in error && error.status === 409 && (saved.phase === 'prepared' || !isNativeWrite(saved.request.command.method)))) throw error;
      }
      await this.store.put(this.key,null);
    });
  }
  private receipt(value: NativeRequest, request: NativeRequest, outcome: NativeOutcome): NativeRequest {
    matchNativeRequest(value,request);
    if (value.state !== outcome.status || !sameNativeValue(value.result,outcome)) throw new Error('手机原始回执尚未核对保存，请稍后重试。');
    return value;
  }
  async run(r: NativeRequest, device: NativeDevice, connection: string, approve: boolean): Promise<NativeRequest | null> {
    return withRecordDraft(this.key, async () => {
      if (!this.active()) return null;
      validateNativeDispatch(r,device,connection,this.now());
      if (await this.load()) throw new Error('上一次手机请求的回执仍待恢复，请先核对结果。');
      if (!approve) return this.client.claim(r,false);
      await this.store.put(this.key,{request:r,phase:'prepared'} satisfies Entry);
      if (!this.active()) {await this.store.put(this.key,null); return null;}
      let admitted: NativeRequest;
      try {admitted = await this.client.claim(r,true);}
      catch (error) {throw error;}
      matchNativeRequest(admitted,r);
      if (admitted.state !== 'executing') throw new Error('手机执行许可与原请求不匹配。');
      // If this durable write fails, absolutely no OS action may start.
      await this.store.put(this.key,{request:r,phase:'admitted'} satisfies Entry);
      let outcome: NativeOutcome;
      try {
        if (!this.active()) throw new NativeDriverError('inactive');
        validateNativeDispatch(r,device,connection,this.now());
        const data = await this.driver.execute(r,device);
        if (!isNativeWrite(r.command.method) && !this.active()) throw new NativeDriverError('inactive');
        outcome = {status:'succeeded',code:'ok',data};
      } catch (error) {
        const code = error instanceof NativeDriverError ? error.code : 'native_error';
        // OS write exceptions may follow a commit, so don't label them failed.
        outcome = {status:isNativeWrite(r.command.method) && !['permission','inactive','expired','conflict','unsupported'].includes(code) ? 'unknown' : 'cancelled',code,data:{}};
      }
      await this.store.put(this.key,{request:r,phase:'receipt',outcome} satisfies Entry);
      const receipt = this.receipt(await this.client.finish(r,outcome),r,outcome);
      await this.store.put(this.key,null);
      return receipt;
    });
  }
}
