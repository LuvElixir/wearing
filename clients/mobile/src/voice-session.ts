import {scopeOf, type Connection, type Media, type Store} from './core';
import {measureVoice, voiceErrorMessage, type VoiceDiagnostic, type VoiceStage} from './voice-diagnostics';

export type VoiceText = {id: string; identity: string; scope: string; text: string};
export type VoiceDraft = {id: string; uri?: string; media?: Media; asset?: string; text?: string; acknowledged?: boolean; name?: string; mime?: string};
export type VoicePhase = 'idle' | 'preparing' | 'recording' | 'saving' | 'transcribing';
export type VoiceState = {phase: VoicePhase; ready: boolean; message: string; draft: VoiceDraft | null};
export type RecordedAudio = {uri: string; name: string; mime: string};
export type VoiceRecorder = {
  prepare(held: () => boolean): Promise<boolean>;
  record(): void | Promise<void>;
  stop(): Promise<RecordedAudio>;
  /** Also releases a prepared recorder which never started. */
  dispose(): Promise<void>;
  durationMillis(): number;
  recognition?(): Promise<{text: string}>;
  abortRecognition?(): void;
  pauseRecognition?(paused: boolean): void;
  discard?(): void;
};
export type VoiceSessionDependencies = {
  connection: Connection;
  store: Store;
  recorder(take: string): VoiceRecorder;
  keepMedia(uri: string, media: Media): Promise<Media>;
  upload(media: Media, blob: Blob, requestKey: string): Promise<string>;
  transcribe(asset: string): Promise<{text: string}>;
  newId(): string;
  isAvailable(): boolean;
  onText(text: VoiceText): void;
  onDiagnostic?(event: VoiceDiagnostic): void;
};

type Take = {id: string; outcome: 'commit' | 'cancel' | 'interrupt' | null; recorder?: VoiceRecorder; started: boolean; preparing: Promise<void>; finishing?: Promise<void>; unlock?: () => void};
const messageOf = voiceErrorMessage;

// Identity changes can overlap asynchronous microphone preparation. The previous
// owner must release its recorder before the next owner can acquire the device.
let microphone = Promise.resolve();
async function acquireMicrophone() {
  const previous = microphone;
  let unlock!: () => void;
  microphone = new Promise<void>(resolve => {unlock = resolve;});
  await previous;
  return unlock;
}

// Serialize acknowledgement and late results, including across hook remounts.
const writes = new WeakMap<Store, Map<string, Promise<unknown>>>();
function exclusive<T>(store: Store, key: string, work: () => Promise<T>): Promise<T> {
  let keys = writes.get(store);
  if (!keys) {keys = new Map(); writes.set(store, keys);}
  const result = (keys.get(key) ?? Promise.resolve()).then(work, work);
  const settled = result.catch(() => {});
  keys.set(key, settled);
  void settled.then(() => {if (keys!.get(key) === settled) keys!.delete(key);});
  return result;
}

/** Owns recording intent and durable recovery; it has no message-send operation. */
export class VoiceSession {
  readonly scope: string;
  readonly key: string;
  private state: VoiceState = {phase: 'idle', ready: false, message: '', draft: null};
  private listeners = new Set<() => void>();
  private take: Take | null = null;
  private disposed = false;
  private epoch = 0;
  private operation: Promise<void> | null = null;
  private restoring: Promise<void> | null = null;
  private receiptTiming: {id: string; started: number} | null = null;

  constructor(private deps: VoiceSessionDependencies) {
    this.scope = scopeOf(deps.connection);
    this.key = 'voice-input:' + this.scope;
  }
  getSnapshot = () => this.state;
  subscribe = (listener: () => void) => {this.listeners.add(listener); return () => {this.listeners.delete(listener);};};
  /** React effect replay may reattach; interrupted work never resumes recording. */
  activate = () => {this.disposed = false;};
  get canStart() {return !this.disposed && this.state.ready && this.state.phase === 'idle' && !this.take && !this.operation && (!this.state.draft || this.state.draft.acknowledged === true);}
  durationMillis = () => this.take?.started ? this.take.recorder?.durationMillis() ?? 0 : 0;
  private available() {return !this.disposed && this.deps.isAvailable();}
  private measured<T>(stage: VoiceStage, work: () => Promise<T>) {return measureVoice(stage, work, this.deps.onDiagnostic);}
  private publish(patch: Partial<VoiceState>) {
    this.state = {...this.state, ...patch};
    if (!this.disposed) this.listeners.forEach(listener => listener());
  }

