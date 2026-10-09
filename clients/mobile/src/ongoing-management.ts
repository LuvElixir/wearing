import {ApiError, Connection, connectionEndpoint, connectionHeaders} from './core';
import {GoalDraft, ScheduleDraft, validTimezone} from './ongoing-management-forms';

export type OngoingKind = 'goals' | 'schedules';
export type OngoingAction = 'pause' | 'resume' | 'cancel' | 'note' | 'complete';
export type OngoingRun = {id: string; taskId: string | null; status: string; at: string; summary: string};
export type OngoingDetail = {
  kind: OngoingKind; id: string; identity: string; revision: number; title: string; status: string;
  reason: string; updatedAt: string; next: string; historyLoaded: boolean; runs: OngoingRun[];
  goal?: {boundaries: string; success: string; used: number; limit: number; notes: {id: number; text: string; at: string}[]};
  schedule?: {instruction: string; kind: 'once' | 'cron' | 'life_change'; timezone: string; at: string | null; cron: string | null;
    nextRun: string | null; changes: {record_kinds: string[]; max_runs_per_day: number} | null; draft: ScheduleDraft};
};
export type OngoingControl = {action: OngoingAction; note?: string; addSteps?: number};

const isId = (value: unknown): value is string => typeof value === 'string' && /^[a-zA-Z0-9_-]{1,64}$/.test(value);
const isDate = (value: unknown): value is string => typeof value === 'string' && Number.isFinite(Date.parse(value));
const text = (value: unknown): value is string => typeof value === 'string';
const count = (value: unknown): value is number => Number.isSafeInteger(value) && (value as number) >= 0;
const dictionary = (value: unknown): value is Record<string, any> => !!value && typeof value === 'object' && !Array.isArray(value);
const failure = () => new ApiError('没有读到当前身份的完整安排，请刷新后再操作。', 422);
const goalStatuses = new Set(['active', 'waiting', 'paused', 'needs_user', 'needs_review', 'limited', 'completed', 'cancelled']);
const scheduleStatuses = new Set(['active', 'paused', 'finished', 'cancelled']);
const terminal = new Set(['completed', 'cancelled', 'finished']);
const running = new Set(['draft', 'starting', 'running', 'waiting_for_approval', 'stopping', 'ambiguous', 'connection_lost']);

export const ongoingStatus = (status: string, kind?: OngoingKind) => ({active: kind === 'schedules' ? '已开启' : '正在推进', waiting: '等待时机', paused: '已暂停', needs_user: '需要你补充',
  needs_review: '结果待确认', limited: '已到约定轮次', completed: '已完成', cancelled: '已结束', finished: '已执行',
  succeeded: '已完成', done: '已完成', failed: '未完成', stopped: '已停止', stopping: '正在停止', pending: '等待执行',
  draft: '等待执行', starting: '正在开始', running: '正在执行', waiting_for_approval: '等待确认', skipped: '已跳过',
  missed: '已错过', ambiguous: '需要核对状态', connection_lost: '连接中断', closed_by_user: '已结束'}[status] || '状态待确认');

