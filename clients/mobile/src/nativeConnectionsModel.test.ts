import {strict as assert} from 'node:assert';
import {test} from 'node:test';
import {calendarEventTime, calendarPreviews, locationDraft, nativeDraftError, NATIVE_DRAFT_LIMIT, selectedCalendarDraft} from './nativeConnectionsModel';

test('calendar preview preserves recurring occurrences, deduplicates repeats and rejects invalid dates', () => {
  const rows = calendarPreviews([
    {id: 'same', title: '周会', calendarId: 'work', startDate: '2026-10-07T10:00:00+08:00', endDate: '2026-10-07T11:00:00+08:00'},
    {id: 'same', title: '周会', calendarId: 'work', startDate: '2026-10-08T10:00:00+08:00', endDate: '2026-10-08T11:00:00+08:00'},
    {id: 'same', title: '周会', calendarId: 'work', startDate: '2026-10-07T10:00:00+08:00', endDate: '2026-10-07T11:00:00+08:00'},
    {id: 'bad', title: '坏日期', calendarId: 'work', startDate: 'invalid', endDate: 'invalid'},
  ], {work: '工作'});
  assert.equal(rows.length, 2);
  assert.notEqual(rows[0].key, rows[1].key);
  assert.equal(rows[0].calendar, '工作');
});

test('draft includes only explicit selected rows; an empty or stale selection sends no calendar context', () => {
  const rows = calendarPreviews([
    {id: 'a', title: '已选安排', calendarId: 'work', startDate: '2026-10-07T10:00:00Z', endDate: '2026-10-07T11:00:00Z'},
    {id: 'b', title: '私人安排', calendarId: 'private', startDate: '2026-10-08T10:00:00Z', endDate: '2026-10-08T11:00:00Z'},
  ], {});
  assert.equal(selectedCalendarDraft(rows, []), '');
  assert.equal(selectedCalendarDraft(rows, ['gone']), '');
  assert.match(selectedCalendarDraft(rows, [rows[0].key]), /已选安排/);
  assert.doesNotMatch(selectedCalendarDraft(rows, [rows[0].key]), /私人安排/);
});

test('location draft includes observation time and accuracy but rejects invalid coordinates', () => {
  const location = {latitude: 31.23042, longitude: 121.4737, accuracy: 65.7, timestamp: 1791340000000};
  assert.match(locationDraft(location), /31.23042/);
  assert.match(locationDraft(location), /66 米/);
  assert.equal(locationDraft({...location, latitude: NaN}), '');
  assert.equal(locationDraft({...location, longitude: 181}), '');
});

test('calendar draft preserves year and both ends of an overnight event across New Year', () => {
  const rows = calendarPreviews([{id: 'overnight', title: '跨年值班', calendarId: 'work',
    startDate: new Date(2026, 11, 31, 23, 30), endDate: new Date(2027, 0, 1, 1, 15)}], {});
  const draft = selectedCalendarDraft(rows, [rows[0].key]);
  assert.match(draft, /2026年12月31日 23:30–2027年1月1日 01:15/);
});

test('same-day event shows its end time and multi-day all-day events retain an exclusive end', () => {
  const rows = calendarPreviews([
    {id: 'meeting', title: '会议', calendarId: 'work', startDate: new Date(2026, 9, 7, 10), endDate: new Date(2026, 9, 7, 11, 45)},
    {id: 'trip', title: '出差', calendarId: 'work', allDay: true, startDate: new Date(2026, 9, 8), endDate: new Date(2026, 9, 10)},
  ], {});
  assert.equal(calendarEventTime(rows[0]), '2026年10月7日 10:00–11:45');
  assert.equal(calendarEventTime(rows[1]), '2026年10月8日 至 2026年10月9日 · 全天');
  assert.match(selectedCalendarDraft(rows, [rows[1].key]), /2026年10月10日 00:00 结束，不含结束时刻/);
});

test('oversized calendar selection is rejected with a recovery action, and deselecting makes it importable', () => {
  const rows = calendarPreviews([
    {id: 'long', title: '长日程标题'.repeat(2500), calendarId: 'work', startDate: new Date(2026, 9, 7, 10), endDate: new Date(2026, 9, 7, 11)},
    {id: 'short', title: '拿快递', calendarId: 'work', startDate: new Date(2026, 9, 8, 10), endDate: new Date(2026, 9, 8, 11)},
  ], {});
  const all = selectedCalendarDraft(rows, rows.map(row => row.key));
  assert.ok(all.length > NATIVE_DRAFT_LIMIT);
  assert.match(nativeDraftError(all)!, /减少勾选的日程/);
  assert.equal(nativeDraftError(selectedCalendarDraft(rows, [rows[1].key])), null);
  // Emoji use two UTF-16 code units, matching the existing bridge's .length gate.
  assert.equal(nativeDraftError('📅'.repeat(6000)), null);
  assert.match(nativeDraftError('📅'.repeat(6000) + '。')!, /12,000/);
});