  restore = (): Promise<void> => {
    if (this.restoring) return this.restoring;
    if (this.state.ready) return Promise.resolve();
    this.restoring = exclusive(this.deps.store, this.key, async () => {
      try {
        const draft = await this.measured('restore', () => this.deps.store.get<VoiceDraft>(this.key));
        this.publish({draft, ready: true, phase: 'idle', message: draft && !draft.acknowledged ? draft.text ? '上次的语音文字还在，可带入输入框。' : '上次的录音还在，可以继续识别。' : ''});
      } catch (error) {
        this.publish({ready: false, phase: 'idle', message: messageOf(error, '本机语音暂时无法读取，请重试。')});
      }
    }).finally(() => {this.restoring = null;});
    return this.restoring;
  };

  start = (): Promise<void> => {
    if (!this.canStart || !this.available()) return Promise.resolve();
    const take: Take = {id: 'voice-' + this.deps.newId(), outcome: null, started: false, preparing: Promise.resolve()};
    this.take = take;
    this.publish({phase: 'preparing', message: '正在准备麦克风…'});
    take.preparing = this.prepare(take);
    return take.preparing;
  };
  private async prepare(take: Take) {
    const held = () => this.available() && this.take === take && take.outcome === null;
    try {
      take.unlock = await acquireMicrophone();
      if (!held()) return;
      take.recorder = this.deps.recorder(take.id);
      if (!(await this.measured('prepare', () => take.recorder!.prepare(held))) || !held()) return;
      await take.recorder.record();
      take.started = true;
      if (held()) this.publish({phase: 'recording', message: '正在听，松开转成文字，上滑取消。'});
    } catch (error) {
      this.publish({message: messageOf(error, '麦克风暂时不可用，可以先打字。')});
    } finally {
      if (!take.started) {
        take.recorder?.abortRecognition?.();
        await this.releaseRecorder(take);
        try {take.recorder?.discard?.();}
        catch {this.publish({message: '录音准备未完成，可以重新按住说话。'});}
        if (this.take === take) this.take = null;
        this.publish({phase: 'idle', ...(take.outcome === 'commit' ? {message: '刚才还未开始录音，请按住再说一次。'} : take.outcome === 'cancel' ? {message: '已取消录音。'} : take.outcome === 'interrupt' ? {message: '录音未开始，可以重新按住说话。'} : {})});
      }
    }
  }

  commit = () => this.finish('commit');
  pauseRecognition = (paused: boolean) => this.take?.recorder?.pauseRecognition?.(paused);
  cancel = () => {this.epoch++; return this.finish('cancel');};
  /** Navigation, background and unmount stop remote processing and preserve local audio. */
  interrupt = () => {this.epoch++; return this.finish('interrupt');};
  private finish(outcome: NonNullable<Take['outcome']>): Promise<void> {
    const take = this.take;
    if (!take) return Promise.resolve();
    if (!take.outcome || outcome === 'cancel' || (outcome === 'interrupt' && take.outcome === 'commit')) take.outcome = outcome;
    if (outcome !== 'commit') take.recorder?.abortRecognition?.();
    if (!take.finishing) take.finishing = take.preparing.then(() => this.finishPrepared(take));
    return take.finishing;
  }
  private async releaseRecorder(take: Take) {
    try {await this.measured('release', async () => {await take.recorder?.dispose();});}
    catch (error) {this.publish({message: messageOf(error, '麦克风释放未完成，请检查系统麦克风状态。')});}
    finally {take.unlock?.(); take.unlock = undefined;}
  }
  private async finishPrepared(take: Take) {
    if (!take.started || !take.recorder) return;
    this.receiptTiming = take.outcome === 'commit' ? {id: take.id, started: performance.now()} : null;
    const deliveryEpoch = this.epoch;
    this.publish({phase: 'saving', message: take.outcome === 'cancel' ? '正在取消…' : '正在保存录音…'});
    let audio: RecordedAudio | undefined;
    try {audio = await this.measured('stop', () => take.recorder!.stop());}
    catch (error) {this.publish({message: messageOf(error, '录音未能保存完整，请再试一次。')});}
    finally {take.started = false; await this.releaseRecorder(take);}
    try {
      if (take.outcome === 'cancel') {take.recorder.discard?.(); this.publish({message: '已取消录音。'}); return;}
      if (!audio?.uri) return;
      // Keep the document URI first. A failed copy or offline service can never
      // erase the only pointer to a successfully stopped recording.
      let draft: VoiceDraft = {id: take.id, ...audio};
      this.publish({draft});
      await this.save(draft, true);
      draft = await this.ensureMedia(draft);
      if (take.outcome === 'commit' && this.available() && deliveryEpoch === this.epoch) await this.recognize(draft, deliveryEpoch, take.recorder.recognition?.bind(take.recorder));
      else this.publish({message: '录音已保存在本机，可继续识别。'});
    } catch (error) {this.publish({message: messageOf(error, '识别未完成，录音还在，可以重试。')});}
    finally {
      // Also close a live session when local persistence fails before finalization.
      // Successful/previously cancelled sessions ignore this idempotent cleanup.
      take.recorder.abortRecognition?.();
      if (this.take === take) this.take = null;
      this.publish({phase: 'idle'});
    }
  }

