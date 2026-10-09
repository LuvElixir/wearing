import {useEffect, useLayoutEffect, useState, useSyncExternalStore} from 'react';
import {Animated, Easing, Platform, StyleSheet, View} from 'react-native';
import {useAppTheme} from './app-theme';
import {useReducedMotion} from './experience/primitives';
import {PajamaBear} from './PajamaBear';
import {WardrobeTransition, type WardrobePreviewState} from './wardrobe-transition';
import type {OutfitId} from './wardrobe';

/** Keep the displayed bear and the requested preview decoded, never all eight
 * full-size images. The same short, interruptible curtain serves every outfit. */
export function WardrobeStage({outfit, size = 260, retryToken = 0, onPreviewChange}: {
  outfit: OutfitId; size?: number; retryToken?: number;
  onPreviewChange?: (state: WardrobePreviewState) => void;
}) {
  const {colors: c} = useAppTheme();
  const reduced = useReducedMotion();
  const [transition] = useState(() => new WardrobeTransition(outfit));
  const preview = useSyncExternalStore(transition.subscribe, transition.snapshot, transition.snapshot);
  const [curtain] = useState(() => new Animated.Value(0));

  useLayoutEffect(() => {transition.select(outfit, reduced);}, [outfit, reduced, transition]);
  useEffect(() => () => transition.cancel(), [transition]);
  useEffect(() => {if (retryToken) transition.retry();}, [retryToken, transition]);
  useEffect(() => {onPreviewChange?.(preview);}, [onPreviewChange, preview]);
  useEffect(() => {
    let active = true;
    let frame: number | undefined;
    const revision = preview.revision;
    const timing = (toValue: number, duration: number, complete?: () => void) => {
      Animated.timing(curtain, {toValue, duration, easing: Easing.inOut(Easing.cubic),
        useNativeDriver: Platform.OS !== 'web', isInteraction: false}).start(({finished}) => {
        if (finished && active) complete?.();
      });
    };
    if (preview.phase === 'closing') {
      timing(1, 150, () => transition.closed(revision));
    } else if (preview.phase === 'opening') {
      // Keep the pose swap covered until its native view has committed.
      curtain.setValue(1);
      frame = requestAnimationFrame(() => timing(0, 230, () => transition.opened(revision)));
    } else if (reduced) curtain.setValue(0);
    else timing(0, 120);
    return () => {active = false; if (frame !== undefined) cancelAnimationFrame(frame); curtain.stopAnimation();};
  }, [curtain, preview.phase, preview.revision, reduced, transition]);

  const frames = preview.shown.key === preview.requested.key ? [preview.shown] : [preview.shown, preview.requested];
  return <View pointerEvents="none" accessible={false} accessibilityElementsHidden importantForAccessibility="no-hide-descendants"
    style={{width: size, height: size, overflow: 'hidden', borderRadius: 28}}>
    {frames.map(frame => <View key={frame.key} style={[StyleSheet.absoluteFill, {opacity: preview.shown.key === frame.key ? 1 : 0}]}>
      <PajamaBear outfit={frame.outfit} size={size} onLoad={() => transition.loaded(frame.key)} onError={() => transition.failed(frame.key)}/>
    </View>)}
    {([-1, 1] as const).map(side => <Animated.View key={side} style={{position: 'absolute', top: 0, bottom: 0, width: size / 2 + 1,
      left: side === -1 ? 0 : size / 2, backgroundColor: c.soft,
      transform: [{translateX: curtain.interpolate({inputRange: [0, 1], outputRange: [side * (size / 2 + 2), 0]})}]}}>
      {[.2, .5, .8].map(fold => <View key={fold} style={{position: 'absolute', top: 0, bottom: 0, left: `${fold * 100}%`, width: 2, backgroundColor: c.line, opacity: .38}}/>)}
    </Animated.View>)}
  </View>;
}