/** Reads and mutations both check the exact identity and object, including mutation receipts. */
export function parseOngoing(value: unknown, kind: OngoingKind, identity: string, id?: string, details = false): OngoingDetail {
  if (!dictionary(value) || !isId(value.id) || (id && value.id !== id) || value.identity_id !== identity ||
    !Number.isSafeInteger(value.revision) || value.revision < 1 || !text(value.status) || !text(value.reason) || !isDate(value.updated_at)) throw failure();
  const result: OngoingDetail = {kind, id: value.id, identity, revision: value.revision, title: '', status: value.status,
    reason: value.reason, updatedAt: value.updated_at, next: '', historyLoaded: details, runs: []};
  if (kind === 'goals') {
    if (!goalStatuses.has(value.status) || !text(value.objective) || !value.objective.trim() || !text(value.boundaries) || !text(value.success_criteria) ||
      !count(value.used_steps) || !count(value.max_steps) || value.max_steps < 1 || value.used_steps > value.max_steps || !text(value.next_step)) throw failure();
    result.title = value.objective; result.next = value.next_step;
    result.goal = {boundaries: value.boundaries, success: value.success_criteria, used: value.used_steps, limit: value.max_steps, notes: []};
    if (details) {
      if (!Array.isArray(value.notes) || !Array.isArray(value.steps)) throw failure();
      result.goal.notes = value.notes.map((note: unknown) => {
        if (!dictionary(note) || !count(note.id) || note.id < 1 || !text(note.content) || !isDate(note.created_at)) throw failure();
        return {id: note.id, text: note.content, at: note.created_at};
      });
      result.runs = value.steps.map((step: unknown) => {
        if (!dictionary(step) || !isId(step.task_id) || !text(step.task_status) || !isDate(step.created_at) ||
          (step.report !== null && step.report !== undefined && (!dictionary(step.report) || !text(step.report.summary)))) throw failure();
        return {id: step.task_id, taskId: step.task_id, status: step.task_status, at: step.created_at,
          summary: step.report?.summary || (text(step.error) ? step.error : '') || (text(step.output) ? step.output : '')};
      }).reverse();
    }
  } else {
    const spec = value.schedule;
    if (!scheduleStatuses.has(value.status) || !dictionary(spec) || !text(spec.title) || !spec.title.trim() || !text(spec.instruction) ||
      !['once', 'cron', 'life_change'].includes(spec.kind) || !text(spec.timezone) ||
      (value.next_run !== null && !isDate(value.next_run)) || (spec.kind === 'once' && !isDate(spec.at)) ||
      (spec.kind === 'cron' && (!text(spec.cron) || !spec.cron.trim()))) throw failure();
    try {new Intl.DateTimeFormat('zh-CN', {timeZone: spec.timezone});} catch {throw failure();}
    if (spec.kind === 'life_change' && (!dictionary(spec.changes) || !Array.isArray(spec.changes.record_kinds) ||
      !spec.changes.record_kinds.length || spec.changes.record_kinds.some((entry: unknown) => !['note', 'task', 'event'].includes(String(entry))) ||
      !count(spec.changes.max_runs_per_day) || spec.changes.max_runs_per_day < 1)) throw failure();
    result.title = spec.title;
    const grace = spec.grace_minutes ?? 60, debounce = spec.changes?.debounce_seconds ?? 60, cooldown = spec.changes?.cooldown_minutes ?? 15;
    if (!Number.isInteger(grace) || grace < 1 || grace > 1440 ||
      (spec.goal_id !== null && spec.goal_id !== undefined && (!isId(spec.goal_id) || spec.kind !== 'life_change')) ||
      (spec.kind === 'life_change' && (!Number.isInteger(debounce) || debounce < 15 || debounce > 600 || !Number.isInteger(cooldown) || cooldown < 1 || cooldown > 1440 || spec.changes.max_runs_per_day > 48))) throw failure();
    const draft: ScheduleDraft = {title: spec.title, instruction: spec.instruction, kind: spec.kind, timezone: spec.timezone,
      at: spec.at || null, cron: spec.cron || null, grace_minutes: grace, goal_id: spec.goal_id || null,
      changes: spec.kind === 'life_change' ? {record_kinds: [...spec.changes.record_kinds], max_runs_per_day: spec.changes.max_runs_per_day, debounce_seconds: debounce, cooldown_minutes: cooldown} : null};
    result.schedule = {instruction: spec.instruction, kind: spec.kind, timezone: spec.timezone, at: spec.at || null, cron: spec.cron || null,
      nextRun: value.next_run, changes: spec.kind === 'life_change' ? spec.changes : null, draft};
    if (details) {
      if (!Array.isArray(value.occurrences)) throw failure();
      result.runs = value.occurrences.map((run: unknown) => {
        if (!dictionary(run) || !count(run.id) || run.id < 1 || (run.task_id !== null && !isId(run.task_id)) || !text(run.status) || !isDate(run.due_at)) throw failure();
        return {id: String(run.id), taskId: run.task_id, status: text(run.task_status) ? run.task_status : run.status, at: run.due_at,
          summary: (text(run.reason) ? run.reason : '') || (text(run.error) ? run.error : '') || (text(run.output) ? run.output : '')};
      });
    }
  }
  if (new Set(result.runs.map(run => run.id)).size !== result.runs.length) throw failure();
  return result;
}

