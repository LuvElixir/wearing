import {ApiError, type Store} from './core';
import {withRecordDraft} from './record-editor';
import {syncKey, syncNonce, syncSettings, validSources, validSyncBatch, type SyncLocal, type SyncSettings, type SyncSource, type SyncSnapshot, type SyncBatch, type SyncReceipt} from './native-sync-model';

export class SyncPermissionLost extends Error {}
export type SyncRemote = {state():Promise<SyncSettings>; configure(v:SyncSettings & {request_id:string}):Promise<SyncSettings>; upload(v:SyncBatch):Promise<SyncReceipt>};
type SyncStore = Pick<Store,'get'|'put'>;
export function validateSyncLocal(value: SyncLocal | null): SyncLocal | null {
  if (!value) return null;
  if (value.version !== 1 || !/^[a-f0-9]{32}$/.test(value.installation) || !/^[a-f0-9]{32}$/.test(value.choice) || !value.desired || typeof value.desired.enabled !== 'boolean' || !validSources(value.desired.sources) || value.desired.enabled && !value.desired.sources.length) throw new Error('本机同步设置无法读取，请保留数据并重新打开。');
  syncSettings(value.settings);
  if (!(value.configured===null || value.configured===value.choice) || typeof value.error!=='string' ||
    value.configured===value.choice && (value.settings.enabled!==value.desired.enabled || JSON.stringify(value.settings.sources)!==JSON.stringify(value.desired.sources)) ||
    value.pendingConfig!==null && (!value.pendingConfig || !syncNonce(value.pendingConfig.request_id) || syncSettings(value.pendingConfig).enabled!==value.desired.enabled || JSON.stringify(value.pendingConfig.sources)!==JSON.stringify(value.desired.sources)) ||
    value.pending!==null && (!value.desired.enabled || value.configured!==value.choice || !validSyncBatch(value.pending,value.settings))) throw new Error('本机同步队列无法核对，保留原数据等待检查。');
  return value;
}
export async function chooseNativeSync(store:SyncStore, scope:string, desired:{enabled:boolean;sources:SyncSource[]}, nonce:()=>string) {
  if (!validSources(desired.sources) || desired.enabled && !desired.sources.length) throw new Error('请先选择要同步的来源。');
  const key = syncKey(scope);
  return withRecordDraft(key, async () => {
    const before = validateSyncLocal(await store.get<SyncLocal>(key));
    const next:SyncLocal = {version:1, installation:before?.installation || nonce(), choice:nonce(), desired,
      configured:null, settings:before?.settings || {revision:0,enabled:false,sources:[]}, pendingConfig:null, pending:null, receipt:before?.receipt || null, error:''};
    await store.put(key,next); return next;
  });
}

/** One run owns one selection generation; every asynchronous boundary rechecks it. */
export async function runNativeSync(options:{store:SyncStore;scope:string;remote:(state:SyncLocal)=>SyncRemote;active:()=>boolean;nonce:()=>string;
  allowed:(sources:SyncSource[])=>Promise<void>;read:(source:SyncSource)=>Promise<SyncSnapshot>;changed:()=>void;now?:()=>string}) {
  const {store,scope,active,nonce} = options, key = syncKey(scope);
  let value = validateSyncLocal(await store.get<SyncLocal>(key));
  if (!value || !active()) return;
  const choice = value.choice, remote = options.remote(value);
  const check = async () => active() && (await store.get<SyncLocal>(key))?.choice === choice;
  const update = async (patch:Partial<SyncLocal>) => withRecordDraft(key, async () => {
    const current = validateSyncLocal(await store.get<SyncLocal>(key));
    if (!active() || !current || current.choice !== choice) throw new Error('同步选择已变化。');
    value = {...current,...patch}; await store.put(key,value);
  });
  try {
    if (value.configured !== choice) {
      if (!value.pendingConfig) {
        const state = await remote.state();
        if (!await check()) return;
        await update({pendingConfig:{...value.desired,revision:state.revision,request_id:nonce()}});
      }
      const settings = await remote.configure(value.pendingConfig!);
      if (!await check()) return;
      await update({settings,configured:choice,pendingConfig:null,error:''});
    }
    if (!value.desired.enabled || !await check()) return;
    await options.allowed(value.desired.sources);
    if (!await check()) return;
    if (value.pending) {
      const result = await remote.upload(value.pending);
      if (!await check()) return;
      await update({pending:null,receipt:result,error:''}); options.changed();
    }
    // Bounded independently per selected list; partial or missing sources never become deletion signals.
    for (const source of value.desired.sources) {
      if (!await check()) return;
      const snapshot = await options.read(source);
      if (!await check()) return;
      await options.allowed(value.desired.sources);
      if (!await check()) return;
      const pending:SyncBatch = {request_id:nonce(),revision:value.settings.revision,observed_at:(options.now || (()=>new Date().toISOString()))(),snapshots:[snapshot]};
      await update({pending});
      if (!await check()) return;
      const receipt = await remote.upload(pending);
      if (!await check()) return;
      await update({pending:null,receipt,error:''}); options.changed();
    }
  } catch (error) {
    if (!await check()) return;
    if (error instanceof SyncPermissionLost) {
      await chooseNativeSync(store,scope,{enabled:false,sources:value.desired.sources},nonce);
    } else {
      await update({error:error instanceof Error ? error.message : '同步暂未完成。', ...(error instanceof ApiError && error.status === 409 ? {configured:null,pendingConfig:null,pending:null} : {})});
    }
    throw error;
  }
}
