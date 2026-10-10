/** Bounded foreground reads. Never accepts a mutation function or replays credentials. */
export type ReadPollState = {busy: boolean; stopped: boolean; exhausted: boolean};
type Options<T> = {
  read: (signal: AbortSignal) => Promise<T>;
  accept: (value: T) => number | null;
  error: (error: unknown) => boolean; // true: stop until an explicit refresh
  change?: (state: ReadPollState) => void;
  limit?: number;
  schedule?: (callback: () => void, delay: number) => unknown;
  cancel?: (timer: unknown) => void;
};
export class ReadOnlyPoll<T> {
  private active = true;
  private foreground = false;
  private generation = 0;
  private attempts = 0;
  private failures = 0;
  private stopped = false;
  private inFlight = false;
  private timer: unknown;
  private controller?: AbortController;
  private delay = 0;
  private schedule: NonNullable<Options<T>['schedule']>;
  private cancel: NonNullable<Options<T>['cancel']>;
  constructor(private options: Options<T>) {
    this.schedule = options.schedule || ((callback, delay) => setTimeout(callback, delay));
    this.cancel = options.cancel || (timer => clearTimeout(timer as ReturnType<typeof setTimeout>));
  }
  private clear() {if (this.timer !== undefined) this.cancel(this.timer); this.timer = undefined;}
  private notify() {if (this.active) this.options.change?.({busy: this.inFlight, stopped: this.stopped, exhausted: this.attempts >= (this.options.limit || 20)});}
  setForeground(value: boolean, delay?: number) {
    if (!this.active || this.foreground === value) return;
    this.foreground = value;
    if (!value) {this.generation++; this.clear(); this.controller?.abort();}
    else {if (delay !== undefined) this.delay = Math.max(0, Math.min(900000, delay)); this.queue(this.delay);}
    this.notify();
  }
  /** User action resets only the read budget, never a registration/provisioning operation. */
  refresh() {
    if (!this.active || this.inFlight) return;
    this.clear(); this.attempts = 0; this.failures = 0; this.stopped = false; this.delay = 0;
    this.queue(0); this.notify();
  }
  dispose() {this.active = false; this.generation++; this.clear(); this.controller?.abort();}
  private queue(delay: number) {
    if (!this.active || !this.foreground || this.inFlight || this.stopped || this.timer !== undefined || this.attempts >= (this.options.limit || 20)) return;
    this.timer = this.schedule(() => {this.timer = undefined; void this.poll();}, delay);
  }
  private async poll() {
    if (!this.active || !this.foreground || this.inFlight || this.stopped) return;
    const generation = this.generation, controller = new AbortController();
    this.controller = controller; this.inFlight = true; this.attempts++; this.notify();
    const valid = () => this.active && this.foreground && this.generation === generation && !controller.signal.aborted;
    try {
      const value = await this.options.read(controller.signal);
      if (valid()) {
        this.failures = 0;
        const next = this.options.accept(value);
        this.stopped = next === null; this.delay = next === null ? 0 : Math.max(3000, Math.min(900000, next));
      }
    } catch (error) {
      if (valid()) {this.failures++; this.stopped = this.options.error(error) || this.failures >= 3; this.delay = Math.min(30000, 3000 * 2 ** this.failures);}
    } finally {
      this.inFlight = false; this.controller = undefined;
      this.notify(); this.queue(this.delay);
    }
  }
}
