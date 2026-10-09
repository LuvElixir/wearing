"use strict";
/* Pajio 选定聊天导入（Web/桌面）：文件选择 → 本机预览 → 确认 → 幂等回执 → 批次详情 → 删除。
   对齐 clients/mobile/src/chat-import-parser.ts / chat-import-client.ts / ChatImportPanel.tsx 与
   src/wearing/chat_imports{,_api}.py（只读参考，未改动）：
   - 只支持 ZIP / UTF-8 TXT；先本地解析预览，预览阶段零网络请求；原始 ZIP、图片与语音不上传，
     附件仅声明未导入、不猜归属；聊天文字只是来源，不构成操作授权。
   - 严格解析：UTF-8（含 BOM）/LF/CRLF；非法编码、未知格式、无效日期、路径穿越、嵌套压缩、
     重名/别名、加密、ZIP64、越界区块一律拒绝；CRC 核对；1 KiB 块间让出线程。
   - 上限：文件 15 MiB、聊天 TXT 384 KiB、单消息 16 KiB、500 条消息、50 位作者、500 项 ZIP、
     展开总量 30 MiB、压缩倍率 200、结构化请求 512 KiB。
   - 幂等：pending journal（WearingStore，按账户+身份隔离）先持久完整请求再 POST；
     重试先 GET /api/chat-imports/receipts/{key}，404 才补交原请求；回执严格校验；
     deleted 回执不重发恢复。
   - 生命周期：epoch+generation 双围栏（会话围栏 vs 操作票据，吸取 onboarding v6 教训）、
     注销冻结 workAllowed/registerWorkGate 不写不清不 POST、身份切换 reset；未确认草稿留存范围
     仅本机 WearingStore，注销清理含 chat-import 两键（account-deletion）。
   - 私密远控未开放：本面板不提供任何远控入口。 */
