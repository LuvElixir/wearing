import {ApiError, Connection, connectionEndpoint, connectionHeaders} from './core';

export const ARTIFACT_MAX_BYTES = 1024 * 1024;
export type ArtifactMetadata = {id: string; task_id: string; title: string; summary: string; presentation: 'dashboard' | 'diagram' | 'interactive';
  sources: string[]; assumptions: string[]; limitations: string[]; revision: number; previous_id: string | null; family_id: string; created_at: string;
  size: number; sha256: string; state: 'generated'; checks: {file: string; render: string; content: string}};
export type ArtifactDocument = {metadata: ArtifactMetadata; html: string};
export type ArtifactDigest = (bytes: Uint8Array) => Promise<string>;
const object = (value: unknown): value is Record<string, any> => !!value && typeof value === 'object' && !Array.isArray(value);
const id = (value: unknown): value is string => typeof value === 'string' && /^[a-zA-Z0-9_-]{1,64}$/.test(value);
const text = (value: unknown): value is string => typeof value === 'string';
const texts = (value: unknown) => Array.isArray(value) && value.every(text);
const invalid = () => new ApiError('这份结果的信息暂时不完整，请重新读取。', 422);
export function parseArtifactMetadata(value: unknown, expectedId: string): ArtifactMetadata {
  if (!object(value) || !id(value.id) || value.id !== expectedId || !id(value.task_id) || !text(value.title) || !text(value.summary) ||
    !['dashboard', 'diagram', 'interactive'].includes(value.presentation) || !texts(value.sources) || !texts(value.assumptions) || !texts(value.limitations) ||
    !Number.isSafeInteger(value.revision) || value.revision < 1 || !(value.previous_id === null || id(value.previous_id)) || !id(value.family_id) ||
    !text(value.created_at) || !Number.isFinite(Date.parse(value.created_at)) || !Number.isSafeInteger(value.size) || value.size < 1 || value.size > ARTIFACT_MAX_BYTES ||
    !text(value.sha256) || !/^[a-f0-9]{64}$/.test(value.sha256) || value.state !== 'generated' || !object(value.checks) ||
    !['file', 'render', 'content'].every(key => text(value.checks[key]))) throw invalid();
  return value as ArtifactMetadata;
}
/** Credentials are only used by the native transport, never embedded into a WebView. */
export class ArtifactApi {
  private readonly connection: Connection;
  constructor(connection: Connection, private readonly digest: ArtifactDigest, private readonly fetcher: typeof fetch = fetch) {
    this.connection = {...connection, ...(connection.development ? {development: {...connection.development}} : {}), ...(connection.session ? {session: {...connection.session}} : {})};
  }
  private async read<T>(idValue: string, suffix: string, consume: (response: Response) => Promise<T>): Promise<T> {
    if (!id(idValue)) throw invalid();
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 20000);
    try {
      const response = await this.fetcher(new URL(`/api/artifacts/${encodeURIComponent(idValue)}${suffix}`, connectionEndpoint(this.connection)).toString(), {
        method: 'GET', redirect: 'error', signal: controller.signal,
        headers: {...connectionHeaders(this.connection), 'X-Wearing-Identity': this.connection.identity},
      });
      if (!response.ok) {
        const data: unknown = await response.json().catch(() => null);
        throw new ApiError(object(data) && text(data.detail) ? data.detail : '暂时没有读到这份结果，请重试。', response.status);
      }
      // Keep the timeout alive until the response body has been consumed, too.
      return await consume(response);
    } catch (cause) {
      if (cause instanceof ApiError) throw cause;
      throw new ApiError('读取结果时连接中断，请检查连接后重试。');
    } finally {clearTimeout(timer);}
  }
  async metadata(identifier: string): Promise<ArtifactMetadata> {
    return this.read(identifier, '', async response => parseArtifactMetadata(await response.json().catch(() => {throw invalid();}), identifier));
  }
  private async verifiedBytes(metadata: ArtifactMetadata, suffix: '/preview' | '/download'): Promise<Uint8Array> {
    parseArtifactMetadata(metadata, metadata.id);
    return this.read(metadata.id, suffix, async response => {
      const length = response.headers.get('Content-Length');
      if (length !== null && (!/^\d+$/.test(length) || Number(length) > ARTIFACT_MAX_BYTES || Number(length) !== metadata.size)) throw new ApiError('文件大小与保存回执不一致，请重新读取。', 422);
      const type = (response.headers.get('Content-Type') || '').split(';')[0].trim().toLowerCase();
      if (type !== (suffix === '/preview' ? 'text/html' : 'application/octet-stream')) throw new ApiError('结果返回了错误的文件类型，未打开。', 422);
      const bytes = new Uint8Array(await response.arrayBuffer());
      if (bytes.length !== metadata.size || bytes.length > ARTIFACT_MAX_BYTES) throw new ApiError('结果文件校验未通过，请重新读取原来的版本。', 422);
      let digest: string;
      try {digest = await this.digest(bytes);} catch {throw new ApiError('本机暂时无法校验结果文件，请重试或更新 App。', 422);}
      if (digest !== metadata.sha256) throw new ApiError('结果文件校验未通过，请重新读取原来的版本。', 422);
      return bytes;
    });
  }
  async document(identifier: string): Promise<ArtifactDocument> {
    const metadata = await this.metadata(identifier), bytes = await this.verifiedBytes(metadata, '/preview');
    let html: string;
    try {html = new TextDecoder('utf-8', {fatal: true}).decode(bytes);} catch {throw new ApiError('这份结果不是有效的 UTF-8 页面，未打开。', 422);}
    if (!/<html\b/i.test(html) || !/<\/html\s*>/i.test(html)) throw new ApiError('这份图文页面不完整，请重新整理。', 422);
    return {metadata, html};
  }
  async original(metadata: ArtifactMetadata): Promise<Uint8Array> {
    const current = await this.metadata(metadata.id);
    if (current.revision !== metadata.revision || current.sha256 !== metadata.sha256 || current.task_id !== metadata.task_id) throw new ApiError('结果版本发生变化，请重新打开后再保存。', 409);
    return this.verifiedBytes(current, '/download');
  }
}

