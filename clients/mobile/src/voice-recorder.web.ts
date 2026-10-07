import type {RecordedAudio, VoiceRecorder} from './voice-session';

// Expo Audio 57's web stop() calls MediaRecorder.stop even while inactive. This
// adapter owns tracks directly so release-during-permission can also stop a
// prepared microphone without briefly starting an unwanted recording.
export function createVoiceRecorder(): VoiceRecorder {
  let stream: MediaStream | null = null;
  let recorder: MediaRecorder | null = null;
  let started = 0;
  let completed: Promise<RecordedAudio> | null = null;
  let stopTracks = () => {};
  return {
    async prepare(held) {
      if (typeof navigator === 'undefined' || !navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') throw new Error('当前浏览器无法录音，可以改用文字输入。');
      stream = await navigator.mediaDevices.getUserMedia({audio: true});
      const tracks = stream.getTracks();
      stopTracks = () => tracks.forEach(track => track.stop());
      if (!held()) {stopTracks(); return false;}
      const mimeType = ['audio/webm;codecs=opus', 'audio/mp4', 'audio/webm'].find(type => MediaRecorder.isTypeSupported(type));
      recorder = new MediaRecorder(stream, {audioBitsPerSecond: 64000, ...(mimeType ? {mimeType} : {})});
      const current = recorder;
      completed = new Promise<RecordedAudio>((resolve, reject) => {
        const chunks: Blob[] = [];
        current.addEventListener('dataavailable', event => {if (event.data.size) chunks.push(event.data);});
        current.addEventListener('error', () => {stopTracks(); reject(new Error('浏览器录音中断，请再试一次。'));});
        current.addEventListener('stop', () => {
          stopTracks();
          const mime = (current.mimeType || chunks[0]?.type || 'audio/webm').split(';')[0];
          const blob = new Blob(chunks, {type: mime});
          if (!blob.size) {reject(new Error('这段录音太短，请按住再说一次。')); return;}
          resolve({uri: URL.createObjectURL(blob), mime, name: '语音输入.' + (mime.includes('mp4') ? 'm4a' : mime.includes('ogg') ? 'ogg' : 'webm')});
        });
      });
      // Errors can precede the release gesture; stop() still reads the rejection.
      void completed.catch(() => {});
      return true;
    },
    record() {if (!recorder) throw new Error('麦克风尚未准备好。'); recorder.start(); started = Date.now();},
    async stop() {
      if (!recorder || !completed || !started) throw new Error('录音尚未开始。');
      if (recorder.state !== 'inactive') recorder.stop();
      stopTracks();
      return completed;
    },
    async dispose() {
      try {if (recorder?.state !== 'inactive' && recorder) recorder.stop();}
      finally {stopTracks(); recorder = null; stream = null;}
    },
    durationMillis: () => started ? Math.max(0, Date.now() - started) : 0,
  };
}
