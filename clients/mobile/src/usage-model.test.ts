import assert from 'node:assert/strict';
import test from 'node:test';
import {loadUsage, moneyLabel, tokenLabel, usageSnapshot} from './usage-model';
const resource = {calls: 2, active: 0, uncertain: 1, limit: 200, remaining: 198, concurrency: 2, audio_ms: 0};
const snapshot = {mode: 'trial', scope: 'runtime', reset_at: null, resources: {model: resource, speech: {...resource, ms_limit: 180000, ms_remaining: 180000}}, identity_usage: {calls: 2, input_tokens: null, output_tokens: null, unreported_model_calls: 2}, cost: null, cost_status: 'unavailable', observed_at: 100};
test('unknown receipts remain unknown and invalid server accounting rejected', () => {
  assert.equal(usageSnapshot(snapshot).identity_usage.input_tokens, null);
  assert.equal(tokenLabel(null), '尚无供应商用量回执');
  assert.equal(tokenLabel(0), '0');
  assert.throws(() => usageSnapshot({...snapshot, cost: 0}));
  assert.throws(() => usageSnapshot({...snapshot, resources: {...snapshot.resources, model: {...resource, active: 3}}}));
});
test('read-only usage sends identity and never places credentials in URL', async () => {
  let request: RequestInit | undefined, url = '';
  await loadUsage({endpoint: 'http://127.0.0.1:8765/', identity: 'work'}, (async (input, init) => {url = String(input); request = init; return new Response(JSON.stringify(snapshot));}) as typeof fetch);
  assert.equal(url, 'http://127.0.0.1:8765/api/usage');
  assert.equal((request?.headers as Record<string, string>)['X-Wearing-Identity'], 'work');
  assert.equal(request?.redirect, 'error');
  assert.equal(request?.body, undefined);
});
const cost = {basis: 'operator_rates', supplier_bill: false, scope: 'runtime_model_calls', currency: 'CNY', price_version: 'operator-v1', unit: 'micros', budget_micros: 5000000, committed_micros: 3000010, remaining_micros: 1999990, settled_estimate_micros: 10, active_reserved_micros: 2000000, uncertain_reserved_micros: 1000000, unpriced_calls: 0, upper_bound_calls: 1, overrun_calls: 0};
test('operator estimates require explicit non-bill provenance and consistent amounts', () => {
  assert.equal(usageSnapshot({...snapshot, cost, cost_status: 'estimated'}).cost?.remaining_micros, 1999990);
  for (const changed of [{supplier_bill: true}, {basis: 'supplier'}, {unit: 'yuan'}, {remaining_micros: 5000000}, {committed_micros: 10}, {active_reserved_micros: -1}, {settled_estimate_micros: NaN}, {currency: 'cny'}, {price_version: ''}]) {
    assert.throws(() => usageSnapshot({...snapshot, cost: {...cost, ...changed}, cost_status: 'estimated'}));
  }
  assert.throws(() => usageSnapshot({...snapshot, cost, cost_status: 'unavailable'}));
  assert.throws(() => usageSnapshot({...snapshot, cost: null, cost_status: 'estimated'}));
});
test('unpriced calls are explicitly partial and tiny amounts do not round to free', () => {
  assert.equal(usageSnapshot({...snapshot, cost: {...cost, unpriced_calls: 2}, cost_status: 'partial'}).cost_status, 'partial');
  assert.throws(() => usageSnapshot({...snapshot, cost: {...cost, unpriced_calls: 2}, cost_status: 'estimated'}));
  assert.equal(moneyLabel(1, 'CNY'), 'CNY 0.000001');
  assert.equal(moneyLabel(0, 'CNY'), 'CNY 0.00');
});