// Same content restrictions as the backend preview, with the sandbox enforced by an iframe.
// No allow-same-origin, forms, popups, top navigation, downloads or native message bridge.
export const ARTIFACT_CONTENT_CSP = "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; font-src data:; media-src data:; connect-src 'none'; frame-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'";
const escapeAttribute = (value: string) => value.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
export function artifactPreviewDocument(html: string, surface: string): string {
  if (!/^#[a-fA-F0-9]{6}$/.test(surface)) throw new Error('Preview surface must be a theme color.');
  const inner = '<meta http-equiv="Content-Security-Policy" content="' + escapeAttribute(ARTIFACT_CONTENT_CSP) + '">' + html;
  const outerPolicy = "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; frame-src about:; connect-src 'none'; img-src data:; font-src data:; media-src data:; base-uri 'none'; form-action 'none'";
  return `<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no"><meta http-equiv="Content-Security-Policy" content="${escapeAttribute(outerPolicy)}"><style>html,body{margin:0;width:100%;height:100%;overflow:hidden;background:${surface}}iframe{display:block;border:0;width:100%;height:100%;background:white}</style></head><body><iframe title="图文结果" sandbox="allow-scripts" referrerpolicy="no-referrer" allow="camera 'none'; microphone 'none'; geolocation 'none'; clipboard-read 'none'; clipboard-write 'none'; payment 'none'" srcdoc="${escapeAttribute(inner)}"></iframe></body></html>`;
}
export function artifactNavigationAllowed(url: string, isTopFrame?: boolean): boolean {
  return url === 'about:blank' || (isTopFrame === false && url === 'about:srcdoc');
}
