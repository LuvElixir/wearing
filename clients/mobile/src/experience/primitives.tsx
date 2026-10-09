import {useAppTheme, useThemedStyles, type AppColors} from '../app-theme';
import React, {ReactNode, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState} from 'react';
import {
  AccessibilityInfo, ActivityIndicator, Animated, Easing, findNodeHandle,
  Keyboard, KeyboardAvoidingView, Modal, PanResponder, Platform, Pressable,
  PressableProps, ScrollView, StyleProp, StyleSheet, Text, useWindowDimensions,
  View, ViewStyle,
} from 'react-native';
import {useSafeAreaInsets} from 'react-native-safe-area-context';
import {X} from 'lucide-react-native';
import {motion, radii, spacing} from './tokens';

const nativeDriver = Platform.OS !== 'web';

export function useReducedMotion() {
  // Start still until the OS preference resolves; never animate over an unknown preference.
  const [reduced, setReduced] = useState(true);
  useEffect(() => {
    let active = true;
    let preferenceChanged = false;
    AccessibilityInfo.isReduceMotionEnabled()
      .then(value => {if (active && !preferenceChanged) setReduced(value);})
      .catch(() => {/* Keep motion reduced if the system preference is unavailable. */});
    const subscription = AccessibilityInfo.addEventListener('reduceMotionChanged', value => {
      preferenceChanged = true;
      if (active) setReduced(value);
    });
    return () => {active = false; subscription.remove();};
  }, []);
  return reduced;
}

const AnimatedPressable = Animated.createAnimatedComponent(Pressable);
type TactileProps = Omit<PressableProps, 'children' | 'style'> & {
  children: ReactNode;
  style?: StyleProp<ViewStyle>;
  pressScale?: number;
};

/** A press remains interruptible; navigation never waits for the release animation. */
export function TactilePressable({children, style, pressScale = 0.975, disabled, onPressIn, onPressOut, accessibilityState, ...props}: TactileProps) {
  const reduced = useReducedMotion();
  const [progress] = useState(() => new Animated.Value(0));
  const animate = (pressed: boolean) => {
    progress.stopAnimation();
    Animated.timing(progress, {
      toValue: pressed ? 1 : 0,
      duration: reduced ? 0 : pressed ? motion.press : motion.release,
      easing: Easing.out(Easing.cubic), useNativeDriver: nativeDriver,
    }).start();
  };
  useEffect(() => {if (disabled) progress.setValue(0); return () => progress.stopAnimation();}, [disabled, progress]);
  // RN Web forwards aria-selected, but drops the grouped native accessibilityState.
  const webSelection = Platform.OS === 'web'
    ? {'aria-selected': props['aria-selected'] ?? accessibilityState?.selected}
    : {};
  return <AnimatedPressable accessibilityRole="button" {...props} {...webSelection} disabled={disabled}
    accessibilityState={{...accessibilityState, disabled: !!disabled}}
    onPressIn={event => {animate(true); onPressIn?.(event);}}
    onPressOut={event => {animate(false); onPressOut?.(event);}}
    style={[style, {
      opacity: disabled ? 0.44 : progress.interpolate({inputRange: [0, 1], outputRange: [1, 0.72]}),
      transform: [{scale: reduced ? 1 : progress.interpolate({inputRange: [0, 1], outputRange: [1, pressScale]})}],
    }]}>{children}</AnimatedPressable>;
}

export type IconButtonProps = {
  label: string;
  onPress: () => void;
  children: ReactNode;
  disabled?: boolean;
  selected?: boolean;
  variant?: 'plain' | 'soft';
  size?: number;
  style?: StyleProp<ViewStyle>;
  testID?: string;
};

export function IconButton({label, onPress, children, disabled, selected, variant = 'soft', size = 44, style, testID}: IconButtonProps) {
  const styles = useThemedStyles(makeStyles);

  return <TactilePressable accessibilityRole="button" accessibilityLabel={label}
    accessibilityState={{selected}} disabled={disabled} onPress={onPress} testID={testID}
    style={[styles.icon, {width: Math.max(44, size), height: Math.max(44, size)},
      variant === 'soft' && styles.iconSoft, selected && styles.iconSelected, style]}>
    {children}
  </TactilePressable>;
}

export type PrimaryButtonProps = {
  label: string;
  onPress: () => void;
  leading?: ReactNode;
  disabled?: boolean;
  loading?: boolean;
  tone?: 'accent' | 'quiet' | 'danger';
  style?: StyleProp<ViewStyle>;
  testID?: string;
};

export function PrimaryButton({label, onPress, leading, disabled, loading, tone = 'accent', style, testID}: PrimaryButtonProps) {
  const {colors: colors} = useAppTheme();
  const styles = useThemedStyles(makeStyles);

  const foreground = tone === 'accent' ? colors.onAccent : tone === 'danger' ? colors.danger : colors.ink;
  return <TactilePressable accessibilityRole="button" accessibilityLabel={label}
    accessibilityState={{busy: loading}} disabled={disabled || loading} onPress={onPress} testID={testID}
    style={[styles.button, tone === 'accent' ? styles.buttonAccent : tone === 'danger' ? styles.buttonDanger : styles.buttonQuiet, style]}>
    {loading ? <ActivityIndicator size="small" color={foreground}/> : leading}
    <Text style={[styles.buttonLabel, {color: foreground}]}>{label}</Text>
  </TactilePressable>;
}

