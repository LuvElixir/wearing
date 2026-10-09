"""Reproducible paired local ASR benchmark; never contacts a remote provider.

Use synthetic/public fixture audio only: the output includes its transcript.
Example from repo root:
.venv/bin/python perf/bench/voice-warm.py --audio /tmp/wearing-voice-bench/sample.aiff --output perf/bench/voice-warm-20261007.json
"""
import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import platform
import statistics
import sys
import tempfile
from time import perf_counter

from wearing.capture import CaptureBook
from wearing.capture_worker import CaptureWorker
from wearing.life import LifeBook
from wearing.store import Store

ROOT=Path(__file__).resolve().parents[2]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def distribution(values):
    ordered=sorted(values)
    return {'count':len(values),'p50_seconds':round(statistics.median(values),4),
            'p75_seconds':round(ordered[math.ceil(.75*len(ordered))-1],4),
            'p95_seconds':round(ordered[math.ceil(.95*len(ordered))-1],4),
            'min_seconds':min(values),'max_seconds':max(values)}


async def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audio',type=Path,required=True)
    parser.add_argument('--model',type=Path,default=ROOT/'.wearing/runtime/capture-models/small')
    parser.add_argument('--pairs',type=int,default=10)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.pairs<10:parser.error('Use at least 10 pairs.')
    audio,model=args.audio.resolve(),args.model.resolve()
    baseline=Path(__file__).with_name('voice-cold-baseline.py')
    revised=ROOT/'src/wearing/capture_stt.py'
    with tempfile.TemporaryDirectory(prefix='wearing-voice-bench-') as directory:
        worker=CaptureWorker(CaptureBook(LifeBook(Store(Path(directory)/'wearing.sqlite3'))))
        async def measure(kind):
            start=perf_counter()
            if kind=='warm':
                raw=await worker.command([sys.executable,str(revised),'--serve',str(model)],
                                         body={'path':str(audio)},reuse=True)
            else:
                raw=await worker.command([sys.executable,str(baseline),str(audio),str(model)])
            result=json.loads(raw)
            if not result.get('text'):raise RuntimeError('Decoder returned no fixture transcript')
            return {'seconds':round(perf_counter()-start,4),'transcript':result['text'],
                    'audio_seconds':result['duration'],'timings':result.get('timings')}
        try:
            first_request=await measure('warm')
            pairs=[]
            for index in range(args.pairs):
                order=['cold','warm'] if index%2==0 else ['warm','cold']
                row={'pair':index+1,'order':order}
                for kind in order:row[kind]=await measure(kind)
                row['transcripts_equal']=row['cold']['transcript']==row['warm']['transcript']
                pairs.append(row)
                print(json.dumps({'pair':index+1,'order':order,'cold':row['cold']['seconds'],
                                  'warm':row['warm']['seconds'],'equal':row['transcripts_equal']}),flush=True)
        finally:
            await worker.close()
    import importlib.metadata
    cold=distribution([p['cold']['seconds'] for p in pairs])
    warm=distribution([p['warm']['seconds'] for p in pairs])
    report={'created_at':datetime.now(timezone.utc).isoformat(),'fixture_sha256':digest(audio),
            'fixture_name':audio.name,'fixture_origin':'macOS say, Tingting (中文（中国大陆）), synthetic Mandarin',
            'fixture_script':'明天下午三点提醒我拿快递，周末想找一个人少一点的地方走走，预算五百块。',
            'hardware':{'machine':platform.machine(),'system':platform.platform()},
            'packages':{n:importlib.metadata.version(n) for n in ('faster-whisper','ctranslate2','av')},
            'model_manifest_sha256':digest(model/'wearing-model.json'),
            'sources':{str(p.relative_to(ROOT)):digest(p) for p in (baseline,revised,ROOT/'src/wearing/capture_worker.py')},
            'method':'10 sequential pairs, alternating order. First warm-worker request reported separately; p95 is nearest-rank. Same local small/int8, 4 threads, beam=5, VAD and prompt. No remote provider, no accuracy claim.',
            'first_warm_worker_request':first_request,'cold':cold,'warm':warm,
            'p50_reduction_percent':round((1-warm['p50_seconds']/cold['p50_seconds'])*100,1),
            'all_pair_transcripts_equal':all(p['transcripts_equal'] for p in pairs),'pairs':pairs}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({key:report[key] for key in ('cold','warm','p50_reduction_percent','all_pair_transcripts_equal')},ensure_ascii=False))


if __name__=='__main__':asyncio.run(main())
