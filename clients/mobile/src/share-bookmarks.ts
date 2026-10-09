import {ApiError, scopeOf, type Connection, type Outbox, type Store} from './core';
import {bookmarkDraft, bookmarkPending, withBookmarkDraft, type BookmarkFields} from './bookmark-model';
import {isBookmarkUrl} from './bookmark-url';
import {parseShareManifest, SHARE_ID, type ShareReceipt, type ShareSubmission} from './share-intake-model';
export function sharedBookmark(text: string): BookmarkFields | null {
  const original = text.split(/\r?\n/), lines = original.map(v => v.trim()), urls = lines.filter(isBookmarkUrl);
  if (urls.length !== 1 || lines.some(v => /^https?:/i.test(v) && !isBookmarkUrl(v))) return null;
  const notes = original.filter((_, index) => lines[index] !== urls[0]).join('\n').trim();
  return {url: urls[0], title: (lines.find(v => v && v !== urls[0]) || new URL(urls[0]).hostname).slice(0, 200), notes};
}
export const bookmarkShareKey = (scope: string, id: string) => `bookmark-share:v1:${scope}:${id}`;
export function createShareBookmarkHandler(connection: Connection, deps: {store: Store; outbox: Pick<Outbox, 'enqueue'>; isCurrent?: () => boolean}) {
  const scope = scopeOf(connection);
  return (submission: ShareSubmission): Promise<ShareReceipt> => {
    const key = bookmarkShareKey(scope, submission.requestId);
    return withBookmarkDraft(deps.store, key, async () => {
      if (!SHARE_ID.test(submission.requestId) || submission.scope !== scope) throw new ApiError('分享身份或编号不一致，请回到原身份重试。', 409);
      parseShareManifest({version: 1, id: submission.requestId, createdAt: '2000-01-01T00:00:00Z', text: submission.text, files: submission.files});
      const fields = sharedBookmark(submission.text);
      if (!fields || submission.files.length) throw new ApiError('收藏需要一条单独成行的网页链接；其他内容可导入笔记。', 422);
      const signature = JSON.stringify({text: submission.text, files: []});
      const prior = await deps.store.get<{version: number; signature: string; scope: string; id: string}>(key);
      if (prior) {
        if (prior.version !== 1 || prior.signature !== signature || prior.scope !== scope || prior.id !== submission.requestId) throw new ApiError('分享回执不一致，请保留原内容后核对。', 409);
        return {requestId: submission.requestId, scope};
      }
      if (deps.isCurrent && !deps.isCurrent()) throw new ApiError('身份已切换，收藏尚未保存。', 409);
      const zone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'Asia/Shanghai'; bookmarkDraft(fields, zone);
      const entry = bookmarkPending(scope, {...fields, version: 1, revision: 0, requestId: `bookmark-share-${submission.requestId}`}, zone);
      // One transaction makes the replay tombstone durable before any outbox flush.
      await deps.outbox.enqueue(entry, [key, {version: 1, scope, id: submission.requestId, signature}]);
      const saved = await deps.store.get<{signature: string}>(key);
      if (saved?.signature !== signature) throw new Error('收藏尚未完整加入队列，请重试核对。');
      return {requestId: submission.requestId, scope};
    });
  };
}
