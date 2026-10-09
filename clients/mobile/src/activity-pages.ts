import {ApiError, type ActivitySnapshot} from './core';

/** Pages are one server snapshot. A changed cursor is retried from the first
 * page by an explicit refresh, never spliced into a different ordering. */
export function appendActivityPage(previous: ActivitySnapshot, next: ActivitySnapshot): ActivitySnapshot {
  const stale = () => {throw new ApiError('进展列表已更新，请刷新后继续查看。', 409);};
  if (!previous.next_cursor || !previous.revision || previous.revision !== next.revision || previous.total !== next.total || previous.unread !== next.unread ||
    previous.filtered_total !== next.filtered_total || Object.keys(previous.counts).some(key => previous.counts[key as keyof typeof previous.counts] !== next.counts[key as keyof typeof next.counts])) return stale();
  const known = new Set(previous.items.map(item => item.task_id));
  if (!next.items.length || next.items.some(item => known.has(item.task_id))) return stale();
  const items = [...previous.items, ...next.items];
  if (items.length > (next.filtered_total ?? next.total) || (!next.has_more && items.length !== next.filtered_total)) return stale();
  return {...next, items};
}
