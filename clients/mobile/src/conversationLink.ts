import type {RecordItem} from './core';
export function conversationLink(endpoint: string, identity: string, record?: RecordItem | null, previewOrigin?: string, reviewRequest?: ReviewRequest | null) {
  const url = new URL(endpoint);
  if (previewOrigin === url.origin) url.pathname = '/wearing';
  url.searchParams.set('identity', identity);
  if (reviewRequest?.target === 'activity') {
    if (!/^[-a-zA-Z0-9_]{1,64}$/.test(reviewRequest.taskId)) throw new Error('这条进展的任务标识不完整，请刷新后再试。');
    url.searchParams.set('activity_task', reviewRequest.taskId);
  } else if (record) {url.searchParams.set('life_record', record.id); url.searchParams.set('life_revision', String(record.revision));}
  url.hash = 'conversation-main';
  return url.toString();
}

// Native navigation is owned by the App; ordinary web links keep full site navigation.
export function nativeConversationLink(endpoint: string, identity: string, record?: RecordItem | null) {
  const url = new URL(conversationLink(endpoint, identity, record));
  url.searchParams.set('host', 'mobile');
  url.searchParams.set('input', 'voice');
  url.searchParams.set('composer', 'native');
  // Refresh retained WebViews when their request protocol/assets change. Drafts
  // remain identity-scoped in storage; a refresh never submits existing text.
  url.searchParams.set('web_ui', '3');
  return url.toString();
}

export function allowsConversationNavigation(requestUrl: string, conversationUrl: string) {
  if (requestUrl === 'about:blank') return true;
  try {
    const target = new URL(requestUrl), conversation = new URL(conversationUrl);
    return !target.username && !target.password && target.origin === conversation.origin && ['https:', 'http:'].includes(target.protocol);
  } catch {return false;}
}

export type ReviewRequest = {id: number; target: 'files' | 'goals' | 'schedules' | 'search'} | {id: number; target: 'draft'; text: string} | {id: number; target: 'activity'; taskId: string};
