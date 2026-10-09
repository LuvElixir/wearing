import {ApiError, Connection, connectionEndpoint, connectionHeaders, scopeOf} from './core';

export const taskPhases = ['draft', 'queued', 'starting', 'running', 'waiting_for_approval', 'stopping', 'connection_lost', 'ambiguous', 'failed', 'stopped', 'completed_unverified', 'verified', 'closed', 'unknown'] as const;
const phases = ['idle', 'downloading', 'installing', 'ready', 'running', 'failed', 'stopped', 'unknown'] as const;
const serverErrors = ['engine_connection_lost', 'run_state_unknown', 'run_failed', 'stop_unconfirmed', 'operation_failed'] as const;
const errorCodes = ['session_expired', 'permission_denied', 'state_changed', 'invalid_receipt', 'rate_limited', 'storage_busy', 'storage_unavailable', 'network_unavailable', 'timeout', 'recognition_unavailable', 'quota_exhausted', 'quota_busy', 'quota_duplicate', 'quota_unavailable', 'unavailable'] as const;
const sources = ['sync', 'chat', 'voice', 'record', 'files', 'notifications', 'devices', 'diagnostics'] as const;
export type DiagnosticSource = typeof sources[number];
export type DiagnosticError = {source: DiagnosticSource; category: typeof errorCodes[number]; observed_at: string};
export type DiagnosticTask = {task_id: string; run_id: string | null; phase: typeof taskPhases[number]; attempt: number; created_at: string | null; record_updated_at: string | null; last_state_event_at: string | null; seconds_without_state_change: number | null; needs_progress_check: boolean; error_category: typeof serverErrors[number] | null};
export type DiagnosticSnapshot = {schema: 1; report_id: string; identity_id: string; captured_at: string;
  service: {state: 'reachable'; version: string | null; deployment: 'local' | 'cloud' | 'synthetic' | 'unknown'};
  runtime: {state: 'observed' | 'unavailable'; observed_at: string; phase: typeof phases[number]; installed: boolean | null; running: boolean | null; error_present: boolean; connectors: Record<'files' | 'phone' | 'computer', {phase: typeof phases[number]; active: boolean | null; error_present: boolean}>};
  engine_probe: {state: 'reachable' | 'unavailable' | 'not_configured' | 'not_observed' | 'timeout'; observed_at: string | null};
  devices: {state: 'observed' | 'not_observed' | 'unavailable'; observed_at: string | null; truncated: boolean; items: {kind: 'computer' | 'phone' | 'browser' | 'desktop' | 'android' | 'ios' | 'other'; connected: boolean | null; online: boolean | null; paused: boolean | null; control_pending: boolean | null; needs_review: boolean | null; last_seen_at: string | null}[]};
  tasks: {items: DiagnosticTask[]; truncated: boolean; limit: 30; long_phase_seconds: 900}};
const invalid = () => new ApiError('诊断回执无法核对，可以先导出本机诊断。', 422);
function object(v: unknown): Record<string, unknown> {if (!v || typeof v !== 'object' || Array.isArray(v)) throw invalid(); return v as Record<string, unknown>;}
function option<T extends string>(v: unknown, values: readonly T[]): T {if (typeof v !== 'string' || !values.includes(v as T)) throw invalid(); return v as T;}
function bool(v: unknown): boolean {if (typeof v !== 'boolean') throw invalid(); return v;}
function nullableBool(v: unknown): boolean | null {return v === null ? null : bool(v);}
function integer(v: unknown, max = Number.MAX_SAFE_INTEGER): number {if (!Number.isSafeInteger(v) || (v as number) < 0 || (v as number) > max) throw invalid(); return v as number;}
function date(v: unknown): string {if (typeof v !== 'string' || !/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|[+-]\d\d:\d\d)$/.test(v) || !Number.isFinite(Date.parse(v))) throw invalid(); return new Date(v).toISOString();}
const maybeDate = (v: unknown) => v === null ? null : date(v);
function reference(v: unknown): string {if (typeof v !== 'string' || !/^(?:[a-f0-9]{32}|[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}|run_[a-f0-9]{32}|ref_[a-f0-9]{16})$/.test(v)) throw invalid(); return v;}
function rows(v: unknown, limit: number): unknown[] {if (!Array.isArray(v) || v.length > limit) throw invalid(); return v;}
function version(v: unknown): string | null {return typeof v === 'string' && /^\d+(?:\.\d+){0,3}$/.test(v) && v.length <= 24 ? v : null;}

