"""One bounded extraction/organization job; originals precede every model call."""
import asyncio
import json
import logging
from pathlib import Path
import shutil
import sys
from time import perf_counter

from filelock import FileLock, Timeout
from contextlib import suppress

from .capture import CaptureBook, OrganizedNote
from .capture_setup import prepare, PROVIDER
from .life import LifeError
from .runtime import HermesRuntime


class CaptureWorker:
    def __init__(self, book:CaptureBook):
        self.book=book
        self.task=None
        self.process=None
        self.process_busy=False
        self.lock=FileLock(book.store.path.parent/"capture-worker.lock")
        self.process_lock=FileLock(book.store.path.parent/"capture-process.lock", thread_local=False)
        self.owns_lock=False
        self.voice_busy=False

    def start(self):
        try:self.lock.acquire(timeout=0)
        except Timeout:return
        self.owns_lock=True
        self.book.recover()

    def capabilities(self):
        stt=prepare(self.book.store.path.parent)["prepared"]
        return {"ocr": "apple-vision" if sys.platform=="darwin" and shutil.which("swift") else ("tesseract" if shutil.which("tesseract") else None),
                "transcription": PROVIDER if stt else None,"transcription_mode": "recorded-utterance" if stt else None,"max_asset_bytes":15*1024*1024,"max_recording_seconds":180,
                "organization":"configured-model","originals":"private"}

    def tick(self, busy=False):
        if not self.owns_lock or busy or self.voice_busy or (self.task and not self.task.done()):return
        job=self.book.claim()
        if job:self.task=asyncio.create_task(self.run(job))

    async def transcribe_voice(self, identity, asset_id):
        path, asset = self.book.file(identity, asset_id)
        if not asset['mime'].startswith('audio/'):
            raise LifeError('请选择一段录音。', 422)
        cached = self.book.transcript(identity, asset_id)
        if cached is not None:
            return {'asset_id': asset_id, 'text': cached}
        if self.voice_busy or (self.task and not self.task.done()):
            raise LifeError('正在处理上一份原件，录音已保存，请稍后重试。', 409)
        if not self.capabilities()['transcription']:
            raise LifeError('录音已保存，语音转写尚未准备好。可以先用文字输入。', 503)
        self.voice_busy = True
        try:
            raw = await self.recognize(path, identity=identity)
            result = json.loads(raw)
            if isinstance(result, dict) and str(result.get("error_code", "")).startswith("quota_"):
                from .usage import UsageError
                raise LifeError(UsageError(result["error_code"]).detail, 429)
            if isinstance(result, dict) and result.get('error_code') == 'duration_limit':
                raise LifeError('录音超过三分钟，请分成几段发送。原录音已保留。', 422)
            if isinstance(result, dict) and result.get('error_code') == 'invalid_audio':
                raise LifeError('这段录音无法读取，原件已保留。可以重录或改用文字输入。', 422)
            if isinstance(result, dict) and result.get('error_code') == 'no_speech':
                raise LifeError('没有听清，试着再说一次。录音已保留。', 422)
            if isinstance(result, dict) and result.get('error_code') in ('not_configured', 'service_not_enabled'):
                raise LifeError('语音服务尚未接通，录音已保留。可以先用文字输入。', 503)
            if isinstance(result, dict) and (result.get('error') or result.get('error_code')):
                raise LifeError('识别暂时没有完成，录音已保留，请稍后重试。', 503)
            text = result.get('text', '') if isinstance(result, dict) else ''
            text = text.strip() if isinstance(text, str) else ''
            if not text:
                raise LifeError('没有听清这段话，录音已保留。可以重录或用文字输入。', 422)
            if len(text) > 12000:
                raise LifeError('这段话太长，请分成几段发送。原录音已保留。', 422)
            return {'asset_id': asset_id, 'text': self.book.save_transcript(identity, asset_id, text)}
        except (asyncio.TimeoutError, ValueError):
            raise LifeError('识别暂时没有完成，录音已保留，请稍后重试。', 503) from None
        finally:
            self.voice_busy = False

    async def recognize(self, path, *, identity="daily"):
        started=perf_counter()
        raw=await self.command([sys.executable, "-m", "wearing.capture_stt",
            "--data-dir", str(self.book.store.path.parent.resolve()),
            "--audio", str(path.resolve()), "--identity", identity], timeout=55)
        result=json.loads(raw)
        timings=result.get("timings", {}) if isinstance(result, dict) else {}
        if not isinstance(timings,dict):timings={}
        safe={key: value for key,value in timings.items()
              if key in ("decode_ms", "recognition_ms", "total_ms")
              and isinstance(value, (int,float))}
        safe["worker_ms"]=round((perf_counter()-started)*1000)
        code=result.get("error_code") if isinstance(result,dict) else None
        if code in {"duration_limit", "invalid_audio", "no_speech", "not_configured",
                    "service_not_enabled", "service_unavailable", "invalid_response"}:
            safe["error_code"]=code
        # Neither provider response bodies nor original paths enter logs.
        logging.getLogger(__name__).info("Cloud voice timings: %s", json.dumps(safe))
        return raw

    async def command(self, args, *, env=None, cwd=None, body=None, timeout=120):
        # HTTP workers and the capture background worker share one bounded
        # local subprocess slot, even when they are different Python processes.
        if self.process_busy:
            raise LifeError('正在处理上一份原件，录音已保存，请稍后重试。', 409)
        try:self.process_lock.acquire(timeout=0)
        except Timeout:
            raise LifeError('正在处理上一份原件，录音已保存，请稍后重试。', 409) from None
        except OSError:
            raise LifeError('本地读取资源暂时不可用，原件已保存，请稍后重试。', 503) from None
        self.process_busy=True
        process = None
        try:
            try:
                self.process=await asyncio.create_subprocess_exec(*args,env=env,cwd=cwd,stdin=asyncio.subprocess.PIPE if body is not None else asyncio.subprocess.DEVNULL,
                            stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL)
            except OSError:
                raise LifeError('读取或整理暂时不可用，原件已经保存，请稍后重试。', 503) from None
            process=self.process
            stdout,_=await asyncio.wait_for(process.communicate(json.dumps(body,ensure_ascii=False).encode() if body is not None else None),timeout)
            if process.returncode!=0:raise LifeError("读取或整理暂时没有完成，原件已经保存，请稍后重试。", 503)
            return stdout.decode("utf-8")
        finally:
            try:
                if process is not None and process.returncode is None:
                    with suppress(ProcessLookupError):process.kill()
                    await process.wait()
            finally:
                self.process=None
                self.process_busy=False
                self.process_lock.release()

    async def extract(self, job):
        # A failed second attachment must not make a retry silently skip it.
        previous={part["asset_id"]:part for part in job["extracted"] if part.get("asset_id") in job["asset_ids"]}
        output=[]
        caps=self.capabilities()
        for asset_id in job["asset_ids"]:
            if asset_id in previous:
                output.append(previous[asset_id])
                continue
            path,asset=self.book.file(job["identity_id"],asset_id)
            if asset["mime"].startswith("image/"):
                if caps["ocr"]=="apple-vision":
                    raw=await self.command([shutil.which("swift"),str(Path(__file__).with_name("capture_ocr.swift")),str(path)],timeout=90)
                    text=json.loads(raw).get("text","")
                elif caps["ocr"]=="tesseract":
                    text=await self.command([shutil.which("tesseract"),str(path),"stdout"],timeout=60)
                else:raise LifeError("原图已保存；这台运行主机尚未接入图片文字识别。")
                if not text.strip():raise LifeError("原图已保存，没有读到文字。可以补一句说明后继续聊。")
            else:
                if not caps["transcription"]:raise LifeError("录音已保存，语音转写尚未准备好。可以先听原录音或手动补充。")
                raw=await self.recognize(path, identity=job["identity_id"])
                result=json.loads(raw)
                if str(result.get("error_code", "")).startswith("quota_"):
                    from .usage import UsageError
                    raise LifeError(UsageError(result["error_code"]).detail, 429)
                if result.get('error_code') == 'duration_limit':raise LifeError('录音超过三分钟，请分成几段发送。原录音已保留。',422)
                if result.get('error_code') == 'invalid_audio':raise LifeError('这段录音无法读取，原件已保留。可以重录或手动补充。',422)
                if result.get('error_code') or result.get('error'):raise LifeError('识别暂时没有完成，录音已保留，请稍后重试。',503)
                text=result.get("text","")
                if not isinstance(text,str) or not text.strip():raise LifeError("录音已保存，但没有听清这段话。可以重新录一段或手动补充。")
            output.append({"asset_id":asset_id,"kind":"image_text" if asset["mime"].startswith("image/") else "transcript","text":text[:8000]})
            self.book.state(job,"extracting",extracted=output)
        return output

    async def run(self,job):
        try:
            record=self.book.life.get(job["identity_id"],job["record_id"])
            if record["deleted_at"]:raise LifeError("记录已移除，整理已停下；原件保留。")
            extracted=await self.extract(job)
            self.book.state(job,"organizing",extracted=extracted)
            engine=HermesRuntime(self.book.store.path.parent,job["identity_id"])
            if not engine.python.is_file():raise LifeError("原件已经保存，模型还没接通。接通后可以重新整理。")
            body={"kind":record["kind"],"original_text":job["original_text"],"current_title":record["title"],"current_content":record["content"],"sources":extracted}
            raw=await self.command([str(engine.python),str(Path(__file__).with_name("capture_bridge.py")),str(engine.source)],env=engine.env(),cwd=engine.source,body=body,timeout=150)
            result=json.loads(raw)
            if result.get("error"):raise LifeError(result["error"])
            output=result.get("output","").strip()
            if output.startswith("```"):
                output="\n".join(output.splitlines()[1:-1])
            proposal=OrganizedNote.model_validate_json(output)
            self.book.apply(job,proposal)
        except asyncio.CancelledError:
            self.book.state(job,"paused",error="整理中断了，原件已经保存。可以重新整理。")
            raise
        except Exception as error:
            message=str(error) if isinstance(error,LifeError) else "这次整理没有完成，原件和原话已保留。可以再试一次或直接编辑。"
            self.book.state(job,"failed",error=message)

    async def close(self):
        if self.task and not self.task.done():
            self.task.cancel()
            try:await self.task
            except asyncio.CancelledError:pass
        if self.owns_lock:self.lock.release();self.owns_lock=False
