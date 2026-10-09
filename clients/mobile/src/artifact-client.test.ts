import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {readFileSync} from 'node:fs';
import {test} from 'node:test';
import {ApiError, type Connection} from './core';
import {ARTIFACT_CONTENT_CSP, ARTIFACT_MAX_BYTES, ArtifactApi, ArtifactMetadata, artifactNavigationAllowed, artifactPreviewDocument, parseArtifactMetadata} from './artifact-client';
import {exportWorkspaceOriginal, type WorkspaceExportPorts} from './workspace-export';
import {palettes} from './appearance';

const html = '<!doctype html><html><head><meta charset="utf-8"></head><body>图文结果</body></html>';
const bytes = new TextEncoder().encode(html);
const digest = async (value: Uint8Array) => createHash('sha256').update(value).digest('hex');
const metadata: ArtifactMetadata = {id: 'art_1', task_id: 'task_1', title: '今日简报', summary: '合成内容', presentation: 'dashboard',
  sources: ['笔记'], assumptions: [], limitations: ['未读取外部服务'], revision: 1, previous_id: null, family_id: 'art_1',
  created_at: '2026-10-07T08:00:00Z', size: bytes.length, sha256: createHash('sha256').update(bytes).digest('hex'), state: 'generated',
  checks: {file: 'verified', render: 'not_verified', content: 'not_verified'}};
