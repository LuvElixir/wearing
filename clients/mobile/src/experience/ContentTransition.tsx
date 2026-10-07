import type {ReactNode} from 'react';
import Animated, {FadeIn, FadeOut, ReduceMotion} from 'react-native-reanimated';

const enter = FadeIn.duration(180).reduceMotion(ReduceMotion.System);
const exit = FadeOut.duration(120).reduceMotion(ReduceMotion.System);

/** Animate the content group, preserving the stable input and navigation below it. */
export function ContentTransition({children, changeKey, grow}: {children:ReactNode;changeKey:string;grow?:boolean}) {
  return <Animated.View key={changeKey} entering={enter} exiting={exit} collapsable={false}
    style={grow?{flexGrow:1}:undefined}>{children}</Animated.View>;
}
