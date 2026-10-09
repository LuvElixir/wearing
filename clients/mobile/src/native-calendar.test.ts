import {test} from 'node:test';
import assert from 'node:assert/strict';
import type {Calendar, Event, PermissionResponse, Reminder} from 'expo-calendar/legacy';
import {NativeCalendarService, NativePermissionError, nativeDialogMessage, reminderDraft, reminderTime, validateReminderDraft,
  type NativeCalendarApi, type NativeEvent, type ReminderDraft, type ReminderIntent} from './native-calendar';

const granted = {status: 'granted', granted: true, canAskAgain: true, expires: 'never'} as PermissionResponse;
const denied = {status: 'denied', granted: false, canAskAgain: false, expires: 'never'} as PermissionResponse;
const calendar = (patch: Partial<Calendar> = {}): Calendar => ({id: 'calendar_test', title: '合成列表', allowsModifications: true, color: '#123456', source: {id: 'source_test', name: '合成源'}, allowedAvailabilities: [], ...patch});
const rawReminder = (patch: Partial<Reminder> = {}): Reminder => ({id: 'reminder_test', calendarId: 'calendar_test', title: '合成提醒', notes: '原备注', location: '原地点', completed: false,
  lastModifiedDate: '2026-10-07T01:00:00Z', dueDate: '2026-10-08T07:00:00Z', allDay: false, ...patch});
const draft: ReminderDraft = {calendarId: 'calendar_test', title: '新提醒', notes: '要保留的备注', dueDate: '2026-10-08T07:00:00.000Z', allDay: false};
const intent = (patch: Partial<ReminderIntent> = {}): ReminderIntent => ({requestId: 'a'.repeat(32), draft, ...patch});
function harness(initial: Reminder[] = [], overrides: Partial<NativeCalendarApi> = {}, platform = 'ios', active = () => true) {
  const rows = initial.map(row => ({...row})), calls: {method: string; args: unknown[]}[] = [];
  const record = (method: string, ...args: unknown[]) => {calls.push({method, args});};
  const api: NativeCalendarApi = {
    getCalendarPermissionsAsync: async () => {record('getCalendarPermissions'); return granted;},
    requestCalendarPermissionsAsync: async () => {record('requestCalendarPermissions'); return granted;},
    getRemindersPermissionsAsync: async () => {record('getRemindersPermissions'); return granted;},
    requestRemindersPermissionsAsync: async () => {record('requestRemindersPermissions'); return granted;},
    getCalendarsAsync: async kind => {record('getCalendars', kind); return [calendar()];},
    getEventsAsync: async (...args) => {record('getEvents', ...args); return [];},
    createEventInCalendarAsync: async (...args) => {record('createEventDialog', ...args); return {action: 'saved', id: 'event_created'} as never;},
    editEventInCalendarAsync: async (...args) => {record('editEventDialog', ...args); return {action: 'saved', id: 'event_test'} as never;},
    openEventInCalendarAsync: async (...args) => {record('viewEventDialog', ...args); return {action: 'done'} as never;},
    getRemindersAsync: async (...args) => {record('getReminders', ...args); return rows.map(row => ({...row}));},
    getReminderAsync: async id => {record('getReminder', id); const row = rows.find(r => r.id === id); if (!row) throw new Error('not found'); return {...row};},
    createReminderAsync: async (calendarId, value) => {record('createReminder', calendarId, value); const id = `created_${rows.length}`; rows.push({...value, id, calendarId: calendarId!}); return id;},
    // Mirrors SDK 57's unconditional native assignment of title/location.
    updateReminderAsync: async (id, value) => {record('updateReminder', id, value); const i = rows.findIndex(r => r.id === id); if (i < 0) throw new Error('not found'); rows[i] = {...rows[i], ...value, title: value?.title, location: value?.location}; return id;},
    deleteReminderAsync: async id => {record('deleteReminder', id); const i = rows.findIndex(r => r.id === id); if (i < 0) throw new Error('not found'); rows.splice(i, 1);},
    ...overrides,
  };
  return {service: new NativeCalendarService(api, platform, active), rows, calls, api};
}

test('denied native permissions stop before personal data collection and expose a settings action', async () => {
  const h = harness([], {getCalendarPermissionsAsync: async () => denied});
  await assert.rejects(() => h.service.events(), e => e instanceof NativePermissionError && e.settings);
  assert.equal(h.calls.some(c => c.method === 'getCalendars' || c.method === 'getEvents'), false);
});

