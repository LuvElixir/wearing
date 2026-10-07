import {useCallback, useEffect, useRef, useState} from 'react';
import {useFocusEffect} from 'expo-router';
import {useEvent} from 'expo';
import {useVideoPlayer, VideoView} from 'expo-video';
import {AppState, Image, Platform, StyleProp, StyleSheet, useWindowDimensions, View, ViewStyle} from 'react-native';
import {useReducedMotion} from './primitives';
import {CompanionFrames} from './CompanionFrames';

const loop = require('../../assets/motion/companion-idle.mp4');
const poster = require('../../assets/motion/companion-poster.png');

/** The approved, exposure-matched 3D loop; playback never represents task execution. */
export function CompanionMotion({active = true, style, testID = 'companion-motion'}: {active?: boolean; style?: StyleProp<ViewStyle>; testID?: string}) {
  const reduced = useReducedMotion();
  const viewport = useWindowDimensions();
  const host = useRef<View>(null);
  const [focused, setFocused] = useState(false);
  const [foreground, setForeground] = useState(AppState.currentState === 'active');
  const [inViewport, setInViewport] = useState(false);
  const [firstFrame, setFirstFrame] = useState(false);
  const [frameFailed, setFrameFailed] = useState(false);
  const frameReady = useCallback(() => setFirstFrame(true), []);
  const frameFailure = useCallback(() => setFrameFailed(true), []);
  const player = useVideoPlayer(loop, instance => {
    instance.loop = true;
    instance.muted = true;
    instance.audioMixingMode = 'mixWithOthers';
    instance.staysActiveInBackground = false;
    instance.showNowPlayingNotification = false;
    if (Platform.OS === 'ios') instance.allowsExternalPlayback = false;
  });
  const {status} = useEvent(player, 'statusChange', {status: player.status});
  useFocusEffect(useCallback(() => {
    setFocused(true);
    return () => {player.pause(); setFocused(false);};
  }, [player]));
  useEffect(() => {
    const subscription = AppState.addEventListener('change', state => {
      if (state !== 'active') player.pause();
      setForeground(state === 'active');
    });
    return () => subscription.remove();
  }, [player]);
  useEffect(() => {
    if (Platform.OS !== 'web') return;
    // Observe the actual clipped rectangle, including the preview's nested ScrollView.
    const node = host.current as unknown as Element | null;
    if (!node || typeof IntersectionObserver === 'undefined') return;
    const observer = new IntersectionObserver(([entry]) => setInViewport(entry.isIntersecting && entry.intersectionRatio > 0), {threshold: [0, .01]});
    observer.observe(node);
    const visibility = () => {if (document.hidden) player.pause(); setForeground(!document.hidden);};
    document.addEventListener('visibilitychange', visibility);
    return () => {observer.disconnect(); document.removeEventListener('visibilitychange', visibility);};
  }, [player]);
  const measure = useCallback(() => {
    if (Platform.OS === 'web') return;
    host.current?.measureInWindow((x, y, width, height) => {
      setInViewport(width > 0 && height > 0 && x + width > 0 && y + height > 0 && x < viewport.width && y < viewport.height);
    });
  }, [viewport.width, viewport.height]);
  useEffect(() => {
    if (Platform.OS === 'web' || !active || !focused || !foreground || reduced) return;
    // Native View has no IntersectionObserver. Measure only while this screen is foreground.
    measure();
    const timer = setInterval(measure, 250);
    return () => clearInterval(timer);
  }, [active, focused, foreground, reduced, measure]);
  const playing = active && focused && foreground && inViewport && !reduced && !frameFailed && status === 'readyToPlay';
  useEffect(() => {
    if (playing) player.play(); else player.pause();
    return () => player.pause();
  }, [player, playing]);
  const showPoster = reduced || !firstFrame || frameFailed || status === 'error';
  return <View ref={host} testID={testID} onLayout={measure} pointerEvents="none" accessible={false} accessibilityElementsHidden importantForAccessibility="no-hide-descendants" style={[s.frame, style]}>
    <VideoView player={player} style={[StyleSheet.absoluteFill, s.video]} contentFit="contain" surfaceType="textureView"
      nativeControls={false} playsInline fullscreenOptions={{enable: false}} allowsPictureInPicture={false}
      startsPictureInPictureAutomatically={false} onFirstFrameRender={Platform.OS === 'web' ? undefined : frameReady}/>
    <CompanionFrames host={host} playing={playing} testID={testID} onFrame={frameReady} onFailure={frameFailure}/>
    {showPoster && <Image testID={`${testID}-poster`} source={poster} resizeMode="contain" style={StyleSheet.absoluteFill}/>}
  </View>;
}

const s = StyleSheet.create({
  // Keep video on a normal compositor layer; blending can blank WKWebView video.
  frame: {overflow: 'hidden'},
  // Web <video> keeps its intrinsic dimensions even with inset: 0 unless sized.
  video: {width: '100%', height: '100%', backgroundColor: '#fafafa'},
});
