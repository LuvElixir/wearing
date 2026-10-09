/** Isolated UI preview. No API proxy, credentials, or backend writes. */
import http from 'node:http';
import {Buffer} from 'node:buffer';
import {readFile, realpath, stat} from 'node:fs/promises';
import {dirname, extname, resolve, sep} from 'node:path';
import {fileURLToPath} from 'node:url';

const defaultRoot = resolve(dirname(fileURLToPath(import.meta.url)), '../dist-experience');
const mime = {
  '.html': 'text/html; charset=utf-8', '.js': 'application/javascript; charset=utf-8',
  '.mjs': 'application/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8', '.map': 'application/json; charset=utf-8',
  '.txt': 'text/plain; charset=utf-8', '.svg': 'image/svg+xml', '.png': 'image/png',
  '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.gif': 'image/gif', '.webp': 'image/webp',
  '.avif': 'image/avif', '.ico': 'image/x-icon', '.woff': 'font/woff', '.woff2': 'font/woff2',
  '.ttf': 'font/ttf', '.otf': 'font/otf', '.mp4': 'video/mp4', '.webm': 'video/webm',
  '.mp3': 'audio/mpeg', '.m4a': 'audio/mp4', '.wav': 'audio/wav', '.ogg': 'audio/ogg',
  '.pdf': 'application/pdf', '.wasm': 'application/wasm',
};

function contained(root, file) {return file === root || file.startsWith(root + sep);}

// Expo may export hashed assets without their original extension.
function contentType(file, data) {
  if (mime[extname(file).toLowerCase()]) return mime[extname(file).toLowerCase()];
  if (data.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]))) return 'image/png';
  if (data[0] === 255 && data[1] === 216 && data[2] === 255) return 'image/jpeg';
  if (/^GIF8[79]a$/.test(data.subarray(0, 6).toString('ascii'))) return 'image/gif';
  if (data.subarray(0, 4).toString('ascii') === 'RIFF' && data.subarray(8, 12).toString('ascii') === 'WEBP') return 'image/webp';
  if (data.subarray(4, 8).toString('ascii') === 'ftyp') return 'video/mp4';
  return 'application/octet-stream';
}

export function createPreviewHandler({root = defaultRoot, port = 8793} = {}) {
  const origins = [`http://127.0.0.1:${port}`, `http://localhost:${port}`];
  const hosts = [`127.0.0.1:${port}`, `localhost:${port}`];
  return async (request, response) => {
    response.setHeader('X-Content-Type-Options', 'nosniff');
    response.setHeader('Cache-Control', 'no-store');
    response.setHeader('Referrer-Policy', 'no-referrer');
    const end = (status, message) => {
      response.writeHead(status, {'Content-Type': 'text/plain; charset=utf-8'});
      response.end(request.method === 'HEAD' ? undefined : message);
    };
    if (!hosts.includes(request.headers.host) || (request.headers.origin && !origins.includes(request.headers.origin))) {
      end(403, 'Local preview only'); return;
    }
    if (!['GET', 'HEAD'].includes(request.method)) {
      response.setHeader('Allow', 'GET, HEAD'); end(405, 'Read-only preview'); return;
    }
    let pathname;
    try {
      if (!request.url?.startsWith('/')) throw new Error('Invalid path');
      pathname = decodeURIComponent(request.url.split(/[?#]/, 1)[0]);
      if (pathname.includes('\0') || pathname.includes('\\')) throw new Error('Invalid path');
      pathname = pathname.replace(/\/{2,}/g, '/');
    } catch {end(400, 'Invalid path'); return;}
    if (pathname.split('/').some(part => part === '..')) {end(403, 'Outside preview'); return;}
    if (pathname.split('/').some(part => part.startsWith('.')) || /^\/api(?:\/|$)/.test(pathname)) {
      end(404, 'Not available in this preview'); return;
    }
    try {
      const canonicalRoot = await realpath(root);
      const requested = resolve(canonicalRoot, '.' + pathname);
      if (!contained(canonicalRoot, requested)) {end(403, 'Outside preview'); return;}
      const route = !extname(pathname) && !/^\/(?:assets|_expo|static)(?:\/|$)/.test(pathname);
      let file = requested;
      try {
        const info = await stat(file);
        if (info.isDirectory()) file = resolve(file, 'index.html');
        else if (!info.isFile()) {end(404, 'Not found'); return;}
        await stat(file);
      } catch (error) {
        if (error.code !== 'ENOENT' && error.code !== 'ENOTDIR') throw error;
        if (!route) {end(404, 'Not found'); return;}
        file = resolve(canonicalRoot, 'index.html');
      }
      // Resolve symlinks too, rather than only checking the lexical path.
      file = await realpath(file);
      if (!contained(canonicalRoot, file)) {end(403, 'Outside preview'); return;}
      if (!(await stat(file)).isFile()) {end(404, 'Not found'); return;}
      const data = await readFile(file);
      response.writeHead(200, {'Content-Type': contentType(file, data), 'Content-Length': data.byteLength});
      response.end(request.method === 'HEAD' ? undefined : data);
    } catch (error) {
      if (response.headersSent) {response.destroy(); return;}
      end(503, error.code === 'ENOENT' ? 'Build dist-experience first: npx expo export --platform web --output-dir dist-experience' : 'Preview files are unavailable');
    }
  };
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const port = Number(process.env.WEARING_EXPERIENCE_PORT || 8793);
  if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error('WEARING_EXPERIENCE_PORT must be a valid port.');
  const server = http.createServer(createPreviewHandler({port}));
  server.listen(port, '127.0.0.1', () => console.log(`Wearing iPhone experience preview: http://127.0.0.1:${port}/experience`));
}
