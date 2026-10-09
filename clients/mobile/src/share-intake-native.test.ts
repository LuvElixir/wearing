import assert from 'node:assert/strict';
import test from 'node:test';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import vm from 'node:vm';
import crypto from 'node:crypto';
import {fileURLToPath, pathToFileURL} from 'node:url';
import ts from 'typescript';
import * as model from './share-intake-model';

const GROUP = 'group.io.luckyloading.wearing.mobile.share';
const ID = 'aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee';
const nativeSource = fs.readFileSync(path.join(import.meta.dirname, 'share-intake-native.ts'), 'utf8');
function fixture(platform: 'ios' | 'android') {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'pajio-share-adapter-'));
  const documents = path.join(directory, 'documents'), cache = path.join(directory, 'cache'), group = path.join(directory, 'app-group');
  for (const folder of [documents, cache, group]) fs.mkdirSync(folder);
  const data = new Map<string, unknown>();
  const contents = new Map<string, string>();
  let payloads: {value: string; mimeType?: string; shareType: string}[] = [], cleared = 0;
  function normalize(parts: (string | {uri: string})[]) {
    return path.join(...parts.map(p => {const uri = typeof p === 'string' ? p : p.uri; return uri.startsWith('file:') ? fileURLToPath(uri) : contents.get(uri) || uri;}));
  }
  class File {
    file: string;
    constructor(...parts: (string | {uri: string})[]) {this.file = normalize(parts);}
    get uri() {return pathToFileURL(this.file).href;}
    get name() {return path.basename(this.file);}
    get exists() {return fs.existsSync(this.file);}
    get size() {return fs.statSync(this.file).size;}
    async text() {return fs.readFileSync(this.file, 'utf8');}
    create() {fs.writeFileSync(this.file, '');}
    open(mode: string) {
      const fd = fs.openSync(this.file, mode); let position = 0;
      return {readBytes(length: number) {const buffer = Buffer.alloc(length), size = fs.readSync(fd, buffer, 0, length, position); position += size; return buffer.subarray(0, size);}, writeBytes(bytes: Uint8Array) {fs.writeSync(fd, bytes);}, close() {fs.closeSync(fd);}};
    }
  }
  class Directory {
    file: string;
    constructor(...parts: (string | {uri: string})[]) {this.file = normalize(parts);}
    get uri() {return pathToFileURL(this.file).href;}
    get name() {return path.basename(this.file);}
    get exists() {return fs.existsSync(this.file);}
    create() {fs.mkdirSync(this.file, {recursive: true});}
    delete() {fs.rmSync(this.file, {recursive: true});}
    move(destination: Directory) {fs.renameSync(this.file, destination.file); this.file = destination.file;}
    list() {return fs.readdirSync(this.file, {withFileTypes: true}).map(entry => entry.isDirectory() ? new Directory(this, entry.name) : new File(this, entry.name));}
  }
  const load = () => {
    const exports: Record<string, unknown> = {};
    const dependencies: Record<string, unknown> = {
      'expo-file-system': {File, Directory, FileMode: {ReadOnly: 'r', WriteOnly: 'w'}, Paths: {document: new Directory(documents), cache: new Directory(cache), appleSharedContainers: {[GROUP]: new Directory(group)}}},
      'expo-crypto': {CryptoDigestAlgorithm: {SHA256: 'sha256'}, randomUUID: crypto.randomUUID, async digestStringAsync(_: string, value: string) {return crypto.createHash('sha256').update(value).digest('hex');}},
      'expo-sharing': {getSharedPayloads: () => structuredClone(payloads), clearSharedPayloads: () => {cleared++; payloads = [];}, getResolvedSharedPayloadsAsync: () => {throw new Error('network resolution forbidden');}},
      'react-native': {Platform: {OS: platform}},
      './storage': {storage: {async get(key: string) {return structuredClone(data.get(key) ?? null);}, async put(key: string, value: unknown) {data.set(key, structuredClone(value));}}},
      './share-intake-model': model,
    };
    const output = ts.transpileModule(nativeSource, {compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022}}).outputText;
    vm.runInNewContext(output, {exports, require: (name: string) => {if (!(name in dependencies)) throw new Error(name); return dependencies[name];}, setTimeout, URL, console}, {filename: 'share-intake-native.js'});
    return exports as unknown as {receiveSharedIntake(): Promise<void>; shareIntakeQueue: model.ShareIntakeQueue};
  };
  return {directory, documents, group, data, contents, load, get cleared() {return cleared;}, set payloads(value: typeof payloads) {payloads = value;}, get payloads() {return payloads;}, cleanup() {fs.rmSync(directory, {recursive: true, force: true});}};
}

test('iOS synthetic share is copied privately before app-group consumption and survives restart', async () => {
  const f = fixture('ios');
  try {
    const folder = path.join(f.group, 'pajio-share-inbox', ID); fs.mkdirSync(folder, {recursive: true});
    fs.writeFileSync(path.join(folder, '0.pdf'), '%PDF-1.7 synthetic');
    fs.writeFileSync(path.join(folder, 'manifest.json'), JSON.stringify({version: 1, id: ID, createdAt: new Date().toISOString(), text: '看看这份文件', files: [{path: '0.pdf', name: '测试.pdf', mime: 'application/pdf', size: 18}]}));
    const app = f.load(); await app.receiveSharedIntake();
    assert(!fs.existsSync(folder));
    assert.equal(fs.readFileSync(path.join(f.documents, 'share-intake', ID, '0.pdf'), 'utf8'), '%PDF-1.7 synthetic');
    const records = await f.load().shareIntakeQueue.list('A'); assert.equal(records.length, 1); assert.equal(records[0].state, 'pending');
    assert.equal(records[0].files[0].size, 18);
    await app.shareIntakeQueue.cancel(ID);
    assert(!fs.existsSync(path.join(f.documents, 'share-intake', ID)));
  } finally {f.cleanup();}
});

