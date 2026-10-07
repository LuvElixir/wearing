export type CalendarDate = {year: number; month: number; day: number};
export type CalendarEvent = {start_at?: string; end_at?: string; all_day?: boolean};

export function dateKey(date: CalendarDate): string {
  return `${String(date.year).padStart(4, '0')}-${String(date.month).padStart(2, '0')}-${String(date.day).padStart(2, '0')}`;
}

export function daysInMonth(year: number, month: number): number {
  const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  return [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1];
}

/** Moving from a long month keeps the selected day within the destination month. */
export function moveMonth(date: CalendarDate, offset: number): CalendarDate {
  const index = date.year * 12 + date.month - 1 + offset;
  const year = Math.floor(index / 12), month = index - year * 12 + 1;
  return {year, month, day: Math.min(date.day, daysInMonth(year, month))};
}

/** Monday-first rows; empty cells are spacing, never selectable dates. */
export function monthWeeks(date: Pick<CalendarDate, 'year' | 'month'>): (CalendarDate | null)[][] {
  const first = new Date(0);
  first.setUTCFullYear(date.year, date.month - 1, 1);
  first.setUTCHours(0, 0, 0, 0);
  const offset = (first.getUTCDay() + 6) % 7;
  const count = daysInMonth(date.year, date.month);
  return Array.from({length: Math.ceil((offset + count) / 7)}, (_, row) =>
    Array.from({length: 7}, (_, column) => {
      const day = row * 7 + column - offset + 1;
      return day > 0 && day <= count ? {...date, day} : null;
    }));
}

export function localDateTime(date: CalendarDate, hour = 0): Date {
  const value = new Date(0);
  value.setFullYear(date.year, date.month - 1, date.day);
  value.setHours(hour, 0, 0, 0);
  return value;
}

/** End times are exclusive. Civil all-day dates must never pass through UTC parsing. */
export function eventOccursOn(event: CalendarEvent, date: CalendarDate): boolean {
  if (!event.start_at || !event.end_at) return false;
  const civil = /^\d{4}-\d{2}-\d{2}$/;
  if (civil.test(event.start_at) && civil.test(event.end_at)) {
    const key = dateKey(date);
    return event.start_at <= key && key < event.end_at;
  }
  if (event.all_day) return false;
  const start = Date.parse(event.start_at), end = Date.parse(event.end_at);
  if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) return false;
  const midnight = localDateTime(date), tomorrow = localDateTime({...date, day: date.day + 1});
  return start < tomorrow.getTime() && end > midnight.getTime();
}
