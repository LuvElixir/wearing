import {test} from 'node:test';
import assert from 'node:assert/strict';
import {exportWorkspaceOriginal, WorkspaceExportPorts} from './workspace-export';

const file = {path: 'work/report.pdf', size: 2, modified: 1};
function harness() {
  const events: string[] = [];
  let active = true;
  const ports: WorkspaceExportPorts = {
    available: async () => true, active: () => active,
    write: (_bytes, name) => {events.push('write:' + name); return {uri: 'file:///cache/report.pdf', remove: () => events.push('remove')};},
    share: async uri => {events.push('share:' + uri);},
  };
  return {events, ports, leave: () => {active = false;}};
}

test('original is cleaned after a share is completed or dismissed', async () => {
  const {ports, events} = harness();
  await exportWorkspaceOriginal({original: async () => new Uint8Array([1, 2])}, file, ports);
  assert.deepEqual(events, ['write:report.pdf', 'share:file:///cache/report.pdf', 'remove']);
});

test('changing identity while downloading never opens a share sheet for the old identity', async () => {
  const {ports, events, leave} = harness();
  let complete!: (bytes: Uint8Array) => void;
  const done = exportWorkspaceOriginal({original: () => new Promise(resolve => {complete = resolve;})}, file, ports);
  await Promise.resolve();
  leave(); complete(new Uint8Array([1, 2])); await done;
  assert.deepEqual(events, []);
});

test('a failed native share cleans the private temporary file and allows error recovery', async () => {
  const {ports, events} = harness();
  ports.share = async () => {throw new Error('no app available');};
  await assert.rejects(() => exportWorkspaceOriginal({original: async () => new Uint8Array([1, 2])}, file, ports), /no app available/);
  assert.deepEqual(events, ['write:report.pdf', 'remove']);
});

test('unavailable sharing and an abandoned screen do not download data', async () => {
  let reads = 0;
  const api = {original: async () => {reads++; return new Uint8Array();}};
  const first = harness(); first.ports.available = async () => false;
  await assert.rejects(() => exportWorkspaceOriginal(api, file, first.ports), /分享面板/);
  const second = harness(); second.leave();
  await exportWorkspaceOriginal(api, file, second.ports);
  assert.equal(reads, 0);
});

test('exported names cannot escape their private temporary directory', async () => {
  const {ports, events} = harness();
  await exportWorkspaceOriginal({original: async () => new Uint8Array()}, {...file, path: '..'}, ports);
  assert.equal(events[0], 'write:原件');
  events.length = 0;
  await exportWorkspaceOriginal({original: async () => new Uint8Array()}, {...file, path: '..\\report.pdf'}, ports);
  assert.equal(events[0], 'write:report.pdf');
});
