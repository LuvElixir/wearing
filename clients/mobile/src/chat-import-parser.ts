import {Inflate, strFromU8} from 'fflate';

// Parser evidence: WeChatBridge 0b00e3f / WeChatForward.swift. The format is
// undocumented by Tencent. Unknown formats fail closed instead of inventing roles.
export const CHAT_IMPORT_LIMITS = {fileBytes: 15 * 1024 * 1024, textBytes: 384 * 1024, expandedBytes: 30 * 1024 * 1024, entries: 500, messages: 500, authors: 50, messageBytes: 16 * 1024, ratio: 200} as const;
export type ChatAttachment = {name: string; media_type: string | null; size_bytes: number | null; sha256: string | null};
export type ChatImportMessage = {id: string; author: string; sent_at: string | null; text: string; attachments: ChatAttachment[]};
export type ChatImportPreview = {title: string; authors: string[]; messages: ChatImportMessage[]; attachments: ChatAttachment[]; textPath: string; start: string; end: string};
const fail = (message = '这份聊天文件的格式暂不支持，或内容不完整。请重新导出选定聊天。'): never => {throw new Error(message);};
const yieldUI = () => new Promise<void>(resolve => setTimeout(resolve, 0));
export const utf8Size = (text: string) => new TextEncoder().encode(text).length;

