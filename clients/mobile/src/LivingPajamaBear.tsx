import {useCallback, useEffect, useRef, useState} from 'react';
import {useFocusEffect} from 'expo-router';
import {useEvent, useEventListener} from 'expo';
import {useVideoPlayer, VideoView} from 'expo-video';
import {AppState, Image, Platform, View} from 'react-native';
import {useReducedMotion} from './experience/primitives';
import {PajamaBear} from './PajamaBear';
import {defaultOutfit, type OutfitId} from './wardrobe';

/** Actual articulated footage. Other outfits retain their correct static artwork. */
export function LivingPajamaBear({outfit = defaultOutfit, size = 48, portrait = true}: {outfit?: OutfitId; size?: number; portrait?: boolean}) {
  return outfit === 'mist-blue' ? <BlueBearMotion size={size} portrait={portrait}/> : <PajamaBear outfit={outfit} size={size} portrait={portrait}/>;
}

function BlueBearMotion({size, portrait}: {size: number; portrait: boolean}) {
  const reduced = useReducedMotion();
  const [focused, setFocused] = useState(false);
  const [foreground, setForeground] = useState(AppState.currentState === 'active');
  const [firstFrame, setFirstFrame] = useState(false);
  const greeted = useRef(false);
  const greetingFinished = useRef(false);
  const player = useVideoPlayer(require('../assets/bear-motion/mist-blue-idle.mp4'), instance => {
    instance.loop = false; instance.muted = true; instance.audioMixingMode = 'mixWithOthers';
    instance.staysActiveInBackground = false; instance.showNowPlayingNotification = false;
    if (Platform.OS === 'ios') instance.allowsExternalPlayback = false;
  });
  const {status} = useEvent(player, 'statusChange', {status: player.status});
  useEventListener(player, 'playToEnd', () => {greetingFinished.current = true;});
  useFocusEffect(useCallback(() => {setFocused(true); return () => {setFocused(false);};}, []));
  useEffect(() => {
    const subscription = AppState.addEventListener('change', state => {if (state !== 'active') player.pause(); setForeground(state === 'active');});
    return () => subscription.remove();
  }, [player]);
  useEffect(() => {
    if (reduced || !focused || !foreground || status !== 'readyToPlay') {player.pause(); return;}
    // Greet once for this appearance, then stay still while the user reads.
    // Foregrounding and toggling Reduce Motion must not restart the greeting.
    if (!greeted.current) {greeted.current = true; player.replay();}
    else if (!greetingFinished.current) player.play();
  }, [player, status, reduced, focused, foreground]);
  const frame = portrait ? {position: 'absolute' as const, width: size * 1.92, height: size * 1.92, left: -size * .46, top: -size * .04} : {position: 'absolute' as const, width: size, height: size, left: 0, top: 0};
  return <View pointerEvents="none" accessible={false} accessibilityElementsHidden importantForAccessibility="no-hide-descendants"
    style={{width: size, height: size, overflow: 'hidden', borderRadius: portrait ? size / 2 : 24}}>
    <VideoView player={player} style={frame} contentFit="contain" surfaceType="textureView" nativeControls={false}
      playsInline fullscreenOptions={{enable: false}} allowsPictureInPicture={false} startsPictureInPictureAutomatically={false}
      onFirstFrameRender={() => setFirstFrame(true)}/>
    {reduced || !firstFrame || status === 'error' ? <Image source={require('../assets/bear-motion/mist-blue-poster.jpg')} resizeMode="contain" style={frame}/> : null}
  </View>;
}
