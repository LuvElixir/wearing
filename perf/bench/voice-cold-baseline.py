"""Pre-2026-10-07 decoder baseline, kept only for paired local benchmarks."""
import json
from pathlib import Path
import sys


def main():
    from faster_whisper import WhisperModel
    from faster_whisper.audio import decode_audio
    try:
        import av
        with av.open(sys.argv[1]) as container:
            if not container.streams.audio:
                raise ValueError("no audio stream")
            if container.duration is not None and container.duration / av.time_base > 180:
                print('{"error_code":"duration_limit"}')
                return
        samples = decode_audio(sys.argv[1], sampling_rate=16000)
    except Exception:
        print('{"error_code":"invalid_audio"}')
        return
    if len(samples) > 180 * 16000:
        print('{"error_code":"duration_limit"}')
        return
    if not len(samples):
        print('{"error_code":"invalid_audio"}')
        return
    model=WhisperModel(str(Path(sys.argv[2])),device="cpu",compute_type="int8",cpu_threads=4,local_files_only=True)
    segments, info=model.transcribe(samples,beam_size=5,vad_filter=True,condition_on_previous_text=False,
                                   initial_prompt="中文口述备忘，使用简体中文，保留日期、人名和数字。")
    text="\n".join(s.text.strip() for s in segments if s.avg_logprob > -1 and s.no_speech_prob < .6).strip()
    print(json.dumps({"text":text,"language":info.language,"duration":info.duration},ensure_ascii=False))


if __name__=="__main__":
    try:main()
    except Exception:
        print('{"error":"录音暂时没有转成文字，原录音已保存。"}')
        sys.exit(1)