export function strictUTF8(bytes: Uint8Array): string {
  // Check before decoding: never silently replace invalid bytes (GBK/UTF-16 etc).
  for (let i = 0; i < bytes.length;) {
    const a = bytes[i++]; if (a < 0x80) continue;
    let count = a >= 0xc2 && a <= 0xdf ? 1 : a >= 0xe0 && a <= 0xef ? 2 : a >= 0xf0 && a <= 0xf4 ? 3 : -1;
    if (count < 0 || i + count > bytes.length) fail('聊天文字须为 UTF-8 编码，请重新导出；不会尝试乱码导入。');
    const b = bytes[i];
    if (a === 0xe0 && b < 0xa0 || a === 0xed && b >= 0xa0 || a === 0xf0 && b < 0x90 || a === 0xf4 && b >= 0x90) fail('聊天文字包含无效编码。');
    while (count--) if ((bytes[i++] & 0xc0) !== 0x80) fail('聊天文字包含无效编码。');
  }
  return strFromU8(bytes);
}
function validDate(text: string) {
  const m = /^(\d{4})年(\d{1,2})月(\d{1,2})日 (\d{2}):(\d{2})$/.exec(text); if (!m) return false;
  const [year, month, day, hour, minute] = m.slice(1).map(Number), date = new Date(Date.UTC(year, month - 1, day, hour, minute));
  return year >= 1900 && year <= 9999 && date.getUTCFullYear() === year && date.getUTCMonth() === month - 1 && date.getUTCDate() === day && hour < 24 && minute < 60;
}
export function parseChatText(bytes: Uint8Array, name = '聊天记录.txt'): ChatImportPreview {
  if (!bytes.length || bytes.length > CHAT_IMPORT_LIMITS.textBytes) fail('聊天文字最多 384 KB，请减少所选消息后再导出。');
  const text = strictUTF8(bytes).replace(/^\uFEFF/, '').replace(/\r\n/g, '\n');
  if (/[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/.test(text)) fail('聊天文字包含不能识别的控制字符。');
  const header = /^·([^\n]+)\n(\d{4}年\d{1,2}月\d{1,2}日 \d{2}:\d{2})\n/gm;
  const matches = [...text.matchAll(header)];
  if (!matches.length || matches[0].index !== 0) fail('未识别到微信选定聊天格式。请使用带作者和时间的 TXT 或原始 ZIP。');
  if (matches.length > CHAT_IMPORT_LIMITS.messages) fail('一次最多导入 500 条消息，请分批选择。');
  const authors: string[] = [];
  const messages = matches.map((match, i): ChatImportMessage => {
    const author = match[1].trim(), sent_at = match[2], body = text.slice(match.index! + match[0].length, matches[i + 1]?.index ?? text.length).trim();
    if (!author || author.length > 80 || !validDate(sent_at)) fail('部分消息的作者或时间无法核对，请重新导出。');
    if (!authors.includes(author)) authors.push(author);
    if (authors.length > CHAT_IMPORT_LIMITS.authors) fail('一次最多保留 50 位聊天作者，请缩小聊天范围。');
    if (utf8Size(body) > CHAT_IMPORT_LIMITS.messageBytes) fail('有一条消息超过 16 KB，请减少或拆分后再导入。');
    return {id: `message-${i + 1}`, author, sent_at, text: body, attachments: []};
  });
  const sorted = messages.map(message => message.sent_at!).sort((a, b) => {
    const key = (value: string) => value.replace(/\d+/g, n => n.padStart(4, '0')); return key(a).localeCompare(key(b));
  });
  const title = name.split('/').at(-1)!.replace(/\.txt$/i, '').normalize('NFC').slice(0, 160) || '选定微信聊天';
  return {title, authors, messages, attachments: [], textPath: name, start: sorted[0], end: sorted.at(-1)!};
}

type Entry = {name: string; compressed: number; expanded: number; method: number; crc: number; start: number; end: number; directory: boolean};
function zipEntries(bytes: Uint8Array): Entry[] {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const number = (at: number, length: 2 | 4) => {if (at < 0 || at + length > bytes.length) fail(); return length === 2 ? view.getUint16(at, true) : view.getUint32(at, true);};
  let end = -1;
  for (let at = bytes.length - 22; at >= Math.max(0, bytes.length - 65557); at--) if (number(at, 4) === 0x06054b50 && at + 22 + number(at + 20, 2) === bytes.length) {end = at; break;}
  if (end < 0 || number(end + 4, 2) || number(end + 6, 2)) fail();
  const count = number(end + 10, 2), directorySize = number(end + 12, 4), directoryStart = number(end + 16, 4);
  if (!count || count > CHAT_IMPORT_LIMITS.entries || count !== number(end + 8, 2) || directoryStart + directorySize !== end) fail('ZIP 文件目录不受支持，或文件数量超过 500。');
  const seen = new Set<string>(), aliases = new Map<string, string>(), entries: Entry[] = []; let cursor = directoryStart, expandedTotal = 0;
  for (let i = 0; i < count; i++) {
    if (number(cursor, 4) !== 0x02014b50) fail();
    const flags = number(cursor + 8, 2), method = number(cursor + 10, 2), compressed = number(cursor + 20, 4), expanded = number(cursor + 24, 4), length = number(cursor + 28, 2), extra = number(cursor + 30, 2), comment = number(cursor + 32, 2), offset = number(cursor + 42, 4);
    if (flags & ~0x080e || flags & 1 || ![0, 8].includes(method) || number(cursor + 34, 2) || cursor + 46 + length + extra + comment > end || offset >= directoryStart || [compressed, expanded, offset].includes(0xffffffff)) fail('暂不支持加密、ZIP64 或特殊压缩格式。');
    const name = strictUTF8(bytes.subarray(cursor + 46, cursor + 46 + length)), directory = name.endsWith('/'), path = directory ? name.slice(0, -1) : name, parts = path.split('/');
    const kind = (number(cursor + 38, 4) >>> 16) & 0o170000;
    if (!path || name.length > 255 || /[\\:\x00-\x1f\x7f]/.test(name) || parts.some(part => !part || part === '.' || part === '..') || kind && kind !== (directory ? 0o040000 : 0o100000) || /\.(zip|rar|7z|gz|tar)$/i.test(path)) fail('ZIP 包含不安全路径、链接或嵌套压缩文件，已停止读取。');
    const key = path.normalize('NFC').toLowerCase(); if (seen.has(key)) fail('ZIP 包含重复文件名，已停止读取。'); seen.add(key);
    for (let n = 1; n <= parts.length; n++) {const prefix = parts.slice(0, n).join('/'), alias = prefix.normalize('NFC').toLowerCase(); if (aliases.has(alias) && aliases.get(alias) !== prefix) fail('ZIP 文件路径存在重名。'); aliases.set(alias, prefix);}
    expandedTotal += expanded;
    if (expandedTotal > CHAT_IMPORT_LIMITS.expandedBytes || expanded > CHAT_IMPORT_LIMITS.expandedBytes || expanded > Math.max(1024 * 1024, compressed * CHAT_IMPORT_LIMITS.ratio) || directory && expanded !== 0) fail('ZIP 解压规模异常，或展开后超过 30 MB，请缩小聊天范围。');
    if (number(offset, 4) !== 0x04034b50 || number(offset + 6, 2) !== flags || number(offset + 8, 2) !== method) fail();
    const localLength = number(offset + 26, 2), localExtra = number(offset + 28, 2), start = offset + 30 + localLength + localExtra;
    if (strictUTF8(bytes.subarray(offset + 30, offset + 30 + localLength)) !== name || start + compressed > directoryStart || entries.some(entry => offset < entry.end && start + compressed > entry.start) || method === 0 && compressed !== expanded) fail();
    entries.push({name, method, compressed, expanded, crc: number(cursor + 16, 4), start, end: start + compressed, directory});
    cursor += 46 + length + extra + comment;
  }
  if (cursor !== end) fail(); return entries;
}
const crcTable = Array.from({length: 256}, (_, i) => {let c = i; for (let n = 0; n < 8; n++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; return c >>> 0;});
async function readEntry(bytes: Uint8Array, entry: Entry, active: () => boolean): Promise<Uint8Array> {
  if (!entry.expanded || entry.expanded > CHAT_IMPORT_LIMITS.textBytes) fail('聊天文字最多 384 KB，请减少所选消息后再导出。');
  const output = new Uint8Array(entry.expanded); let written = 0, crc = 0xffffffff;
  const accept = (chunk: Uint8Array) => {if (written + chunk.length > output.length) fail('ZIP 实际展开大小不符合目录，已停止读取。'); output.set(chunk, written); written += chunk.length; for (const byte of chunk) crc = crcTable[(crc ^ byte) & 255] ^ (crc >>> 8);};
  const inflater = entry.method === 8 ? new Inflate(accept) : null;
  // Small compressed chunks cap a malicious stream's transient expansion;
  // yielding keeps the native UI responsive without requiring Web Workers.
  for (let at = entry.start; at < entry.end; at += 1024) {
    if (!active()) fail('已停止读取这份聊天。');
    const chunk = bytes.subarray(at, Math.min(at + 1024, entry.end));
    if (inflater) inflater.push(chunk, at + chunk.length === entry.end); else accept(chunk);
    await yieldUI();
  }
  if (written !== entry.expanded || ((crc ^ 0xffffffff) >>> 0) !== entry.crc) fail('聊天文件校验不通过，请重新导出。');
  return output;
}
export async function parseChatImport(bytes: Uint8Array, name: string, active: () => boolean = () => true): Promise<ChatImportPreview> {
  if (!active()) fail('读取已停止。');
  if (!bytes.length || bytes.length > CHAT_IMPORT_LIMITS.fileBytes) fail('请选择非空且不超过 15 MB 的聊天文件。');
  if (/\.txt$/i.test(name)) {await yieldUI(); if (!active()) fail('读取已停止。'); return parseChatText(bytes, name);}
  if (!/\.zip$/i.test(name)) fail('请选择微信选定聊天的 ZIP 或 UTF-8 TXT 文件。');
  const entries = zipEntries(bytes), texts = entries.filter(entry => !entry.directory && /\.txt$/i.test(entry.name));
  const native = texts.filter(entry => entry.name.split('/').at(-1) === '聊天记录.txt');
  const selected = native.length === 1 ? native[0] : native.length === 0 && texts.length === 1 ? texts[0] : null;
  if (!selected) throw new Error('ZIP 中没有唯一的聊天记录 TXT，暂时不能确认哪份是原始会话。');
  const preview = parseChatText(await readEntry(bytes, selected, active), selected.name);
  // Attachments are declared, never extracted, sent as bytes or presented as read.
  preview.attachments = entries.filter(entry => !entry.directory && entry !== selected).map(entry => ({name: entry.name, media_type: null, size_bytes: entry.expanded, sha256: null}));
  return preview;
}
