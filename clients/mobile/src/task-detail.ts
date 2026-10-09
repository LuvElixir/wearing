import {ApiError, type Connection, connectionEndpoint, connectionHeaders} from './core';
import {accountWorkAllowed} from './account-work';

const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const id = (v: unknown): v is string => typeof v === 'string' && /^[a-f0-9]{32}$/.test(v);
const text = (v: unknown, max = 1048576): v is string => typeof v === 'string' && v.length <= max;
const time = (v: unknown): v is string => typeof v === 'string' && Number.isFinite(Date.parse(v));
const bad = () => new ApiError('任务回执不完整，请重新读取。', 422);
const active = ['starting', 'running', 'waiting_for_approval', 'connection_lost', 'ambiguous'];
const labels: Record<string, string> = {draft:'尚未开始', starting:'正在开始', running:'正在推进', waiting_for_approval:'有一步等你确认', stopping:'正在确认停止', connection_lost:'连接中断，进展待确认', ambiguous:'原运行状态待确认', failed:'执行未完成', stopped:'已停止', completed_unverified:'结果已返回', verified:'已核对', closed_by_user:'已结案'};
const eventLabels: Record<string, string> = {created:'任务已记下', confirmation_recheck:'已记下重新核对请求', message_queued:'消息已排队', message_cancelled:'消息已撤回', starting:'准备开始', running:'开始执行', waiting_for_approval:'等待确认', stopping:'已请求停止', stopped:'已停止', stop_unconfirmed:'停止尚未确认', connection_lost:'连接中断', ambiguous:'运行状态待确认', completed_unverified:'结果已返回', verified:'已核对结果', closed_by_user:'已结案', failed:'执行未完成'};
export function taskDetail(value: unknown, expected: string, identity: string) {
  if (!object(value) || !id(expected) || value.id !== expected || value.identity_id !== identity || !text(value.title, 1000) || !text(value.prompt) || !text(value.output) || !text(value.status, 100) || !(value.run_id === null || text(value.run_id, 200)) || !time(value.created_at) || !time(value.updated_at)) throw bad();
  // Older servers may not return the queue receipt. Absence never grants cancel.
  if (value.queued !== undefined && typeof value.queued !== 'boolean') throw bad();
  if ([value.can_cancel, value.can_retry].some(flag => flag !== undefined && typeof flag !== 'boolean') || value.blocked_reason != null && !text(value.blocked_reason, 400)) throw bad();
  const queued = value.status === 'draft' && value.queued === true;
  const fresh = value.status === 'draft' && value.run_id === null;
  const canCancel = fresh && (value.can_cancel === undefined ? queued : value.can_cancel === true), canRetry = fresh && !queued && value.can_retry === true;
  const recovery = value.message_kind === 'confirmation_recovery';
  const failureReason = value.status === 'failed' && value.failure_code === 'execution_limit' ? '这次达到了执行上限，已经返回的结果和过程都已保留。这件事还没完成，可以回到对话继续交代。' : null;
  let receipt: {task_id: string; version: string} | null = null;
  if (value.activity_receipt != null) {
    const row = value.activity_receipt;
    if (!object(row) || row.task_id !== expected || typeof row.version !== 'string' || !/^[a-f0-9]{64}$/.test(row.version)) throw bad();
    receipt = {task_id: expected, version: row.version};
  }
  if (value.events !== undefined && !Array.isArray(value.events)) throw bad();
  const rawEvents = (value.events || []) as unknown[];
  const events = rawEvents.filter(object).filter(row => typeof row.kind === 'string' && eventLabels[row.kind] && time(row.created_at)).slice(-100).map(row => ({label: eventLabels[row.kind as string], at: row.created_at as string}));
  if (value.artifacts !== undefined && !Array.isArray(value.artifacts)) throw bad();
  const artifacts = ((value.artifacts || []) as unknown[]).slice(-100).map(row => {
    if (!object(row) || typeof row.id !== 'string' || !/^art_[a-f0-9]{1,64}$/.test(row.id) || row.task_id !== expected || !text(row.title, 1000)) throw bad();
    return {id: row.id, title: row.title};
  });
  return {id: expected, identity, receipt, title: value.title, prompt: value.prompt, output: value.output, status: value.status, runId: value.run_id as string | null, createdAt: value.created_at, updatedAt: value.updated_at, queued, canCancel, canRetry, recovery, failureReason, blockedReason: fresh && typeof value.blocked_reason === 'string' ? value.blocked_reason : null, label: queued ? '已排队，尚未开始' : value.status === 'stopped' && value.queue_state === 'cancelled' ? '已撤回' : labels[value.status] || '状态待确认', canStop: active.includes(value.status) && !!value.run_id, events, eventsTruncated: rawEvents.length > 100, artifacts, artifactsTruncated: Array.isArray(value.artifacts) && value.artifacts.length > 100};
}
export type TaskDetail = ReturnType<typeof taskDetail>;
export type TaskControl = 'stop' | 'cancel-message' | 'start';
/** Read back after controls. Never automatically repeat an uncertain stop/cancel. */
export class TaskDetailApi {
  readonly connection: Connection;
  private enabled = true;
  private generation = 0;
  private requests = new Set<AbortController>();
  constructor(connection: Connection, private fetcher: typeof fetch = fetch, private current: () => boolean = () => true) {this.connection = {...connection, ...(connection.session ? {session: {...connection.session}} : {}), ...(connection.development ? {development: {...connection.development}} : {})};}
  setCurrent(value: () => boolean) {this.current = value;}
  activate() {this.generation++; this.enabled = true;}
  close() {this.enabled = false; this.generation++; for (const request of this.requests) request.abort();}
  private check() {if (!this.enabled || !this.current() || !accountWorkAllowed(this.connection)) throw new ApiError('账户或页面已切换，请重新打开。', 409);}
  private async request(path: string, token?: string, body: unknown = {}) {
    this.check(); const generation = this.generation, check = () => {this.check(); if (generation !== this.generation) throw new ApiError('页面已重新打开，请重新读取。',409);}; const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 25000); this.requests.add(controller);
    try {
      const response = await this.fetcher(new URL(path, connectionEndpoint(this.connection)), {method: token === undefined ? 'GET' : 'POST', redirect: 'error', signal: controller.signal, headers: {...connectionHeaders(this.connection), 'X-Wearing-Identity': this.connection.identity, ...(token === undefined ? {} : {'X-Wearing-Token': token, 'Content-Type': 'application/json'})}, ...(token === undefined ? {} : {body: JSON.stringify(body)})});
      check();
      if (!response.ok) throw new ApiError(response.status === 404 ? '当前账户或身份没有这项任务。' : response.status === 401 ? '登录已到期，请重新连接。' : response.status === 409 ? '任务状态已有变化，请重新查看。' : '暂时无法读取或处理任务，请重新查看。', response.status);
      if (!response.headers.get('Content-Type')?.includes('application/json') || Number(response.headers.get('Content-Length') || 0) > 2097152) throw bad();
      const raw = await response.text(); check(); if (raw.length > 2097152) throw bad(); return JSON.parse(raw) as unknown;
    } catch (cause) {if (cause instanceof ApiError) throw cause; throw new ApiError(token === undefined ? '连接中断，请重新读取任务。' : '请求结果尚未确认，请先重新读取原任务；不会自动重复操作。', 0);}
    finally {clearTimeout(timer); this.requests.delete(controller);}
  }
  private async token() {const value = await this.request('/api/bootstrap'); if (!object(value) || typeof value.token !== 'string' || !value.token || !Array.isArray(value.identities) || !value.identities.some(row => object(row) && row.id === this.connection.identity)) throw bad(); return value.token;}
  async read(taskId: string) {if (!id(taskId)) throw bad(); return taskDetail(await this.request('/api/tasks/' + taskId), taskId, this.connection.identity);}
  async refresh(taskId: string) {if (!id(taskId)) throw bad(); const token = await this.token(); await this.request('/api/tasks/' + taskId + '/refresh', token); return this.read(taskId);}
  async seen(rendered: TaskDetail) {
    if (!rendered.receipt || rendered.identity !== this.connection.identity) return false;
    const token = await this.token();
    await this.request('/api/activity/seen', token, {items: [rendered.receipt]});
    return true;
  }
  async control(previous: TaskDetail, action: TaskControl) {
    if (action !== 'stop' && action !== 'cancel-message' && action !== 'start') throw bad();
    const current = await this.read(previous.id);
    if (current.identity !== previous.identity || current.runId !== previous.runId || (action === 'stop' ? !current.canStop : action === 'start' ? !current.canRetry : !current.canCancel)) throw new ApiError('这次运行已有变化，请查看最新状态后再操作。', 409);
    const token = await this.token();
    const receipt = await this.request('/api/tasks/' + current.id + '/' + action, token);
    taskDetail(receipt, current.id, this.connection.identity);
    return this.read(current.id);
  }
}
