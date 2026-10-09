import {ApiError, Connection, connectionEndpoint, connectionHeaders} from './core';

export type UsageResource = {calls: number; active: number; uncertain: number; limit: number; remaining: number; concurrency: number; audio_ms: number; ms_limit?: number; ms_remaining?: number};
export type UsageCost = {basis: 'operator_rates'; supplier_bill: false; scope: 'runtime_model_calls'; currency: string; price_version: string; unit: 'micros'; budget_micros: number; committed_micros: number; remaining_micros: number; settled_estimate_micros: number; active_reserved_micros: number; uncertain_reserved_micros: number; unpriced_calls: number; upper_bound_calls: number; overrun_calls: number};
export type UsageSnapshot = {mode: 'trial' | 'not_enabled'; scope: 'runtime'; reset_at: null; resources: {model: UsageResource; speech: UsageResource & {ms_limit: number; ms_remaining: number}}; identity_usage: {calls: number; input_tokens: number | null; output_tokens: number | null; unreported_model_calls: number}; cost: UsageCost | null; cost_status: 'unavailable' | 'estimated' | 'partial'; observed_at: number};
function object(value: unknown): value is Record<string, unknown> {return !!value && typeof value === 'object' && !Array.isArray(value);}
const nonnegative = (value: unknown): value is number => Number.isSafeInteger(value) && (value as number) >= 0;
export function usageSnapshot(value: unknown): UsageSnapshot {
  const invalid = () => new ApiError('用量数据暂时无法核对，请刷新后重试。');
  if (!object(value) || !['trial', 'not_enabled'].includes(String(value.mode)) || value.scope !== 'runtime' || value.reset_at !== null || !object(value.resources) || !object(value.identity_usage) || typeof value.observed_at !== 'number' || !Number.isFinite(value.observed_at)) throw invalid();
  const cost = value.cost;
  if (cost === null) {if (value.cost_status !== 'unavailable') throw invalid();}
  else {
    if (!object(cost) || cost.basis !== 'operator_rates' || cost.supplier_bill !== false || cost.scope !== 'runtime_model_calls' || cost.unit !== 'micros' || typeof cost.currency !== 'string' || !/^[A-Z]{3}$/.test(cost.currency) || typeof cost.price_version !== 'string' || !/^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$/.test(cost.price_version)) throw invalid();
    if (['budget_micros', 'committed_micros', 'remaining_micros', 'settled_estimate_micros', 'active_reserved_micros', 'uncertain_reserved_micros', 'unpriced_calls', 'upper_bound_calls', 'overrun_calls'].some(key => !nonnegative(cost[key]))) throw invalid();
    const total = (cost.settled_estimate_micros as number) + (cost.active_reserved_micros as number) + (cost.uncertain_reserved_micros as number);
    if (!Number.isSafeInteger(total) || cost.committed_micros !== total || cost.remaining_micros !== Math.max(0, (cost.budget_micros as number) - total) || value.cost_status !== (cost.unpriced_calls ? 'partial' : 'estimated')) throw invalid();
  }
  for (const kind of ['model', 'speech']) {
    const row = value.resources[kind];
    if (!object(row) || ['calls', 'active', 'uncertain', 'limit', 'remaining', 'concurrency', 'audio_ms', ...(kind === 'speech' ? ['ms_limit', 'ms_remaining'] : [])].some(key => !nonnegative(row[key]))) throw invalid();
    if ((row.active as number) + (row.uncertain as number) > (row.calls as number) || (row.remaining as number) > (row.limit as number)) throw invalid();
  }
  const own = value.identity_usage;
  if (!nonnegative(own.calls) || !nonnegative(own.unreported_model_calls) || ['input_tokens', 'output_tokens'].some(key => own[key] !== null && !nonnegative(own[key]))) throw invalid();
  return value as UsageSnapshot;
}
export async function loadUsage(connection: Connection, fetcher: typeof fetch = fetch): Promise<UsageSnapshot> {
  const controller = new AbortController(), timeout = setTimeout(() => controller.abort(), 15000);
  try {
    const response = await fetcher(new URL('/api/usage', connectionEndpoint(connection)).toString(), {signal: controller.signal, redirect: 'error', headers: {...connectionHeaders(connection), 'X-Wearing-Identity': connection.identity}});
    if (!response.ok) throw new ApiError(response.status === 401 ? '连接已失效，请重新连接后查看用量。' : '暂时无法读取用量，请稍后刷新。', response.status);
    return usageSnapshot(await response.json());
  } catch (error) {if (error instanceof ApiError) throw error; throw new ApiError('暂时连不上用量服务，请检查连接后刷新。');}
  finally {clearTimeout(timeout);}
}
export function tokenLabel(value: number | null) {return value === null ? '尚无供应商用量回执' : value.toLocaleString('zh-CN');}
export function minutesLabel(ms: number) {return `${Math.floor(ms / 60000)} 分 ${Math.floor(ms % 60000 / 1000)} 秒`;}
export function moneyLabel(micros: number, currency: string) {return `${currency} ${(micros / 1_000_000).toLocaleString('zh-CN', {minimumFractionDigits: 2, maximumFractionDigits: 6})}`;}