export type SheetProps = {
  visible: boolean;
  onDismiss: () => void;
  title: string;
  subtitle?: string;
  children: ReactNode;
  footer?: ReactNode;
  height?: number | 'auto';
  scrollable?: boolean;
  closeLabel?: string;
  testID?: string;
};

/** Drag belongs only to the grabber. The content keeps native scrolling and text gestures. */
export function Sheet({visible, onDismiss, title, subtitle, children, footer, height = 'auto', scrollable = true, closeLabel = '关闭', testID}: SheetProps) {
  const {colors: colors} = useAppTheme();
  const styles = useThemedStyles(makeStyles);

  const insets = useSafeAreaInsets();
  const window = useWindowDimensions();
  const reduced = useReducedMotion();
  const [mounted, setMounted] = useState(visible);
  const [progress] = useState(() => new Animated.Value(0));
  const [drag] = useState(() => new Animated.Value(0));
  const titleRef = useRef<Text>(null);
  const closing = useRef(false);
  const latest = useRef({onDismiss, visible});
  useLayoutEffect(() => {latest.current = {onDismiss, visible};}, [onDismiss, visible]);
  if (visible && !mounted) setMounted(true);
  const maxHeight = Math.max(220, window.height - insets.top - 16);
  const animateClose = useCallback((notify: boolean) => {
    if (closing.current) return;
    closing.current = true;
    Keyboard.dismiss();
    progress.stopAnimation();
    Animated.timing(progress, {toValue: 0, duration: reduced ? motion.crossfade : motion.exit,
      easing: Easing.in(Easing.quad), useNativeDriver: nativeDriver}).start(({finished}) => {
      if (!finished) return;
      setMounted(false);
      if (notify) latest.current.onDismiss();
      closing.current = false;
    });
  }, [progress, reduced]);
  useEffect(() => {
    if (visible) {
      closing.current = false;
      drag.setValue(0);
      progress.stopAnimation();
      Animated.timing(progress, {toValue: 1, duration: reduced ? motion.crossfade : motion.enter,
        easing: Easing.out(Easing.cubic), useNativeDriver: nativeDriver}).start();
    } else if (mounted) animateClose(false);
  }, [visible, reduced, drag, progress, mounted, animateClose]);
  useEffect(() => () => {progress.stopAnimation(); drag.stopAnimation();}, [progress, drag]);

  const dismiss = useCallback(() => animateClose(true), [animateClose]);
  // PanResponder registers these callbacks; it never invokes them during render.
  // eslint-disable-next-line react-hooks/refs
  const responder = useMemo(() => PanResponder.create({
    onMoveShouldSetPanResponder: (_, gesture) => gesture.dy > 5 && Math.abs(gesture.dy) > Math.abs(gesture.dx),
    onPanResponderGrant: () => {drag.stopAnimation();},
    onPanResponderMove: (_, gesture) => drag.setValue(Math.max(0, gesture.dy)),
    onPanResponderRelease: (_, gesture) => {
      if (gesture.dy > 90 || (gesture.dy > 24 && gesture.vy > 0.8)) dismiss();
      else if (reduced) drag.setValue(0);
      else Animated.spring(drag, {toValue: 0, ...motion.spring, useNativeDriver: nativeDriver}).start();
    },
    onPanResponderTerminate: () => {
      if (reduced) drag.setValue(0);
      else Animated.spring(drag, {toValue: 0, ...motion.spring, useNativeDriver: nativeDriver}).start();
    },
  }), [dismiss, drag, reduced]);

  const focusTitle = () => {
    if (Platform.OS === 'web') {
      // React Native Web's Modal owns focus trapping and restoration.
      const node = titleRef.current as unknown as {setAttribute?: (name: string, value: string) => void; focus?: () => void};
      node?.setAttribute?.('tabindex', '-1');
      node?.focus?.();
    } else {
      const node = findNodeHandle(titleRef.current);
      if (node) AccessibilityInfo.setAccessibilityFocus(node);
    }
  };
  return <Modal visible={mounted} transparent animationType="none" statusBarTranslucent
    onRequestClose={dismiss} onShow={focusTitle} supportedOrientations={['portrait', 'landscape']}>
    <View style={styles.modalRoot}>
      <Animated.View pointerEvents="none" style={[StyleSheet.absoluteFill, styles.scrim, {opacity: progress}]}/>
      <Pressable accessibilityRole="button" accessibilityLabel={closeLabel} onPress={dismiss}
        style={StyleSheet.absoluteFill}/>
      <KeyboardAvoidingView pointerEvents="box-none" behavior={Platform.OS === 'ios' ? 'padding' : undefined} style={[styles.keyboard, Platform.OS === 'web' && window.width >= 500 && {paddingLeft:window.width>=860?370:0,paddingBottom:Math.max(20,(window.height-900)/2)}]}>
        <Animated.View testID={testID} accessibilityViewIsModal onAccessibilityEscape={dismiss}
          style={[styles.sheet, {maxHeight, paddingBottom: Math.max(insets.bottom, spacing.lg),
            marginLeft: insets.left, marginRight: insets.right,
            height: height === 'auto' ? undefined : Math.min(height, maxHeight),
            opacity: progress,
            transform: [{translateY: Animated.add(drag, progress.interpolate({inputRange: [0, 1], outputRange: [reduced ? 0 : maxHeight, 0]}))}],
          }]}>
          <View {...responder.panHandlers} style={styles.grabberArea} accessible={false}>
            <View style={styles.grabber}/>
          </View>
          <View style={styles.sheetHeader}>
            <View style={styles.heading}>
              <Text ref={titleRef} accessibilityRole="header" style={styles.sheetTitle}>{title}</Text>
              {subtitle ? <Text style={styles.sheetSubtitle}>{subtitle}</Text> : null}
            </View>
            <IconButton label={closeLabel} onPress={dismiss}><X size={20} strokeWidth={1.8} color={colors.muted}/></IconButton>
          </View>
          {scrollable ? <ScrollView style={styles.sheetScroll} contentContainerStyle={styles.sheetContent}
            keyboardShouldPersistTaps="handled" keyboardDismissMode={Platform.OS === 'ios' ? 'interactive' : 'on-drag'}
            showsVerticalScrollIndicator={false}>{children}</ScrollView>
            : <View style={styles.sheetContent}>{children}</View>}
          {footer ? <View style={styles.sheetFooter}>{footer}</View> : null}
        </Animated.View>
      </KeyboardAvoidingView>
    </View>
  </Modal>;
}

