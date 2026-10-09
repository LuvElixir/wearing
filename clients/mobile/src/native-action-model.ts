import {ApiError} from './core';

export const nativeMethods = ['calendar.read', 'reminders.read', 'location.read', 'calendar.create', 'reminders.create', 'calendar.update', 'calendar.delete', 'reminders.update', 'reminders.delete'] as const;
export type NativeMethod = typeof nativeMethods[number];
export type NativeList = {id: string; title: string; writable: boolean};
export type NativePolicy = {calendars: NativeList[]; reminders: NativeList[]; location: boolean; calendar_create: boolean; reminder_create: boolean; calendar_edit: boolean; reminder_edit: boolean};
export type NativeDevice = {server_id: string; identity_id: string; installation_id: string; name: string; revision: number; enabled: boolean; policy: NativePolicy; online: boolean; capabilities: NativeMethod[]; availability: 'foreground_only'};
export type NativeCredential = {installation_id: string; secret: string};
export type NativeCommand = {protocol_version: '1'; command_id: string; scope: {tenant_id: string; identity_id: string}; task_id: string; resource_id: string; connector_id: string; connection_id: string; pairing_generation: number; policy_revision: number; lease_epoch: number; method: NativeMethod; params: Record<string, unknown>; created_at: string; expires_at: string};
export type NativeOutcome = {status: 'succeeded' | 'cancelled' | 'failed' | 'unknown'; code: 'ok' | 'denied' | 'permission' | 'inactive' | 'expired' | 'native_error' | 'readback' | 'interrupted' | 'conflict' | 'unsupported'; data: Record<string, unknown>};
export type NativeRequest = {id: string; identity_id: string; installation_id: string; task_id: string; task_title?: string; run_id: string; command: NativeCommand; fingerprint: string; state: string; result: NativeOutcome | null; reviewed: boolean};
export const emptyNativePolicy = (): NativePolicy => ({calendars: [], reminders: [], location: false, calendar_create: false, reminder_create: false, calendar_edit: false, reminder_edit: false});
export const isNativeEdit = (method: NativeMethod) => method.endsWith('.update') || method.endsWith('.delete');
export const isNativeWrite = (method: NativeMethod) => method.endsWith('.create') || isNativeEdit(method);
export const hex = (v: unknown, count: number): v is string => typeof v === 'string' && new RegExp(`^[a-f0-9]{${count}}$`).test(v);
export const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const string = (v: unknown, max = 240): v is string => typeof v === 'string' && v.length > 0 && v.length <= max;
const positive = (v: unknown): v is number => Number.isSafeInteger(v) && (v as number) >= 1;
const instant = (v: unknown): v is string => typeof v === 'string' && /(?:Z|[+-]\d\d:\d\d)$/.test(v) && Number.isFinite(Date.parse(v));
const bad = () => new ApiError('手机请求无法核对，已停止执行。请重新读取。', 422);
/** JSON property order is not part of the wire contract. */
export function sameNativeValue(a: unknown, b: unknown): boolean {
  if (Object.is(a,b)) return true;
  if (Array.isArray(a) && Array.isArray(b)) return a.length === b.length && a.every((v,i) => sameNativeValue(v,b[i]));
  if (!object(a) || !object(b)) return false;
  const keys = Object.keys(a);
  return keys.length === Object.keys(b).length && keys.every(k => Object.hasOwn(b,k) && sameNativeValue(a[k],b[k]));
}
export function nativeOutcome(v: unknown): NativeOutcome {
  if (!object(v) || Object.keys(v).some(k => !['status','code','data'].includes(k)) || !['succeeded','failed','cancelled','unknown'].includes(String(v.status)) || !['ok','denied','permission','inactive','expired','native_error','readback','interrupted','conflict','unsupported'].includes(String(v.code)) || !object(v.data) || (v.status === 'succeeded' ? v.code !== 'ok' : Object.keys(v.data).length > 0)) throw bad();
  return v as NativeOutcome;
}
export function matchNativeRequest(actual: NativeRequest, expected: NativeRequest): NativeRequest {
  if (actual.id !== expected.id || actual.identity_id !== expected.identity_id || actual.installation_id !== expected.installation_id || actual.task_id !== expected.task_id || actual.run_id !== expected.run_id || actual.fingerprint !== expected.fingerprint || !sameNativeValue(actual.command,expected.command)) throw bad();
  return actual;
}
export function nativePolicy(v: unknown): NativePolicy {
  if (!object(v)) throw bad();
  for (const k of ['calendars', 'reminders']) {
    const rows = v[k];
    if (!Array.isArray(rows) || rows.length > 30 || rows.some(r => !object(r) || !string(r.id) || !string(r.title, 200) || typeof r.writable !== 'boolean') || new Set(rows.map(r => r.id)).size !== rows.length) throw bad();
  }
  if (['location', 'calendar_create', 'reminder_create'].some(k => typeof v[k] !== 'boolean')) throw bad();
  if (['calendar_edit','reminder_edit'].some(k => v[k] !== undefined && typeof v[k] !== 'boolean')) throw bad();
  return {...v,calendar_edit:v.calendar_edit === true,reminder_edit:v.reminder_edit === true} as NativePolicy;
}
export function nativeDevice(v: unknown, identity: string): NativeDevice {
  if (!object(v) || !hex(v.server_id, 32) || v.identity_id !== identity || !hex(v.installation_id, 32) || !string(v.name, 60) || !positive(v.revision) || typeof v.enabled !== 'boolean' || typeof v.online !== 'boolean' || v.availability !== 'foreground_only' || !Array.isArray(v.capabilities) || v.capabilities.some(m => !nativeMethods.includes(m))) throw bad();
  return {...v,policy:nativePolicy(v.policy)} as NativeDevice;
}
export function nativeRequest(v: unknown, identity: string, installation: string): NativeRequest {
  if (!object(v) || !string(v.id) || !/^native_[a-f0-9]{32}$/.test(v.id) || v.identity_id !== identity || v.installation_id !== installation || !string(v.task_id) || !string(v.run_id) || !hex(v.fingerprint, 64) || typeof v.reviewed !== 'boolean' || !['queued', 'executing', 'succeeded', 'failed', 'cancelled', 'expired', 'unknown'].includes(String(v.state))) throw bad();
  const c = v.command;
  if (!object(c) || c.protocol_version !== '1' || c.command_id !== v.id || !object(c.scope) || !hex(c.scope.tenant_id, 32) || c.scope.identity_id !== identity || c.task_id !== v.task_id || c.resource_id !== installation || c.connector_id !== installation || !hex(c.connection_id, 32) || c.pairing_generation !== 1 || !positive(c.policy_revision) || !positive(c.lease_epoch) || !nativeMethods.includes(c.method as NativeMethod) || !object(c.params) || !instant(c.created_at) || !instant(c.expires_at) || Date.parse(c.expires_at) - Date.parse(c.created_at) > 60000 || Date.parse(c.expires_at) <= Date.parse(c.created_at)) throw bad();
  if (v.result !== null) {const result = nativeOutcome(v.result); if (result.status !== v.state) throw bad();}
  return v as NativeRequest;
}
export function allowedNativeMethods(policy: NativePolicy): NativeMethod[] {
  const methods: NativeMethod[] = [];
  if (policy.calendars.length) {methods.push('calendar.read'); if (policy.calendar_create && policy.calendars.some(c => c.writable)) methods.push('calendar.create'); if (policy.calendar_edit && policy.calendars.some(c=>c.writable)) methods.push('calendar.update','calendar.delete');}
  if (policy.reminders.length) {methods.push('reminders.read'); if (policy.reminder_create && policy.reminders.some(c => c.writable)) methods.push('reminders.create'); if (policy.reminder_edit && policy.reminders.some(c=>c.writable)) methods.push('reminders.update','reminders.delete');}
  if (policy.location) methods.push('location.read');
  return methods.sort();
}
/** Recheck the actual selected lists and immutable foreground epoch at dispatch. */
export function validateNativeDispatch(r: NativeRequest, device: NativeDevice, connection: string, now: number) {
  nativeRequest(r, device.identity_id, device.installation_id);
  const c = r.command, p = c.params;
  if (!device.enabled || !device.online || !device.capabilities.includes(c.method) || c.scope.tenant_id !== device.server_id || c.policy_revision !== device.revision || c.connection_id !== connection || Date.parse(c.expires_at) <= now || Date.parse(c.created_at) > now + 5000 || !allowedNativeMethods(device.policy).includes(c.method)) throw bad();
  const keys = Object.keys(p);
  if (c.method === 'location.read') {if (keys.length) throw bad(); return;}
  const lists = c.method.startsWith('calendar.') ? device.policy.calendars : device.policy.reminders;
  if (isNativeEdit(c.method)) {
    validateNativeTarget(c.method,p);
    if (!lists.some(l => l.id === p.calendar_id && l.writable)) throw bad();
  } else if (isNativeWrite(c.method)) {
    if (!string(p.calendar_id) || !lists.some(l => l.id === p.calendar_id && l.writable) || !string(p.title, 300) || !p.title.trim() || typeof p.notes !== 'string' || p.notes.length > 5000 || typeof p.all_day !== 'boolean') throw bad();
    if (c.method === 'calendar.create') {
      if (keys.some(k => !['calendar_id','title','notes','start','end','all_day'].includes(k)) || !instant(p.start) || !instant(p.end) || Date.parse(p.end) <= Date.parse(p.start) || Date.parse(p.end) - Date.parse(p.start) > 31 * 86400000) throw bad();
    } else if (p.all_day || keys.some(k => !['calendar_id','title','notes','due','all_day'].includes(k)) || (p.due !== null && !instant(p.due))) throw bad();
  } else {
    if (!Array.isArray(p.calendar_ids) || !p.calendar_ids.length || p.calendar_ids.length > 30 || p.calendar_ids.some(id => !lists.some(l => l.id === id)) || new Set(p.calendar_ids).size !== p.calendar_ids.length || !positive(p.limit) || p.limit > 100) throw bad();
    if (c.method === 'calendar.read') {
      if (keys.some(k => !['calendar_ids','start','end','limit'].includes(k)) || !instant(p.start) || !instant(p.end) || Date.parse(p.end) <= Date.parse(p.start) || Date.parse(p.end) - Date.parse(p.start) > 31 * 86400000) throw bad();
    } else if (keys.some(k => !['calendar_ids','completed','limit'].includes(k)) || typeof p.completed !== 'boolean') throw bad();
  }
}
export const nativeMethodLabel = (m: NativeMethod) => ({'calendar.read':'读取所选日历','reminders.read':'读取所选提醒事项','location.read':'读取一次当前位置','calendar.create':'新建系统日程','reminders.create':'新建系统提醒','calendar.update':'修改这一次系统日程','calendar.delete':'删除这一次系统日程','reminders.update':'修改系统提醒','reminders.delete':'删除系统提醒'})[m];
export const nativeStateLabel = (s: string) => ({queued:'等待手机',executing:'正在处理',succeeded:'已核对完成',failed:'未完成',cancelled:'已取消',expired:'请求已到期',unknown:'结果待核对'}[s] || '待核对');
export function nativeRequestSummary(r: NativeRequest, policy: NativePolicy): string {
  const p = r.command.params, lists = r.command.method.startsWith('calendar.') ? policy.calendars : policy.reminders;
  if (r.command.method === 'location.read') return '只读取本次位置，包含坐标、精度和时间，不在后台持续跟踪。';
  if (isNativeEdit(r.command.method)) {
    const t = p.target as Record<string,unknown>, patch = p.patch as Record<string,unknown> | undefined;
    const names:Record<string,string> = {title:'标题',notes:'备注',start:'开始',end:'结束',completed:'完成状态'};
    return ['原记录：'+String(t.title), '所在列表：'+(lists.find(c=>c.id===p.calendar_id)?.title || '所选列表'),
      t.start ? '原开始：'+new Date(String(t.start)).toLocaleString('zh-CN') : '',
      t.end ? '原结束：'+new Date(String(t.end)).toLocaleString('zh-CN') : '', t.due ? '原截止：'+new Date(String(t.due)).toLocaleString('zh-CN') : '',
      t.notes ? '原备注：'+t.notes : '',
      patch ? Object.entries(patch).map(([key,value])=>names[key]+' → '+(key==='completed'?(value?'已完成':'未完成'):['start','end'].includes(key)?new Date(String(value)).toLocaleString('zh-CN'):String(value))).join('\n') : '将从系统应用删除这条记录。',
      (t.snapshot as {recurring?:boolean}).recurring ? '只处理上方这一次，不修改后续日程。' : '',
      '保存前会重新核对系统记录；有变化就停止。'].filter(Boolean).join('\n');
  }
  if (isNativeWrite(r.command.method)) return [String(p.title), '保存到：' + (lists.find(c => c.id === p.calendar_id)?.title || '所选列表'), p.start ? '开始：' + new Date(String(p.start)).toLocaleString('zh-CN') : '', p.end ? '结束：' + new Date(String(p.end)).toLocaleString('zh-CN') : '', p.due ? '提醒：' + new Date(String(p.due)).toLocaleString('zh-CN') : '', p.all_day ? '全天' : '', p.notes ? '备注：' + p.notes : ''].filter(Boolean).join('\n');
  return '读取：' + lists.filter(l => (p.calendar_ids as string[]).includes(l.id)).map(l => l.title).join('、') + (p.start ? '\n' + new Date(String(p.start)).toLocaleDateString('zh-CN') + ' — ' + new Date(String(p.end)).toLocaleDateString('zh-CN') : '') + `\n最多 ${p.limit} 项；内容只回到当前身份的这次任务。`;
}