export function ongoingActions(item: OngoingDetail): OngoingAction[] {
  if (terminal.has(item.status)) return [];
  const actions: OngoingAction[] = [];
  if (item.status !== 'paused' && item.status !== 'limited' && item.status !== 'needs_review') actions.push('pause');
  if (item.status !== 'active' && !item.runs.some(run => ['ambiguous', 'connection_lost', 'stopping'].includes(run.status))) actions.push('resume');
  if (item.goal) {
    actions.push('note');
    if (item.historyLoaded && !item.runs.some(run => running.has(run.status))) actions.push('complete');
  }
  actions.push('cancel');
  return actions;
}

export function ongoingControlBody(item: OngoingDetail, request: OngoingControl): Record<string, string | number> {
  if (!ongoingActions(item).includes(request.action)) throw new ApiError('当前状态不能执行这个操作，请刷新后再查看。', 409);
  const body: Record<string, string | number> = {revision: item.revision, action: request.action};
  const note = (request.note || '').trim(), addSteps = request.addSteps ?? 0;
  if (item.kind === 'schedules') {
    if (note || addSteps) throw new ApiError('定时安排不能增加目标轮次或补充目标记录。', 422);
    return body;
  }
  if ((request.action === 'note' || request.action === 'complete') && (note.length < 3 || note.length > 2000)) throw new ApiError('请写下至少三个字的具体内容。', 422);
  if (note.length > 2000 || !Number.isSafeInteger(addSteps) || addSteps < 0 || (addSteps && request.action !== 'resume') ||
    item.goal!.limit + addSteps > 1000) throw new ApiError('请检查补充内容和增加的轮次，单个目标最多 1000 轮。', 422);
  if (request.action === 'resume' && item.goal!.used >= item.goal!.limit + addSteps) throw new ApiError('已经到达约定轮次，请填写愿意增加的轮次后继续。', 422);
  body.note = note; body.add_steps = addSteps;
  return body;
}

export function ongoingTime(value: string | null, timezone?: string): string {
  if (!value || !isDate(value)) return '尚未安排';
  return new Date(value).toLocaleString('zh-CN', {month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false, ...(timezone ? {timeZone: timezone} : {})});
}

export function scheduleRule(item: OngoingDetail): string {
  const spec = item.schedule;
  if (!spec) return '';
  if (spec.kind === 'once') return `单次 · ${ongoingTime(spec.at, spec.timezone)}`;
  if (spec.kind === 'life_change') return `${spec.changes!.record_kinds.map(kind => ({note: '笔记', task: '待办', event: '日程'}[kind])).join('、')}有变化时 · 每天最多 ${spec.changes!.max_runs_per_day} 次`;
  const parts = spec.cron!.trim().split(/\s+/);
  if (parts.length === 5 && /^\d+$/.test(parts[0]) && /^\d+$/.test(parts[1]) && parts[2] === '*' && parts[3] === '*') {
    const time = `${parts[1].padStart(2, '0')}:${parts[0].padStart(2, '0')}`;
    if (parts[4] === '*') return `每天 ${time}`;
    if (parts[4] === '1-5') return `工作日 ${time}`;
    if (/^[0-7]$/.test(parts[4])) return `每周${['日', '一', '二', '三', '四', '五', '六', '日'][Number(parts[4])]} ${time}`;
  }
  return '按已保存的重复规则执行';
}