(() => {
  if (document.documentElement.classList.contains("mobile-host")) return;
  const $ = id => document.getElementById(id);
  const esc = text => String(text ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));

  /* ---------- 严格解析器（移植 chat-import-parser.ts；格式证据 WeChatBridge 0b00e3f） ---------- */
  const LIMITS = {fileBytes: 15*1024*1024, textBytes: 384*1024, expandedBytes: 30*1024*1024, entries: 500, messages: 500, authors: 50, messageBytes: 16*1024, ratio: 200};
  const fail = (message = "这份聊天文件的格式暂不支持，或内容不完整。请重新导出选定聊天。") => {throw Object.assign(new Error(message), {operational: true});};
  const yieldUI = () => new Promise(resolve => setTimeout(resolve, 0));
  const utf8Size = text => new TextEncoder().encode(text).length;
  function strictUTF8(bytes) {
    for (let i = 0; i < bytes.length;) {
      const a = bytes[i++];
      if (a < 0x80) continue;
      let count = a >= 0xc2 && a <= 0xdf ? 1 : a >= 0xe0 && a <= 0xef ? 2 : a >= 0xf0 && a <= 0xf4 ? 3 : -1;
      if (count < 0 || i + count > bytes.length) fail("聊天文字须为 UTF-8 编码，请重新导出；不会尝试乱码导入。");
      const b = bytes[i];
      if (a === 0xe0 && b < 0xa0 || a === 0xed && b >= 0xa0 || a === 0xf0 && b < 0x90 || a === 0xf4 && b >= 0x90) fail("聊天文字包含无效编码。");
      while (count--) if ((bytes[i++] & 0xc0) !== 0x80) fail("聊天文字包含无效编码。");
    }
    return new TextDecoder("utf-8").decode(bytes);
  }
  function validDate(text) {
    const m = /^(\d{4})年(\d{1,2})月(\d{1,2})日 (\d{2}):(\d{2})$/.exec(text); if (!m) return false;
    const [year, month, day, hour, minute] = m.slice(1).map(Number), date = new Date(Date.UTC(year, month-1, day, hour, minute));
    return year >= 1900 && year <= 9999 && date.getUTCFullYear() === year && date.getUTCMonth() === month-1 && date.getUTCDate() === day && hour < 24 && minute < 60;
  }
  function parseChatText(bytes, name = "聊天记录.txt") {
    if (!bytes.length || bytes.length > LIMITS.textBytes) fail("聊天文字最多 384 KB，请减少所选消息后再导出。");
    const text = strictUTF8(bytes).replace(/^\uFEFF/, "").replace(/\r\n/g, "\n");
    if (/[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/.test(text)) fail("聊天文字包含不能识别的控制字符。");
    const header = /^·([^\n]+)\n(\d{4}年\d{1,2}月\d{1,2}日 \d{2}:\d{2})\n/gm;
    const matches = [...text.matchAll(header)];
    if (!matches.length || matches[0].index !== 0) fail("未识别到微信选定聊天格式。请使用带作者和时间的 TXT 或原始 ZIP。");
    if (matches.length > LIMITS.messages) fail("一次最多导入 500 条消息，请分批选择。");
    const authors = [];
    const messages = matches.map((match, i) => {
      const author = match[1].trim(), sentAt = match[2], body = text.slice(match.index + match[0].length, matches[i+1] ? matches[i+1].index : text.length).trim();
      if (!author || author.length > 80 || !validDate(sentAt)) fail("部分消息的作者或时间无法核对，请重新导出。");
      if (!authors.includes(author)) authors.push(author);
      if (authors.length > LIMITS.authors) fail("一次最多保留 50 位聊天作者，请缩小聊天范围。");
      if (utf8Size(body) > LIMITS.messageBytes) fail("有一条消息超过 16 KB，请减少或拆分后再导入。");
      return {id: `message-${i+1}`, author, sent_at: sentAt, text: body, attachments: []};
    });
    const sorted = messages.map(message => message.sent_at).sort((a, b) => {
      const key = value => value.replace(/\d+/g, n => n.padStart(4, "0")); return key(a).localeCompare(key(b));
    });
    const title = (name.split("/").at(-1) || "").replace(/\.txt$/i, "").normalize("NFC").slice(0, 160) || "选定微信聊天";
    return {title, authors, messages, attachments: [], textPath: name, start: sorted[0], end: sorted[sorted.length-1]};
  }
  function zipEntries(bytes) {
    const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    const number = (at, length) => {if (at < 0 || at + length > bytes.length) fail(); return length === 2 ? view.getUint16(at, true) : view.getUint32(at, true);};
    let end = -1;
    for (let at = bytes.length - 22; at >= Math.max(0, bytes.length - 65557); at--) if (number(at, 4) === 0x06054b50 && at + 22 + number(at + 20, 2) === bytes.length) {end = at; break;}
    if (end < 0 || number(end + 4, 2) || number(end + 6, 2)) fail();
    const count = number(end + 10, 2), directorySize = number(end + 12, 4), directoryStart = number(end + 16, 4);
    if (!count || count > LIMITS.entries || count !== number(end + 8, 2) || directoryStart + directorySize !== end) fail("ZIP 文件目录不受支持，或文件数量超过 500。");
    const seen = new Set(), aliases = new Map(), entries = []; let cursor = directoryStart, expandedTotal = 0;
    for (let i = 0; i < count; i++) {
      if (number(cursor, 4) !== 0x02014b50) fail();
      const flags = number(cursor + 8, 2), method = number(cursor + 10, 2), compressed = number(cursor + 20, 4), expanded = number(cursor + 24, 4), length = number(cursor + 28, 2), extra = number(cursor + 30, 2), comment = number(cursor + 32, 2), offset = number(cursor + 42, 4);
      if (flags & ~0x080e || flags & 1 || ![0, 8].includes(method) || number(cursor + 34, 2) || cursor + 46 + length + extra + comment > end || offset >= directoryStart || [compressed, expanded, offset].includes(0xffffffff)) fail("暂不支持加密、ZIP64 或特殊压缩格式。");
      const name = strictUTF8(bytes.subarray(cursor + 46, cursor + 46 + length)), directory = name.endsWith("/"), path = directory ? name.slice(0, -1) : name, parts = path.split("/");
      const kind = (number(cursor + 38, 4) >>> 16) & 0o170000;
      if (!path || name.length > 255 || /[\\:\x00-\x1f\x7f]/.test(name) || parts.some(part => !part || part === "." || part === "..") || kind && kind !== (directory ? 0o040000 : 0o100000) || /\.(zip|rar|7z|gz|tar)$/i.test(path)) fail("ZIP 包含不安全路径、链接或嵌套压缩文件，已停止读取。");
      const key = path.normalize("NFC").toLowerCase(); if (seen.has(key)) fail("ZIP 包含重复文件名，已停止读取。"); seen.add(key);
      for (let n = 1; n <= parts.length; n++) {const prefix = parts.slice(0, n).join("/"), alias = prefix.normalize("NFC").toLowerCase(); if (aliases.has(alias) && aliases.get(alias) !== prefix) fail("ZIP 文件路径存在重名。"); aliases.set(alias, prefix);}
      expandedTotal += expanded;
      if (expandedTotal > LIMITS.expandedBytes || expanded > LIMITS.expandedBytes || expanded > Math.max(1024*1024, compressed * LIMITS.ratio) || directory && expanded !== 0) fail("ZIP 解压规模异常，或展开后超过 30 MB，请缩小聊天范围。");
      if (number(offset, 4) !== 0x04034b50 || number(offset + 6, 2) !== flags || number(offset + 8, 2) !== method) fail();
      const localLength = number(offset + 26, 2), localExtra = number(offset + 28, 2), start = offset + 30 + localLength + localExtra;
      if (strictUTF8(bytes.subarray(offset + 30, offset + 30 + localLength)) !== name || start + compressed > directoryStart || entries.some(entry => offset < entry.end && start + compressed > entry.start) || method === 0 && compressed !== expanded) fail();
      entries.push({name, method, compressed, expanded, crc: number(cursor + 16, 4), start, end: start + compressed, directory});
      cursor += 46 + length + extra + comment;
    }
    if (cursor !== end) fail(); return entries;
  }
  const crcTable = Array.from({length: 256}, (_, i) => {let c = i; for (let n = 0; n < 8; n++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; return c >>> 0;});
  async function readEntry(bytes, entry, active) {
    if (!entry.expanded || entry.expanded > LIMITS.textBytes) fail("聊天文字最多 384 KB，请减少所选消息后再导出。");
    const output = new Uint8Array(entry.expanded); let written = 0, crc = 0xffffffff;
    const accept = chunk => {if (written + chunk.length > output.length) fail("ZIP 实际展开大小不符合目录，已停止读取。"); output.set(chunk, written); written += chunk.length; for (const byte of chunk) crc = crcTable[(crc ^ byte) & 255] ^ (crc >>> 8);};
    const Inflate = window.fflate && window.fflate.Inflate;
    const inflater = entry.method === 8 ? (Inflate ? new Inflate(accept) : null) : null;
    if (entry.method === 8 && !inflater) fail("本机 ZIP 解码组件未加载，请刷新页面后重试。");
    for (let at = entry.start; at < entry.end; at += 1024) {
      if (!active()) fail("已停止读取这份聊天。");
      const chunk = bytes.subarray(at, Math.min(at + 1024, entry.end));
      if (inflater) inflater.push(chunk, at + chunk.length === entry.end); else accept(chunk);
      await yieldUI();
    }
    if (!active()) fail("读取已停止。");
    if (written !== entry.expanded || ((crc ^ 0xffffffff) >>> 0) !== entry.crc) fail("聊天文件校验不通过，请重新导出。");
    return output;
  }
  async function parseChatImport(bytes, name, active = () => true) {
    if (!active()) fail("读取已停止。");
    if (!bytes.length || bytes.length > LIMITS.fileBytes) fail("请选择非空且不超过 15 MB 的聊天文件。");
    if (/\.txt$/i.test(name)) {await yieldUI(); if (!active()) fail("读取已停止。"); return parseChatText(bytes, name);}
    if (!/\.zip$/i.test(name)) fail("请选择微信选定聊天的 ZIP 或 UTF-8 TXT 文件。");
    const entries = zipEntries(bytes), texts = entries.filter(entry => !entry.directory && /\.txt$/i.test(entry.name));
    const native = texts.filter(entry => entry.name.split("/").at(-1) === "聊天记录.txt");
    const selected = native.length === 1 ? native[0] : native.length === 0 && texts.length === 1 ? texts[0] : null;
    if (!selected) throw Object.assign(new Error("ZIP 中没有唯一的聊天记录 TXT，暂时不能确认哪份是原始会话。"), {operational: true});
    const preview = parseChatText(await readEntry(bytes, selected, active), selected.name);
    // 附件只声明、不解压、不上传、不猜归属。
    preview.attachments = entries.filter(entry => !entry.directory && entry !== selected).map(entry => ({name: entry.name, media_type: null, size_bytes: entry.expanded, sha256: null}));
    return preview;
  }

  /* ---------- 请求构造与回执校验（移植 chat-import-client.ts） ---------- */
  const KEY = /^[A-Za-z0-9_-]{16,120}$/, HASH = /^[a-f0-9]{64}$/;
  const emptyValues = () => ({});
  function makeRequest(draft) {
    const p = draft.preview;
    if (!KEY.test(draft.key) || !HASH.test(draft.sourceHash) || !p.title.trim() || p.title.length > 160
      || p.authors.length < 1 || p.authors.length > 50 || p.messages.length < 1 || p.messages.length > 500
      || draft.selfAuthor !== null && !p.authors.includes(draft.selfAuthor))
      throw Object.assign(new Error("聊天预览尚不完整，请重新选择文件。"), {operational: true});
    const body = {request_key: draft.key, platform: "wechat", conversation_title: p.title, authors: p.authors,
      self_author: draft.selfAuthor, source_sha256: draft.sourceHash, messages: p.messages, confirmed: true};
    if (utf8Size(JSON.stringify(body)) > 512 * 1024) throw Object.assign(new Error("这批聊天整理后超过 512 KB，请减少所选消息。"), {operational: true});
    return body;
  }
  function verifyReceipt(raw, key) {
    const r = raw;
    if (!r || r.schema !== 1 || r.identity_id !== state.identityId || r.request_key !== key || typeof r.import_id !== "string"
      || !/^[A-Za-z0-9_-]{1,120}$/.test(r.import_id) || !["imported", "deleted"].includes(r.status) || typeof r.created_at !== "string")
      throw Object.assign(new Error("导入回执尚未核对，请重试同一次导入。"), {operational: true});
    return r;
  }
  const statusMessage = (status, method) => status === 409 ? (method === "DELETE"
    ? "Pajio 正在处理任务，请先停止或等任务结束，再移除这批聊天。"
    : "这次导入的内容与原请求不一致，请先核对已导入批次。")
    : status === 404 ? "这台服务暂未找到对应聊天导入。"
    : status === 413 ? "聊天超出当前导入限制，可减少所选消息或移除旧批次后重试。"
    : status === 422 ? "聊天文件未通过导入检查，请减少选定范围后重试。"
    : status === 415 ? "请先在设备上预览聊天资料，再提交确认后的文本。"
    : "聊天导入暂时无法完成，请重试。";
  const asError = (error, method) => {if (error && error.status) {error.message = error.message || statusMessage(error.status, method); return error;} return error;};

  /* ---------- 注销冻结门与围栏（会话围栏 vs 操作票据） ---------- */
  const deletionBlocked = () => window.WearingDeletion?.workAllowed?.() === false;
  const DELETION_NOTICE = "这个账户的注销申请已受理，聊天导入操作已停止。";

  /* ---------- 作用域 journal（WearingStore；预览正文在确认前不出本机） ---------- */
  const draftKey = () => `chat-import-draft:v1:${state.identityId}`;
  const pendingKey = () => `chat-import-pending:v1:${state.identityId}`;
  const readJournal = name => {try {const row = JSON.parse(window.WearingStore.get(name) || "null"); return row && row.identity === state.identityId ? row : null;} catch {return null;}};
  function writeJournal(name, row) {
    try {
      if (row === null) {
        // 删除成功的必要条件是 remove 显式成功（返回 true）；localStorage 整体被拒时
        // remove 抛错返回 false、get 也吞异常返回 null——只看读回会误报已移除（P2 边界修复）。
        const removed = window.WearingStore.remove(name) === true;
        const readback = window.WearingStore.get(name);
        return removed && (readback === null || readback === undefined);
      }
      return window.WearingStore.set(name, JSON.stringify(row)) === true;
    } catch {return false;}
  }

  const ui = {epoch: -1, generation: 0, loadTicket: 0, opTicket: 0, open: false, busy: false, error: "", notice: "", listError: "",
    draft: null, pending: null, ready: false, batches: [], cursor: null, deleting: null, selectedBatch: null, batchDetail: null, messageLimit: 20, detailLimit: 20, missing: false};
  window.WearingDeletion?.registerWorkGate?.({stop() {ui.generation++; ui.busy = false;}});

  const active = () => state.identityEpoch === ui.epoch;

  async function load() {
    const epoch = state.identityEpoch, generation = ui.generation, ticket = ++ui.loadTicket;
    const current = () => epoch === state.identityEpoch && generation === ui.generation && ticket === ui.loadTicket;
    ui.epoch = epoch; ui.ready = false;
    const draftRow = readJournal(draftKey()), pendingRow = readJournal(pendingKey());
    ui.draft = draftRow ? draftRow.draft : null;
    ui.pending = pendingRow ? pendingRow.pending : null;
    ui.ready = true;
    paint();
    await refresh(false, current);
  }
  async function refresh(more, fence = () => active()) {
    try {
      const params = new URLSearchParams({limit: "20", ...(more && ui.cursor ? {cursor: ui.cursor} : {})});
      const data = await api("/api/chat-imports?" + params);
      if (!fence()) return;
      const items = Array.isArray(data?.items) ? data.items.filter(i => i?.schema === 1 && i.identity_id === state.identityId && i.status === "imported" && /^[A-Za-z0-9_-]{1,120}$/.test(String(i.import_id))) : null;
      if (!items || data.next_cursor != null && typeof data.next_cursor !== "string") {ui.listError = "聊天批次列表不完整，请刷新。"; paint(); return;}
      ui.batches = more ? [...ui.batches.filter(old => !items.some(item => item.import_id === old.import_id)), ...items] : items;
      ui.cursor = data.next_cursor || null;
      ui.listError = "";
      paint();
    } catch (error) {if (fence()) {ui.listError = error.message || "暂时无法读取已导入聊天。"; paint();}}
  }
  function retain(nextDraft) {
    if (ui.pending) throw Object.assign(new Error("请先核对上次导入。"), {operational: true});
    if (deletionBlocked()) throw Object.assign(new Error(DELETION_NOTICE), {operational: true});
    makeRequest(nextDraft); // 先验后存
    if (!writeJournal(draftKey(), {identity: state.identityId, draft: nextDraft}))
      throw Object.assign(new Error("本机暂时没能保留这份预览，请稍后再试。"), {operational: true});
    ui.draft = nextDraft;
  }
  async function pick(file) {
    const epoch = state.identityEpoch, generation = ui.generation, ticket = ++ui.opTicket;
    const current = () => epoch === state.identityEpoch && generation === ui.generation && ticket === ui.opTicket;
    ui.busy = true; ui.error = ""; ui.notice = ""; paint();
    try {
      if (deletionBlocked()) throw Object.assign(new Error(DELETION_NOTICE), {operational: true});
      // 伪造的超大 File 必须在读字节/摘要前被拒（P2 修复）：不先完整读取再发现超限。
      if (typeof file.size === "number" && (file.size <= 0 || file.size > LIMITS.fileBytes)) fail("请选择非空且不超过 15 MB 的聊天文件。");
      const bytes = new Uint8Array(await file.arrayBuffer());
      if (!current()) return;
      const sourceHash = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", bytes))).map(b => b.toString(16).padStart(2, "0")).join("");
      if (!current()) return;
      const preview = await parseChatImport(bytes, file.name, current);
      // 解析含多次让出线程：任何存储写之前必须复核账户/身份/面板围栏（P1 修复）。
      if (!current()) return;
      const next = {version: 1, key: window.WearingIds.uuid().replaceAll("-", ""), sourceHash, preview, selfAuthor: null};
      retain(next);
      ui.messageLimit = 20;
      ui.notice = "";
    } catch (error) {if (current()) ui.error = error.message || "这份聊天文件暂时没有读取成功。";}
    finally {if (current()) {ui.busy = false; paint();}}
  }
  async function chooseAuthor(selfAuthor) {
    if (!ui.draft || ui.busy || ui.pending) return;
    try {
      const next = {...ui.draft, selfAuthor};
      retain(next);
      ui.error = "";
      paint();
    } catch (error) {ui.error = error.message; paint();}
  }
  function discard() {
    if (ui.pending) {ui.error = "上次导入结果尚需核对，请先重试。"; paint(); return;}
    if (deletionBlocked()) {ui.error = DELETION_NOTICE; paint(); return;}
    if (!writeJournal(draftKey(), null)) {
      // 存储拒绝删除时不得谎称已移除（P2 修复）：预览仍在，如实显示失败。
      ui.error = "本机暂时没能移除这份预览，请稍后再试；原文件不受影响。";
      paint(); return;
    }
    ui.draft = null; ui.notice = "已移除本机聊天预览，原文件不受影响。"; ui.error = "";
    paint();
  }
  async function confirm() {
    const epoch = state.identityEpoch, generation = ui.generation, ticket = ++ui.opTicket;
    const current = () => epoch === state.identityEpoch && generation === ui.generation && ticket === ui.opTicket;
    ui.busy = true; ui.error = ""; ui.notice = ""; ui.missing = false; paint();
    try {
      if (deletionBlocked()) throw Object.assign(new Error(DELETION_NOTICE), {operational: true});
      let pendingRow = readJournal(pendingKey());
      let pending = pendingRow ? pendingRow.pending : null;
      if (!pending) {
        if (!ui.draft) throw Object.assign(new Error("请先选择并预览聊天。"), {operational: true});
        const request = makeRequest(ui.draft);
        if (!writeJournal(pendingKey(), {identity: state.identityId, pending: {version: 1, key: request.request_key, request}}))
          throw Object.assign(new Error("本机暂时没能保留这次确认，没有发出请求。请稍后再试。"), {operational: true});
        pending = {version: 1, key: request.request_key, request};
      }
      let receipt = null;
      // GET/POST/清 journal 之前都必须复核围栏：关闭面板、注销冻结或换身份后，
      // 旧 operation 不得再发网络请求或清写存储（P1 修复）；未知提交保留同请求键待重开续查。
      if (!current()) return;
      try {receipt = verifyReceipt(await api(`/api/chat-imports/receipts/${encodeURIComponent(pending.key)}`), pending.key);}
      catch (error) {if (error && error.status === 404) receipt = null; else throw asError(error, "GET");}
      if (!current()) return;
      if (!receipt) {
        if (!pending.request) {ui.missing = true; throw Object.assign(new Error("服务尚无这次导入记录。本机聊天正文已清除，请重新选择文件。"), {operational: true});}
        let raw;
        try {raw = await api("/api/chat-imports", {method: "POST", body: JSON.stringify(pending.request)});}
        catch (error) {throw asError(error, "POST");}
        receipt = verifyReceipt(raw, pending.key);
      }
      if (!current()) return;
      writeJournal(draftKey(), null);
      writeJournal(pendingKey(), null);
      ui.draft = null; ui.pending = null;
      if (current()) {
        ui.notice = receipt.status === "deleted" ? "这批聊天此前已删除，没有重新导入。" : "选定聊天已导入当前身份。作者原话会保留来源，不会直接当作你的偏好。";
        await refresh(false, current);
        paint();
      }
    } catch (error) {
      if (current()) {
        // 未知结果（无状态码、非操作性错误）不泄漏原始传输文案，保留同请求键待重试。
        ui.error = error && (error.operational || error.status) ? error.message : "操作结果尚未确认，请重试核对同一次操作。";
        const pendingRow = readJournal(pendingKey());
        ui.pending = pendingRow ? pendingRow.pending : null;
      }
    } finally {if (current()) {ui.busy = false; paint();}}
  }
  async function clearMissing() {
    if (!ui.pending || ui.pending.request) return;
    const epoch = state.identityEpoch, ticket = ++ui.opTicket;
    const current = () => epoch === state.identityEpoch && ticket === ui.opTicket;
    try {
      let receipt = null;
      if (!current()) return;
      try {receipt = verifyReceipt(await api(`/api/chat-imports/receipts/${encodeURIComponent(ui.pending.key)}`), ui.pending.key);}
      catch (error) {if (error && error.status === 404) receipt = null; else throw asError(error, "GET");}
      if (!current()) return;
      if (receipt) throw Object.assign(new Error("服务已有这次导入，请先核对结果。"), {operational: true});
      writeJournal(pendingKey(), null);
      ui.pending = null; ui.missing = false; ui.error = "";
      paint();
    } catch (error) {if (current()) {ui.error = error.message; paint();}}
  }
  async function openBatch(importId) {
    ui.selectedBatch = importId; ui.batchDetail = null; ui.detailLimit = 20; paint();
    const epoch = state.identityEpoch, ticket = ++ui.opTicket;
    const current = () => epoch === state.identityEpoch && ticket === ui.opTicket;
    try {
      const data = await api(`/api/chat-imports/${encodeURIComponent(importId)}`);
      if (!current()) return;
      if (data?.schema !== 1 || data.identity_id !== state.identityId || data.import_id !== importId || data.status !== "imported" || !Array.isArray(data.messages) || data.messages.length > 500 || data.messages.some(m => typeof m.id !== "string" || typeof m.author !== "string" || typeof m.text !== "string" || m.sent_at !== null && typeof m.sent_at !== "string")) throw Object.assign(new Error("聊天详情尚未完整读取，请重试。"), {operational: true});
      ui.batchDetail = data; paint();
      document.querySelector(`[data-ci-message="${esc(importId)}:${esc(data.messages[0]?.id || "")}"]`)?.scrollIntoView({block: "center"});
    } catch (error) {if (current()) {ui.error = error.message; paint();}}
  }
  async function removeBatch(importId) {
    const epoch = state.identityEpoch, generation = ui.generation, ticket = ++ui.opTicket;
    const current = () => epoch === state.identityEpoch && generation === ui.generation && ticket === ui.opTicket;
    ui.busy = true; ui.error = ""; paint();
    try {
      if (deletionBlocked()) throw Object.assign(new Error(DELETION_NOTICE), {operational: true});
      if (!current()) return;
      let data;
      try {data = await api(`/api/chat-imports/${encodeURIComponent(importId)}`, {method: "DELETE"});}
      catch (error) {throw asError(error, "DELETE");}
      if (data?.schema !== 1 || data.identity_id !== state.identityId || data.import_id !== importId || data.status !== "deleted") throw Object.assign(new Error("删除回执尚未确认，请重试同一批聊天。"), {operational: true});
      ui.deleting = null;
      if (ui.selectedBatch === importId) {ui.selectedBatch = null; ui.batchDetail = null;}
      if (current()) {ui.notice = "已移除这批聊天来源。"; await refresh(false, current); paint();}
    } catch (error) {if (current()) ui.error = error.message || "删除回执尚未确认，请重试同一批聊天。";}
    finally {if (current()) {ui.busy = false; paint();}}
  }

  /* ---------- 渲染 ---------- */
  function paint() {
    const panel = $("chat-import-panel"); if (!panel || !ui.open) return;
    const duplicate = ui.draft && ui.batches.find(batch => batch.source_sha256 === ui.draft.sourceHash);
    $("ci-body").innerHTML = `
      <p class="ob-copy">把想让 Pajio 了解的那一段带过来。先在本机预览，确认后才导入当前身份；不读取整段聊天历史。</p>
      ${ui.error ? `<p class="ob-error" role="alert">${esc(ui.error)}</p>` : ""}
      ${ui.notice ? `<p class="ob-copy">${esc(ui.notice)}</p>` : ""}
      ${!ui.ready || ui.busy ? `<p class="ob-copy">${!ui.ready ? "读取本机预览…" : "正在处理这批聊天…"}</p>` : ""}
      ${!ui.draft && !ui.pending && !ui.busy ? `<button class="secondary" type="button" data-ci-pick>选择聊天 ZIP 或 TXT</button>
        <p class="ob-caption">仅支持带作者、日期和时间的选定聊天 TXT 或原始 ZIP。文件最多 15 MB、聊天文字 384 KB、500 条消息。图片、语音等附件不会导入。</p>` : ""}
      ${ui.draft ? previewMarkup(duplicate) : ""}
      ${ui.pending ? `<p class="ob-copy">上次导入结果尚需核对。重试会查询同一编号，服务未收到时才补交原请求。${!ui.pending.request && !ui.draft ? " 本机正文已清除，仅保留结果查询编号。" : ""}</p>` : ""}
      ${(ui.draft || ui.pending) && !ui.busy ? `<button class="primary" type="button" data-ci-confirm>${ui.pending ? "重试并核对导入" : `确认导入 ${ui.draft.preview.messages.length} 条消息`}</button>` : ""}
      ${ui.draft && !ui.pending && !ui.busy ? `<button class="text-button" type="button" data-ci-discard>移除本机预览</button>` : ""}
      ${ui.missing && ui.pending && !ui.pending.request && !ui.busy ? `<button class="text-button" type="button" data-ci-clear-missing>清除空请求，重新选择文件</button>` : ""}
      ${listMarkup()}`;
  }
  function previewMarkup(duplicate) {
    const d = ui.draft, p = d.preview;
    return `<div class="ob-card">
      <p class="ob-option">${esc(p.title)}</p>
      <p class="ob-copy">${p.messages.length} 条消息 · ${p.authors.length} 位作者</p>
      <p class="ob-caption">${esc(p.start)} — ${esc(p.end)}　时间照原文件展示；未推断时区。</p>
      <p class="ob-caption">图片、语音、视频及文件附件均未导入，Pajio 不会看到或听到它们的内容。${p.attachments.length ? `ZIP 另有 ${p.attachments.length} 个附件，仅在本机检查文件目录。` : ""}</p>
      ${p.attachments.slice(0, 8).map(item => `<p class="ob-caption">未导入 · ${esc(item.name)}</p>`).join("")}
      <p class="ob-label">哪一位是你？</p>
      <p class="ob-caption">可不选。即使选了，也会区分你的原话、转述和其他人的观点。</p>
      <div class="ob-chips">${[null, ...p.authors].map(author => `<button type="button" class="ob-choice chip${d.selfAuthor === author ? " on" : ""}" data-ci-author="${esc(author || "")}" aria-pressed="${d.selfAuthor === author ? "true" : "false"}"${ui.busy || ui.pending ? " disabled" : ""}><span>${esc(author || "暂不指定")}</span></button>`).join("")}</div>
      <p class="ob-label">消息预览</p>
      ${p.messages.slice(0, ui.messageLimit).map(message => `<div class="ci-message"><p class="ci-author">${esc(message.author)}</p><p class="ob-caption">${esc(message.sent_at || "")}</p><p class="ob-copy">${esc(message.text || "（原文件未提供文字内容）")}</p></div>`).join("")}
      ${ui.messageLimit < p.messages.length ? `<button class="text-button" type="button" data-ci-more>继续预览（剩余 ${p.messages.length - ui.messageLimit} 条）</button>` : ""}
      ${duplicate ? `<p class="ob-error">这份文件已在当前列表中导入过。请先查看下方批次，避免重复保存。</p>` : ""}
      <p class="ob-caption">确认后会将以上文字发送至当前 Pajio 服务，作为可删除的聊天来源。不会自动发消息或执行文件中的指令。</p>
    </div>`;
  }
  // 列表展示人可读的本地导入时间；消息原时间仍按原文件展示、不推时区。
  const importTime = value => {
    const date = new Date(value);
    return Number.isFinite(date.getTime()) ? date.toLocaleString("zh-CN", {year: "numeric", month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit"}) : String(value || "");
  };
  function listMarkup() {
    return `<p class="ob-label">已导入的聊天</p>
      ${ui.listError ? `<p class="ob-error">${esc(ui.listError)}</p>` : ""}
      <div class="brief-actions"><button class="text-button" type="button" data-ci-refresh>刷新已导入聊天</button></div>
      ${!ui.batches.length && !ui.listError ? `<p class="ob-caption">当前身份还没有已导入的聊天。</p>` : ""}
      ${ui.batches.map(batch => `<div class="ob-card" data-ci-batch-card="${esc(batch.import_id)}">
        <button class="text-button" type="button" data-ci-batch="${esc(batch.import_id)}"><strong>${esc(batch.conversation_title)}</strong><br><small>${batch.message_count} 条消息 · 导入于 ${esc(importTime(batch.created_at))}</small></button>
        ${ui.selectedBatch === batch.import_id ? detailMarkup(batch) : ""}
        ${ui.deleting === batch.import_id ? `<p class="ob-copy">移除这批来源、消息和来源索引。已生成的对话或结果可能仍含引用，可另行删除对应内容。</p>
          <div class="brief-actions"><button class="primary" type="button" data-ci-delete-confirm="${esc(batch.import_id)}"${ui.busy ? " disabled" : ""}>确认移除这批聊天</button><button class="text-button" type="button" data-ci-delete-keep>保留</button></div>`
        : `<button class="text-button" type="button" data-ci-delete="${esc(batch.import_id)}"${ui.busy ? " disabled" : ""}>移除这批聊天</button>`}
      </div>`).join("")}
      ${ui.cursor ? `<button class="text-button" type="button" data-ci-more-list${ui.busy ? " disabled" : ""}>加载更早的导入</button>` : ""}`;
  }
  function detailMarkup(batch) {
    const detail = ui.batchDetail && ui.batchDetail.import_id === batch.import_id ? ui.batchDetail : null;
    return `<p class="ob-copy">作者：${esc(batch.authors.join("、"))}<br>本人：${esc(batch.self_author || "未指定")}</p>
      <p class="ob-caption">来源批次：${esc(batch.import_id)}　附件内容未导入。</p>
      ${detail ? `${detail.messages.slice(0, ui.detailLimit).map(message => `<div class="ci-message" data-ci-message="${esc(batch.import_id)}:${esc(message.id)}"><p class="ci-author">${esc(message.author)}</p><p class="ob-caption">${esc(message.sent_at || "")}</p><p class="ob-copy">${esc(message.text || "（无文字内容）")}</p><p class="ob-caption">来源消息 · ${esc(message.id)}</p></div>`).join("")}
        ${ui.detailLimit < detail.messages.length ? `<button class="text-button" type="button" data-ci-more-detail>继续查看消息</button>` : ""}` : `<p class="ob-caption">正在读取批次消息…</p>`}`;
  }

  /* ---------- 事件 ---------- */
  const panel = document.getElementById("chat-import-panel");
  panel.addEventListener("click", event => {
    if (event.target.closest("[data-ci-close]") || event.target.closest("[data-ci-close-btn]")) {close(); return;}
    if (event.target.closest("[data-ci-pick]")) {$("ci-file").click(); return;}
    if (event.target.closest("[data-ci-more]")) {ui.messageLimit += 20; paint(); return;}
    if (event.target.closest("[data-ci-more-detail]")) {ui.detailLimit += 20; paint(); return;}
    if (event.target.closest("[data-ci-more-list]")) {refresh(true); return;}
    if (event.target.closest("[data-ci-refresh]")) {refresh(false); return;}
    if (event.target.closest("[data-ci-discard]")) {discard(); return;}
    if (event.target.closest("[data-ci-confirm]")) {confirm(); return;}
    if (event.target.closest("[data-ci-clear-missing]")) {clearMissing(); return;}
    const author = event.target.closest("[data-ci-author]");
    if (author) {chooseAuthor(author.dataset.ciAuthor === "" ? null : author.dataset.ciAuthor); return;}
    const batch = event.target.closest("[data-ci-batch]");
    if (batch) {if (ui.selectedBatch === batch.dataset.ciBatch) {ui.selectedBatch = null; ui.batchDetail = null; paint();} else openBatch(batch.dataset.ciBatch); return;}
    const del = event.target.closest("[data-ci-delete]");
    if (del) {ui.deleting = del.dataset.ciDelete; paint(); return;}
    if (event.target.closest("[data-ci-delete-keep]")) {ui.deleting = null; paint(); return;}
    const delConfirm = event.target.closest("[data-ci-delete-confirm]");
    if (delConfirm) {removeBatch(delConfirm.dataset.ciDeleteConfirm); return;}
  });
  $("ci-file") && $("ci-file").addEventListener("change", event => {
    const file = event.target.files[0];
    event.target.value = "";
    if (file) pick(file);
  });
  document.addEventListener("click", event => {
    if (event.target.closest("#chat-import-entry") || event.target.closest("#ci-files-entry")) {
      // 面板交接：从设置或文件面板进入时关闭父面板，避免双模态叠加。
      for (const parentId of ["settings-panel", "files-panel"]) {
        const parent = $(parentId);
        if (parent?.open) closePanel(parentId);
      }
      open(); return;
    }
  });

  function open() {
    ui.open = true;
    openPanel("chat-import-panel");
    load();
  }
  function close() {
    // 关闭面板即作废在途 operation（confirm/pick/removeBatch 的票据）并释放忙态，重开后续查同请求键。
    ui.opTicket++; ui.loadTicket++; ui.busy = false;
    closePanel("chat-import-panel"); ui.open = false;
  }
  panel.addEventListener("close", () => {ui.open = false; ui.opTicket++; ui.loadTicket++; ui.busy = false;});
  function reset() {ui.generation++; ui.loadTicket++; ui.opTicket++; ui.epoch = -1; ui.open = false; ui.busy = false; ui.draft = null; ui.pending = null; ui.batches = []; ui.cursor = null; ui.deleting = null; ui.selectedBatch = null; ui.batchDetail = null; ui.error = ""; ui.notice = ""; ui.listError = ""; ui.ready = false; ui.missing = false; try {$("chat-import-panel").close();} catch {}}
  // 跨对象搜索深链：kind=chat_import 打开批次详情（不当成任务跳转）。
  function openSearchResult(target) {
    if (target?.kind !== "chat_import" || !/^[A-Za-z0-9_-]{1,120}$/.test(String(target.import_id || ""))) return false;
    open();
    openBatch(String(target.import_id));
    return true;
  }

  window.WearingChatImport = {open, close, reset, openSearchResult,
    _test: {ui, pick, chooseAuthor, discard, confirm, clearMissing, removeBatch, openBatch, refresh, load, paint, parseChatImport, parseChatText, makeRequest, verifyReceipt, draftKey, pendingKey, retain, deletionBlocked, LIMITS}};
})();