const connection: Connection = {endpoint: 'https://pajio.example/', identity: 'daily', session: {
  accessToken: 'a'.repeat(64), credentialId: 'c'.repeat(32), userId: 'user_' + 'f'.repeat(32), tenantId: 'tenant_1', expiresAt: '2099-01-01T00:00:00Z',
}};
type Call = {path: string; headers: Headers; init: RequestInit | undefined};
function harness(handler?: (call: Call) => Response | Promise<Response>) {
  const calls: Call[] = [];
  const copy = {...connection, session: {...connection.session!}};
  const api = new ArtifactApi(copy, digest, (async (url, init) => {
    const call = {path: new URL(String(url)).pathname, headers: new Headers(init?.headers), init}; calls.push(call);
    assert.equal(init?.method, 'GET'); assert.equal(init?.redirect, 'error'); assert.ok(init?.signal); assert.equal(init?.body, undefined);
    return handler ? handler(call) : call.path.endsWith('/art_1') ? Response.json(metadata) : new Response(bytes, {headers: {'Content-Type': call.path.endsWith('/preview') ? 'text/html; charset=utf-8' : 'application/octet-stream', 'Content-Length': String(bytes.length)}});
  }) as typeof fetch);
  return {api, calls, copy};
}
test('artifact metadata refuses unrelated or partial version receipts before opening bytes', () => {
  assert.equal(parseArtifactMetadata(metadata, 'art_1').revision, 1);
  for (const change of [{id: 'art_2'}, {task_id: ''}, {revision: 0}, {previous_id: '../other'}, {family_id: ''}, {created_at: 'never'},
    {size: ARTIFACT_MAX_BYTES + 1}, {size: -1}, {sha256: 'bad'}, {sources: [42]}, {checks: {file: 'verified'}}, {state: 'ready'}]) {
    assert.throws(() => parseArtifactMetadata({...metadata, ...change}, 'art_1'), /不完整/);
  }
});
test('native document transport verifies UTF8 bytes and freezes the original identity and bearer', async () => {
  const {api, calls, copy} = harness(); copy.identity = 'other'; copy.session!.accessToken = 'z'.repeat(64);
  const document = await api.document('art_1'); assert.equal(document.html, html); assert.equal(document.metadata.checks.content, 'not_verified');
  assert.deepEqual(calls.map(call => call.path), ['/api/artifacts/art_1', '/api/artifacts/art_1/preview']);
  for (const {headers} of calls) {assert.equal(headers.get('X-Wearing-Identity'), 'daily'); assert.equal(headers.get('Authorization'), 'Bearer ' + 'a'.repeat(64));}
});
test('mismatched MIME, size or content hash never reaches the preview', async () => {
  for (const [body, headers] of [
    [bytes, {'Content-Type': 'text/plain'}], [bytes, {'Content-Type': 'text/html', 'Content-Length': '1'}],
    [new Uint8Array(bytes.length).fill(65), {'Content-Type': 'text/html'}], [bytes.slice(1), {'Content-Type': 'text/html'}],
  ] as [Uint8Array, Record<string, string>][]) {
    const {api} = harness(call => call.path.endsWith('/art_1') ? Response.json(metadata) : new Response(new Uint8Array(body).buffer, {headers}));
    await assert.rejects(api.document('art_1'), (cause: unknown) => cause instanceof ApiError && cause.status === 422);
  }
});
test('native verifier failure is distinguished from a failed connection', async () => {
  const api = new ArtifactApi(connection, async () => {throw Error('native typed array failure');}, (async url => String(url).endsWith('/preview')
    ? new Response(bytes, {headers: {'Content-Type': 'text/html'}}) : Response.json(metadata)) as typeof fetch);
  await assert.rejects(api.document('art_1'), (cause: unknown) => cause instanceof ApiError && cause.status === 422 && /本机暂时无法校验/.test(cause.message));
});
test('invalid UTF8 and incomplete documents are rejected even with a matching digest', async () => {
  for (const raw of [new Uint8Array([255, 254]), new TextEncoder().encode('<div>not a page</div>')]) {
    const entry = {...metadata, size: raw.length, sha256: await digest(raw)};
    const {api} = harness(call => call.path.endsWith('/art_1') ? Response.json(entry) : new Response(raw.buffer, {headers: {'Content-Type': 'text/html'}}));
    await assert.rejects(api.document('art_1'), /UTF-8|不完整/);
  }
});
test('download refetches the exact immutable version and returns original bytes without preview wrapper', async () => {
  const {api, calls} = harness(); assert.deepEqual(await api.original(metadata), bytes);
  assert.deepEqual(calls.map(call => call.path), ['/api/artifacts/art_1', '/api/artifacts/art_1/download']);
  const changed = harness(() => Response.json({...metadata, revision: 2}));
  await assert.rejects(changed.api.original(metadata), (cause: unknown) => cause instanceof ApiError && cause.status === 409);
  assert.equal(changed.calls.length, 1);
});
test('network interruption is retryable without a background retry or external redirect', async () => {
  let healthy = false;
  const {api, calls} = harness(() => {if (!healthy) throw new Error('offline'); return Response.json(metadata);});
  await assert.rejects(api.metadata('art_1'), /连接中断/); assert.equal(calls.length, 1);
  healthy = true; assert.equal((await api.metadata('art_1')).id, 'art_1'); assert.equal(calls.length, 2);
  await assert.rejects(api.metadata('../secrets'), /不完整/); assert.equal(calls.length, 2);
});
test('preview uses an opaque script-only sandbox, CSP and escaped srcdoc without native credentials', () => {
  const hostile = '<html><body>"/><iframe src="https://escape.example"><script>parent.test=1</script></body></html>';
  const wrapped = artifactPreviewDocument(hostile, palettes.night.surface);
  assert.equal((wrapped.match(/<iframe\b/g) || []).length, 1); assert.ok(wrapped.includes('sandbox="allow-scripts"'));
  assert.ok(!wrapped.includes('allow-same-origin')); assert.ok(!wrapped.includes('Authorization')); assert.ok(!wrapped.includes('ReactNativeWebView'));
  assert.ok(wrapped.includes('&lt;iframe src=&quot;https://escape.example&quot;&gt;'));
  for (const restriction of ["connect-src 'none'", "frame-src 'none'", "form-action 'none'", "default-src 'none'"]) assert.ok(ARTIFACT_CONTENT_CSP.includes(restriction));
  assert.throws(() => artifactPreviewDocument(html, 'red;}</style><script>'), /theme color/);
});
test('navigation never hands external schemes, downloads or top-level srcdoc to the operating system', () => {
  assert.equal(artifactNavigationAllowed('about:blank', true), true); assert.equal(artifactNavigationAllowed('about:srcdoc', false), true);
  for (const url of ['https://example.com', 'http://127.0.0.1:8765/api/files', 'javascript:alert(1)', 'file:///private/key', 'data:text/html,test', 'tel:123', 'pajio://auth', 'about:blank?url=https://example.com']) assert.equal(artifactNavigationAllowed(url, false), false);
  assert.equal(artifactNavigationAllowed('about:srcdoc', true), false); assert.equal(artifactNavigationAllowed('about:srcdoc'), false);
  // RN WebView opens failed origin-whitelist URLs with Linking before invoking
  // a custom callback; all URLs must reach our deny-by-default callback instead.
  const source = readFileSync(new URL('./ArtifactPanel.tsx', import.meta.url), 'utf8');
  assert.match(source, /originWhitelist=\{\['\*'\]\}/); assert.doesNotMatch(source, /onMessage=|injectedJavaScript=|Linking\.openURL/);
});
test('leaving the identity while an artifact downloads prevents the native share handoff', async () => {
  const {api} = harness(); let active = true; const events: string[] = [];
  const ports: WorkspaceExportPorts = {available: async () => true, active: () => active,
    write: () => {events.push('write'); return {uri: 'file:///cache/result.html', remove: () => events.push('remove')};},
    share: async () => {events.push('share');}};
  await exportWorkspaceOriginal({original: async () => {const result = await api.original(metadata); active = false; return result;}}, {path: 'result.html', size: metadata.size, modified: 0}, ports);
  assert.deepEqual(events, []);
});