test('only a user-initiated read can prompt, and a revoked grant discards the just-read event results', async () => {
  let checks = 0, prompts = 0;
  const h = harness([], {getCalendarPermissionsAsync: async () => ++checks === 1 ? {...denied, canAskAgain: true} : denied,
    requestCalendarPermissionsAsync: async () => {prompts++; return granted;}});
  await assert.rejects(() => h.service.events(), NativePermissionError);
  assert.equal(prompts, 1);
  assert.equal(h.calls.filter(c => c.method === 'getEvents').length, 1);
  await assert.rejects(() => h.service.permission('event', false), NativePermissionError);
  assert.equal(prompts, 1);
});

test('recurring events preserve the selected occurrence when opening native edit and read-only dialogs', async () => {
  const source = {id: 'repeat_id', calendarId: 'calendar_test', title: '循环会议', startDate: '2026-10-08T07:00:00Z', endDate: '2026-10-08T08:00:00Z'} as Event;
  const h = harness([], {getEventsAsync: async () => [source, {...source, startDate: '2026-10-09T07:00:00Z', endDate: '2026-10-09T08:00:00Z'}]});
  const events = await h.service.events(30);
  assert.equal(events.length, 2); assert.notEqual(events[0].key, events[1].key);
  await h.service.eventDialog(events[1]);
  const edit = h.calls.find(c => c.method === 'editEventDialog')!;
  assert.deepEqual(edit.args, [{id: 'repeat_id', instanceStartDate: new Date('2026-10-09T07:00:00Z')}, {startNewActivityTask: false}]);
  await h.service.eventDialog({...events[0], writable: false});
  assert.deepEqual(h.calls.find(c => c.method === 'viewEventDialog')!.args[1], {startNewActivityTask: false, allowsEditing: false});
});

test('Android native dialog done never claims a saved or deleted event; iOS receipts are differentiated', async () => {
  assert.match(nativeDialogMessage({action: 'done'}, 'android'), /重新读取/);
  assert.doesNotMatch(nativeDialogMessage({action: 'done'}, 'android'), /已保存|已删除/);
  assert.equal(nativeDialogMessage({action: 'saved'}, 'ios'), '已保存到系统日历。');
  assert.equal(nativeDialogMessage({action: 'deleted'}, 'ios'), '已从系统日历删除。');
  assert.doesNotMatch(nativeDialogMessage({action: 'canceled'}, 'ios'), /已保存/);
  const h = harness(); await h.service.eventDialog();
  assert.deepEqual(h.calls, [{method: 'createEventDialog', args: [{}, {startNewActivityTask: false}]}]);
});

test('reminder reads explicitly include undated items and separate completed from incomplete rows', async () => {
  const h = harness([rawReminder({id: 'finished', completed: true}), rawReminder({id: 'undated', dueDate: undefined})]);
  const {items, calendars} = await h.service.reminders();
  assert.deepEqual(h.calls.find(c => c.method === 'getReminders')!.args, [['calendar_test'], null, null, null]);
  assert.equal(items[0].id, 'undated'); assert.equal(items[0].dueDate, null); assert.equal(items[1].completed, true);
  assert.equal(calendars[0].writable, true);
});

test('reminders are iOS-only and a missing identity on native rows is not accepted as usable data', async () => {
  const android = harness([], {}, 'android');
  await assert.rejects(() => android.service.reminders(), /只在 iPhone/);
  assert.equal(android.calls.length, 0);
  const malformed = harness([rawReminder({id: undefined})]);
  await assert.rejects(() => malformed.service.reminders(), /回执不完整/);
});

test('drafts validate blank titles and normalize all-day due dates to local midnight', () => {
  assert.throws(() => validateReminderDraft({...draft, title: ' \n '}), /提醒标题/);
  assert.throws(() => validateReminderDraft({...draft, dueDate: 'invalid-date'}), /日期/);
  const value = validateReminderDraft({...draft, title: ' 新提醒 ', notes: ' 备注 ', allDay: true});
  assert.equal(new Date(value.dueDate!).getHours(), 0);
  assert.equal(value.title, '新提醒'); assert.equal(value.notes, '备注');
});

test('native creation returns a read-back receipt with a recoverable request marker', async () => {
  const h = harness();
  const saved = await h.service.createReminder(intent());
  assert.equal(saved.title, draft.title);
  assert.equal(saved.raw.url, 'pajio://reminder/' + 'a'.repeat(32));
  assert.deepEqual(h.calls.filter(c => c.method === 'createReminder')[0].args, ['calendar_test', {
    title: draft.title, notes: draft.notes, url: saved.raw.url, allDay: false, dueDate: draft.dueDate, completed: false,
  }]);
});

