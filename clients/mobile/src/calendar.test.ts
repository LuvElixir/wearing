import {test} from 'node:test';
import assert from 'node:assert/strict';
import {dateKey, daysInMonth, eventOccursOn, localDateTime, monthWeeks, moveMonth} from './calendar';
import {previewCalendarEvents} from './experience/calendar-events';

function inTimezone(zone: string, run: () => void) {
  const previous = process.env.TZ;
  process.env.TZ = zone;
  try {run();} finally {if (previous === undefined) delete process.env.TZ; else process.env.TZ = previous;}
}

test('month navigation crosses years and clamps days to the destination month', () => {
  assert.deepEqual(moveMonth({year: 2026, month: 12, day: 31}, 1), {year: 2027, month: 1, day: 31});
  assert.deepEqual(moveMonth({year: 2026, month: 1, day: 31}, -1), {year: 2025, month: 12, day: 31});
  assert.deepEqual(moveMonth({year: 2026, month: 1, day: 31}, 1), {year: 2026, month: 2, day: 28});
  assert.deepEqual(moveMonth({year: 2028, month: 3, day: 31}, -1), {year: 2028, month: 2, day: 29});
  assert.deepEqual(moveMonth({year: 2026, month: 10, day: 7}, 12), {year: 2027, month: 10, day: 7});
});

test('February respects Gregorian leap-year and century boundaries', () => {
  assert.equal(daysInMonth(2028, 2), 29);
  assert.equal(daysInMonth(2026, 2), 28);
  assert.equal(daysInMonth(1900, 2), 28);
  assert.equal(daysInMonth(2000, 2), 29);
  assert.equal(daysInMonth(2100, 2), 28);
});

test('the month grid is Monday-first and includes every date exactly once', () => {
  const october = monthWeeks({year: 2026, month: 10});
  assert.deepEqual(october[0].map(date => date?.day ?? null), [null, null, null, 1, 2, 3, 4]);
  for (const year of [2026, 2028, 2100]) for (let month = 1; month <= 12; month++) {
    const weeks = monthWeeks({year, month});
    assert(weeks.length >= 4 && weeks.length <= 6);
    assert(weeks.every(week => week.length === 7));
    assert.deepEqual(weeks.flat().filter(date => date !== null).map(date => date.day),
      Array.from({length: daysInMonth(year, month)}, (_, i) => i + 1));
  }
  assert.equal(monthWeeks({year: 2026, month: 3}).length, 6);
});

test('month positions and civil date keys do not depend on the device timezone', () => {
  for (const zone of ['Asia/Shanghai', 'America/Los_Angeles', 'Pacific/Auckland']) inTimezone(zone, () => {
    assert.equal(monthWeeks({year: 2026, month: 3})[0][6]?.day, 1);
    assert.equal(dateKey({year: 2026, month: 1, day: 2}), '2026-01-02');
  });
});

test('a timed event appears on each local day it overlaps, including month boundaries', () => {
  inTimezone('Asia/Shanghai', () => {
    const event = {start_at: '2026-10-31T15:45:00Z', end_at: '2026-10-31T16:15:00Z'};
    assert(eventOccursOn(event, {year: 2026, month: 10, day: 31}));
    assert(eventOccursOn(event, {year: 2026, month: 11, day: 1}));
    assert(!eventOccursOn(event, {year: 2026, month: 11, day: 2}));
    assert(!eventOccursOn(event, {year: 2026, month: 10, day: 30}));
  });
});

test('an event ending at local midnight does not occupy the following day', () => {
  inTimezone('Asia/Shanghai', () => {
    const event = {start_at: '2026-12-31T23:00:00+08:00', end_at: '2027-01-01T00:00:00+08:00'};
    assert(eventOccursOn(event, {year: 2026, month: 12, day: 31}));
    assert(!eventOccursOn(event, {year: 2027, month: 1, day: 1}));
  });
});

test('all-day ranges keep their civil dates in western and eastern timezones', () => {
  const event = {all_day: true, start_at: '2026-12-31', end_at: '2027-01-02'};
  for (const zone of ['Asia/Shanghai', 'America/Los_Angeles']) inTimezone(zone, () => {
    assert(!eventOccursOn(event, {year: 2026, month: 12, day: 30}));
    assert(eventOccursOn(event, {year: 2026, month: 12, day: 31}));
    assert(eventOccursOn(event, {year: 2027, month: 1, day: 1}));
    assert(!eventOccursOn(event, {year: 2027, month: 1, day: 2}));
  });
});

test('day ranges follow local DST midnights rather than assuming 24 hours', () => {
  inTimezone('America/New_York', () => {
    const spring = {year: 2026, month: 3, day: 8}, fall = {year: 2026, month: 11, day: 1};
    assert.equal(localDateTime({...spring, day: 9}).getTime() - localDateTime(spring).getTime(), 23 * 3600000);
    assert.equal(localDateTime({...fall, day: 2}).getTime() - localDateTime(fall).getTime(), 25 * 3600000);
    assert(!eventOccursOn({start_at: '2026-03-09T00:15:00-04:00', end_at: '2026-03-09T00:30:00-04:00'}, spring));
    assert(eventOccursOn({start_at: '2026-11-01T23:15:00-05:00', end_at: '2026-11-01T23:30:00-05:00'}, fall));
  });
});

test('incomplete and invalid timed records cannot create phantom calendar entries', () => {
  const date = {year: 2026, month: 10, day: 6};
  for (const event of [{}, {start_at: 'broken', end_at: 'broken'}, {start_at: '2026-10-06T14:00:00Z'},
    {start_at: '2026-10-06T14:00:00Z', end_at: '2026-10-06T14:00:00Z'},
    {start_at: '2026-10-06T15:00:00Z', end_at: '2026-10-06T14:00:00Z'}]) assert(!eventOccursOn(event, date));
});

test('preview events retain their exact dates and weekend confirmation spans only two days', () => {
  const entries = previewCalendarEvents(true);
  const count = (year: number, month: number, day: number) => entries.filter(event => eventOccursOn(event, {year, month, day})).length;
  assert.equal(count(2026, 10, 6), 2);
  assert.equal(count(2026, 11, 6), 0);
  assert.equal(count(2027, 10, 6), 0);
  assert.equal(count(2026, 10, 10), 1);
  assert.equal(count(2026, 10, 11), 1);
  assert.equal(count(2026, 10, 12), 0);
  assert(!previewCalendarEvents(false).some(event => event.id === 'weekend'));
});
