import {PUBLIC_PAJIO_ENDPOINT} from './connection-default';
import {type Connection} from './core';
import {accountCredentials, EnrollmentError, enrollmentResult, inviteCode, recoveryRecord, type EnrollmentRecovery, type EnrollmentResult} from './enrollment-model';
import {type Vault} from './session-protocol';

const KEY = 'pajio.enrollment.v1';
type Proof = {operation_id: string; receipt: string; verifier: string; challenge: string; state: string};
type Action = 'verify' | 'register' | 'status' | 'cancel';
export type EnrollmentSnapshot = {recovery: EnrollmentRecovery | null; result: EnrollmentResult | null};
type Options = {
  vault: Vault; fetcher: typeof fetch; proof: () => Promise<Proof>;
  finish: (pending: EnrollmentRecovery, handoff: {code: string; state: string}, isCurrent: () => boolean) => Promise<Connection>;
  now?: () => number;
};

/** A retained operation is queried, never automatically re-registered after a lost response. */
export class EnrollmentFlow {
  private active = true;
  private busy = false;
  private exchanged = new Set<string>();
  private snapshot: EnrollmentSnapshot = {recovery: null, result: null};
  private now: () => number;
  constructor(private options: Options) {this.now = options.now || Date.now;}
  dispose() {this.active = false;}
  current() {return this.snapshot;}
  private assertActive() {if (!this.active) throw new EnrollmentError('enrollment_inactive');}
  private async run<T>(action: () => Promise<T>): Promise<T> {
    this.assertActive();
    if (this.busy) throw new EnrollmentError('enrollment_busy');
    this.busy = true;
    try {return await action();} finally {this.busy = false;}
  }
  async restore(): Promise<EnrollmentSnapshot> {
    return this.run(async () => {
      let raw: string | null;
      try {raw = await this.options.vault.get(KEY);} catch {throw new EnrollmentError('enrollment_storage');}
      this.assertActive();
      if (raw) {
        try {this.snapshot = {recovery: recoveryRecord(JSON.parse(raw), PUBLIC_PAJIO_ENDPOINT), result: null};}
        catch {throw new EnrollmentError('enrollment_storage');}
      }
      return this.snapshot;
    });
  }
  private pending() {
    this.assertActive();
    const pending = this.snapshot.recovery;
    if (!pending) throw new EnrollmentError('enrollment_invalid');
    if (Date.parse(pending.expires_at) <= this.now()) throw new EnrollmentError('enrollment_expired');
    return pending;
  }
  private async request(action: Action, data: Record<string, unknown>): Promise<EnrollmentSnapshot> {
    const pending = this.pending();
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 30_000);
    try {
      const response = await this.options.fetcher(new URL('/auth/mobile/enrollment/' + action, pending.origin).toString(), {
        method: 'POST', headers: {'Content-Type': 'application/json'}, credentials: 'omit', redirect: 'error',
        body: JSON.stringify(data), signal: controller.signal,
      });
      this.assertActive();
      const raw = await response.text();
      this.assertActive();
      if (raw.length > 8192) throw new EnrollmentError('enrollment_invalid');
      let value: unknown;
      try {value = JSON.parse(raw);} catch {throw new EnrollmentError('enrollment_unconfirmed');}
      const record = value && typeof value === 'object' ? value as Record<string, unknown> : {};
      if (!record.operation_id) {
        const code = typeof record.code === 'string' && /^[a-z_]{1,64}$/.test(record.code) ? record.code : 'enrollment_unconfirmed';
        // The protocol's sole definitive verify rejection creates no server operation.
        // No register or status error has this permission to remove the retained proof.
        if (action === 'verify' && response.status === 422 && Object.keys(record).join() === 'code' && code === 'invitation_unavailable') await this.clearRetained(pending);
        throw new EnrollmentError(code);
      }
      let result = enrollmentResult(value, pending, this.now());
      if (!response.ok && !['pending', 'rejected', 'cancelled'].includes(result.status)) throw new EnrollmentError('enrollment_unconfirmed');
      if (result.handoff && this.exchanged.has(result.handoff.code)) result = {...result, handoff: undefined, next_action: 'existing_login'};
      const updated = {...pending, expires_at: result.expires_at};
      if (updated.expires_at !== pending.expires_at) {
        try {
          const saved = await this.options.vault.get(KEY); this.assertActive();
          if (!saved || recoveryRecord(JSON.parse(saved), PUBLIC_PAJIO_ENDPOINT).operation_id !== pending.operation_id) throw new EnrollmentError('enrollment_storage');
          await this.options.vault.put(KEY, JSON.stringify(updated)); this.assertActive();
        } catch (error) {if (error instanceof EnrollmentError) throw error; throw new EnrollmentError('enrollment_storage');}
      }
      this.snapshot = {recovery: updated, result};
      return this.snapshot;
    } catch (error) {
      if (error instanceof EnrollmentError) throw error;
      throw new EnrollmentError('enrollment_unconfirmed');
    } finally {clearTimeout(timer);}
  }
  async verify(code: string): Promise<EnrollmentSnapshot> {
    return this.run(async () => {
      const valid = inviteCode(code);
      if (this.snapshot.recovery) throw new EnrollmentError('enrollment_unconfirmed');
      // A failed initial restore or interrupted SecureStore write cannot be replaced by a new attempt.
      let saved: string | null;
      try {saved = await this.options.vault.get(KEY);} catch {throw new EnrollmentError('enrollment_storage');}
      this.assertActive();
      if (saved) {
        try {this.snapshot = {recovery: recoveryRecord(JSON.parse(saved), PUBLIC_PAJIO_ENDPOINT), result: null};}
        catch {throw new EnrollmentError('enrollment_storage');}
        throw new EnrollmentError('enrollment_unconfirmed');
      }
      const proof = await this.options.proof(); this.assertActive();
      const pending = recoveryRecord({origin: PUBLIC_PAJIO_ENDPOINT, operation_id: proof.operation_id, receipt: proof.receipt,
        verifier: proof.verifier, state: proof.state, expires_at: new Date(this.now() + 900_000).toISOString()}, PUBLIC_PAJIO_ENDPOINT);
      // The private receipt is durable before any network mutation. No invitation or password is saved.
      try {await this.options.vault.put(KEY, JSON.stringify(pending));} catch {throw new EnrollmentError('enrollment_storage');}
      this.assertActive(); this.snapshot = {recovery: pending, result: null};
      return this.request('verify', {operation_id: pending.operation_id, receipt: pending.receipt, code: valid, challenge: proof.challenge, state: pending.state});
    });
  }
  async register(username: string, password: string): Promise<EnrollmentSnapshot> {
    return this.run(async () => {
      const values = accountCredentials(username, password), pending = this.pending();
      const result = this.snapshot.result;
      if (!result || (result.status !== 'verified' && !(result.status === 'rejected' && ['username_invalid', 'username_unavailable', 'password_invalid'].includes(result.code || '')))) throw new EnrollmentError('enrollment_unconfirmed');
      // Clear the in-memory permission BEFORE dispatch. Even a failed fetch can have reached the service.
      this.snapshot = {recovery: pending, result: null};
      return this.request('register', {...this.proofBody(pending), ...values});
    });
  }
  private proofBody(pending: EnrollmentRecovery) {
    return {operation_id: pending.operation_id, receipt: pending.receipt, verifier: pending.verifier, state: pending.state};
  }
  async status() {return this.run(() => this.request('status', this.proofBody(this.pending())));}
  async cancel() {return this.run(() => this.request('cancel', this.proofBody(this.pending())));}
  async finish(): Promise<Connection> {
    return this.run(async () => {
      const pending = this.pending(), result = this.snapshot.result;
      if (result?.status !== 'completed' || !result.handoff) throw new EnrollmentError('enrollment_unconfirmed');
      this.exchanged.add(result.handoff.code);
      // A one-use handoff is never exchanged twice by this flow, including response loss.
      this.snapshot = {recovery: pending, result: {...result, handoff: undefined, next_action: 'existing_login'}};
      const next = await this.options.finish(pending, result.handoff, () => this.active);
      this.assertActive();
      await this.clearRetained(pending);
      return next;
    });
  }
  private async clearRetained(expected: EnrollmentRecovery) {
    this.assertActive();
    try {
      const current = await this.options.vault.get(KEY); this.assertActive();
      if (!current || recoveryRecord(JSON.parse(current), PUBLIC_PAJIO_ENDPOINT).operation_id !== expected.operation_id) throw new EnrollmentError('enrollment_storage');
      await this.options.vault.remove(KEY); this.assertActive();
      if (await this.options.vault.get(KEY) !== null) throw new EnrollmentError('enrollment_storage');
      this.assertActive(); this.snapshot = {recovery: null, result: null};
    } catch (error) {if (error instanceof EnrollmentError) throw error; throw new EnrollmentError('enrollment_storage');}
  }
  /** Explicit user dismissal only. This does not cancel an already submitted registration. */
  async forget() {return this.run(async () => {
    const pending = this.snapshot.recovery;
    if (!pending) return;
    await this.clearRetained(pending);
  });}
}
