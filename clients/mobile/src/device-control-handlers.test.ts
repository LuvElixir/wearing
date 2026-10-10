import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
import * as ts from 'typescript';
import {ApiError} from './core';
import {deviceControlAction, type CloudDevice} from './device-management';
import type {RemoteAccess} from './remote-device-model';

const device: CloudDevice = {resource_id: 'computer_synthetic', name: '合成电脑', kind: 'computer', methods: ['computer.observe'],
  connector_id: 'connector_test', connected: true, online: false, paused: true, control_pending: false, control_generation: 4,
  permission_revision: 'a'.repeat(64), policy_revision: 1, needs_review: false, last_seen_at: null};
const access = (state: RemoteAccess['state'], patch: Partial<RemoteAccess> = {}): RemoteAccess => ({resource_id: device.resource_id, supported: true,
  state, control_generation: 4, session_id: 'human_test', epoch: 1, gateway_epoch: 2, device_confirmed: true, expires_at: null, ...patch});

test('private pause directs to explicit return; ordinary pause, unknown state and pending ACK stay distinct', () => {
  for (const kind of ['computer', 'android'] as const) {
    const d = {...device, kind};
    for (const state of ['paused', 'human_private'] as const) assert.equal(deviceControlAction(d, access(state)), 'return');
    for (const state of ['handoff_pending', 'return_pending'] as const) assert.equal(deviceControlAction(d, access(state)), 'wait');
    assert.equal(deviceControlAction(d, access('agent_ready')), 'resume');
    assert.equal(deviceControlAction(d, access('unavailable', {supported: false, control_generation: 0})), 'resume');
    assert.equal(deviceControlAction(d, null), 'check');
    assert.equal(deviceControlAction(d, access('agent_ready', {control_generation: 3})), 'check');
    assert.equal(deviceControlAction(d, access('agent_ready', {resource_id: 'other'})), 'check');
    assert.equal(deviceControlAction({...d, control_pending: true}, access('agent_ready')), 'wait');
    assert.equal(deviceControlAction({...d, paused: false}, null), 'pause');
  }
});

function handlers(next = access('paused')) {
  const ast = ts.createSourceFile('NativeDevicePanel.tsx', readFileSync(new URL('./NativeDevicePanel.tsx', import.meta.url), 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const component = ast.statements.find(n => ts.isFunctionDeclaration(n) && n.name?.text === 'RemoteDeviceEntry') as ts.FunctionDeclaration;
  const picked = component.body!.statements.filter(n => ts.isFunctionDeclaration(n) && ['openRemote', 'changeControl'].includes(n.name!.text));
  assert.equal(picked.length, 2);
  const code = ts.transpileModule(picked.map(n => ts.createPrinter().printNode(ts.EmitHint.Unspecified, n, ast)).join('\n'), {compilerOptions: {target: ts.ScriptTarget.ES2022}}).outputText;
  const h = {device: {...device}, mounted: {current: true}, AppState: {currentState: 'active'}, ready: true, busy: '', reads: 0,
    mutations: [] as boolean[], routes: [] as unknown[], observed: null as RemoteAccess | null, ApiError, deviceControlAction,
    api: {status: async (_resource: string) => {h.reads++; return next;}},
    onControl: async (paused: boolean) => {h.mutations.push(paused);},
    router: {setParams: (params: unknown) => {h.routes.push(params);}},
    setAccess: (value: RemoteAccess) => {h.observed = value;}, setFailed: (_value: boolean) => {},
  };
  runInNewContext(code, h);
  return h as typeof h & {changeControl: () => Promise<void>; openRemote: () => void};
}

test('actual restore handler checks fresh private state then only navigates, without resume/takeover/return mutations', async () => {
  for (const state of ['paused', 'human_private'] as const) {
    const h = handlers(access(state)); await h.changeControl();
    assert.equal(h.reads, 1); assert.deepEqual(h.mutations, []); assert.equal(h.routes.length, 1);
    assert.equal(JSON.stringify(h.routes[0]), JSON.stringify({view: 'remote-device', resource: device.resource_id, deviceKind: 'computer', deviceName: '合成电脑'}));
  }
});

test('actual handler preserves ordinary pause and only resumes a freshly checked ordinary pause', async () => {
  const resume = handlers(access('agent_ready')); await resume.changeControl();
  assert.deepEqual(resume.mutations, [false]); assert.equal(resume.reads, 1); assert.deepEqual(resume.routes, []);
  const pause = handlers(); pause.device.paused = false; await pause.changeControl();
  assert.deepEqual(pause.mutations, [true]); assert.equal(pause.reads, 0);
});

test('failed or changed fresh state never resumes and never retries', async () => {
  for (const value of [access('agent_ready', {control_generation: 5}), access('return_pending'), access('agent_ready', {resource_id: 'other'})]) {
    const h = handlers(value); await assert.rejects(h.changeControl, (e: unknown) => e instanceof ApiError && e.status === 409);
    assert.deepEqual(h.mutations, []); assert.deepEqual(h.routes, []); assert.equal(h.reads, 1);
  }
  const h = handlers(); h.api.status = async () => {h.reads++; throw new ApiError('offline', 0);};
  await assert.rejects(h.changeControl); assert.equal(h.reads, 1); assert.deepEqual(h.mutations, []); assert.deepEqual(h.routes, []);
});

test('navigation, background and pending controls suppress late restore actions', async () => {
  for (const disable of [(h: ReturnType<typeof handlers>) => {h.mounted.current = false;}, (h: ReturnType<typeof handlers>) => {h.AppState.currentState = 'background';}]) {
    const h = handlers(); h.api.status = async () => {h.reads++; disable(h); return access('agent_ready');};
    await h.changeControl(); assert.deepEqual(h.mutations, []); assert.deepEqual(h.routes, []); assert.equal(h.observed, null);
  }
  for (const disable of [(h: ReturnType<typeof handlers>) => {h.busy = 'working';}, (h: ReturnType<typeof handlers>) => {h.ready = false;},
    (h: ReturnType<typeof handlers>) => {h.device.control_pending = true;}]) {
    const h = handlers(); disable(h); await h.changeControl(); assert.equal(h.reads, 0); assert.deepEqual(h.mutations, []);
  }
});
