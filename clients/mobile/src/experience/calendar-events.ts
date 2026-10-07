import type {CalendarEvent} from '../calendar';

type PreviewEvent = CalendarEvent & {id: 'meeting' | 'walk' | 'weekend'};
const recorded: PreviewEvent[] = [
  {id: 'meeting', start_at: '2026-10-06', end_at: '2026-10-07'},
  {id: 'walk', start_at: '2026-10-06', end_at: '2026-10-07'},
];

/** These civil dates belong to the dated preview story, rather than repeating each month. */
export function previewCalendarEvents(weekendAccepted: boolean): PreviewEvent[] {
  return weekendAccepted
    ? [...recorded, {id: 'weekend', start_at: '2026-10-10', end_at: '2026-10-12'}]
    : recorded;
}
