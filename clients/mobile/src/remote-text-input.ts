export type RemoteTextCapabilities = {text?: 'ascii' | 'unicode' | 'unavailable'; text_max_chars?: number; text_max_bytes?: number; text_disallow_controls?: boolean};
export type RemoteTextIssue = 'text_unavailable' | 'text_too_long' | 'text_too_large' | 'text_invalid';

/** Limiting an old host cannot prove its Unicode implementation reliable; the wire ceiling never grows. */
export function remoteTextLimits(value: unknown, kind?: 'computer' | 'android'): {chars: number; bytes: number} {
  const caps = value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
  const limit = (value: unknown, fallback: number) => typeof value === 'number' && Number.isSafeInteger(value) && value > 0 ? Math.min(value, 4096) : fallback;
  return {chars: limit(caps.text_max_chars, kind === 'android' ? 4096 : 32), bytes: limit(caps.text_max_bytes, 4096)};
}

/** Returns metadata only. Never normalize, truncate, segment, queue or persist private text. */
export function remoteTextIssue(text: string, capabilities: RemoteTextCapabilities, kind?: 'computer' | 'android'): RemoteTextIssue | null {
  if (capabilities.text !== 'unicode') return 'text_unavailable';
  const points = Array.from(text), limits = remoteTextLimits(capabilities, kind);
  if (points.some(point => {const value = point.codePointAt(0)!; return value >= 0xd800 && value <= 0xdfff;})) return 'text_invalid';
  if (capabilities.text_disallow_controls === true && /[\u0000-\u001f\u007f]/.test(text)) return 'text_invalid';
  if (points.length > limits.chars) return 'text_too_long';
  if (new TextEncoder().encode(text).length > limits.bytes) return 'text_too_large';
  return null;
}

export function remoteTextNotice(code: string, capabilities: RemoteTextCapabilities, kind?: 'computer' | 'android'): string | null {
  if (code === 'text_too_long') return `这台设备一次最多输入 ${remoteTextLimits(capabilities, kind).chars} 个字符，请缩短后再试。`;
  if (code === 'text_too_large') return '文字超过这台设备的输入大小限制，请缩短后再试。';
  if (code === 'text_invalid') return '文字含不支持的字符或换行，请修改后再试。';
  if (code === 'text_unavailable') return '此设备的私密输入尚未就绪，暂时不能从 App 发送文字。';
  return null;
}
