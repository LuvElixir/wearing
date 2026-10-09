/** Validate only. Never resolve, fetch, or preview the destination. */
export function bookmarkUrl(value: unknown): string {
  if (typeof value !== 'string' || !value || value.length > 4096 || /[\x00-\x20\x7f\\]|%(?:0[0-9a-f]|1[0-9a-f]|7f)/i.test(value) || !/^https?:\/\//i.test(value)) throw new Error('请填写完整的 http 或 https 网页链接，不要包含空白或控制字符。');
  const authority = value.match(/^https?:\/\/([^/?#]+)/i)?.[1];
  let url: URL;
  try {url = new URL(value);} catch {throw new Error('网页链接不完整，请检查后再保存。');}
  if (!authority || /[%@]/.test(authority) || !url.hostname || url.username || url.password || url.port === '0') throw new Error('请使用不带登录凭据的网页链接。');
  return value;
}
export function isBookmarkUrl(value: unknown): value is string {try {bookmarkUrl(value); return true;} catch {return false;}}
