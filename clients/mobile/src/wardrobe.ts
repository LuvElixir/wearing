import type {Store} from './core';

export const outfits = [
  {id: 'mist-blue', name: '雾蓝条纹', detail: '细条纹、奶油滚边，熟悉的柔软。', swatch: '#A9B9CC'},
  {id: 'cream-moon', name: '奶油月牙', detail: '把一弯小月亮，收进睡衣口袋。', swatch: '#E8D7B9'},
  {id: 'peach-check', name: '杏桃方格', detail: '杏桃格纹，配一圈小小的花瓣领。', swatch: '#DDB0A0'},
  {id: 'oat-knit', name: '燕麦针织', detail: '软软的针织纹理，像刚晒好的毯子。', swatch: '#CABBA6'},
  {id: 'cocoa-moon', name: '热可可', detail: '可可色的夜晚，落着奶白色月牙。', swatch: '#88614E'},
  {id: 'butter-cloud', name: '黄油云朵', detail: '淡淡的黄油色，口袋是一朵云。', swatch: '#EDDC9F'},
  {id: 'sage-check', name: '鼠尾草格纹', detail: '温柔的绿，和自然亚麻色的领口。', swatch: '#A4AC98'},
  {id: 'rose-dot', name: '玫瑰奶点', detail: '低饱和的玫瑰色，洒一点奶白。', swatch: '#C49694'},
] as const;
export type OutfitId = typeof outfits[number]['id'];
export const defaultOutfit: OutfitId = 'mist-blue';
export function isOutfit(value: unknown): value is OutfitId {return outfits.some(outfit => outfit.id === value);}
export function outfitById(id: OutfitId) {return outfits.find(outfit => outfit.id === id)!;}
export type CompanionPreference = 'bear';
export const wardrobeKey = (scope: string) => `wardrobe:v2:${scope}`;
const legacyWardrobeKey = (scope: string) => `wardrobe:v1:${scope}`;
const isSavedCompanion = (value: unknown) => value === 'symbol' || value === 'bear';
type SavedWardrobe = {version?: number; outfit?: unknown; companion?: unknown};
export type WardrobeState = {outfit: OutfitId; companion: CompanionPreference; ready: boolean; loading: boolean; saving: boolean; error: string};

/** One instance per service/identity. Async replies can only update their own session. */
export class WardrobeSession {
  private state: WardrobeState = {outfit: defaultOutfit, companion: 'bear', ready: false, loading: true, saving: false, error: ''};
  private listeners = new Set<() => void>();
  private loading: Promise<void> | null = null;
  constructor(private store: Pick<Store, 'get' | 'put'>, readonly scope: string) {}
  snapshot = () => this.state;
  subscribe = (listener: () => void) => {this.listeners.add(listener); return () => {this.listeners.delete(listener);};};
  private update(change: Partial<WardrobeState>) {this.state = {...this.state, ...change}; this.listeners.forEach(listener => listener());}
  load = (): Promise<void> => {
    if (this.loading) return this.loading;
    if (this.state.ready) return Promise.resolve();
    this.update({loading: true, error: ''});
    this.loading = (async () => {
      try {
        const saved = await this.store.get<SavedWardrobe>(wardrobeKey(this.scope));
        // Keep saved outfits, including legacy symbol mode. Pajio now always uses the bear.
        // Loading never rewrites the recoverable v1/v2 record.
        const legacy = saved == null ? await this.store.get<SavedWardrobe>(legacyWardrobeKey(this.scope)) : null;
        const valid = saved?.version === 2 && isOutfit(saved.outfit) && isSavedCompanion(saved.companion);
        const chosenBefore = legacy?.version === 1 && isOutfit(legacy.outfit);
        this.update({
          outfit: valid ? saved.outfit as OutfitId : chosenBefore ? legacy.outfit as OutfitId : defaultOutfit,
          companion: 'bear',
          ready: true, loading: false,
        });
      } catch {this.update({loading: false, error: '没能读到上次的形象设置，请重试。'});}
      finally {this.loading = null;}
    })();
    return this.loading;
  };
  /** Explicitly choosing an outfit also enables the bear, including the current outfit. */
  save = (outfit: OutfitId): Promise<boolean> => this.persist(outfit, 'bear');
  private persist = async (outfit: OutfitId, companion: CompanionPreference): Promise<boolean> => {
    if (!this.state.ready || this.state.saving || !isOutfit(outfit) || companion !== 'bear') return false;
    if (outfit === this.state.outfit && companion === this.state.companion) {this.update({error: ''}); return true;}
    this.update({saving: true, error: ''});
    try {
      await this.store.put(wardrobeKey(this.scope), {version: 2, outfit, companion});
      this.update({outfit, companion, saving: false});
      return true;
    } catch {
      this.update({saving: false, error: '形象设置还没保存好，点一下再试。'});
      return false;
    }
  };
}