/** No mutating request is retried after timeout. Revision checks make an explicit retry safe. */
export class OngoingManagementApi {
  private token = '';
  private readonly pending = new Set<string>();
  private readonly creations = new Map<string, {fingerprint: string; receipt?: OngoingDetail}>();
  private readonly connection: Connection;
  constructor(connection: Connection, private readonly fetcher: typeof fetch = fetch) {
    this.connection = {...connection, ...(connection.development ? {development: {...connection.development}} : {})};
  }
  private async request(path: string, method = 'GET', body?: unknown, refresh = true): Promise<unknown> {
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 20000);
    try {
      const response = await this.fetcher(new URL(path, connectionEndpoint(this.connection)).toString(), {method, signal: controller.signal, redirect: 'error',
        headers: {...connectionHeaders(this.connection), 'X-Wearing-Identity': this.connection.identity, ...(method !== 'GET' ? {'Content-Type': 'application/json', 'X-Wearing-Token': this.token} : {})},
        ...(body === undefined ? {} : {body: JSON.stringify(body)})});
      if (response.status === 403 && method !== 'GET' && refresh) {await this.bootstrap(); return await this.request(path, method, body, false);}
      const data: unknown = await response.json().catch(() => {throw new ApiError(method === 'GET' ? '暂时没有读到完整数据，请刷新。' : '保存回执不完整，请保留草稿并重新取回回执。', method === 'GET' ? 422 : 0);});
      if (!response.ok) throw new ApiError(dictionary(data) && text(data.detail) ? data.detail : '这次没有完成，请刷新后重试。', response.status);
      return data;
    } catch (error) {
      if (error instanceof ApiError) throw error;
      throw new ApiError(method === 'GET' ? '暂时连不上 Pajio，请检查连接后刷新。' : '还未收到操作回执，请先刷新确认状态，再决定是否重试。');
    } finally {clearTimeout(timer);}
  }
  private async bootstrap() {
    const data = await this.request('/api/bootstrap');
    if (!dictionary(data) || data.version !== '0.2.0' || !['local', 'cloud'].includes(data.deployment) || !text(data.token) || !data.token ||
      !Array.isArray(data.identities) || !data.identities.some(entry => dictionary(entry) && entry.id === this.connection.identity)) throw failure();
    this.token = data.token;
  }
  async list(kind: OngoingKind): Promise<OngoingDetail[]> {
    const data = await this.request('/api/' + kind);
    const values = kind === 'goals' ? data : dictionary(data) ? data.items : null;
    if (!Array.isArray(values)) throw failure();
    const items = values.map(value => parseOngoing(value, kind, this.connection.identity));
    if (new Set(items.map(item => item.id)).size !== items.length) throw failure();
    return items;
  }
  async detail(kind: OngoingKind, id: string): Promise<OngoingDetail> {
    if (!isId(id)) throw failure();
    return parseOngoing(await this.request(`/api/${kind}/${encodeURIComponent(id)}`), kind, this.connection.identity, id, true);
  }
  async createGoal(draft: GoalDraft, requestKey: string): Promise<OngoingDetail> {
    if (typeof draft.objective !== 'string' || draft.objective.trim().length < 2 || draft.objective.length > 2000 ||
      typeof draft.boundaries !== 'string' || draft.boundaries.trim().length < 2 || draft.boundaries.length > 2000 ||
      typeof draft.success_criteria !== 'string' || draft.success_criteria.trim().length < 2 || draft.success_criteria.length > 2000 ||
      !Number.isInteger(draft.max_steps) || draft.max_steps < 1 || draft.max_steps > 1000) throw new ApiError('请检查目标约定和推进轮次。', 422);
    return this.create('goals', {objective: draft.objective, boundaries: draft.boundaries, success_criteria: draft.success_criteria, max_steps: draft.max_steps, request_key: requestKey}, requestKey);
  }
  async createSchedule(draft: ScheduleDraft, requestKey: string): Promise<OngoingDetail> {
    this.checkSchedule(draft);
    return this.create('schedules', {schedule: draft, request_key: requestKey}, requestKey);
  }
  private checkSchedule(draft: ScheduleDraft) {
    if (!draft || typeof draft.title !== 'string' || !draft.title.trim() || draft.title.length > 100 || typeof draft.instruction !== 'string' ||
      draft.instruction.trim().length < 2 || draft.instruction.length > 6000 || !validTimezone(draft.timezone) ||
      !['once', 'cron', 'life_change'].includes(draft.kind)) throw new ApiError('请检查安排名称、要做的事和执行时间。', 422);
  }
  private async create(kind: OngoingKind, body: unknown, requestKey: string): Promise<OngoingDetail> {
    if (!/^[A-Za-z0-9_-]{16,120}$/.test(requestKey)) throw new ApiError('这份草稿的标识不完整，请重新打开新建。', 422);
    const key = `${kind}/create/${requestKey}`, fingerprint = JSON.stringify(body), previous = this.creations.get(key);
    if (previous && previous.fingerprint !== fingerprint) throw new ApiError('这份草稿已经提交，请先取回原来的回执。', 409);
    if (previous?.receipt) return previous.receipt;
    if (this.pending.has(key)) throw new ApiError('正在保存这次操作，请稍候。', 409);
    this.pending.add(key); this.creations.set(key, {fingerprint});
    try {
      if (!this.token) await this.bootstrap();
      const data = await this.request('/api/' + kind, 'POST', body);
      let receipt: OngoingDetail;
      try {receipt = parseOngoing(data, kind, this.connection.identity, undefined, kind === 'schedules');}
      catch {throw new ApiError('保存回执不完整，请保留草稿并重新取回回执。');}
      this.creations.set(key, {fingerprint, receipt});
      return receipt;
    } finally {this.pending.delete(key);}
  }
  async editSchedule(item: OngoingDetail, draft: ScheduleDraft): Promise<OngoingDetail> {
    if (item.kind !== 'schedules' || !item.schedule || item.identity !== this.connection.identity || !isId(item.id) ||
      !Number.isSafeInteger(item.revision) || item.revision < 1) throw failure();
    if (item.status === 'cancelled') throw new ApiError('已经结束的安排不能再修改。', 409);
    this.checkSchedule(draft);
    const key = `schedules/${item.id}`;
    if (this.pending.has(key)) throw new ApiError('正在保存这次操作，请稍候。', 409);
    this.pending.add(key);
    try {
      if (!this.token) await this.bootstrap();
      const data = await this.request('/api/' + key, 'PATCH', {revision: item.revision, action: 'edit', schedule: draft});
      const receipt = parseOngoing(data, 'schedules', this.connection.identity, item.id, true);
      if (receipt.revision <= item.revision) throw failure();
      return receipt;
    } finally {this.pending.delete(key);}
  }
  async control(item: OngoingDetail, request: OngoingControl): Promise<OngoingDetail> {
    if (item.identity !== this.connection.identity || !isId(item.id) || !Number.isSafeInteger(item.revision) || item.revision < 1) throw failure();
    const key = `${item.kind}/${item.id}`;
    if (this.pending.has(key)) throw new ApiError('正在保存这次操作，请稍候。', 409);
    const body = ongoingControlBody(item, request);
    this.pending.add(key);
    try {
      if (!this.token) await this.bootstrap();
      const data = await this.request(`/api/${key}${item.kind === 'goals' ? '/control' : ''}`, item.kind === 'goals' ? 'POST' : 'PATCH', body);
      const receipt = parseOngoing(data, item.kind, this.connection.identity, item.id, item.kind === 'schedules');
      if (receipt.revision <= item.revision) throw failure();
      return receipt;
    } finally {this.pending.delete(key);}
  }
}
