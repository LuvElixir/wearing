/** Development-only, loopback-bound preview of the same React Native client. */
import http from 'node:http';
import {Buffer} from 'node:buffer';
import {readFile, stat} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {resolve, extname, sep} from 'node:path';
const root = resolve(fileURLToPath(new URL('../dist/', import.meta.url)));
const port = Number(process.env.WEARING_MOBILE_PORT || 8787);
const upstream = new URL(process.env.WEARING_PREVIEW_UPSTREAM || 'http://127.0.0.1:8765/');
if (upstream.protocol !== 'http:' || !['127.0.0.1', 'localhost', '[::1]'].includes(upstream.hostname) || upstream.pathname !== '/' || upstream.username || upstream.password || upstream.search || upstream.hash) throw new Error('Preview upstream must be a loopback Wearing service.');
const mime = {'.html': 'text/html; charset=utf-8', '.js': 'application/javascript', '.css': 'text/css', '.png': 'image/png', '.svg': 'image/svg+xml', '.ttf': 'font/ttf', '.ico': 'image/x-icon'};
const server = http.createServer(async (request, response) => {
  const origin = `http://127.0.0.1:${port}`;
  if (![`127.0.0.1:${port}`, `localhost:${port}`].includes(request.headers.host) || (request.headers.origin && ![origin, `http://localhost:${port}`].includes(request.headers.origin))) {response.writeHead(403); response.end('Local preview only'); return;}
  const url = new URL(request.url, origin);
  response.setHeader('X-Content-Type-Options', 'nosniff'); response.setHeader('Cache-Control', 'no-store');
  try {
    if (url.pathname.startsWith('/api/')) {
      if (!/^\/api\/(bootstrap|memory|goals|schedules|activity(?:\/seen)?|life(?:\/life_[a-f0-9]{32}|\/assets(?:\/asset_[a-f0-9]{32})?)?|captures(?:\/capture_[a-f0-9]{32}\/retry)?)$/.test(url.pathname)) {response.writeHead(404); response.end('Unavailable in mobile preview'); return;}
      if (['/api/memory','/api/goals','/api/schedules'].includes(url.pathname) && request.method !== 'GET') {response.writeHead(405, {Allow:'GET'}); response.end(); return;}
      if (url.pathname === '/api/activity' || url.pathname === '/api/activity/seen') {
        const allowed = url.pathname === '/api/activity' ? 'GET' : 'POST';
        if (request.method !== allowed) {response.writeHead(405, {Allow: allowed}); response.end(); return;}
      }
      const headers = {'host': upstream.host, 'origin': upstream.origin};
      for (const name of ['content-type', 'x-wearing-token', 'x-wearing-identity']) if (typeof request.headers[name] === 'string') headers[name] = request.headers[name];
      let size = 0; const chunks = [];
      for await (const chunk of request) {size += chunk.length; if (size > 15 * 1024 * 1024) {response.writeHead(413); response.end('File too large'); return;} chunks.push(chunk);}
      const result = await fetch(new URL(url.pathname + url.search, upstream), {method: request.method, headers, body: ['GET', 'HEAD'].includes(request.method) ? undefined : Buffer.concat(chunks), redirect: 'error', signal: AbortSignal.timeout(25000)});
      response.writeHead(result.status, {'Content-Type': result.headers.get('content-type') || 'application/json'}); response.end(Buffer.from(await result.arrayBuffer())); return;
    }
    if (request.method !== 'GET' && request.method !== 'HEAD') {response.writeHead(405); response.end(); return;}
    if (url.pathname === '/wearing') {const target = new URL(upstream); const identity = url.searchParams.get('identity'); if (identity) target.searchParams.set('identity', identity.slice(0, 100)); for (const key of ['life_record', 'life_revision']) {const value = url.searchParams.get(key); if (value) target.searchParams.set(key, value.slice(0, 100));} const activityTask = url.searchParams.get('activity_task'); if (activityTask && /^[-a-zA-Z0-9_]{1,64}$/.test(activityTask)) target.searchParams.set('activity_task', activityTask); target.hash = 'conversation-main'; response.writeHead(303, {Location: target.toString()}); response.end(); return;}
    const path = resolve(root, '.' + decodeURIComponent(url.pathname));
    if (path !== root && !path.startsWith(root + sep)) {response.writeHead(403); response.end(); return;}
    let file = path;
    try {if (!(await stat(file)).isFile()) file = resolve(root, 'index.html');} catch {file = resolve(root, 'index.html');}
    const data = await readFile(file); response.writeHead(200, {'Content-Type': mime[extname(file)] || 'application/octet-stream'}); response.end(request.method === 'HEAD' ? undefined : data);
  } catch {if (response.headersSent) {response.destroy(); return;} response.writeHead(503, {'Content-Type': 'application/json'}); response.end(JSON.stringify({detail: '本机 Wearing 暂时未连接，原件和待同步记录仍在本机。'}));}
});
server.listen(port, '127.0.0.1', () => console.log(`Wearing mobile code preview: http://127.0.0.1:${port}/`));