export function Entrance({children, style, transitionKey}: {children: ReactNode; style?: StyleProp<ViewStyle>; transitionKey?: string | number}) {
  const reduced = useReducedMotion();
  const [progress] = useState(() => new Animated.Value(1));
  useEffect(() => {
    progress.stopAnimation();
    progress.setValue(0);
    Animated.timing(progress, {toValue: 1, duration: reduced ? motion.crossfade : motion.enter,
      easing: Easing.out(Easing.cubic), useNativeDriver: nativeDriver}).start();
    return () => progress.stopAnimation();
  }, [transitionKey, progress, reduced]);
  return <Animated.View style={[style, {opacity: progress.interpolate({inputRange:[0,1],outputRange:[.92,1]}),
    transform: [{translateY: progress.interpolate({inputRange: [0, 1], outputRange: [reduced ? 0 : 6, 0]})}]}]}>{children}</Animated.View>;
}

const makeStyles = (colors: AppColors) => StyleSheet.create({
  icon: {alignItems: 'center', justifyContent: 'center', borderRadius: radii.pill},
  iconSoft: {backgroundColor: colors.soft},
  iconSelected: {backgroundColor: colors.accentSoft},
  button: {minHeight: 52, borderRadius: radii.control, paddingHorizontal: spacing.xl, paddingVertical: 14,
    flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: spacing.sm},
  buttonAccent: {backgroundColor: colors.accent},
  buttonQuiet: {backgroundColor: colors.soft},
  buttonDanger: {backgroundColor: colors.dangerSoft},
  buttonLabel: {fontSize: 16, fontWeight: '600', lineHeight: 22, flexShrink: 1, textAlign: 'center'},
  modalRoot: {flex: 1},
  scrim: {backgroundColor: colors.scrim},
  keyboard: {flex: 1, justifyContent: 'flex-end', alignItems: 'center'},
  sheet: {width: '100%', maxWidth: 430, flexShrink: 1, backgroundColor: colors.surface, borderTopLeftRadius: radii.sheet,
    borderTopRightRadius: radii.sheet, overflow: 'hidden'},
  grabberArea: {height: 30, alignItems: 'center', justifyContent: 'center'},
  grabber: {width: 34, height: 4, borderRadius: radii.pill, backgroundColor: colors.line},
  sheetHeader: {paddingHorizontal: spacing.xl, paddingBottom: spacing.xl, flexDirection: 'row', alignItems: 'center', gap: spacing.md},
  heading: {flex: 1},
  sheetTitle: {fontSize: 24, lineHeight: 32, fontWeight: '700', letterSpacing: -0.5, color: colors.ink},
  sheetSubtitle: {fontSize: 14, lineHeight: 21, color: colors.muted, marginTop: spacing.xs},
  sheetScroll: {flexShrink: 1},
  sheetContent: {paddingHorizontal: spacing.xl, paddingBottom: spacing.lg},
  sheetFooter: {paddingHorizontal: spacing.xl, paddingTop: spacing.md},
});
