export const voiceQuotaMessages: Record<string,string> = {
  quota_exhausted:'试用执行额度已用完；仍可查看结果、读取原件和暂停任务。',
  quota_busy:'已有调用正在处理，请稍后再试。',
  quota_duplicate:'这次语音已提交，请查看已有结果，录音原件仍保留。',
  quota_unavailable:'暂时无法核对试用额度，请稍后重试。',
};
export type VoiceStage = 'restore' | 'prepare' | 'stop' | 'release' | 'save' | 'copy' | 'read_audio' | 'upload' | 'transcribe' | 'ack' | 'release_to_draft';
export type VoiceDiagnostic = {stage: VoiceStage; elapsedMs: number; outcome: 'ok' | 'error'; code?: string};

// Only app-authored, actionable messages can reach the input. Native exceptions
// and arbitrary server bodies belong in neither a toast nor diagnostics.
const messages = new Set([
  '麦克风未获允许，可以改用文字输入。',
  '当前浏览器无法录音，可以改用文字输入。',
  '浏览器录音中断，请再试一次。',
  '这段录音太短，请按住再说一次。',
  '另一段语音已更新，请重新打开后查看。',
  '录音原件暂时无法读取，请保留当前记录。',
  '没有收到完整的语音文字，录音仍然保留。',
]);
export function voiceErrorCode(error: unknown): string {
  if(error && typeof error === 'object' && 'code' in error && typeof error.code==='string' && voiceQuotaMessages[error.code])return error.code;
  const text = error instanceof Error ? error.message : typeof error === 'string' ? error : '';
  if (/database (?:table |schema )?is locked|SQLITE_(?:BUSY|LOCKED)\b/i.test(text)) return 'storage_busy';
  if (/SQLite|disk|ENOSPC|本机保存|原件.*(?:读取|保存)/i.test(text)) return 'storage_unavailable';
  if (/permission|NotAllowed|麦克风未获允许/i.test(text)) return 'permission_denied';
  if (/network|offline|fetch failed|连接|网络/i.test(text)) return 'network_unavailable';
  if (/timeout|timed out|超时/i.test(text)) return 'timeout';
  if (/ASR|识别|转写|听清/i.test(text)) return 'recognition_unavailable';
  return 'unavailable';
}
export function voiceErrorMessage(error: unknown, fallback: string): string {
  const message = error instanceof Error ? error.message : '';
  if (voiceQuotaMessages[voiceErrorCode(error)]) return voiceQuotaMessages[voiceErrorCode(error)];
  if (Object.values(voiceQuotaMessages).includes(message)) return message;
  if (messages.has(message)) return message;
  if (message === '没有听清这段话，录音已保留。可以重录或用文字输入。') return '没有听清，可以再试一次或打字。';
  if (message === '正在处理上一份原件，录音已保存，请稍后重试。') return '上一段还在处理，稍后点继续识别。';
  if (voiceErrorCode(error) === 'permission_denied') return '麦克风未获允许，可以改用文字输入。';
  return fallback;
}

/** Reports only stage, duration and a bounded code, never audio/text/paths/IDs. */
export async function measureVoice<T>(stage: VoiceStage, work: () => Promise<T>, report?: (event: VoiceDiagnostic) => void): Promise<T> {
  const started = performance.now();
  let outcome: VoiceDiagnostic['outcome'] = 'ok', code: string | undefined;
  try {return await work();} catch (error) {outcome = 'error'; code = voiceErrorCode(error); throw error;}
  finally {
    try {report?.({stage, elapsedMs: Math.max(0, Math.round(performance.now() - started)), outcome, ...(code ? {code} : {})});}
    catch {/* Diagnostics must never change recording, persistence or delivery. */}
  }
}
