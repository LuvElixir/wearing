import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {test} from 'node:test';
import {runInNewContext} from 'node:vm';
import * as ts from 'typescript';
import {activityScope} from './activity-store';
import type {Connection} from './core';

// Execute the real hook's connection projection with native/React boundaries replaced.
test('activity hook carries the authenticated session into subscribe, read and refresh', () => {
  const source = ts.createSourceFile('use-activity-snapshot.ts', readFileSync(new URL('./use-activity-snapshot.ts', import.meta.url), 'utf8'), ts.ScriptTarget.Latest, true);
  const hook = source.statements.find(node => ts.isFunctionDeclaration(node) && node.name?.text === 'useActivitySnapshot') as ts.FunctionDeclaration;
  const text = ts.createPrinter().printNode(ts.EmitHint.Unspecified, hook, source).replace('export function', 'function');
  const code = ts.transpileModule(text, {compilerOptions: {target: ts.ScriptTarget.ES2022}}).outputText;
  const observed: Connection[] = [];
  const context = {
    activityScope, isForeground: () => true, attachLifecycle: () => {},
    useEffect: () => {}, useMemo: (fn: () => unknown) => fn(), useCallback: (fn: unknown) => fn,
    useSyncExternalStore: (subscribe: (fn: () => void) => unknown, read: () => unknown) => {subscribe(() => {}); return read();},
    activityStore: {setForeground: () => {}, subscribe: (c: Connection) => {observed.push(c); return () => {};},
      getSnapshot: (c: Connection) => {observed.push(c); return {snapshot: null};}, refresh: (c: Connection) => {observed.push(c);}},
  };
  runInNewContext(code, context);
  const hookFn = (context as typeof context & {useActivitySnapshot: (c: Connection) => {refresh: () => void}}).useActivitySnapshot;
  const connection: Connection = {endpoint: 'https://pajio.example', identity: 'daily', session: {
    userId: 'user_' + 'a'.repeat(32), tenantId: 'tenant-a', credentialId: 'b'.repeat(32),
    accessToken: 'c'.repeat(64), expiresAt: '2099-01-01T00:00:00Z'}};
  const result = hookFn(connection); result.refresh();
  assert.equal(observed.length, 3);
  for (const scoped of observed) {
    assert.equal(scoped.session?.accessToken, connection.session?.accessToken);
    assert.equal(scoped.session?.tenantId, 'tenant-a');
    assert.notEqual(scoped, connection); assert.notEqual(scoped.session, connection.session);
  }
  connection.session!.accessToken = 'mutated';
  assert.equal(observed[0].session?.accessToken, 'c'.repeat(64));
});
