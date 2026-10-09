import type * as Calendar from 'expo-calendar/legacy';
import {boundedNativeRead, calendarEventTime, calendarPreviews, type CalendarPreview} from './nativeConnectionsModel';
import {withRecordDraft} from './record-editor';

export type NativeCalendarApi = Pick<typeof Calendar, 'getCalendarPermissionsAsync' | 'requestCalendarPermissionsAsync' | 'getRemindersPermissionsAsync' |
  'requestRemindersPermissionsAsync' | 'getCalendarsAsync' | 'getEventsAsync' | 'createEventInCalendarAsync' | 'editEventInCalendarAsync' | 'openEventInCalendarAsync' |
  'getRemindersAsync' | 'getReminderAsync' | 'createReminderAsync' | 'updateReminderAsync' | 'deleteReminderAsync'>;
export type CalendarList = {id: string; title: string; writable: boolean};
export type NativeEvent = CalendarPreview & {id: string; writable: boolean};
export type ReminderRow = {id: string; calendarId: string; calendar: string; writable: boolean; title: string; notes: string; completed: boolean;
  dueDate: string | null; allDay: boolean | null; raw: Calendar.Reminder; revision: string};
export type ReminderDraft = {calendarId: string; title: string; notes: string; dueDate: string | null; allDay: boolean | null};
export type ReminderIntent = {requestId: string; draft: ReminderDraft};
export class NativePermissionError extends Error {constructor(message: string, readonly settings: boolean) {super(message);}}
const text = (v: unknown): v is string => typeof v === 'string';
const readable = (v: unknown) => text(v) && v.length > 0;
const iso = (v: string | Date | undefined): string | null => v && Number.isFinite(new Date(v).getTime()) ? new Date(v).toISOString() : null;
// SDK 57's legacy iOS serializer omits allDay. Midnight is not evidence of an all-day reminder.
export const reminderAllDay = (value: Calendar.Reminder): boolean | null => typeof value.allDay === 'boolean' ? value.allDay : null;

/** Includes native modification metadata and content so a stale form cannot overwrite a fresh edit. */
export function reminderRevision(value: Calendar.Reminder): string {
  return JSON.stringify([value.id, value.calendarId, value.title || '', value.notes || '', value.location || '', value.url || '',
    value.completed === true, value.allDay === true, iso(value.startDate), iso(value.dueDate), iso(value.completionDate), iso(value.lastModifiedDate), value.recurrenceRule || null, value.alarms || []]);
}
export function reminderDraft(value: ReminderRow): ReminderDraft {return {calendarId: value.calendarId, title: value.title, notes: value.notes, dueDate: value.dueDate, allDay: value.allDay};}
const sameDraft = (saved: ReminderDraft, requested: ReminderDraft) => saved.calendarId === requested.calendarId && saved.title === requested.title && saved.notes === requested.notes && saved.dueDate === requested.dueDate &&
  (saved.allDay === null || saved.allDay === requested.allDay);
export function validateReminderDraft(value: ReminderDraft): ReminderDraft {
  if (!readable(value.calendarId) || !text(value.title) || !value.title.trim() || value.title.trim().length > 300 || !text(value.notes) || value.notes.length > 5000 ||
    (value.dueDate !== null && !iso(value.dueDate)) || (value.allDay !== null && typeof value.allDay !== 'boolean')) throw new Error('请填写提醒标题，并检查日期和备注长度。');
  const due = value.dueDate ? new Date(value.dueDate) : null;
  if (due && value.allDay) due.setHours(0, 0, 0, 0);
  return {...value, title: value.title.trim(), notes: value.notes.trim(), dueDate: due?.toISOString() || null};
}
export function nativeDialogMessage(result: {action: string}, platform: string): string {
  if (platform === 'android' || result.action === 'done') return '已返回 Pajio，正在重新读取系统日历。';
  if (result.action === 'saved') return '已保存到系统日历。';
  if (result.action === 'deleted') return '已从系统日历删除。';
  return '已关闭系统日历编辑器。';
}
export function reminderTime(value: ReminderRow): string {
  if (!value.dueDate) return '未设日期';
  const d = new Date(value.dueDate);
  if (value.allDay === null) return d.toLocaleDateString('zh-CN') + ' · 具体时间请在系统提醒事项中查看';
  return d.toLocaleString('zh-CN', value.allDay ? {year: 'numeric', month: 'numeric', day: 'numeric'} : {month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false});
}

