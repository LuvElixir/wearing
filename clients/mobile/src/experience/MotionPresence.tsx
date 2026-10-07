import {useEffect, useState, type ReactNode} from 'react';
import {Animated, Easing, Platform, type StyleProp, type ViewStyle} from 'react-native';
import {useReducedMotion} from './primitives';

/** Keep exiting content mounted until its animation ends; re-entry cancels the exit. */
export function MotionPresence({visible, children, style}: {visible: boolean; children: ReactNode; style?: StyleProp<ViewStyle>}) {
  const reduced = useReducedMotion();
  const [mounted, setMounted] = useState(visible);
  const [progress] = useState(() => new Animated.Value(visible ? 1 : 0));
  if (visible && !mounted) setMounted(true);
  useEffect(() => {
    progress.stopAnimation();
    Animated.timing(progress, {toValue: visible ? 1 : 0, duration: reduced ? 0 : visible ? 180 : 130,
      easing: Easing.out(Easing.cubic), useNativeDriver: Platform.OS !== 'web'}).start(({finished}) => {
      if (finished && !visible) setMounted(false);
    });
    return () => progress.stopAnimation();
  }, [visible, progress, reduced]);
  if (!mounted) return null;
  return <Animated.View pointerEvents={visible ? 'auto' : 'none'} accessibilityElementsHidden={!visible}
    style={[style, {opacity: progress, transform: [{translateY: progress.interpolate({inputRange: [0,1], outputRange: [reduced ? 0 : 5,0]})}]}]}>{children}</Animated.View>;
}
