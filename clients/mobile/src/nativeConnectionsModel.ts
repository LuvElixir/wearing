export type DeviceCalendarEvent = {
  id: string;
  title: string;
  startDate: Date | string;
  endDate: Date | string;
  allDay?: boolean;
  calendarId: string;
};

export type CalendarPreview = {
  key: string;
  title: string;
  calendar: string;
  start: number;
  end: number;
  allDay: boolean;
};

/** Recurrences share an event id, so retain each occurrence's start in its key. */
export function calendarPreviews(events: DeviceCalendarEvent[], names: Record<string, string>): CalendarPreview[] {
  const unique = new Map<string, CalendarPreview>();
  for (const event of events) {
    const start = new Date(event.startDate).getTime(), end = new Date(event.endDate).getTime();
    if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) continue;
    const key = `${event.calendarId}:${event.id}:${start}`;
    unique.set(key, {key, title: event.title.trim() || '未命名日程', calendar: names[event.calendarId] || '日历',
      start, end, allDay: !!event.allDay});
  }
  return [...unique.values()].sort((a, b) => a.start - b.start || a.title.localeCompare(b.title));
}

export function calendarEventTime(event: CalendarPreview): string {
  const start = new Date(event.start), end = new Date(event.end);
  if (event.allDay) {
    // EventKit's all-day end is exclusive; a two-day event must not appear as three days.
    const finalDay = new Date(event.end > event.start ? event.end - 1 : event.start);
    return `${dateLabel(start)}${sameDay(start, finalDay) ? '' : ` 至 ${dateLabel(finalDay)}`} · 全天`;
  }
  return `${dateLabel(start)} ${clockLabel(start)}–${sameDay(start, end) ? '' : `${dateLabel(end)} `}${clockLabel(end)}`;
}

function dateLabel(date: Date) {return `${date.getFullYear()}年${date.getMonth() + 1}月${date.getDate()}日`;}
function clockLabel(date: Date) {return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`;}
function sameDay(a: Date, b: Date) {return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();}

function calendarDraftTime(event: CalendarPreview): string {
  if (!event.allDay) return calendarEventTime(event);
  const end = new Date(event.end);
  return `${calendarEventTime(event)}（${dateLabel(end)} ${clockLabel(end)} 结束，不含结束时刻）`;
}

/** Only selected, previewed rows enter a draft. This helper never dispatches a message. */
export function selectedCalendarDraft(events: CalendarPreview[], selected: readonly string[]): string {
  const keys = new Set(selected);
  const chosen = events.filter(event => keys.has(event.key));
  if (!chosen.length) return '';
  return `以下是我从手机日历选出的安排（${Intl.DateTimeFormat().resolvedOptions().timeZone}）：\n` +
    chosen.map(event => `- ${calendarDraftTime(event)}：${event.title}（${event.calendar}）`).join('\n');
}

/** Match the bridge's UTF-16 string.length limit before any draft/navigation callback. */
export const NATIVE_DRAFT_LIMIT = 12000;
export function nativeDraftError(text: string): string | null {
  if (text.length > NATIVE_DRAFT_LIMIT) return '所选内容超过 12,000 字符，请减少勾选的日程后再带入。';
  return null;
}

export type LocationPreview = {latitude: number; longitude: number; accuracy: number | null; timestamp: number};

export function locationDraft(location: LocationPreview): string {
  if (![location.latitude, location.longitude, location.timestamp].every(Number.isFinite) ||
      Math.abs(location.latitude) > 90 || Math.abs(location.longitude) > 180) return '';
  const when = new Date(location.timestamp).toLocaleString('zh-CN', {hour12: false});
  const accuracy = location.accuracy !== null && Number.isFinite(location.accuracy)
    ? `，定位精度约 ${Math.round(location.accuracy)} 米` : '';
  return `这是我在 ${when} 获取的位置：纬度 ${location.latitude.toFixed(5)}，经度 ${location.longitude.toFixed(5)}${accuracy}。`;
}
