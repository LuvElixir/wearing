import {Platform} from 'react-native';
import {AudioModule, RecordingPresets, setAudioModeAsync} from 'expo-audio';
import type {AudioRecorder, AudioStream} from 'expo-audio';
import {Directory, File, Paths, type FileHandle} from 'expo-file-system';
import type {VoiceRecorder} from './voice-session';
import type {LiveRecognition} from './voice-stream';
import {VoicePcm, wavHeader} from './voice-pcm';

/** One Expo recorder per take; release happens after stop has returned its URI. */
export function createVoiceRecorder(live?: {take: string; connect: () => LiveRecognition}): VoiceRecorder {
  // Keep the known file recorder for web/older native runtimes. No second mic.
  // eslint-disable-next-line import/namespace
  if (live && Platform.OS === 'ios' && typeof AudioModule.AudioStream === 'function') return createPcmRecorder(live);
  let recorder: AudioRecorder | null = null;
  let configured = false;
  return {
    async prepare(held) {
      if (!(await AudioModule.requestRecordingPermissionsAsync()).granted) throw new Error('麦克风未获允许，可以改用文字输入。');
      if (!held()) return false;
      await setAudioModeAsync({allowsRecording: true, playsInSilentMode: true, allowsBackgroundRecording: false, shouldPlayInBackground: false});
      configured = true;
      if (!held()) return false;
      const preset = RecordingPresets.HIGH_QUALITY;
      // Expo exports this native constructor through the typed AudioModule value.
      // eslint-disable-next-line import/namespace
      recorder = new AudioModule.AudioRecorder({...preset, ...(Platform.OS === 'ios' ? preset.ios : preset.android), numberOfChannels: 1, bitRate: 64000, directory: 'document'});
      await recorder.prepareToRecordAsync();
      return held();
    },
    record() {if (!recorder) throw new Error('麦克风尚未准备好。'); recorder.record();},
    async stop() {
      if (!recorder) throw new Error('录音尚未开始。');
      await recorder.stop();
      if (!recorder.uri) throw new Error('录音暂时未生成，请再试一次。');
      return {uri: recorder.uri, name: '语音输入.m4a', mime: 'audio/mp4'};
    },
    async dispose() {
      try {recorder?.release();}
      finally {
        recorder = null;
        if (configured) {configured = false; await setAudioModeAsync({allowsRecording: false});}
      }
    },
    durationMillis: () => recorder?.getStatus().durationMillis ?? 0,
  };
}

function createPcmRecorder(live: {take: string; connect: () => LiveRecognition}): VoiceRecorder {
  let stream: AudioStream | undefined, file: File | undefined, handle: FileHandle | undefined;
  let subscription: {remove(): void} | undefined, remote: LiveRecognition | undefined;
  let bytes = 0, accepting = false, failure: Error | undefined, stopped: Promise<{uri: string; name: string; mime: string}> | undefined;
  const pcm = new VoicePcm();
  const seal = () => {if (handle) {handle.offset = 0; handle.writeBytes(wavHeader(bytes)); handle.close(); handle = undefined;}};
  return {
    async prepare(held) {
      if (!(await AudioModule.requestRecordingPermissionsAsync()).granted) throw new Error('麦克风未获允许，可以改用文字输入。');
      if (!held()) return false;
      const directory = new Directory(Paths.document, 'voice-takes'); directory.create({idempotent: true, intermediates: true});
      file = new File(directory, live.take + '.wav'); file.create(); handle = file.open(); handle.writeBytes(wavHeader(0));
      // float32 is intentional: the iOS hardware fallback also emits float32.
      // Actual rate is validated/resampled, never relabelled as 16 kHz int16.
      // eslint-disable-next-line import/namespace
      stream = new AudioModule.AudioStream({sampleRate: 16000, channels: 1, encoding: 'float32'});
      subscription = stream.addListener('audioStreamBuffer', buffer => {
        if (!accepting || failure) return;
        try {
          const chunk = pcm.push(buffer.data, buffer.sampleRate, buffer.channels);
          if (!chunk.byteLength) return;
          if (bytes + chunk.byteLength > 5760000) throw new Error('Recording limit reached');
          handle!.writeBytes(chunk); bytes += chunk.byteLength;
          // Repairable WAV header while recording; no per-frame SQLite writes.
          handle!.offset = 0; handle!.writeBytes(wavHeader(bytes)); handle!.offset = 44 + bytes;
          remote?.push(chunk);
        } catch {
          failure = new Error('录音格式发生变化，请重新录制。'); accepting = false; remote?.cancel(); stream?.stop();
        }
      });
      return held();
    },
    async record() {
      if (!stream) throw new Error('麦克风尚未准备好。');
      accepting = true; remote = live.connect();
      try {await stream.start();} catch (error) {accepting = false; remote.cancel(); throw error;}
    },
    stop() {
      if (stopped) return stopped;
      stopped = (async () => {
        stream?.stop();
        // Drain already-enqueued native events before sealing. This is bounded,
        // not a native delivery guarantee; real-device tail-word QA is required.
        await new Promise(resolve => setTimeout(resolve, 150));
        accepting = false; seal();
        if (!file || !bytes) throw new Error('这段录音太短，请按住再说一次。');
        return {uri: file.uri, name: '语音输入.wav', mime: 'audio/wav'};
      })();
      return stopped;
    },
    async dispose() {accepting = false; subscription?.remove(); stream?.stop(); stream?.release(); stream = undefined; seal();},
    durationMillis: () => bytes / 32,
    async recognition() {if (failure) throw failure; if (!remote) throw new Error('识别尚未开始。'); return remote.finish();},
    abortRecognition() {remote?.cancel();},
    pauseRecognition(paused) {remote?.pause(paused);},
    discard() {remote?.cancel(); if (file?.exists) file.delete();},
  };
}
