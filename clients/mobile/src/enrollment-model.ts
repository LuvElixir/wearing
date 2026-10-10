/** Native admission contains no model/tool traffic. Secrets never belong in error text. */
export type EnrollmentField = 'code' | 'username' | 'password';
export type EnrollmentStatus = 'verified' | 'pending' | 'rejected' | 'completed' | 'cancelled';
export type EnrollmentRecovery = {
  origin: string; operation_id: string; receipt: string; verifier: string; state: string; expires_at: string;
};
export type EnrollmentResult = {
  operation_id: string; status: EnrollmentStatus; state: string; expires_at: string;
  code?: string; cancel_requested?: boolean; handoff?: {code: string; state: string}; next_action?: 'register' | 'check_status' | 'exchange' | 'existing_login' | 'start_over';
  attempts_remaining?: number; retry_after?: number;
};
export class EnrollmentError extends Error {
  constructor(public code: string, public field?: EnrollmentField) {super(enrollmentErrorText(code));}
}
const messages: Record<string, string> = {
  code_invalid: '请粘贴完整的邀请码。', invitation_unavailable: '这个邀请码已失效或已使用，请核对后再试。',
  username_invalid: '用字母开头，4–32 位小写字母、数字、点、横线或下划线。',
  username_unavailable: '这个账号名已被使用，换一个试试。',
  password_invalid: '密码需要 12–128 个字符，不能包含换行或控制字符。',
  enrollment_expired: '这次加入已过期。若已提交过注册，请先尝试已有账号登录。',
  enrollment_unconfirmed: '还没确认这次提交的结果。可以查询进度，不用重复提交。',
  enrollment_storage: '暂时无法安全保存登录进度，请解锁手机后再试。',
  enrollment_invalid: '登录服务的回执未能通过验证，请查询进度。',
  enrollment_busy: '正在处理这一步，请稍等。', enrollment_inactive: '已离开这次加入流程。',
  enrollment_rate_limited: '操作有点频繁，请稍后再试。', registration_pending: '账号还在确认中，请稍后查询进度。',
  registration_unavailable: '这次注册还没有提交成功，请稍后再试。',
  operation_unavailable: '暂时查不到这次加入。若已经提交注册，请先尝试已有账号登录。',
  operation_expired: '这次加入已过期。若已提交过注册，请先尝试已有账号登录。',
  rate_limited: '操作有点频繁，请稍后再试。', attempts_exhausted: '这次修改次数已用完，请重新核对邀请码或联系邀请人。',
};
export const enrollmentErrorText = (code: string) => messages[code] || messages.enrollment_unconfirmed;
export function base64urlBytes(bytes: Uint8Array): string {
  const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_';
  let result = '', buffer = 0, bits = 0;
  for (const byte of bytes) {buffer = (buffer << 8) | byte; bits += 8; while (bits >= 6) {bits -= 6; result += alphabet[(buffer >>> bits) & 63];}}
  if (bits) result += alphabet[(buffer << (6 - bits)) & 63];
  return result;
}
export function inviteCode(value: string): string {
  const result = value.trim();
  if (!/^pajio_[A-Za-z0-9_-]{43}$/.test(result)) throw new EnrollmentError('code_invalid', 'code');
  return result;
}
export function accountCredentials(username: string, password: string) {
  const name = username.trim().toLowerCase();
  if (!/^[a-z][a-z0-9_.-]{3,31}$/.test(name)) throw new EnrollmentError('username_invalid', 'username');
  const length = Array.from(password).length;
  if (length < 12 || length > 128 || /[\u0000-\u001f\u007f-\u009f\ud800-\udfff]/u.test(password)) throw new EnrollmentError('password_invalid', 'password');
  return {username: name, password};
}
export function recoveryRecord(raw: unknown, origin: string): EnrollmentRecovery {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) throw new EnrollmentError('enrollment_invalid');
  const v = raw as Record<string, unknown>;
  if (Object.keys(v).sort().join() !== 'expires_at,operation_id,origin,receipt,state,verifier' || v.origin !== origin ||
      typeof v.operation_id !== 'string' || !/^[a-f0-9]{32}$/.test(v.operation_id) ||
      typeof v.receipt !== 'string' || !/^[A-Za-z0-9_-]{43}$/.test(v.receipt) ||
      typeof v.verifier !== 'string' || !/^[A-Za-z0-9._~-]{43,128}$/.test(v.verifier) ||
      typeof v.state !== 'string' || !/^[A-Za-z0-9_-]{32,128}$/.test(v.state) ||
      typeof v.expires_at !== 'string' || !Number.isFinite(Date.parse(v.expires_at))) throw new EnrollmentError('enrollment_invalid');
  return v as EnrollmentRecovery;
}
export function enrollmentResult(raw: unknown, pending: EnrollmentRecovery, now = Date.now()): EnrollmentResult {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) throw new EnrollmentError('enrollment_invalid');
  const v = raw as Record<string, unknown>;
  const statuses = ['verified', 'pending', 'rejected', 'completed', 'cancelled'];
  if (v.operation_id !== pending.operation_id || v.state !== pending.state || !statuses.includes(String(v.status)) ||
      typeof v.expires_at !== 'string' || !Number.isFinite(Date.parse(v.expires_at)) || Date.parse(v.expires_at) > now + 901_000 ||
      (v.code !== undefined && (typeof v.code !== 'string' || !/^[a-z_]{1,64}$/.test(v.code))) ||
      (v.cancel_requested !== undefined && typeof v.cancel_requested !== 'boolean') ||
      (v.next_action !== undefined && !['register', 'check_status', 'exchange', 'existing_login', 'start_over'].includes(String(v.next_action))) ||
      (v.attempts_remaining !== undefined && (!Number.isInteger(v.attempts_remaining) || Number(v.attempts_remaining) < 0 || Number(v.attempts_remaining) > 5)) ||
      (v.retry_after !== undefined && (!Number.isInteger(v.retry_after) || Number(v.retry_after) < 0 || Number(v.retry_after) > 900))) throw new EnrollmentError('enrollment_invalid');
  if (v.handoff !== undefined) {
    const handoff = v.handoff as Record<string, unknown>;
    if (v.status !== 'completed' || !handoff || typeof handoff !== 'object' || Object.keys(handoff).sort().join() !== 'code,state' ||
        typeof handoff.code !== 'string' || !/^[A-Za-z0-9_-]{43}$/.test(handoff.code) || handoff.state !== pending.state ||
        (v.next_action !== undefined && v.next_action !== 'exchange') || v.cancel_requested === true) throw new EnrollmentError('enrollment_invalid');
  }
  return v as EnrollmentResult;
}
export function enrollmentFieldFor(code?: string): EnrollmentField | undefined {
  return code === 'username_invalid' || code === 'username_unavailable' ? 'username' : code === 'password_invalid' ? 'password' : code === 'invitation_unavailable' || code === 'code_invalid' ? 'code' : undefined;
}