/** Always construct a new object: a server upgrade cannot smuggle logs into export. */
export function diagnosticSnapshot(value: unknown, identity: string): DiagnosticSnapshot {
  const raw = object(value), service = object(raw.service), runtime = object(raw.runtime), connectors = object(runtime.connectors), probe = object(raw.engine_probe), devices = object(raw.devices), tasks = object(raw.tasks);
  if (raw.schema !== 1 || raw.identity_id !== identity || typeof raw.report_id !== 'string' || !/^[a-f0-9]{32}$/.test(raw.report_id) || tasks.limit !== 30 || tasks.long_phase_seconds !== 900) throw invalid();
  function connector(key: string) {const row = object(connectors[key]); return {phase: option(row.phase, phases), active: nullableBool(row.active), error_present: bool(row.error_present)};}
  return {schema: 1, report_id: raw.report_id, identity_id: identity, captured_at: date(raw.captured_at),
    service: {state: option(service.state, ['reachable']), version: version(service.version), deployment: option(service.deployment, ['local', 'cloud', 'synthetic', 'unknown'])},
    runtime: {state: option(runtime.state, ['observed', 'unavailable']), observed_at: date(runtime.observed_at), phase: option(runtime.phase, phases), installed: nullableBool(runtime.installed), running: nullableBool(runtime.running), error_present: bool(runtime.error_present), connectors: {files: connector('files'), phone: connector('phone'), computer: connector('computer')}},
    engine_probe: {state: option(probe.state, ['reachable', 'unavailable', 'not_configured', 'not_observed', 'timeout']), observed_at: maybeDate(probe.observed_at)},
    devices: {state: option(devices.state, ['observed', 'not_observed', 'unavailable']), observed_at: maybeDate(devices.observed_at), truncated: bool(devices.truncated), items: rows(devices.items, 30).map(value => {const d = object(value); return {kind: option(d.kind, ['computer', 'phone', 'browser', 'desktop', 'android', 'ios', 'other']), connected: nullableBool(d.connected), online: nullableBool(d.online), paused: nullableBool(d.paused), control_pending: nullableBool(d.control_pending), needs_review: nullableBool(d.needs_review), last_seen_at: maybeDate(d.last_seen_at)};})},
    tasks: {limit: 30, long_phase_seconds: 900, truncated: bool(tasks.truncated), items: rows(tasks.items, 30).map(value => {const t = object(value); return {task_id: reference(t.task_id), run_id: t.run_id === null ? null : reference(t.run_id), phase: option(t.phase, taskPhases), attempt: integer(t.attempt, 100000), created_at: maybeDate(t.created_at), record_updated_at: maybeDate(t.record_updated_at), last_state_event_at: maybeDate(t.last_state_event_at), seconds_without_state_change: t.seconds_without_state_change === null ? null : integer(t.seconds_without_state_change), needs_progress_check: bool(t.needs_progress_check), error_category: t.error_category === null ? null : option(t.error_category, serverErrors)};})}};
}

/** Read-only request. A snapshot never starts an engine, retries a task or sends feedback. */
export class DiagnosticsClient {
  readonly connection: Connection;
  constructor(connection: Connection, private fetcher: typeof fetch = fetch) {this.connection = {...connection, ...(connection.session ? {session: {...connection.session}} : {}), ...(connection.development ? {development: {...connection.development}} : {})};}
  async snapshot(signal?: AbortSignal): Promise<DiagnosticSnapshot> {
    const controller = new AbortController(), cancel = () => controller.abort(), timer = setTimeout(cancel, 12000);
    signal?.addEventListener('abort', cancel); if (signal?.aborted) cancel();
    try {
      const response = await this.fetcher(new URL('/api/diagnostics', connectionEndpoint(this.connection)).toString(), {method: 'GET', headers: {...connectionHeaders(this.connection), 'X-Wearing-Identity': this.connection.identity}, signal: controller.signal, redirect: 'error'});
      if (!response.ok) throw new ApiError(response.status === 401 ? '登录已失效，可先导出本机诊断，再重新登录。' : '没有取得服务诊断，可先导出本机诊断。', response.status);
      const text = await response.text(); if (text.length > 100000) throw invalid();
      if (controller.signal.aborted) throw new ApiError('这次读取已取消，可以再次生成诊断。', 408);
      let value: unknown; try {value = JSON.parse(text);} catch {throw invalid();}
      return diagnosticSnapshot(value, this.connection.identity);
    } catch (error) {if (error instanceof ApiError) throw error; throw new ApiError('暂时无法取得服务诊断，可先导出本机诊断。', controller.signal.aborted ? 408 : 0);}
    finally {clearTimeout(timer); signal?.removeEventListener('abort', cancel);}
  }
}