export class NativeCalendarService {
  constructor(private readonly api: NativeCalendarApi, private readonly platform: string, private readonly active: () => boolean = () => true) {}
  private checkActive() {if (!this.active()) throw new Error('页面已切换，请在当前身份中重新操作。');}
  async permission(kind: 'event' | 'reminder', ask: boolean) {
    if (kind === 'reminder' && this.platform !== 'ios') throw new Error('Apple 提醒事项只在 iPhone 上提供。');
    const get = kind === 'event' ? this.api.getCalendarPermissionsAsync : this.api.getRemindersPermissionsAsync;
    const request = kind === 'event' ? this.api.requestCalendarPermissionsAsync : this.api.requestRemindersPermissionsAsync;
    let value = await get();
    if (!value.granted && value.canAskAgain && ask) {this.checkActive(); value = await request();}
    this.checkActive();
    if (!value.granted) throw new NativePermissionError(kind === 'event' ? '需要允许访问系统日历。' : '需要允许访问提醒事项。', !value.canAskAgain);
  }
  private async calendars(kind: 'event' | 'reminder'): Promise<CalendarList[]> {
    const rows = await boundedNativeRead(this.api.getCalendarsAsync(kind), '读取系统日历超时，请重试。');
    this.checkActive();
    return rows.map(value => ({id: value.id, title: value.title, writable: value.allowsModifications === true}));
  }
  async events(days: 7 | 30 = 7): Promise<NativeEvent[]> {
    await this.permission('event', true);
    const calendars = await this.calendars('event'), start = new Date(), end = new Date(start);
    end.setDate(end.getDate() + days);
    const rows = calendars.length ? await boundedNativeRead(this.api.getEventsAsync(calendars.map(c => c.id), start, end), '读取日程超时，请重试。') : [];
    await this.permission('event', false);
    const names = Object.fromEntries(calendars.map(c => [c.id, c.title]));
    const previews = calendarPreviews(rows, names);
    return previews.map(p => {
      const original = rows.find(r => `${r.calendarId}:${r.id}:${new Date(r.startDate).getTime()}` === p.key)!;
      return {...p, id: original.id, writable: calendars.some(c => c.id === original.calendarId && c.writable)};
    });
  }
  async eventDialog(event?: NativeEvent): Promise<string> {
    this.checkActive();
    if (event) await this.permission('event', false);
    // The system sheet owns dates, recurrence scope and delete confirmation.
    const options = {startNewActivityTask: false};
    const result = event ? event.writable ? await this.api.editEventInCalendarAsync({id: event.id, instanceStartDate: new Date(event.start)}, options)
      : await this.api.openEventInCalendarAsync({id: event.id, instanceStartDate: new Date(event.start)}, {...options, allowsEditing: false})
      : await this.api.createEventInCalendarAsync({}, options);
    this.checkActive(); return nativeDialogMessage(result, this.platform);
  }
  private row(value: Calendar.Reminder, calendars: CalendarList[]): ReminderRow {
    if (!readable(value.id) || !readable(value.calendarId) || (value.dueDate !== undefined && value.dueDate !== null && !iso(value.dueDate))) throw new Error('提醒事项回执不完整，请重新读取。');
    const calendar = calendars.find(c => c.id === value.calendarId);
    if (!calendar) throw new Error('这条提醒不在当前可见的列表里，请重新读取。');
    return {id: value.id!, calendarId: value.calendarId!, calendar: calendar.title, writable: calendar.writable,
      title: value.title?.trim() || '未命名提醒', notes: value.notes || '', completed: value.completed === true,
      dueDate: iso(value.dueDate), allDay: reminderAllDay(value), raw: value, revision: reminderRevision(value)};
  }
  async reminders(): Promise<{calendars: CalendarList[]; items: ReminderRow[]}> {
    await this.permission('reminder', true);
    const calendars = await this.calendars('reminder');
    // An unbounded date range with status=null includes undated reminders; status filters require dates.
    const values = calendars.length ? await boundedNativeRead(this.api.getRemindersAsync(calendars.map(c => c.id), null, null, null), '读取提醒事项超时，请重试。') : [];
    await this.permission('reminder', false);
    const rows = values.map(v => this.row(v, calendars));
    if (new Set(rows.map(r => r.id)).size !== rows.length) throw new Error('提醒事项列表不完整，请重新读取。');
    return {calendars, items: rows.sort((a, b) => Number(a.completed) - Number(b.completed) || (a.dueDate || 'z').localeCompare(b.dueDate || 'z') || a.title.localeCompare(b.title))};
  }
  async createReminder(intent: ReminderIntent): Promise<ReminderRow> {
    if (!/^[a-f0-9]{32}$/.test(intent.requestId)) throw new Error('创建请求未完整保存，请重新填写。');
    const draft = validateReminderDraft(intent.draft), marker = 'pajio://reminder/' + intent.requestId;
    // Serializes the same durable intent even when an old screen is still finishing after unmount.
    return withRecordDraft('native-reminder:' + intent.requestId, async () => {
      const {calendars, items} = await this.reminders();
      const found = items.filter(r => r.raw.url === marker);
      if (found.length > 1) throw new Error('找到了多份同一次创建的提醒，请先在系统提醒事项里核对。');
      if (found.length === 1) {
        if (!sameDraft(reminderDraft(found[0]), draft)) throw new Error('这条提醒已经在系统里修改过，请重新读取；不会重复创建。');
        return found[0];
      }
      // Allow recovery of an already-written legacy intent above, but never write an unverifiable all-day request.
      if (draft.allDay !== false) throw new Error('请在系统提醒事项中创建全天提醒；这里支持未设日期或指定时间的提醒。');
      if (!calendars.some(c => c.id === draft.calendarId && c.writable)) throw new Error('请选择可以写入的提醒事项列表。');
      this.checkActive();
      const id = await this.api.createReminderAsync(draft.calendarId, {title: draft.title, notes: draft.notes, url: marker, allDay: draft.allDay,
        ...(draft.dueDate ? {dueDate: draft.dueDate} : {}), completed: false});
      if (!readable(id)) throw new Error('尚未收到创建回执，请恢复这次请求核对结果。');
      const saved = this.row(await this.api.getReminderAsync(id), calendars);
      if (saved.id !== id || saved.raw.url !== marker || !sameDraft(reminderDraft(saved), draft)) throw new Error('保存后的提醒与本次内容不一致，请重新读取并核对。');
      return saved;
    });
  }
  private async current(value: ReminderRow): Promise<{row: ReminderRow; calendars: CalendarList[]}> {
    await this.permission('reminder', false);
    const calendars = await this.calendars('reminder');
    const row = this.row(await this.api.getReminderAsync(value.id), calendars);
    if (row.id !== value.id || row.revision !== value.revision) throw new Error('这条提醒刚在系统中有了变化，请重新读取后再修改。你的编辑仍保留。');
    if (!row.writable) throw new Error('这个提醒事项列表只读。');
    this.checkActive(); return {row, calendars};
  }
  async updateReminder(before: ReminderRow, draft: ReminderDraft, completed = before.completed): Promise<ReminderRow> {
    const patch = validateReminderDraft(draft);
    const {row, calendars} = await this.current(before);
    if (patch.calendarId !== row.calendarId) throw new Error('请在系统提醒事项中移动列表。');
    if (patch.allDay !== row.allDay || (patch.dueDate !== row.dueDate && row.allDay !== false)) throw new Error('请在系统提醒事项中修改日期或全天设置；这里可以修改标题、备注和完成状态。');
    // SDK 57's iOS bridge does not clear nil dueDate components. Never silently keep a removed date.
    if (row.dueDate && !patch.dueDate) throw new Error('请在系统提醒事项中移除日期；这里可以修改日期和时间。');
    // Omitting unchanged dates preserves native date components. Sending them again would turn an unknown all-day reminder into a timed one.
    const datePatch = patch.dueDate !== row.dueDate && patch.dueDate ? {dueDate: patch.dueDate, allDay: false} : {};
    const id = await this.api.updateReminderAsync(row.id, {title: patch.title, notes: patch.notes,
      location: row.raw.location || '', ...datePatch, completed});
    if (id !== row.id) throw new Error('未收到对应提醒的保存回执，请重新读取。');
    const saved = this.row(await this.api.getReminderAsync(id), calendars);
    if (saved.completed !== completed || !sameDraft(reminderDraft(saved), patch)) throw new Error('系统中的提醒与这次修改不一致，请重新读取核对。');
    return saved;
  }
  async deleteReminder(value: ReminderRow): Promise<void> {
    const {row} = await this.current(value);
    await this.api.deleteReminderAsync(row.id);
    // Native promise resolution is a commit acknowledgement. A later full list supplies the UI state.
  }
}

export function selectedNativeCalendarDraft(events: NativeEvent[], selected: string[]): string {
  const set = new Set(selected), chosen = events.filter(e => set.has(e.key));
  return chosen.length ? '这是我从手机系统日历选出的安排：\n' + chosen.map(e => `- ${calendarEventTime(e)}：${e.title}（${e.calendar}）`).join('\n') : '';
}