/** The server resolves this immutable target exclusively from a prior phone read. */
export function validateNativeTarget(method: NativeMethod, p: Record<string,unknown>) {
  const t=p.target, patch=p.patch, deleting=method.endsWith('.delete'), event=method.startsWith('calendar.');
  if (!isNativeEdit(method) || Object.keys(p).some(k=>!(deleting?['record_ref','calendar_id','target']:['record_ref','calendar_id','target','patch']).includes(k)) || typeof p.record_ref!=='string' || !/^native_[a-f0-9]{32}:[0-9]{1,2}$/.test(p.record_ref) || !object(t) || !string(t.id) || t.calendar_id!==p.calendar_id || !string(p.calendar_id) || typeof t.title!=='string' || t.title.length>300 || typeof t.notes!=='string' || t.notes.length>1000) throw bad();
  const snap=t.snapshot;
  if (!object(snap) || Object.keys(snap).sort().join('|')!=='mutable|occurrence_start|recurring|revision' || !hex(snap.revision,64) || snap.mutable!==true || typeof snap.recurring!=='boolean') throw bad();
  const fields=['id','calendar_id','title','notes','all_day','snapshot',...(event?['start','end']:['due','completed'])];
  if (Object.keys(t).length!==fields.length || Object.keys(t).some(k=>!fields.includes(k))) throw bad();
  if (event) {if (typeof t.all_day!=='boolean' || !instant(t.start) || !instant(t.end) || Date.parse(t.end)<=Date.parse(t.start) || snap.occurrence_start!==t.start) throw bad();}
  else if (snap.recurring || snap.occurrence_start!==null || !(t.all_day===null || typeof t.all_day==='boolean') || typeof t.completed!=='boolean' || !(t.due===null || instant(t.due))) throw bad();
  if (!deleting) {
    if (!object(patch) || !Object.keys(patch).length || Object.keys(patch).some(k=>!(event?['title','notes','start','end']:['title','notes','completed']).includes(k))) throw bad();
    if (patch.title!==undefined && (!string(patch.title,300) || !patch.title.trim())) throw bad();
    if (patch.notes!==undefined && (typeof patch.notes!=='string' || patch.notes.length>1000)) throw bad();
    if (patch.completed!==undefined && typeof patch.completed!=='boolean') throw bad();
    if (event) {
      if ((patch.start!==undefined || patch.end!==undefined) && t.all_day) throw bad();
      const start=patch.start??t.start,end=patch.end??t.end;
      if (!instant(start) || !instant(end) || Date.parse(end)<=Date.parse(start) || Date.parse(end)-Date.parse(start)>31*86400000) throw bad();
    }
  }
}
