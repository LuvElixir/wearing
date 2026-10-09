import {useEffect, useRef, useState} from 'react';
import {useEvent} from 'expo';
import {useVideoPlayer, VideoView} from 'expo-video';
import {Animated, AppState, Platform, View} from 'react-native';
import {PajamaBear} from './PajamaBear';
import type {OutfitId} from './wardrobe';

/** First validated garment pair. No controls, sound, or network dependency. */
export function WardrobeFilm({from, size, onFinish}: {from: OutfitId; size: number; onFinish: () => void}) {
  const source = from === 'mist-blue' ? require('../assets/bear-motion/blue-to-cream.mp4') : require('../assets/bear-motion/cream-to-blue.mp4');
  const [firstFrame, setFirstFrame] = useState(false);
  const [opacity] = useState(() => new Animated.Value(1));
  const finishing = useRef(false);
  const target = from === 'mist-blue' ? 'cream-moon' : 'mist-blue';
  const player = useVideoPlayer(source, video => {
    video.muted = true; video.loop = false; video.audioMixingMode = 'mixWithOthers';
    video.staysActiveInBackground = false; video.showNowPlayingNotification = false;
  });
  const {status} = useEvent(player, 'statusChange', {status: player.status});
  useEffect(() => {
    const subscription = player.addListener('playToEnd', () => {
      if (finishing.current) return;
      finishing.current = true;
      Animated.timing(opacity, {toValue: 0, duration: 220, useNativeDriver: Platform.OS !== 'web'}).start(({finished}) => {if (finished) onFinish();});
    });
    const stateSubscription = AppState.addEventListener('change', state => {
      if (state === 'active') player.play(); else player.pause();
    });
    return () => {subscription.remove(); stateSubscription.remove(); opacity.stopAnimation();};
  }, [player, onFinish, opacity]);
  useEffect(() => {
    if (status === 'readyToPlay' && AppState.currentState === 'active') player.play();
    if (status === 'error') onFinish();
  }, [player, status, onFinish]);
  return <View style={{position: 'absolute', width: size, height: size, borderRadius: 28, overflow: 'hidden'}}>
    {firstFrame ? <PajamaBear outfit={target} size={size}/> : null}
    <Animated.View style={{position: 'absolute', width: size, height: size, opacity}}>
    <VideoView player={player} style={{width: size, height: size}} contentFit="contain" surfaceType="textureView" nativeControls={false}
      fullscreenOptions={{enable: false}} allowsPictureInPicture={false} playsInline onFirstFrameRender={() => setFirstFrame(true)}/>
    </Animated.View>
    {!firstFrame ? <View style={{position: 'absolute'}}><PajamaBear outfit={from} size={size}/></View> : null}
  </View>;
}