export function diagnosticErrorCategory(error: unknown): DiagnosticError['category'] {
  if (error instanceof ApiError) {
    if (error.status === 401) return 'session_expired';
    if (error.status === 403) return 'permission_denied';
    if (error.status === 409) return 'state_changed';
    if (error.status === 422) return 'invalid_receipt';
    if (error.status === 429) return 'rate_limited';
    if (error.status === 408) return 'timeout';
    if (error.status === 0) return 'network_unavailable';
  }
  const candidate = error && typeof error === 'object' && 'code' in error ? error.code : undefined;
  if (typeof candidate === 'string' && errorCodes.includes(candidate as DiagnosticError['category'])) return candidate as DiagnosticError['category'];
  const text = error instanceof Error ? error.message : '';
  if (/database (?:table |schema )?is locked|SQLITE_(?:BUSY|LOCKED)\b/i.test(text)) return 'storage_busy';
  if (/SQLite|ENOSPC/i.test(text)) return 'storage_unavailable';
  if (/timeout|timed out|超时/i.test(text)) return 'timeout';
  if (/network|offline|fetch failed|网络/i.test(text)) return 'network_unavailable';
  return 'unavailable';
}

// In-memory only; bounded to eight scopes, eight events per scope, one day.
const history = new Map<string, DiagnosticError[]>();
export function observeDiagnosticError(connection: Connection, source: DiagnosticSource, error: unknown, now = Date.now()): void {
  try {
    if (!sources.includes(source)) return;
    const key = scopeOf(connection), prior = history.get(key) || [];
    history.delete(key); history.set(key, [...prior.filter(item => now - Date.parse(item.observed_at) < 86400000), {source, category: diagnosticErrorCategory(error), observed_at: new Date(now).toISOString()}].slice(-8));
    if (history.size > 8) history.delete(history.keys().next().value!);
  } catch {/* Never change the originating operation. */}
}
export function clearDiagnosticErrors(connection: Connection): void {try {history.delete(scopeOf(connection));} catch { /* Invalid connections have no history. */ }}
export function recentDiagnosticErrors(connection: Connection, now = Date.now()): DiagnosticError[] {try {return (history.get(scopeOf(connection)) || []).filter(item => now - Date.parse(item.observed_at) < 86400000).map(item => ({...item}));} catch {return [];}}

