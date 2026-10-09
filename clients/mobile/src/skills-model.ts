import {ApiError, Connection, connectionEndpoint, connectionHeaders, WearingApi} from './core';

export type Skill = {id: string; name: string; description: string; category: string; enabled: boolean; essential: boolean; compatible: boolean; requirements: string[]; revision: string; installed?: boolean};
export type SkillSnapshot = {revision: string; installed: Skill[]; catalog: Skill[]};
export type SkillSource = 'installed' | 'catalog';
export type SkillDetail = Skill & {content: string; source: SkillSource};
export type SkillRemoval = {id: string; name: string; revision: string; package_revision: string; operation_id: string};
export type SkillRemovalReceipt = {removed: true; id: string; operation_id: string; recovery_id: string; snapshot: SkillSnapshot};
const object = (value: unknown): Record<string, unknown> | null => value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : null;
const invalid = () => new ApiError('这次没有读到完整的技能目录，请重试。', 422);
const revision = (value: unknown): value is string => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
export function validSkillId(value: unknown): value is string {return typeof value === 'string' && value.length > 0 && value.length <= 512 && !/[\\\u0000-\u001f]/.test(value) && value.split('/').every(part => !!part && !part.startsWith('.'));}
function skill(value: unknown): Skill {
  const data = object(value);
  if (!data || !validSkillId(data.id) || typeof data.name !== 'string' || typeof data.description !== 'string' || typeof data.category !== 'string' || !revision(data.revision) ||
    !['enabled', 'essential', 'compatible'].every(key => typeof data[key] === 'boolean') || !Array.isArray(data.requirements) || !data.requirements.every(item => typeof item === 'string')) throw invalid();
  return data as Skill;
}
export function skillSnapshot(value: unknown): SkillSnapshot {
  const data = object(value);
  if (!data || !revision(data.revision) || !Array.isArray(data.installed) || !Array.isArray(data.catalog) || data.installed.length > 1000 || data.catalog.length > 1000) throw invalid();
  const installed = data.installed.map(skill), catalog = data.catalog.map(skill);
  if (catalog.some(item => typeof item.installed !== 'boolean')) throw invalid();
  return {revision: data.revision, installed, catalog};
}
export function skillDetail(value: unknown): SkillDetail {
  const item = skill(value), data = object(value)!;
  if (typeof data.content !== 'string' || data.content.length > 256 * 1024 || !['installed', 'catalog'].includes(String(data.source))) throw invalid();
  return {...item, content: data.content, source: data.source as SkillSource};
}
export function skillRemoval(value: unknown): SkillRemoval {
  const data = object(value);
  if (!data || !validSkillId(data.id) || typeof data.name !== 'string' || !revision(data.revision) || !revision(data.package_revision) ||
      typeof data.operation_id !== 'string' || !/^[a-f0-9]{32}$/.test(data.operation_id)) throw invalid();
  return {id: data.id, name: data.name, revision: data.revision, package_revision: data.package_revision, operation_id: data.operation_id};
}

export class SkillsApi {
  private authorization: WearingApi;
  constructor(private connection: Connection, private fetcher: typeof fetch = fetch) {this.authorization = new WearingApi(connection, fetcher);}
  private async request(path: string, method = 'GET', value?: unknown): Promise<unknown> {
    const token = method === 'GET' ? undefined : await this.authorization.voiceAuthorization();
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 20000);
    try {
      const response = await this.fetcher(new URL(path, connectionEndpoint(this.connection)).toString(), {method, redirect: 'error', signal: controller.signal,
        headers: {...connectionHeaders(this.connection), 'X-Wearing-Identity': this.connection.identity, ...(token ? {'X-Wearing-Token': token, 'Content-Type': 'application/json'} : {})},
        ...(value === undefined ? {} : {body: JSON.stringify(value)})});
      const data = await response.json();
      if (!response.ok) throw new ApiError(response.status === 401 ? '连接已到期，请重新连接。' : response.status === 423 ? '当前有任务或自动加载设置在使用技能，请处理后再移除。' : response.status === 409 ? '技能内容或设置已有变化，请刷新后重试。' : response.status === 404 ? '这个技能暂时找不到，请刷新目录。' : '这次操作未完成，请稍后重试。', response.status);
      return data;
    } catch (error) {if (error instanceof ApiError) throw error; throw new ApiError('暂时连不上技能服务，请检查连接后重试。');}
    finally {clearTimeout(timer);}
  }
  async list() {return skillSnapshot(await this.request('/api/skills'));}
  async detail(source: SkillSource, id: string) {if (!validSkillId(id)) throw invalid(); return skillDetail(await this.request('/api/skills/detail?' + new URLSearchParams({source, id})));}
  async enabled(id: string, enabled: boolean, currentRevision: string) {if (!validSkillId(id) || !revision(currentRevision)) throw invalid(); return skillSnapshot(await this.request('/api/skills/enabled', 'PATCH', {id, enabled, revision: currentRevision}));}
  async install(id: string, currentRevision: string) {if (!validSkillId(id) || !revision(currentRevision)) throw invalid(); return skillSnapshot(await this.request('/api/skills/install', 'POST', {id, revision: currentRevision}));}
  async removal(id: string) {
    if (!validSkillId(id)) throw invalid();
    const result = skillRemoval(await this.request('/api/skills/removal?' + new URLSearchParams({id})));
    if (result.id !== id) throw invalid();
    return result;
  }
  async remove(preview: SkillRemoval): Promise<SkillRemovalReceipt> {
    const {id, revision, package_revision, operation_id} = skillRemoval(preview);
    const data = object(await this.request('/api/skills/remove', 'POST', {id, revision, package_revision, operation_id}));
    if (!data || data.removed !== true || data.id !== id || data.operation_id !== operation_id || data.recovery_id !== operation_id) throw invalid();
    const snapshot = skillSnapshot(data.snapshot);
    if (snapshot.installed.some(item => item.id === id)) throw invalid();
    return {removed: true, id, operation_id, recovery_id: operation_id, snapshot};
  }
}
