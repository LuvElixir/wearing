import type {OutfitId} from './wardrobe';

export type WardrobeFrame = {outfit: OutfitId; key: number};
export type WardrobePreviewState = {
  shown: WardrobeFrame;
  requested: WardrobeFrame;
  phase: 'loading' | 'closing' | 'opening' | 'ready' | 'error';
  revision: number;
};

/** A decoded preview becomes visible only after the curtain closes. Every async
 * callback belongs to one request, so a slower, older selection cannot win. */
export class WardrobeTransition {
  private state: WardrobePreviewState;
  private listeners = new Set<() => void>();
  private frameId = 0;
  private shownReady = false;
  private reduced = true;

  constructor(outfit: OutfitId) {
    const frame = {outfit, key: this.frameId};
    this.state = {shown: frame, requested: frame, phase: 'loading', revision: 0};
  }
  snapshot = () => this.state;
  subscribe = (listener: () => void) => {this.listeners.add(listener); return () => {this.listeners.delete(listener);};};
  private update(change: Partial<WardrobePreviewState>) {
    this.state = {...this.state, ...change};
    this.listeners.forEach(listener => listener());
  }

  select = (outfit: OutfitId, reduced: boolean) => {
    this.reduced = reduced;
    if (outfit === this.state.requested.outfit) {
      if (reduced && (this.state.phase === 'closing' || this.state.phase === 'opening')) {
        this.shownReady = true;
        this.update({shown: this.state.requested, phase: 'ready', revision: this.state.revision + 1});
      }
      return;
    }
    const revision = this.state.revision + 1;
    if (outfit === this.state.shown.outfit && this.shownReady) {
      this.update({requested: this.state.shown, phase: 'ready', revision});
    } else {
      this.update({requested: {outfit, key: ++this.frameId}, phase: 'loading', revision});
    }
  };

  loaded = (frameKey: number) => {
    if (frameKey === this.state.shown.key) this.shownReady = true;
    if (frameKey !== this.state.requested.key || this.state.phase !== 'loading') return;
    if (this.reduced || frameKey === this.state.shown.key) {
      this.shownReady = true;
      this.update({shown: this.state.requested, phase: 'ready'});
    } else this.update({phase: 'closing'});
  };
  failed = (frameKey: number) => {
    if (frameKey === this.state.requested.key && this.state.phase === 'loading') this.update({phase: 'error'});
  };
  retry = () => {
    if (this.state.phase !== 'error') return;
    this.update({requested: {outfit: this.state.requested.outfit, key: ++this.frameId}, phase: 'loading', revision: this.state.revision + 1});
  };
  closed = (revision: number) => {
    if (revision !== this.state.revision || this.state.phase !== 'closing') return;
    this.shownReady = true;
    this.update({shown: this.state.requested, phase: 'opening'});
  };
  opened = (revision: number) => {
    if (revision === this.state.revision && this.state.phase === 'opening') this.update({phase: 'ready'});
  };
  cancel = () => {
    this.update({requested: this.state.shown, phase: this.shownReady ? 'ready' : 'loading', revision: this.state.revision + 1});
  };
}

export function wardrobePreviewReady(state: WardrobePreviewState, selected: OutfitId) {
  return state.phase === 'ready' && state.shown.outfit === selected && state.requested.outfit === selected;
}
