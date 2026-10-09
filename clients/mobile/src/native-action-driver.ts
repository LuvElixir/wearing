import type * as Calendar from 'expo-calendar/legacy';
import type * as Location from 'expo-location';
import {boundedNativeRead} from './nativeConnectionsModel';
import {allowedNativeMethods, isNativeWrite, isNativeEdit, validateNativeTarget, sameNativeValue, nativeRequest, type NativeDevice, type NativeList, type NativeMethod, type NativePolicy, type NativeRequest} from './native-action-model';

export type ActionCalendar = Pick<typeof Calendar, 'getCalendarPermissionsAsync' | 'requestCalendarPermissionsAsync' | 'getRemindersPermissionsAsync' | 'requestRemindersPermissionsAsync' | 'getCalendarsAsync' | 'getEventsAsync' | 'getRemindersAsync' | 'createEventAsync' | 'getEventAsync' | 'createReminderAsync' | 'getReminderAsync' | 'updateEventAsync' | 'deleteEventAsync' | 'updateReminderAsync' | 'deleteReminderAsync'>;
export type ActionLocation = Pick<typeof Location, 'getForegroundPermissionsAsync' | 'requestForegroundPermissionsAsync' | 'hasServicesEnabledAsync' | 'getCurrentPositionAsync'>;
export class NativeDriverError extends Error {constructor(readonly code: 'permission' | 'inactive' | 'readback' | 'native_error' | 'expired' | 'conflict' | 'unsupported') {super({permission:'系统权限或所选列表已变化，请重新检查。',inactive:'App 已离开前台，这次操作已停止。',readback:'系统操作结果尚未核对，请查看实际记录。',native_error:'系统操作未返回完整回执，请先核对记录。',expired:'请求已到期，请回到原任务查看。',conflict:'系统记录已有变化或不再存在，本次没有修改。请先重新读取。',unsupported:'这类系统记录目前不能安全修改，请在系统应用处理。'}[code]);}}
const iso = (v: string | Date | undefined | null) => v && Number.isFinite(new Date(v).getTime()) ? new Date(v).toISOString() : null;
const clip = (v: unknown, max: number) => typeof v === 'string' ? v.slice(0, max) : '';
const eventData = (e: Calendar.Event) => ({id:e.id, calendar_id:e.calendarId, title:clip(e.title,300), notes:clip(e.notes,1000), start:iso(e.startDate), end:iso(e.endDate), all_day:e.allDay === true});
const reminderData = (r: Calendar.Reminder) => ({id:r.id, calendar_id:r.calendarId, title:clip(r.title,300), notes:clip(r.notes,1000), due:iso(r.dueDate), all_day:typeof r.allDay === 'boolean' ? r.allDay : null, completed:r.completed === true});

