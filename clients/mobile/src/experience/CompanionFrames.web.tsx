import {useEffect, useRef} from 'react';
import type {CompanionFramesProps} from './CompanionFrames';

/** Paint the existing decoder into the DOM layer; never create a second video. */
export function CompanionFrames({host, playing, testID, onFrame, onFailure}: CompanionFramesProps) {
  const surface = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    if (!playing) return;
    const canvas = surface.current;
    const video = (host.current as unknown as HTMLElement | null)?.querySelector('video');
    const context = canvas?.getContext('2d', {alpha: false});
    if (!canvas || !video || !context) {onFailure(); return;}
    let live = true, ticket: number | null = null, painted = false;
    const frameCallbacks = typeof video.requestVideoFrameCallback === 'function';
    const size = () => {
      const rect = canvas.getBoundingClientRect(), density = Math.min(window.devicePixelRatio || 1, 2);
      const width = Math.max(1, Math.round(rect.width * density)), height = Math.max(1, Math.round(rect.height * density));
      if (canvas.width !== width || canvas.height !== height) {canvas.width = width; canvas.height = height;}
    };
    const paint = () => {
      if (!live || document.hidden || video.readyState < 2 || !video.videoWidth || !video.videoHeight) return;
      try {
        const scale = Math.min(canvas.width / video.videoWidth, canvas.height / video.videoHeight);
        const width = video.videoWidth * scale, height = video.videoHeight * scale;
        context.fillStyle = '#fafafa'; context.fillRect(0, 0, canvas.width, canvas.height);
        context.drawImage(video, (canvas.width - width) / 2, (canvas.height - height) / 2, width, height);
        if (!painted) {painted = true; onFrame();}
      } catch {live = false; onFailure();}
    };
    const cancel = () => {
      if (ticket !== null) {video.cancelVideoFrameCallback(ticket); ticket = null;}
    };
    const schedule = () => {
      if (!live || document.hidden || ticket !== null || !frameCallbacks) return;
      ticket = video.requestVideoFrameCallback(() => {
        ticket = null; paint();
        if (!video.paused && !video.ended) schedule();
      });
    };
    const resume = () => {paint(); schedule();};
    const visibility = () => {if (document.hidden) cancel();};
    size();
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(() => {size(); paint();});
    observer?.observe(canvas);
    video.addEventListener('playing', resume);
    video.addEventListener('pause', cancel);
    video.addEventListener('seeked', paint);
    // Older browsers can paint on actual media events without a blind 60 Hz loop.
    if (!frameCallbacks) video.addEventListener('timeupdate', paint);
    document.addEventListener('visibilitychange', visibility);
    // A decoded frame may already be available before the parent's play effect runs.
    paint(); schedule();
    return () => {
      live = false; cancel(); observer?.disconnect();
      video.removeEventListener('playing', resume); video.removeEventListener('pause', cancel);
      video.removeEventListener('seeked', paint); video.removeEventListener('timeupdate', paint);
      document.removeEventListener('visibilitychange', visibility);
    };
  }, [host, playing, onFrame, onFailure]);
  return <canvas ref={surface} data-testid={`${testID}-canvas`} aria-hidden="true" style={{position: 'absolute', inset: 0, width: '100%', height: '100%', pointerEvents: 'none'}}/>;
}