test('a lost create receipt is recovered by the same intent without another native create', async () => {
  const h = harness(); let writes = 0;
  const original = h.api.createReminderAsync;
  h.api.createReminderAsync = async (id, value) => {const result = await original(id, value); if (++writes === 1) throw new Error('native commit succeeded, receipt lost'); return result;};
  await assert.rejects(() => h.service.createReminder(intent()), /receipt lost/);
  const saved = await h.service.createReminder(intent());
  assert.equal(saved.id, h.rows[0].id); assert.equal(writes, 1); assert.equal(h.rows.length, 1);
});

test('same-intent simultaneous requests share the cross-screen queue and create only once', async () => {
  const h = harness(), same = intent({requestId: 'b'.repeat(32)});
  const [one, two] = await Promise.all([h.service.createReminder(same), h.service.createReminder(same)]);
  assert.equal(one.id, two.id); assert.equal(h.calls.filter(c => c.method === 'createReminder').length, 1);
});

test('an already-created reminder changed externally is not replaced or duplicated during recovery', async () => {
  const h = harness(); await h.service.createReminder(intent());
  h.rows[0].title = '用户在系统里改过';
  await assert.rejects(() => h.service.createReminder(intent()), /不会重复创建/);
  assert.equal(h.rows.length, 1); assert.equal(h.rows[0].title, '用户在系统里改过');
});

test('read-only lists and leaving the identity before mutation prevent native writes', async () => {
  const readonly = harness([], {getCalendarsAsync: async () => [calendar({allowsModifications: false})]});
  await assert.rejects(() => readonly.service.createReminder(intent()), /可以写入/);
  assert.equal(readonly.calls.filter(c => c.method === 'createReminder').length, 0);
  let active = true;
  const changed = harness([], {getRemindersAsync: async () => {active = false; return [];}}, 'ios', () => active);
  await assert.rejects(() => changed.service.createReminder(intent()), /页面已切换/);
  assert.equal(changed.calls.filter(c => c.method === 'createReminder').length, 0);
});

test('completion and reopening preserve title, notes, location and the existing due date', async () => {
  const h = harness([rawReminder()]);
  const before = (await h.service.reminders()).items[0];
  const done = await h.service.updateReminder(before, reminderDraft(before), true);
  assert.equal(done.completed, true);
  assert.equal(done.title, before.title); assert.equal(done.raw.location, '原地点');
  const reopened = await h.service.updateReminder(done, reminderDraft(done), false);
  assert.equal(reopened.completed, false);
  assert.equal(reopened.dueDate, before.dueDate);
  assert.ok(h.calls.filter(c => c.method === 'updateReminder').every(c => (c.args[1] as Reminder).title === before.title && (c.args[1] as Reminder).location === '原地点'));
});

test('external edits conflict before native update or delete and preserve the untouched system object', async () => {
  const h = harness([rawReminder()]); const before = (await h.service.reminders()).items[0];
  h.rows[0].notes = '外部修改';
  await assert.rejects(() => h.service.updateReminder(before, {...reminderDraft(before), title: '我的草稿'}), /编辑仍保留/);
  await assert.rejects(() => h.service.deleteReminder(before), /重新读取/);
  assert.equal(h.calls.filter(c => ['updateReminder', 'deleteReminder'].includes(c.method)).length, 0);
  assert.equal(h.rows[0].notes, '外部修改');
});

test('a malformed write receipt and a native bridge silently retaining changed fields are not treated as saved', async () => {
  const h = harness([rawReminder()], {updateReminderAsync: async () => 'different_id'});
  const before = (await h.service.reminders()).items[0];
  await assert.rejects(() => h.service.updateReminder(before, reminderDraft(before), true), /对应提醒/);
  const unchanged = harness([rawReminder()], {updateReminderAsync: async () => 'reminder_test'});
  const original = (await unchanged.service.reminders()).items[0];
  await assert.rejects(() => unchanged.service.updateReminder(original, {...reminderDraft(original), title: '新标题'}), /不一致/);
});