/** No permission dialogs or model-supplied native function names in this executor. */
export class NativeActionDriver {
  constructor(readonly calendar: ActionCalendar | null, readonly location: ActionLocation | null, private readonly active: () => boolean, private readonly now: () => number = Date.now, private readonly digest?: (value:string)=>Promise<string>) {}
  private check(r?: NativeRequest) {
    if (!this.active()) throw new NativeDriverError('inactive');
    if (r && Date.parse(r.command.expires_at) <= this.now()) throw new NativeDriverError('expired');
  }
  async permission(kind: 'calendar' | 'reminders' | 'location', ask = false): Promise<boolean> {
    this.check();
    const calendar = this.calendar, location = this.location;
    const get = kind === 'location' ? location?.getForegroundPermissionsAsync : kind === 'calendar' ? calendar?.getCalendarPermissionsAsync : calendar?.getRemindersPermissionsAsync;
    const request = kind === 'location' ? location?.requestForegroundPermissionsAsync : kind === 'calendar' ? calendar?.requestCalendarPermissionsAsync : calendar?.requestRemindersPermissionsAsync;
    if (!get) return false;
    let result = await get(); this.check();
    if (ask && !result.granted && result.canAskAgain && request) {result = await request(); this.check();}
    return result.granted;
  }
  async lists(kind: 'calendar' | 'reminders', ask = false): Promise<NativeList[]> {
    if (!this.calendar || !await this.permission(kind, ask)) throw new NativeDriverError('permission');
    const rows = await boundedNativeRead(this.calendar.getCalendarsAsync(kind === 'calendar' ? 'event' : 'reminder'), 'native lists timeout'); this.check();
    return rows.map(r => ({id:r.id,title:clip(r.title,200) || '未命名列表',writable:r.allowsModifications === true}));
  }
  async capabilities(policy: NativePolicy): Promise<NativeMethod[]> {
    const allowed = allowedNativeMethods(policy), result: NativeMethod[] = [];
    for (const kind of ['calendar','reminders'] as const) {
      const chosen = kind === 'calendar' ? policy.calendars : policy.reminders;
      if (!chosen.length) continue;
      try {
        const lists = await this.lists(kind);
        if (chosen.every(c => lists.some(l => l.id === c.id))) result.push(`${kind}.read` as NativeMethod);
        if (chosen.some(c => c.writable && lists.some(l => l.id === c.id && l.writable))) {result.push(`${kind}.create` as NativeMethod); if (this.digest) result.push(`${kind}.update` as NativeMethod,`${kind}.delete` as NativeMethod);}
      } catch (error) {if (error instanceof NativeDriverError && error.code === 'inactive') throw error;}
    }
    if (policy.location && await this.permission('location') && await this.location?.hasServicesEnabledAsync()) result.push('location.read');
    this.check(); return result.filter(m => allowed.includes(m)).sort();
  }
  private pack(items: Record<string, unknown>[], limit: number) {
    const selected: Record<string, unknown>[] = []; let size = 0;
    for (const item of items.slice(0,limit)) {size += JSON.stringify(item).length * 3; if (size > 96000) break; selected.push(item);}
    return {items:selected, has_more:selected.length < items.length, returned:selected.length, text_may_be_truncated:true};
  }
  async execute(r: NativeRequest, device: NativeDevice): Promise<Record<string, unknown>> {
    this.check(r);
    const method = r.command.method, p = r.command.params;
    if (method === 'reminders.create' && p.all_day !== false) throw new NativeDriverError('permission');
    if (method === 'location.read') {
      if (!this.location || !await this.permission('location') || !await this.location.hasServicesEnabledAsync()) throw new NativeDriverError('permission');
      this.check(r);
      const value = await boundedNativeRead(this.location.getCurrentPositionAsync({accuracy:3}), 'native location timeout');
      if (!await this.permission('location')) throw new NativeDriverError('permission');
      this.check(r);
      if (!Number.isFinite(value.timestamp) || Math.abs(this.now() - value.timestamp) > 120000 || !Number.isFinite(value.coords.latitude) || Math.abs(value.coords.latitude) > 90 || !Number.isFinite(value.coords.longitude) || Math.abs(value.coords.longitude) > 180 || value.coords.accuracy === null || !Number.isFinite(value.coords.accuracy) || value.coords.accuracy < 0) throw new NativeDriverError('readback');
      return {latitude:value.coords.latitude,longitude:value.coords.longitude,accuracy:value.coords.accuracy,timestamp:new Date(value.timestamp).toISOString()};
    }
    const kind = method.startsWith('calendar.') ? 'calendar' : 'reminders';
    const lists = await this.lists(kind), api = this.calendar!;
    const ids = isNativeWrite(method) ? [p.calendar_id as string] : p.calendar_ids as string[];
    const chosen = kind === 'calendar' ? device.policy.calendars : device.policy.reminders;
    if (!ids.every(id => chosen.some(l => l.id === id) && lists.some(l => l.id === id && (!isNativeWrite(method) || l.writable)))) throw new NativeDriverError('permission');
    this.check(r);
    if (method === 'calendar.read') {
      const rows = await boundedNativeRead(api.getEventsAsync(ids,new Date(p.start as string),new Date(p.end as string)), 'native events timeout');
      if (!await this.permission('calendar')) throw new NativeDriverError('permission');
      this.check(r);
      return this.pack(await Promise.all(rows.filter(row => ids.includes(row.calendarId)).slice(0,(p.limit as number)+1).map(row => this.readData(row,true))),p.limit as number);
    }
    if (method === 'reminders.read') {
      const rows = await boundedNativeRead(api.getRemindersAsync(ids,null,null,null), 'native reminders timeout');
      if (!await this.permission('reminders')) throw new NativeDriverError('permission');
      this.check(r);
      return this.pack(await Promise.all(rows.filter(row => !!row.calendarId && ids.includes(row.calendarId) && (p.completed || !row.completed)).slice(0,(p.limit as number)+1).map(row => this.readData(row,false))),p.limit as number);
    }
    if (isNativeEdit(method)) return this.mutate(r,device);
    // Claim and the local durable intent exist before this point. There is NO
    // timeout wrapper/retry on a native write: loss of receipt means unknown.
    const marker = 'pajio://native/' + r.id;
    if (method === 'calendar.create') {
      const id = await api.createEventAsync(p.calendar_id as string, {title:p.title as string, notes:p.notes as string, startDate:p.start as string, endDate:p.end as string, allDay:p.all_day as boolean, url:marker});
      if (!id) throw new NativeDriverError('readback');
      const saved = await api.getEventAsync(id);
      if (saved.id !== id || saved.calendarId !== p.calendar_id || saved.url !== marker || saved.title !== p.title || (saved.notes || '') !== p.notes || iso(saved.startDate) !== iso(p.start as string) || iso(saved.endDate) !== iso(p.end as string) || saved.allDay !== p.all_day) throw new NativeDriverError('readback');
      return {...eventData(saved),notes:saved.notes || '',marker};
    }
    const id = await api.createReminderAsync(p.calendar_id as string, {title:p.title as string,notes:p.notes as string,allDay:p.all_day as boolean,...(p.due ? {dueDate:p.due as string} : {}),completed:false,url:marker});
    if (!id) throw new NativeDriverError('readback');
    const saved = await api.getReminderAsync(id);
    if (saved.id !== id || saved.calendarId !== p.calendar_id || saved.url !== marker || saved.title !== p.title || (saved.notes || '') !== p.notes || iso(saved.dueDate) !== (p.due ? iso(p.due as string) : null) || (saved.allDay === true) !== p.all_day || saved.completed === true) throw new NativeDriverError('readback');
    return {...reminderData(saved),notes:saved.notes || '',marker};
  }
  private async revision(value: unknown) {
    if (!this.digest) throw new NativeDriverError('unsupported');
    const raw=canonicalNativeRecord(value);
    if (raw.length>262144) throw new NativeDriverError('unsupported');
    const hash=await this.digest(raw);
    if (!/^[a-f0-9]{64}$/.test(hash)) throw new NativeDriverError('readback');
    return hash;
  }
  private async readData(raw: Calendar.Event | Calendar.Reminder, event: boolean): Promise<Record<string,unknown>> {
    const value = event ? eventData(raw as Calendar.Event) : reminderData(raw as Calendar.Reminder);
    if (!this.digest) return value; // Legacy read-only test/runtime adapters cannot authorize a mutation.
    const recurring = !!raw.recurrenceRule || (event && (raw as Calendar.Event).isDetached === true);
    const mutable = (event || !recurring) && typeof raw.id==='string' && raw.id.length<=240 && (raw.title||'').length<=300 && (raw.notes||'').length<=1000
      && (event ? typeof (raw as Calendar.Event).allDay==='boolean' : typeof (raw as Calendar.Reminder).completed==='boolean')
      && (!event || ((raw.alarms === undefined || Array.isArray(raw.alarms)) && !(raw.alarms || []).some(a=>a.structuredLocation) && typeof (raw as Calendar.Event).availability==='string'));
    return {...value,snapshot:{revision:await this.revision(raw),recurring,occurrence_start:event?iso((raw as Calendar.Event).startDate):null,mutable}};
  }
  private async readTarget(p:Record<string,unknown>, event:boolean) {
    const target=p.target as Record<string,unknown>, snap=target.snapshot as {occurrence_start:string|null};
    const raw = await boundedNativeRead<Calendar.Event|Calendar.Reminder>(event ? this.calendar!.getEventAsync(target.id as string,{instanceStartDate:snap.occurrence_start!}) : this.calendar!.getReminderAsync(target.id as string),'native target timeout');
    if (raw.id!==target.id || raw.calendarId!==p.calendar_id || (event && iso((raw as Calendar.Event).startDate)!==snap.occurrence_start)) throw new NativeDriverError('conflict');
    return raw;
  }
  /** Read-only recovery inspection. Neither absence nor a changed record rewrites the original receipt. */
  async inspect(r:NativeRequest, device:NativeDevice):Promise<string> {
    this.check();nativeRequest(r,device.identity_id,device.installation_id);
    if (r.command.scope.tenant_id!==device.server_id || !isNativeEdit(r.command.method)) throw new NativeDriverError('unsupported');
    validateNativeTarget(r.command.method,r.command.params);
    const event=r.command.method.startsWith('calendar.'), kind=event?'calendar':'reminders', p=r.command.params, target=p.target as Record<string,unknown>;
    const chosen=event?device.policy.calendars:device.policy.reminders, lists=await this.lists(kind);
    if (!device.enabled || !chosen.some(l=>l.id===p.calendar_id) || !lists.some(l=>l.id===p.calendar_id)) throw new NativeDriverError('permission');
    const records = event ? await boundedNativeRead(this.calendar!.getEventsAsync([p.calendar_id as string],new Date(Date.parse(target.start as string)-1),new Date(Date.parse(target.end as string)+1)),'native review timeout') : await boundedNativeRead(this.calendar!.getRemindersAsync([p.calendar_id as string],null,null,null),'native review timeout');
    this.check();if (!await this.permission(kind)) throw new NativeDriverError('permission');
    const found=records.filter(v=>v.id===target.id && v.calendarId===p.calendar_id && (!event || iso((v as Calendar.Event).startDate)===target.start));
    if (!found.length) return event ? '在原来时间范围内未找到这一次记录。它可能已删除或被移到其他时间，请同时到系统日历核对。' : '系统列表中未找到原提醒。这个读取结果不会把原操作改成成功。';
    const current=found[0], unchanged=await this.revision(current)===(target.snapshot as {revision:string}).revision;
    this.check();
    return [unchanged?'系统记录与操作前一致。':'系统记录已有变化，请核对下方实际内容。',current.title||'未命名',current.notes||'',
      ...(event?['开始：'+iso((current as Calendar.Event).startDate),'结束：'+iso((current as Calendar.Event).endDate)]
        :['完成：'+((current as Calendar.Reminder).completed?'是':'否'),'日期：'+(iso((current as Calendar.Reminder).dueDate)||'未设置'),...(typeof (current as Calendar.Reminder).allDay!=='boolean'?['系统未提供日期是否全天的信息。']:[])]),
      '原请求仍保留原来的结果状态，不会自动重做。'].filter(Boolean).join('\n');
  }
  private async mutate(r:NativeRequest, device:NativeDevice):Promise<Record<string,unknown>> {
    const method=r.command.method,p=r.command.params,event=method.startsWith('calendar.'),kind=event?'calendar':'reminders';
    validateNativeTarget(method,p);
    const target=p.target as Record<string,unknown>, snapshot=target.snapshot as {revision:string;recurring:boolean;occurrence_start:string|null};
    let before:Calendar.Event|Calendar.Reminder;
    try {before=await this.readTarget(p,event);} catch {throw new NativeDriverError('conflict');}
    if (await this.revision(before)!==snapshot.revision) throw new NativeDriverError('conflict');
    if (!event && before.recurrenceRule) throw new NativeDriverError('unsupported');
    if (event && (before.alarms || []).some(a=>a.structuredLocation)) throw new NativeDriverError('unsupported');
    const currentLists=await this.lists(kind), selected=event?device.policy.calendars:device.policy.reminders;
    if (!selected.some(c=>c.id===p.calendar_id&&c.writable) || !currentLists.some(c=>c.id===p.calendar_id&&c.writable)) throw new NativeDriverError('permission');
    // Permissions may await the native bridge: reread immediately before the write.
    const checked=await this.readTarget(p,event);
    if (await this.revision(checked)!==snapshot.revision) throw new NativeDriverError('conflict');
    this.check(r);
    const options={instanceStartDate:snapshot.occurrence_start!,futureEvents:false}, api=this.calendar!;
    const base={record_ref:p.record_ref,before_revision:snapshot.revision,operation:method};
    if (method.endsWith('.delete')) {
      if (event) await api.deleteEventAsync(target.id as string,options); else await api.deleteReminderAsync(target.id as string);
      // Only a successful scoped list read proves absence. Exceptions are unknown, never absence.
      const rows=event ? await api.getEventsAsync([p.calendar_id as string],new Date(Date.parse(target.start as string)-1),new Date(Date.parse(target.end as string)+1)) : await api.getRemindersAsync([p.calendar_id as string],null,null,null);
      if (!await this.permissionAfterWrite(kind) || rows.some(row=>row.id===target.id && row.calendarId===p.calendar_id && (!event || iso((row as Calendar.Event).startDate)===target.start))) throw new NativeDriverError('readback');
      return {...base,record:null,absent:true};
    }
    const patch=p.patch as Record<string,unknown>;
    let saved:Calendar.Event|Calendar.Reminder;
    if (event) {
      const previous=before as Calendar.Event;
      const id=await api.updateEventAsync(target.id as string,{title:(patch.title??previous.title) as string,notes:(patch.notes??previous.notes??'') as string,location:previous.location,alarms:previous.alarms || [],allDay:previous.allDay,availability:previous.availability,
        ...(patch.start?{startDate:patch.start as string}:{}),...(patch.end?{endDate:patch.end as string}:{})},options);
      if (!id) throw new NativeDriverError('readback');
      saved=await api.getEventAsync(id,{instanceStartDate:(patch.start??target.start) as string});
      if (saved.calendarId!==p.calendar_id || !sameNativeValue(saved.alarms || [],previous.alarms || []) || (saved.location||'')!==(previous.location||'') || saved.availability!==previous.availability) throw new NativeDriverError('readback');
    } else {
      const previous=before as Calendar.Reminder;
      const id=await api.updateReminderAsync(target.id as string,{title:(patch.title??previous.title) as string,notes:(patch.notes??previous.notes??'') as string,location:previous.location,...(patch.completed!==undefined?{completed:patch.completed as boolean}:{})});
      if (!id || id!==target.id) throw new NativeDriverError('readback');
      saved=await api.getReminderAsync(id);
      if ((saved.location||'')!==(previous.location||'') || iso(saved.startDate)!==iso(previous.startDate) || !sameNativeValue(saved.alarms,previous.alarms)) throw new NativeDriverError('readback');
    }
    const record=event?eventData(saved as Calendar.Event):reminderData(saved as Calendar.Reminder);
    const expected={...target,...patch};delete expected.snapshot;expected.id=record.id;
    for (const key of ['start','end']) if (expected[key]!==undefined) expected[key]=iso(expected[key] as string);
    if (!sameNativeValue(record,expected) || !await this.permissionAfterWrite(kind)) throw new NativeDriverError('readback');
    return {...base,record,absent:false};
  }
  private async permissionAfterWrite(kind:'calendar'|'reminders') {
    try {return await this.permission(kind);} catch {return false;}
  }

}

/** Full native record, including untruncated notes, alarms, recurrence and modification date. */
export function canonicalNativeRecord(value:unknown):string {
  const visit=(v:unknown):unknown=>v instanceof Date?v.toISOString():Array.isArray(v)?v.map(visit):v&&typeof v==='object'?Object.fromEntries(Object.entries(v).filter(([,item])=>item!==undefined).sort(([a],[b])=>a.localeCompare(b)).map(([key,item])=>[key,visit(item)])):v;
  return JSON.stringify(visit(value));
}
