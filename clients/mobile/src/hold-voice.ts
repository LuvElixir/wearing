export type HoldVoicePhase = 'idle' | 'pressing' | 'listening' | 'cancelling';

export type HoldVoiceCallbacks = {
  onPhase: (phase: HoldVoicePhase) => void;
  onStart: () => void;
  onCommit: () => void;
  onCancel: () => void;
  onShortPress: () => void;
};

export type HoldVoiceTiming = {
  now: () => number;
  setTimeout: (callback: () => void, delayMs: number) => unknown;
  clearTimeout: (handle: unknown) => void;
};

const defaultTiming: HoldVoiceTiming = {
  now: () => Date.now(),
  setTimeout: (callback, delayMs) => setTimeout(callback, delayMs),
  clearTimeout: handle => clearTimeout(handle as ReturnType<typeof setTimeout>),
};

/** A gesture only: the caller owns recording, permission and transcription lifetimes. */
export class HoldVoiceGesture {
  private currentPhase: HoldVoicePhase = 'idle';
  private readonly clock: HoldVoiceTiming;
  private held = false;
  private started = false;
  private readyToStart = false;
  private cancelRegion = false;
  private beganAt = 0;
  private generation = 0;
  private timer: unknown;
  private disposed = false;
  private settling = false;

  constructor(private readonly callbacks: HoldVoiceCallbacks, timing: Partial<HoldVoiceTiming> = {}) {
    this.clock = {...defaultTiming, ...timing};
  }

  get phase(): HoldVoicePhase {return this.currentPhase;}

  begin(): void {
    if (this.disposed || this.held || this.settling) return;
    this.held = true;
    this.beganAt = this.clock.now();
    const generation = ++this.generation;
    this.changePhase('pressing');
    // A phase observer may have cancelled or disposed the gesture synchronously.
    if (!this.held || generation !== this.generation) return;
    this.timer = this.clock.setTimeout(() => {
      if (this.disposed || !this.held || generation !== this.generation) return;
      this.timer = undefined;
      this.readyToStart = true;
      this.startIfReady();
    }, 220);
  }

  /** dy is displacement from the original touch, never from the last move. */
  move(dy: number): void {
    if (!this.held || this.disposed || !Number.isFinite(dy)) return;
    if (!this.cancelRegion && dy <= -64) {
      this.cancelRegion = true;
      this.changePhase('cancelling');
    } else if (this.cancelRegion && dy > -40) {
      this.cancelRegion = false;
      if (this.started) this.changePhase('listening');
      else if (this.readyToStart) this.startIfReady();
      else this.changePhase('pressing');
    }
  }

  release(): void {
    if (!this.held || this.disposed || this.settling) return;
    const outcome = this.cancelRegion ? 'cancel' :
      !this.started || this.clock.now() - this.beganAt < 600 ? 'short' : 'commit';
    this.settle(outcome);
  }

  /** Gesture loss, navigation or backgrounding never commits or shows a short-press hint. */
  cancel(): void {
    if (!this.held || this.settling) return;
    this.settle('cancel');
  }

  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    this.cancel();
    this.clearTimer();
  }

  private startIfReady(): void {
    if (!this.held || this.disposed || !this.readyToStart || this.cancelRegion || this.started) return;
    const generation = this.generation;
    this.changePhase('listening');
    if (!this.held || this.disposed || this.cancelRegion || generation !== this.generation) return;
    this.started = true;
    this.callbacks.onStart();
  }

  private changePhase(phase: HoldVoicePhase): void {
    if (this.currentPhase === phase) return;
    this.currentPhase = phase;
    this.callbacks.onPhase(phase);
  }

  private clearTimer(): void {
    if (this.timer !== undefined) this.clock.clearTimeout(this.timer);
    this.timer = undefined;
  }

  private settle(outcome: 'commit' | 'short' | 'cancel'): void {
    this.settling = true;
    const started = this.started;
    this.clearTimer();
    this.held = false;
    this.started = false;
    this.readyToStart = false;
    this.cancelRegion = false;
    ++this.generation;
    try {
      this.changePhase('idle');
      if (outcome === 'commit' && !this.disposed) this.callbacks.onCommit();
      else {
        if (started) this.callbacks.onCancel();
        if (outcome === 'short' && !this.disposed) this.callbacks.onShortPress();
      }
    } finally {
      this.settling = false;
    }
  }
}
