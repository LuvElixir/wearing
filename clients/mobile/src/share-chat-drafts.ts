import type {Store} from './core';
import {SHARE_ID, type ShareSubmission} from './share-intake-model';

export type SharedChatDraft = {id: string; text: string; state: 'ready' | 'appending' | 'received' | 'dismissed'; contextKey?: string};
const pending = (item: SharedChatDraft) => item.state === 'ready' || item.state === 'appending';
const listeners = new Set<() => void>();
export function observeSharedChatDrafts(fn: () => void) {listeners.add(fn); return () => {listeners.delete(fn);};}
const queues = new WeakMap<object, Promise<unknown>>();

/** Separate from the composer's current text: incoming shares never replace a draft.
 * The existing append receipt protocol is also suitable for shared text. Its
 * UUID is just a delivery identifier; this path never invokes speech recognition.
 */
export class SharedChatDrafts {
  constructor(private store: Pick<Store, 'get' | 'put'>) {}
  private key(scope: string) {if (!scope) throw new Error('请先选择身份。'); return `share-chat-drafts:${scope}`;}
  private serial<T>(work: () => Promise<T>): Promise<T> {
    const next = (queues.get(this.store) ?? Promise.resolve()).then(work, work);
    queues.set(this.store, next.catch(() => {})); return next;
  }
  private async read(scope: string) {return await this.store.get<SharedChatDraft[]>(this.key(scope)) || [];}
  private async write(scope: string, items: SharedChatDraft[]) {await this.store.put(this.key(scope), items); listeners.forEach(fn => fn());}
  list(scope: string) {return this.serial(async () => (await this.read(scope)).filter(pending));}
  save(input: ShareSubmission) {
    return this.serial(async () => {
      if (!SHARE_ID.test(input.requestId) || input.files.length || !input.text.trim() || input.text.length > 12000) throw new Error('这份分享无法作为文字草稿，请导入记录。');
      const items = await this.read(input.scope), prior = items.find(item => item.id === input.requestId);
      if (prior && pending(prior) && prior.text !== input.text) throw new Error('这份分享已经变化，请重新分享。');
      if (!prior) {
        if (items.filter(pending).length >= 8) throw new Error('聊天里还有 8 份分享待处理，请先带入草稿。');
        await this.write(input.scope, [...items, {id: input.requestId, text: input.text, state: 'ready'}]);
      }
      return {requestId: input.requestId, scope: input.scope};
    });
  }
  append(scope: string, id: string, contextKey: string, currentText: string) {
    return this.serial(async () => {
      const items = await this.read(scope), item = items.find(value => value.id === id);
      if (!item || !pending(item)) throw new Error('这份文字已处理，请查看当前草稿。');
      if (item.contextKey && item.contextKey !== contextKey) throw new Error('这份文字正在带入另一个对话，请回到原对话核对。');
      if (!contextKey || contextKey.length > 4000) throw new Error('对话尚未就绪，请稍候。');
      if (item.state === 'ready' && [currentText, item.text].filter(Boolean).join('\n').length > 12000) throw new Error('当前草稿太长，请先处理，再带入分享。');
      item.state = 'appending'; item.contextKey = contextKey;
      await this.write(scope, items);
      return {kind: 'append' as const, text: item.text, voiceId: `voice-${item.id}`};
    });
  }
  dismiss(scope: string, id: string) {
    return this.serial(async () => {
      const items = await this.read(scope), item = items.find(value => value.id === id);
      if (!item || !pending(item)) return;
      item.state = 'dismissed'; item.text = ''; delete item.contextKey;
      await this.write(scope, items);
    });
  }
  acknowledge(scope: string, deliveryId: string, contextKey: string) {
    return this.serial(async () => {
      const items = await this.read(scope), item = items.find(value => `voice-${value.id}` === deliveryId);
      if (!item || item.state !== 'appending' || item.contextKey !== contextKey) return false;
      item.state = 'received'; item.text = ''; delete item.contextKey;
      await this.write(scope, items); return true;
    });
  }
}
