import {ApiError} from './core';
import type {OngoingDetail} from './ongoing-management';

export type GoalDraft = {objective: string; boundaries: string; success_criteria: string; max_steps: number};
export type GoalFormValues = {title: string; brief: string; boundaries: string; success: string; steps: string};
export type ScheduleDraft = {
  title: string; instruction: string; kind: 'once' | 'cron' | 'life_change'; timezone: string;
  at: string | null; cron: string | null; grace_minutes: number;
  changes: {record_kinds: string[]; debounce_seconds: number; cooldown_minutes: number; max_runs_per_day: number} | null;
  goal_id: string | null;
};
export type ScheduleRepeat = 'once' | 'daily' | 'weekly' | 'existing';
export type ScheduleFormValues = {title: string; instruction: string; repeat: ScheduleRepeat; timezone: string; date: string; time: string; weekday: number};
/** A recommendation opens a draft. It never creates or enables an arrangement by itself. */
export type OngoingCreateRequest = {id: string; title?: string; instruction?: string; repeat?: 'once' | 'daily' | 'weekly'; timezone?: string; time?: string; weekday?: number};

function invalid(message: string): never {throw new ApiError(message, 422);}
export function validTimezone(value: string): boolean {
  if (!value || value.length > 100) return false;
  try {new Intl.DateTimeFormat('en', {timeZone: value}); return true;} catch {return false;}
}
export function wallClock(value: Date, timezone: string): {date: string; time: string} {
  const parts = new Intl.DateTimeFormat('en-CA', {timeZone: timezone, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23'}).formatToParts(value);
  const field = (key: string) => parts.find(part => part.type === key)!.value;
  return {date: `${field('year')}-${field('month')}-${field('day')}`, time: `${field('hour')}:${field('minute')}`};
}
/** Resolve a local wall clock, rejecting nonexistent or ambiguous DST times instead of moving them. */
export function wallTimeToInstant(date: string, time: string, timezone: string): string {
  if (!validTimezone(timezone)) invalid('请填写有效时区，例如 Asia/Shanghai。');
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date) || !/^([01]\d|2[0-3]):[0-5]\d$/.test(time)) invalid('请选择完整日期和 24 小时制时间。');
  const target = Date.parse(`${date}T${time}:00Z`);
  if (!Number.isFinite(target) || new Date(target).toISOString().slice(0, 10) !== date) invalid('这个日期不存在，请重新选择。');
  // Nearby UTC instants reveal both offsets on a DST transition; fractional-hour zones work too.
  const offsets = new Set<number>();
  for (const delta of [-36, -12, 0, 12, 36]) {
    const probe = target + delta * 3600000, wall = wallClock(new Date(probe), timezone);
    offsets.add(Date.parse(`${wall.date}T${wall.time}:00Z`) - probe);
  }
  const matches = [...offsets].map(offset => target - offset).filter(candidate => {
    const wall = wallClock(new Date(candidate), timezone);
    return wall.date === date && wall.time === time;
  });
  if (!matches.length) invalid('这一天的所选时间因夏令时不存在，请换一个时间。');
  if (matches.length > 1) invalid('这一天的所选时间会因夏令时重复，请避开这一小时。');
  return new Date(matches[0]).toISOString();
}
export function goalDraft(values: GoalFormValues): GoalDraft {
  const title = values.title.trim(), brief = values.brief.trim(), boundaries = values.boundaries.trim(), success = values.success.trim();
  if (title.length < 2 || title.length > 120) invalid('请用 2–120 个字给目标起个名字。');
  const objective = title + (brief ? '\n\n' + brief : '');
  if (objective.length > 2000) invalid('目标名称和具体要求合计不能超过 2000 字。');
  if (boundaries.length < 2 || boundaries.length > 2000) invalid('请写清允许做什么，以及哪些事情要先问你（2–2000 字）。');
  if (success.length < 2 || success.length > 2000) invalid('请写清做到什么算完成（2–2000 字）。');
  if (!/^\d+$/.test(values.steps.trim())) invalid('请明确填写愿意授权的推进轮次。');
  const steps = Number(values.steps.trim());
  if (!Number.isSafeInteger(steps) || steps < 1 || steps > 1000) invalid('推进轮次须为 1–1000 之间的整数。');
  return {objective, boundaries, success_criteria: success, max_steps: steps};
}
export function scheduleDraft(values: ScheduleFormValues, original?: ScheduleDraft, now = Date.now()): ScheduleDraft {
  const title = values.title.trim(), instruction = values.instruction.trim(), timezone = values.timezone.trim();
  if (!title || title.length > 100) invalid('请填写 1–100 字的安排名称。');
  if (instruction.length < 2 || instruction.length > 6000) invalid('请写清届时要做的事（2–6000 字）。');
  if (!validTimezone(timezone)) invalid('请填写有效时区，例如 Asia/Shanghai。');
  if (values.repeat === 'existing') {
    if (!original) invalid('请先选择重复方式。');
    return {...original, title, instruction, timezone};
  }
  if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(values.time)) invalid('请选择 24 小时制时间，例如 08:30。');
  const [hour, minute] = values.time.split(':').map(Number);
  const spec: ScheduleDraft = {title, instruction, timezone, kind: values.repeat === 'once' ? 'once' : 'cron',
    at: null, cron: null, grace_minutes: original?.grace_minutes ?? 60, changes: null, goal_id: null};
  if (values.repeat === 'once') {
    spec.at = wallTimeToInstant(values.date, values.time, timezone);
    if (Date.parse(spec.at) <= now) invalid('执行时间已经过去，请选择未来的时间。');
  } else if (values.repeat === 'daily') spec.cron = `${minute} ${hour} * * *`;
  else if (values.repeat === 'weekly' && Number.isInteger(values.weekday) && values.weekday >= 0 && values.weekday <= 6) spec.cron = `${minute} ${hour} * * ${values.weekday}`;
  else invalid('请选择每周的具体星期。');
  return spec;
}
export function initialScheduleForm(request?: OngoingCreateRequest, item?: {title: string; schedule?: Pick<NonNullable<OngoingDetail['schedule']>, 'timezone' | 'at' | 'kind' | 'instruction' | 'cron'>}, now = Date.now()): ScheduleFormValues {
  const spec = item?.schedule, timezone = spec?.timezone || request?.timezone || 'Asia/Shanghai';
  const wall = wallClock(new Date(spec?.at || now + 3600000), timezone);
  const values: ScheduleFormValues = {title: item?.title || request?.title || '', instruction: spec?.instruction || request?.instruction || '',
    repeat: spec ? 'existing' : request?.repeat || 'once', timezone, date: wall.date, time: request?.time || wall.time, weekday: request?.weekday ?? 1};
  if (spec?.kind === 'once') values.repeat = 'once';
  if (spec?.kind === 'cron') {
    const match = /^(\d|[1-5]\d)\s+(\d|1\d|2[0-3])\s+\*\s+\*\s+(\*|[0-7])$/.exec(spec.cron!.trim());
    if (match) {values.repeat = match[3] === '*' ? 'daily' : 'weekly'; values.time = `${match[2].padStart(2, '0')}:${match[1].padStart(2, '0')}`; values.weekday = match[3] === '*' ? 1 : Number(match[3]) % 7;}
  }
  return values;
}