  private save(draft: VoiceDraft, initial = false): Promise<VoiceDraft> {
    return this.measured('save', () => exclusive(this.deps.store, this.key, async () => {
      const current = await this.deps.store.get<VoiceDraft>(this.key);
      if (initial ? current && current.id !== draft.id && !current.acknowledged : !current || current.id !== draft.id) throw new Error('另一段语音已更新，请重新打开后查看。');
      const saved = {...draft, acknowledged: current?.id === draft.id && current.acknowledged === true};
      await this.deps.store.batch([[this.key, saved], ['voice-original:' + this.scope + ':' + draft.id, saved]]);
      this.publish({draft: saved});
      return saved;
    }));
  }
  private async ensureMedia(draft: VoiceDraft) {
    if (draft.media) return draft;
    if (!draft.uri) throw new Error('录音原件暂时无法读取，请保留当前记录。');
    const media = await this.measured('copy', () => this.deps.keepMedia(draft.uri!, {id: this.deps.newId(), name: draft.name ?? '语音输入.m4a', mime: draft.mime ?? 'audio/mp4', size: 0}));
    return this.save({...draft, media});
  }
  private async recognize(original: VoiceDraft, deliveryEpoch: number, live?: () => Promise<{text: string}>) {
    let draft = await this.save(original, true);
    this.publish({phase: 'transcribing', message: ''});
    if (!draft.text) {
      draft = await this.ensureMedia(draft);
      if (!this.available() || deliveryEpoch !== this.epoch) return;
      if (!live && !draft.asset) {
        const media = draft.media!;
        const blob = await this.measured('read_audio', () => this.deps.store.blob(media.id));
        if (!this.available() || deliveryEpoch !== this.epoch) return;
        draft = await this.save({...draft, asset: await this.measured('upload', () => this.deps.upload(media, blob, draft.id))});
      }
      if (!this.available() || deliveryEpoch !== this.epoch) return;
      const result = await this.measured('transcribe', () => live ? live() : this.deps.transcribe(draft.asset!));
      if (typeof result.text !== 'string' || !result.text.trim() || result.text.length > 12000) throw new Error('没有收到完整的语音文字，录音仍然保留。');
      draft = await this.save({...draft, text: result.text});
    }
    if (this.available() && deliveryEpoch === this.epoch) {
      this.publish({message: ''});
      this.deps.onText({id: draft.id, identity: this.deps.connection.identity, scope: this.scope, text: draft.text!});
    } else this.publish({message: '录音和已识别的文字保存在本机。'});
  }

  retry = (): Promise<void> => {
    if (!this.available() || this.take || this.operation) return this.operation ?? Promise.resolve();
    if (!this.state.ready) return this.restore();
    const draft = this.state.draft;
    if (!draft) return Promise.resolve();
    const epoch = this.epoch;
    this.operation = this.recognize(draft, epoch)
      .catch(error => {this.publish({message: messageOf(error, '识别未完成，录音还在，可以重试。')});})
      .finally(() => {this.operation = null; this.publish({phase: 'idle'});});
    return this.operation;
  };
  /** Call only after this exact transcription has entered the editable draft. */
  ack = (id: string): Promise<void> => exclusive(this.deps.store, this.key, async () => {
    try {
      const current = await this.deps.store.get<VoiceDraft>(this.key);
      if (!current || current.id !== id || !current.text) return;
      // WebView snapshots repeat the latest receipt on every edit. It is not a
      // new save operation, including after a remount or a late snapshot.
      if (current.acknowledged) {
        if (this.state.draft?.id === id && !this.state.draft.acknowledged) this.publish({draft: current, message: ''});
        return;
      }
      const draft = {...current, acknowledged: true};
      await this.measured('ack', () => this.deps.store.batch([[this.key, draft], ['voice-original:' + this.scope + ':' + id, draft]]));
      if (this.receiptTiming?.id === id) {
        try {this.deps.onDiagnostic?.({stage: 'release_to_draft', elapsedMs: Math.max(0, Math.round(performance.now() - this.receiptTiming.started)), outcome: 'ok'});}
        catch {/* Telemetry cannot invalidate a saved receipt. */}
        this.receiptTiming = null;
      }
      if (this.state.draft?.id === id) this.publish({draft, message: ''});
    } catch (error) {this.publish({message: messageOf(error, '文字已识别，语音回执暂时未保存。')});}
  });
  dispose = (): Promise<void> => {
    this.disposed = true;
    return this.interrupt();
  };
}