test('iOS truncated file or traversal manifest never consumes original inbox or indexes success', async () => {
  const f = fixture('ios');
  try {
    const folder = path.join(f.group, 'pajio-share-inbox', ID); fs.mkdirSync(folder, {recursive: true});
    fs.writeFileSync(path.join(folder, '0.pdf'), 'short');
    const manifest = {version: 1, id: ID, createdAt: new Date().toISOString(), text: '', files: [{path: '0.pdf', name: 'test.pdf', mime: 'application/pdf', size: 100}]};
    fs.writeFileSync(path.join(folder, 'manifest.json'), JSON.stringify(manifest));
    const app = f.load(); await assert.rejects(app.receiveSharedIntake()); assert(fs.existsSync(folder));
    assert.equal((await app.shareIntakeQueue.list('A')).length, 0);
    manifest.files[0].path = '../secret.pdf'; fs.writeFileSync(path.join(folder, 'manifest.json'), JSON.stringify(manifest));
    await assert.rejects(app.receiveSharedIntake()); assert(fs.existsSync(folder));
  } finally {f.cleanup();}
});

test('Android grants are copied as bounded files, clear after persistence, and keep a stable restart id', async () => {
  const f = fixture('android');
  try {
    const source = path.join(f.directory, 'provider.pdf'); fs.writeFileSync(source, '%PDF-synthetic');
    f.contents.set('content://provider/document/1', source);
    f.payloads = [{value: 'content://provider/document/1', mimeType: 'application/pdf', shareType: 'file'}];
    const app = f.load(); await app.receiveSharedIntake();
    const entries = await app.shareIntakeQueue.list('A'); assert.equal(entries.length, 1); assert.equal(f.cleared, 1);
    assert.equal(fs.readFileSync(fileURLToPath(entries[0].files[0].uri), 'utf8'), '%PDF-synthetic');
    assert.equal((await f.load().shareIntakeQueue.list('A'))[0].id, entries[0].id);
    assert(fs.existsSync(source));
  } finally {f.cleanup();}
});

test('Android saved-before-clear recovery never requires expired provider grant', async () => {
  const f = fixture('android');
  try {
    const source = path.join(f.directory, 'provider.pdf'); fs.writeFileSync(source, 'pdf'); f.contents.set('content://test/file', source);
    const original = [{value: 'content://test/file', mimeType: 'application/pdf', shareType: 'file'}]; f.payloads = original;
    await f.load().receiveSharedIntake();
    const journal = f.data.get('share-intake:android-journal:v1') as {cleared: boolean}; journal.cleared = false;
    f.payloads = original; fs.unlinkSync(source);
    await f.load().receiveSharedIntake();
    assert.equal(f.cleared, 2); assert.equal((await f.load().shareIntakeQueue.list('A')).length, 1);
  } finally {f.cleanup();}
});

test('Android rejects private file paths, unsupported MIME and credentials URLs without clearing source', async () => {
  const f = fixture('android');
  try {
    const app = f.load();
    for (const payload of [{value: 'file:///private/auth.db', mimeType: 'application/pdf', shareType: 'file'}, {value: 'content://test/app', mimeType: 'application/x-executable', shareType: 'file'}, {value: 'https://key:secret@example.com', shareType: 'url'}]) {
      f.payloads = [payload]; await assert.rejects(app.receiveSharedIntake());
    }
    assert.equal(f.cleared, 0); assert.equal((await app.shareIntakeQueue.list('A')).length, 0);
  } finally {f.cleanup();}
});

test('Android same text shared again after successful clear is a new deliberate request; no URL resolution', async () => {
  const f = fixture('android');
  try {
    const app = f.load(), payload = [{value: 'https://example.com/share', shareType: 'url'}];
    f.payloads = payload; await app.receiveSharedIntake();
    f.payloads = payload; await app.receiveSharedIntake();
    const entries = await app.shareIntakeQueue.list('A'); assert.equal(entries.length, 2); assert.notEqual(entries[0].id, entries[1].id); assert.equal(f.cleared, 2);
  } finally {f.cleanup();}
});

test('Android SDK text-type content URI is imported as a file, never exposed as draft text', async () => {
  const f = fixture('android');
  try {
    const source = path.join(f.directory, 'provider.md'); fs.writeFileSync(source, '# synthetic'); f.contents.set('content://test/markdown', source);
    f.payloads = [{value: 'content://test/markdown', shareType: 'text', mimeType: 'text/markdown'}];
    const app = f.load(); await app.receiveSharedIntake();
    const entries = await app.shareIntakeQueue.list('A'); assert.equal(entries[0].text, ''); assert.equal(entries[0].files[0].mime, 'text/markdown');
  } finally {f.cleanup();}
});

test('Android synthetic ZIP remains private and is classified for chat preview', async () => {
  const f = fixture('android');
  try {
    const source = path.join(f.directory, 'provider.zip'); fs.writeFileSync(source, 'PK-synthetic'); f.contents.set('content://test/chat', source);
    f.payloads = [{value:'content://test/chat',mimeType:'application/zip',shareType:'file'}];
    const app = f.load(); await app.receiveSharedIntake();
    const entries = await app.shareIntakeQueue.list('A'); assert.equal(entries.length, 1); assert.equal(entries[0].files[0].path, '0.zip');
    let called = false; await assert.rejects(app.shareIntakeQueue.submit(entries[0].id, 'A', 'capture', async r => {called = true; return r;})); assert.equal(called, false);
  } finally {f.cleanup();}
});