export const feedbackKinds = {general: '其他问题', task: '任务没有继续', connection: '连接或网络', voice: '语音输入', files: '文件与结果', appearance: '显示与交互'} as const;
export type FeedbackKind = keyof typeof feedbackKinds;
export type DiagnosticLocal = {app_version: unknown; native_build: unknown; platform: unknown; os_version: unknown; network?: unknown};
export type DiagnosticReport = ReturnType<typeof makeDiagnosticReport>;
function exportedSnapshot(snapshot: DiagnosticSnapshot, identity: string): Omit<DiagnosticSnapshot, 'identity_id'> {
  const safe = diagnosticSnapshot(snapshot, identity);
  return {schema: safe.schema, report_id: safe.report_id, captured_at: safe.captured_at, service: safe.service, runtime: safe.runtime, engine_probe: safe.engine_probe, devices: safe.devices, tasks: safe.tasks};
}
export function makeDiagnosticReport(connection: Connection, local: DiagnosticLocal, server: DiagnosticSnapshot | null, category: FeedbackKind, errors: DiagnosticError[], now = Date.now()) {
  let mode: 'cloud_session' | 'development_pairing' | 'local' | 'remote' | 'invalid' = 'invalid', transport: 'https' | 'loopback_http' | 'development_http' | 'unknown' = 'unknown';
  try {const address = new URL(connectionEndpoint(connection, true)); mode = connection.session ? 'cloud_session' : connection.development ? 'development_pairing' : address.protocol === 'http:' ? 'local' : 'remote'; transport = address.protocol === 'https:' ? 'https' : connection.development ? 'development_http' : 'loopback_http';} catch { /* No raw address is exported. */ }
  const network = local.network && typeof local.network === 'object' ? local.network as Record<string, unknown> : {};
  const expires = connection.session?.expiresAt || connection.development?.expiresAt;
  return {schema: 'pajio.diagnostics.v1' as const, captured_at: new Date(now).toISOString(), feedback: {category: option(category, Object.keys(feedbackKinds) as FeedbackKind[])},
    app: {name: 'Pajio', manifest_version: version(local.app_version), native_build: version(String(local.native_build ?? '')), platform: ['ios', 'android', 'web'].includes(String(local.platform)) ? String(local.platform) : 'other', os_version: version(String(local.os_version ?? ''))},
    connection: {mode, transport, identity: 'current', authorization: expires ? Number.isFinite(Date.parse(expires)) && Date.parse(expires) > now ? 'active' : 'expired' : 'not_applicable'},
    network: {type: ['NONE', 'UNKNOWN', 'CELLULAR', 'WIFI', 'BLUETOOTH', 'ETHERNET', 'WIMAX', 'VPN', 'OTHER'].includes(String(network.type)) ? String(network.type) : 'UNKNOWN', connected: typeof network.isConnected === 'boolean' ? network.isConnected : null, os_internet_reachable: typeof network.isInternetReachable === 'boolean' ? network.isInternetReachable : null},
    // Re-validate projection before sharing, even if a caller supplies a wider object.
    server: server ? exportedSnapshot(server, connection.identity) : null,
    recent_errors: errors.slice(-8).filter(e => sources.includes(e.source) && errorCodes.includes(e.category)).map(e => ({source: e.source, category: e.category, observed_at: date(e.observed_at)})),
    limitations: ['point_in_time_not_heartbeat', 'state_change_age_not_execution_progress', 'network_os_state_not_service_reachability', 'recent_errors_this_app_process_only', 'user_share_not_support_submission']};
}
export function diagnosticBytes(report: DiagnosticReport): Uint8Array {return new TextEncoder().encode(JSON.stringify(report, null, 2));}
export async function shareDiagnosticReport(report: DiagnosticReport, active: () => boolean, share: (bytes: Uint8Array) => Promise<void>): Promise<boolean> {
  if (!active()) return false;
  await share(diagnosticBytes(report));
  return active();
}
export function diagnosticFindings(snapshot: Omit<DiagnosticSnapshot, 'identity_id'> | null): string[] {
  if (!snapshot) return ['未取得服务诊断。本机诊断仍可保存；重新连接后可补齐任务和设备状态。'];
  const findings: string[] = [];
  if (snapshot.engine_probe.state === 'unavailable' || snapshot.engine_probe.state === 'timeout') findings.push('服务可达，但本次没有确认执行引擎可达。现有任务没有重发。');
  if (snapshot.runtime.phase === 'failed') findings.push('运行环境报告失败，请检查执行服务。');
  const uncertain = snapshot.tasks.items.filter(t => ['connection_lost', 'ambiguous'].includes(t.phase)).length;
  if (uncertain) findings.push(`${uncertain} 个任务的执行状态需要重新核对。`);
  const long = snapshot.tasks.items.filter(t => t.needs_progress_check).length;
  if (long) findings.push(`${long} 个任务超过 15 分钟未记录新的状态变化；这不等于任务已卡死，请打开任务核对进展。`);
  const disconnected = snapshot.devices.items.filter(d => d.connected === false).length;
  if (disconnected) findings.push(`${disconnected} 个设备资源的连接租约已失效。`);
  const review = snapshot.devices.items.filter(d => d.needs_review).length;
  if (review) findings.push(`${review} 个设备资源有未核对的旧动作；请先核对结果。`);
  if (!findings.length) findings.push('本次已取得服务快照；没有发现上述已知异常，不代表任务已完成或后台持续健康。');
  return findings;
}
