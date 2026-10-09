import {useAppTheme, useThemedStyles, type AppColors} from '../app-theme';
import {useEffect, useState, type ComponentType} from 'react';
import {Animated, Easing, Platform, StyleSheet, Text, View} from 'react-native';
import {ListTodo, UserRound} from 'lucide-react-native';
import type {OutfitId} from '../wardrobe';
import {ChatIcon, LocalCalendarIcon, MemoryIcon, type NavigationIconProps} from '../navigation-icons';
import {TactilePressable, useReducedMotion} from './primitives';
import {motion} from './tokens';

export type BottomNavigationPage = 'now' | 'review' | 'goals' | 'memory' | 'companion';
export type BottomNavigationProps = {
  selected: BottomNavigationPage;
  onSelect: (page: BottomNavigationPage) => void;
  outfit?: OutfitId;
};

type Destination = {page: BottomNavigationPage; label: string; icon?: ComponentType<NavigationIconProps>};
const destinations: readonly Destination[] = [
  {page: 'now', label: '聊天', icon: ChatIcon},
  {page: 'review', label: '今天', icon: LocalCalendarIcon},
  {page: 'goals', label: '任务', icon: ListTodo},
  {page: 'memory', label: '记忆', icon: MemoryIcon},
  {page: 'companion', label: '我的', icon: UserRound},
];


function NavigationItem({destination, selected, reduced, onSelect}: {
  destination: Destination;
  selected: boolean;
  reduced: boolean;
  onSelect: BottomNavigationProps['onSelect'];
  outfit?: OutfitId;
}) {
  const {colors: c} = useAppTheme();
  const s = useThemedStyles(makeStyles);

  const [selection] = useState(() => new Animated.Value(selected ? 1 : 0));
  useEffect(() => {
    selection.stopAnimation();
    if (reduced) {
      selection.setValue(selected ? 1 : 0);
      return;
    }
    // A new selection reverses from the current value, including rapid re-taps.
    const animation = Animated.timing(selection, {
      toValue: selected ? 1 : 0,
      duration: selected ? motion.release : motion.crossfade,
      easing: Easing.out(Easing.cubic),
      useNativeDriver: Platform.OS !== 'web',
      isInteraction: false,
    });
    animation.start();
    return () => animation.stop();
  }, [selected, reduced, selection]);

  const Icon = destination.icon;
  return <TactilePressable
    accessibilityRole="tab"
    accessibilityLabel={destination.label}
    accessibilityState={{selected}}
    onPress={() => onSelect(destination.page)}
    pressScale={0.98}
    style={s.item}>
    <Animated.View pointerEvents="none" style={[s.selection, {
      opacity: selection,
      transform: [{scale: reduced ? 1 : selection.interpolate({inputRange: [0, 1], outputRange: [0.94, 1]})}],
    }]}/>
    <View pointerEvents="none" accessible={false} accessibilityElementsHidden
      importantForAccessibility="no-hide-descendants" style={s.content}>
      {Icon ? <Icon size={24} strokeWidth={1.65} color={selected ? c.accentInk : c.muted}/>
        : null}
      <Text style={[s.label, selected && s.selectedLabel]}>{destination.label}</Text>
    </View>
  </TactilePressable>;
}

/** The parent owns routing and safe-area insets; selection never delays navigation. */
export function BottomNavigation({selected, onSelect}: BottomNavigationProps) {
  const s = useThemedStyles(makeStyles);

  const reduced = useReducedMotion();
  return <View accessibilityRole="tablist" accessibilityLabel="主要页面" style={s.bar}>
    {destinations.map(destination => <NavigationItem key={destination.page}
      destination={destination} selected={selected === destination.page}
      reduced={reduced} onSelect={onSelect}/>)}
  </View>;
}

const makeStyles = (c: AppColors) => StyleSheet.create({
  bar: {minHeight: 60, paddingHorizontal: 10, paddingVertical: 4, flexDirection: 'row', backgroundColor: 'transparent'},
  item: {flex: 1, minWidth: 44, minHeight: 52, alignItems: 'center', justifyContent: 'center'},
  selection: {position: 'absolute', top: 2, bottom: 2, left: 4, right: 4, borderRadius: 16, backgroundColor: c.soft},
  content: {alignItems: 'center', justifyContent: 'center', gap: 3, paddingVertical: 5, paddingHorizontal: 2},
  portrait: {width: 22, height: 22, borderRadius: 8},
  label: {fontSize: 11, lineHeight: 16, fontWeight: '500', color: c.muted, textAlign: 'center'},
  selectedLabel: {color: c.accentInk},
});