test('unsupported due-date removal is rejected instead of falsely reporting it cleared', async () => {
  const h = harness([rawReminder()]); const before = (await h.service.reminders()).items[0];
  await assert.rejects(() => h.service.updateReminder(before, {...reminderDraft(before), dueDate: null}), /移除日期/);
  assert.equal(h.calls.filter(c => c.method === 'updateReminder').length, 0);
});

test('deleting re-reads the exact reminder and then deletes only its native id', async () => {
  const h = harness([rawReminder(), rawReminder({id: 'unrelated'})]); const before = (await h.service.reminders()).items.find(r => r.id === 'reminder_test')!;
  await h.service.deleteReminder(before);
  assert.deepEqual(h.calls.filter(c => c.method === 'deleteReminder'), [{method: 'deleteReminder', args: ['reminder_test']}]);
  assert.deepEqual(h.rows.map(r => r.id), ['unrelated']);
});

test('an event edit cannot start after the screen was left', async () => {
  const h = harness([], {}, 'ios', () => false);
  await assert.rejects(() => h.service.eventDialog({id: 'event', start: 100} as NativeEvent), /页面已切换/);
  assert.equal(h.calls.length, 0);
});

function legacyReceipts(h: ReturnType<typeof harness>) {
  const one = h.api.getReminderAsync, many = h.api.getRemindersAsync;
  const serialized = (value: Reminder) => {const row = {...value}; delete row.allDay; return row;};
  h.api.getReminderAsync = async id => serialized(await one(id));
  h.api.getRemindersAsync = async (...args) => (await many(...args)).map(serialized);
}

test('SDK 57 missing allDay stays unknown and never shows midnight as a confirmed reminder time', async () => {
  const h = harness([rawReminder({allDay: true, dueDate: '2026-10-08T00:00:00Z'})]); legacyReceipts(h);
  const row = (await h.service.reminders()).items[0];
  assert.equal(row.allDay, null); assert.equal(reminderDraft(row).allDay, null);
  assert.match(reminderTime(row), /具体时间请在系统提醒事项中查看/);
});

test('SDK 57 timed creation and lost receipt recovery succeed with unknown allDay, without a second write', async () => {
  const h = harness(); legacyReceipts(h);
  const saved = await h.service.createReminder(intent());
  assert.equal(saved.allDay, null);
  assert.equal((await h.service.createReminder(intent())).id, saved.id);
  assert.equal(h.calls.filter(c => c.method === 'createReminder').length, 1);
});

test('all-day creation is refused before writing, while a pre-existing old intent can still be recovered', async () => {
  const h = harness(); legacyReceipts(h);
  const old = intent({draft: {...draft, allDay: true}});
  await assert.rejects(() => h.service.createReminder(old), /系统提醒事项中创建全天提醒/);
  assert.equal(h.calls.filter(c => c.method === 'createReminder').length, 0);
  const normalized = validateReminderDraft(old.draft);
  h.rows.push(rawReminder({...normalized, dueDate: normalized.dueDate!, allDay: true, url: 'pajio://reminder/' + old.requestId} as Partial<Reminder>));
  assert.equal((await h.service.createReminder(old)).allDay, null);
  assert.equal(h.calls.filter(c => c.method === 'createReminder').length, 0);
});

test('SDK 57 editing or completing an all-day reminder preserves native date components, recurrence and alarms', async () => {
  const h = harness([rawReminder({allDay: true, dueDate: '2026-10-08T00:00:00Z', startDate: '2026-10-08T00:00:00Z',
    recurrenceRule: {frequency: 'daily' as never}, alarms: [{relativeOffset: -10}]})]); legacyReceipts(h);
  const before = (await h.service.reminders()).items[0];
  const saved = await h.service.updateReminder(before, {...reminderDraft(before), title: '新标题'}, true);
  assert.equal(saved.allDay, null); assert.equal(saved.completed, true); assert.equal(h.rows[0].allDay, true);
  const patch = h.calls.find(c => c.method === 'updateReminder')!.args[1] as Partial<Reminder>;
  for (const key of ['allDay', 'dueDate', 'startDate', 'recurrenceRule', 'alarms', 'url']) assert.equal(Object.hasOwn(patch, key), false, key);
  await assert.rejects(() => h.service.updateReminder(saved, {...reminderDraft(saved), dueDate: '2026-10-09T01:00:00Z'}), /系统提醒事项中修改日期/);
  await assert.rejects(() => h.service.updateReminder(saved, {...reminderDraft(saved), allDay: false}), /系统提醒事项中修改日期/);
  assert.equal(h.calls.filter(c => c.method === 'updateReminder').length, 1);
});
