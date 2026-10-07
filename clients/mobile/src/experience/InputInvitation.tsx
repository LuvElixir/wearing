import {useCallback, useEffect, useRef, useState} from 'react';
import {useFocusEffect} from 'expo-router';
import {Animated, AppState, Easing, Image, Platform, StyleSheet, Text, View} from 'react-native';
import {colors as c} from './tokens';
import {useReducedMotion} from './primitives';

const nativeDriver = Platform.OS !== 'web';
const words = ['“明天，', '提醒我', '带伞。”'];

/** A short illustration of speaking, never a recording indicator. It settles after 4.4s. */
export function InputInvitation({active}: {active: boolean}) {
  const reduced = useReducedMotion();
  const [focused, setFocused] = useState(false);
  const [foreground, setForeground] = useState(AppState.currentState === 'active');
  const [progress] = useState(() => new Animated.Value(1));
  const played = useRef(false);

  useFocusEffect(useCallback(() => {
    setFocused(true);
    return () => setFocused(false);
  }, []));
  useEffect(() => {
    const listener = AppState.addEventListener('change', value => setForeground(value === 'active'));
    return () => listener.remove();
  }, []);
  useEffect(() => {
    if (reduced || !active || !focused || !foreground || played.current) {
      progress.setValue(1);
      return;
    }
    played.current = true;
    progress.setValue(0);
    const animation = Animated.timing(progress, {
      toValue: 1, duration: 4400, easing: Easing.linear,
      useNativeDriver: nativeDriver, isInteraction: false,
    });
    animation.start();
    return () => {animation.stop(); progress.setValue(1);};
  }, [active, focused, foreground, progress, reduced]);

  return <View style={s.hero}>
    <Image source={require('../../assets/companion-portrait.png')} testID="companion-static-now" style={s.character} resizeMode="contain"/>
    <Text style={s.title}>你说，我来做。</Text>
    <View style={s.scene} pointerEvents="none" accessible={false} accessibilityElementsHidden importantForAccessibility="no-hide-descendants">
      <View style={s.wave}>{[8, 16, 23, 13, 20, 9].map((height, i) => <Animated.View key={i} style={[s.bar, {height, transform: [{scaleY: progress.interpolate({inputRange: [0, .12, .23, .34, .45, .56, .7, 1], outputRange: i % 2 ? [.45, 1, .5, .95, .4, .9, .55, .55] : [.65, .35, 1, .4, 1, .5, .55, .55]})}]}]}/>)}</View>
      <Animated.View style={{transform: [{translateY: progress.interpolate({inputRange: [0, .15, 1], outputRange: [3, 0, 0]})}]}}>
        <Text style={s.phrase}>{words.map((word, i) => <Animated.Text key={word} style={{opacity: progress.interpolate({inputRange: [0, .14 + i * .14, .27 + i * .14, 1], outputRange: [.12, .12, 1, 1]})}}>{word}</Animated.Text>)}</Text>
      </Animated.View>
    </View>
  </View>;
}

const s = StyleSheet.create({
  hero: {flexGrow: 1, minHeight: 330, alignItems: 'center', justifyContent: 'center', paddingVertical: 34},
  title: {fontSize: 25, lineHeight: 36, letterSpacing: -.5, fontWeight: '600', color: c.ink, textAlign: 'center', marginTop: 21},
  scene: {flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 10, minHeight: 30, marginTop: 11},
  character: {width: 105, height: 125},
  phrase: {fontSize: 14, lineHeight: 23, color: c.muted},
  wave: {height: 25, flexDirection: 'row', alignItems: 'center', gap: 2},
  bar: {width: 2, borderRadius: 2, backgroundColor: c.accent},
});
