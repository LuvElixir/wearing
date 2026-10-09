import {ApiError, type Connection, connectionEndpoint, connectionHeaders} from './core';

export type ResultChoice = {id: string; label: string; instruction: string};
export type ChoiceRequest = {request_key: string; choice_id: string; artifact_revision: number; selection_revision: number};
export type ChoiceReceipt = {artifact_id: string; revision: number; request_key: string; choice_id: string; task_id: string;
  source_task_id: string; created_at: string; task_status: string; queue_state: string};
export type ChoiceState = {artifact_id: string; artifact_revision: number; revision: number; newer_id: string | null; choices: ResultChoice[]; selection: ChoiceReceipt | null};
const obj = (value: unknown): value is Record<string, any> => !!value && typeof value === 'object' && !Array.isArray(value);
const id = (value: unknown) => typeof value === 'string' && /^[A-Za-z0-9_-]{1,64}$/.test(value);
const integer = (value: unknown, minimum: number) => Number.isSafeInteger(value) && (value as number) >= minimum;
const states = new Set(['draft', 'starting', 'running', 'waiting_for_approval', 'stopping', 'connection_lost', 'ambiguous', 'stopped', 'failed', 'completed_unverified', 'verified']);
const invalid = (mutation = false) => new ApiError('暂时没有读到完整的选择回执，请重新读取，避免重复提交。', mutation ? 0 : 422);
export const choicePendingKey = (scope: string, artifact: string) => `artifact-choice:${scope}:${artifact}`;
export function validChoiceRequest(value: unknown): value is ChoiceRequest {
  return obj(value) && typeof value.request_key === 'string' && /^[A-Za-z0-9_-]{16,100}$/.test(value.request_key) &&
    typeof value.choice_id === 'string' && /^[A-Za-z0-9_-]{1,40}$/.test(value.choice_id) && integer(value.artifact_revision, 1) && integer(value.selection_revision, 0);
}
export function parseChoiceReceipt(value: unknown, artifact: string, sourceTask: string): ChoiceReceipt {
  if (!obj(value) || value.artifact_id !== artifact || value.source_task_id !== sourceTask || !id(value.task_id) || value.task_id === sourceTask ||
    !integer(value.revision, 1) || !validChoiceRequest({...value, artifact_revision: 1, selection_revision: 0}) ||
    typeof value.created_at !== 'string' || !Number.isFinite(Date.parse(value.created_at)) || !states.has(value.task_status) ||
    !['queued', 'blocked', 'dispatched', 'cancelled'].includes(value.queue_state)) throw invalid();
  return value as ChoiceReceipt;
}
export function parseChoiceState(value: unknown, artifact: string, revision: number, sourceTask: string): ChoiceState {
  if (!obj(value) || value.artifact_id !== artifact || value.artifact_revision !== revision || !integer(value.revision, 0) ||
    !(value.newer_id === null || (id(value.newer_id) && value.newer_id !== artifact)) || !Array.isArray(value.choices) || value.choices.length > 8 ||
    !value.choices.every(c => obj(c) && typeof c.id === 'string' && /^[A-Za-z0-9_-]{1,40}$/.test(c.id) &&
      typeof c.label === 'string' && c.label.trim().length > 0 && c.label.length <= 80 &&
      typeof c.instruction === 'string' && c.instruction.trim().length > 0 && c.instruction.length <= 1000) ||
    new Set(value.choices.map(c => c.id)).size !== value.choices.length) throw invalid();
  if (value.selection !== null) {
    const receipt = parseChoiceReceipt(value.selection, artifact, sourceTask);
    if (receipt.revision !== value.revision || !value.choices.some(c => c.id === receipt.choice_id)) throw invalid();
  } else if (value.revision !== 0) throw invalid();
  return value as ChoiceState;
}
export function choiceTaskPending(receipt: ChoiceReceipt | null) {
  return !!receipt && !['stopped', 'failed', 'completed_unverified', 'verified'].includes(receipt.task_status);
}
export class ArtifactChoiceApi {
  private token = '';
  private readonly connection: Connection;
  constructor(connection: Connection, private readonly artifact: string, private readonly revision: number, private readonly sourceTask: string,
    private readonly fetcher: typeof fetch = fetch) {
    this.connection = {...connection, ...(connection.development ? {development: {...connection.development}} : {}), ...(connection.session ? {session: {...connection.session}} : {})};
  }
  private async request(path: string, body?: ChoiceRequest, refresh = true): Promise<unknown> {
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 20000);
    try {
      const response = await this.fetcher(new URL(path, connectionEndpoint(this.connection)).toString(), {
        method: body ? 'POST' : 'GET', redirect: 'error', signal: controller.signal,
        headers: {...connectionHeaders(this.connection), 'X-Wearing-Identity': this.connection.identity,
          ...(body ? {'X-Wearing-Token': this.token, 'Content-Type': 'application/json'} : {})},
        ...(body ? {body: JSON.stringify(body)} : {}),
      });
      if (body && response.status === 403 && refresh) {await this.bootstrap(); return await this.request(path, body, false);}
      const data: unknown = await response.json().catch(() => {throw invalid(!!body);});
      if (!response.ok) throw new ApiError(obj(data) && typeof data.detail === 'string' ? data.detail : '请求没有完成，请重新读取。', response.status);
      return data;
    } catch (cause) {
      if (cause instanceof ApiError) throw cause;
      throw new ApiError(body ? '连接中断，这次选择已在手机保留。重试会取回同一项提交。' : '暂时连不上 Pajio，请重新读取。');
    } finally {clearTimeout(timer);}
  }
  private async bootstrap() {
    const value = await this.request('/api/bootstrap');
    if (!obj(value) || typeof value.token !== 'string' || !value.token || !Array.isArray(value.identities) ||
      !value.identities.some(item => obj(item) && item.id === this.connection.identity)) throw invalid();
    this.token = value.token;
  }
  private path() {
    if (!id(this.artifact) || !id(this.sourceTask)) throw invalid();
    return `/api/artifacts/${encodeURIComponent(this.artifact)}/choices`;
  }
  async read() {return parseChoiceState(await this.request(this.path()), this.artifact, this.revision, this.sourceTask);}
  async choose(body: ChoiceRequest) {
    if (!validChoiceRequest(body) || body.artifact_revision !== this.revision) throw invalid();
    if (!this.token) await this.bootstrap();
    const data = await this.request(this.path(), body);
    try {
      const receipt = parseChoiceReceipt(data, this.artifact, this.sourceTask);
      if (receipt.request_key !== body.request_key || receipt.choice_id !== body.choice_id || receipt.revision !== body.selection_revision + 1) throw invalid();
      return receipt;
    } catch {throw invalid(true);}
  }
}
