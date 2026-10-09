import {useAppTheme, useThemedStyles, type AppColors} from '../app-theme';
import {useCallback, useEffect, useLayoutEffect, useRef, useState, type ReactNode} from 'react';
import {useFocusEffect} from 'expo-router';
import {Animated, AppState, Easing, PanResponder, Platform, StyleSheet, Text, TextInput, useWindowDimensions, View} from 'react-native';
import {ArrowUp, Camera, Keyboard, Mic, Plus, X} from 'lucide-react-native';
import {HoldVoiceGesture, type HoldVoicePhase} from '../hold-voice';
import {IconButton, useReducedMotion} from './primitives';
import {motion} from './tokens';

const nativeDriver = Platform.OS !== 'web';
const inputReset = Platform.OS === 'web' ? {outlineWidth: 0, resize: 'none' as const} : {};
const fill = {position: 'absolute' as const, top: 0, right: 0, bottom: 0, left: 0};

function useTransition(target: number, reduced: boolean, duration: number = motion.crossfade) {
  const [value] = useState(() => new Animated.Value(target));
  useEffect(() => {
    const animation = Animated.timing(value, {toValue: target, duration: reduced ? 0 : duration,
      easing: Easing.out(Easing.cubic), useNativeDriver: nativeDriver, isInteraction: false});
    animation.start();
    return () => animation.stop();
  }, [duration, reduced, target, value]);
  return value;
}

function CrossfadeIcon({progress, first, second}: {progress: Animated.Value; first: ReactNode; second: ReactNode}) {
  const s = useThemedStyles(makeStyles);

  return <View pointerEvents="none" style={s.glyph}>
    <Animated.View style={[s.glyphLayer, {opacity: progress.interpolate({inputRange: [0, 1], outputRange: [1, 0]})}]}>{first}</Animated.View>
    <Animated.View style={[s.glyphLayer, {opacity: progress}]}>{second}</Animated.View>
  </View>;
}

/** Indeterminate activity, not microphone level or invented recognition progress.
 * A single native animation graph keeps moving when JS is busy saving audio.
 */
function ProcessingDots({active, reduced}: {active: boolean; reduced: boolean}) {
  const s = useThemedStyles(makeStyles);

  const [progress] = useState(() => new Animated.Value(0));
  useEffect(() => {
    progress.setValue(0);
    if (!active || reduced) return;
    const animation = Animated.loop(Animated.timing(progress, {
      toValue: 1, duration: 1440, easing: Easing.linear,
      useNativeDriver: nativeDriver, isInteraction: false,
    }));
    animation.start();
    return () => animation.stop();
  }, [active, progress, reduced]);
  return <View accessible={false} accessibilityElementsHidden importantForAccessibility="no-hide-descendants" style={s.dots}>
    {[0, 1, 2].map(index => <Animated.View key={index} style={[s.dot, {opacity: reduced ? 0.65 : progress.interpolate({
      inputRange: [0, 0.12 + index * 0.17, 0.27 + index * 0.17, 0.52 + index * 0.17, 1],
      outputRange: [0.24, 0.24, 0.9, 0.24, 0.24],
    })}]}/>) }
  </View>;
}

type Hint = {text: string; kind: 'notice' | 'listening' | 'cancelling'};
/** Keep the last content alive while its opacity exits; never reserve dock height. */
function FloatingHint({text, kind, reduced}: {text: string; kind: Hint['kind']; reduced: boolean}) {
  const {colors: c} = useAppTheme();
  const s = useThemedStyles(makeStyles);

  const [shown, setShown] = useState<Hint>({text, kind});
  const progress = useTransition(text ? 1 : 0, reduced, text ? motion.release : motion.exit);
  if (text && (shown.text !== text || shown.kind !== kind)) setShown({text, kind});
  const danger = shown.kind === 'cancelling';
  return <Animated.View pointerEvents="none" aria-hidden={!text} accessibilityElementsHidden={!text}
    importantForAccessibility={text ? 'auto' : 'no-hide-descendants'}
    style={[s.floating, {opacity: progress, transform: [{translateY: progress.interpolate({inputRange: [0, 1], outputRange: [5, 0]})}]}]}>
    <View style={s.status} accessibilityLiveRegion="polite">
      {danger ? <X size={16} color={c.danger}/> : shown.kind === 'listening' ? <Mic size={16} color={c.accent}/> : null}
      <Text numberOfLines={3} style={[s.statusText, danger && {color: c.danger}]}>{shown.text}</Text>
    </View>
  </Animated.View>;
}

export type VoiceInputDriver = {
  phase: 'idle' | 'preparing' | 'recording' | 'saving' | 'transcribing';
  ready: boolean; canStart: boolean; message: string;
  start: () => unknown; commit: () => unknown; cancel: () => unknown; interrupt: () => unknown;
  pauseRecognition?: (paused: boolean) => void;
};
type Props = {
  active: boolean; offline: boolean; keyboard: boolean; text: string;
  scopeKey?: string;
  onKeyboard: (value: boolean) => void; onText: (value: string) => void;
  onAppend: (value: string) => void; onSend: () => void;
  onAdd: () => void; onCamera: () => void; onEngage: () => void;
  voice?: VoiceInputDriver; sending?: boolean; mediaActions?: boolean; notice?: string;
};

/** Shared input surface. The explicit driver owns real recording; demos remain isolated. */
export function IntentComposer(props: Props) {
  const {colors: c} = useAppTheme();
  const s = useThemedStyles(makeStyles);

  const latest = useRef(props);
  const {fontScale} = useWindowDimensions();
  // Text follows Dynamic Type; its native container grows with it rather than
  // clipping two input lines inside a fixed 44 pt viewport.
  const inputHeight = Math.max(44, Math.ceil(44 * fontScale));
  const intentHeight = inputHeight + 2, barHeight = inputHeight + 14;
  useLayoutEffect(() => {latest.current = props;});
  const realVoice = !!props.voice;
  const [phase, setPhase] = useState<HoldVoicePhase>('idle');
  const [processing, setProcessing] = useState(false);
  const [pendingCopy, setPendingCopy] = useState('正在转文字');
  const [notice, setNotice] = useState('');
  const [focused, setFocused] = useState(false), [wrappedText, setWrappedText] = useState(false);
  const input = useRef<TextInput>(null);
  const reduced = useReducedMotion();
  const alive = useRef(true), blocked = useRef(false);
  const interrupting = useRef(false);
  const timers = useRef<{recognition?: ReturnType<typeof setTimeout>; notice?: ReturnType<typeof setTimeout>}>({});
  const notify = (message: string) => {
    clearTimeout(timers.current.notice);
    if (!alive.current) return;
    setNotice(message);
    timers.current.notice = setTimeout(() => {if (alive.current) setNotice('');}, 2600);
  };
  // The constructor only stores these event callbacks; no ref is read during render.
  // eslint-disable-next-line react-hooks/refs
  const [gesture] = useState(() => new HoldVoiceGesture({
    onPhase: value => {if (alive.current) setPhase(value);},
    onStart: () => {setNotice(''); latest.current.onEngage(); latest.current.voice?.start();},
    onCommit: () => {
      if (latest.current.voice) {latest.current.voice.commit(); return;}
      if (!alive.current || !latest.current.active || latest.current.offline) return;
      const scope = latest.current.scopeKey;
      blocked.current = true;
      setProcessing(true);
      timers.current.recognition = setTimeout(() => {
        blocked.current = false;
        if (!alive.current || !latest.current.active || latest.current.offline || latest.current.scopeKey !== scope) return;
        setProcessing(false);
        latest.current.onAppend('明天提醒我带伞。');
        notify('示例文字，可修改后发送');
      }, 420);
    },
    onCancel: () => {
      if (latest.current.voice) {
        if (interrupting.current) latest.current.voice.interrupt(); else latest.current.voice.cancel();
      } else notify('已取消');
    },
    onShortPress: () => notify('按住说话，松开转文字'),
  }));
  const cancel = useCallback(() => {
    interrupting.current = true;
    gesture.cancel();
    latest.current.voice?.interrupt();
    interrupting.current = false;
    clearTimeout(timers.current.recognition);
    blocked.current = false;
    if (alive.current) setProcessing(false);
  }, [gesture]);
  useFocusEffect(useCallback(() => () => cancel(), [cancel]));
  useLayoutEffect(() => {cancel();}, [props.scopeKey, cancel]);
  useLayoutEffect(() => {
    if (!props.active || (props.offline && !realVoice) || props.keyboard) cancel();
  }, [props.active, props.offline, props.keyboard, realVoice, cancel]);
  useEffect(() => {
    alive.current = true;
    const activeTimers = timers.current;
    const listener = AppState.addEventListener('change', state => {if (state !== 'active') cancel();});
    if (Platform.OS === 'web') window.addEventListener('blur', cancel);
    return () => {
      alive.current = false;
      interrupting.current = true;
      gesture.cancel();
      latest.current.voice?.interrupt();
      clearTimeout(activeTimers.recognition);
      clearTimeout(activeTimers.notice);
      listener.remove();
      if (Platform.OS === 'web') window.removeEventListener('blur', cancel);
    };
  }, [cancel, gesture]);
  const begin = () => {
    if (!latest.current.active || blocked.current || latest.current.sending) return;
    if (latest.current.voice && !latest.current.voice.canStart) {notify(latest.current.voice.message || '麦克风正在准备'); return;}
    if (latest.current.offline && !latest.current.voice) {notify('离线时可以先打字'); return;}
    latest.current.onEngage();
    gesture.begin();
  };
  const beginRef = useRef(begin);
  useLayoutEffect(() => {beginRef.current = begin;});
  // PanResponder.create stores handlers; refs are read only by later input events.
  // eslint-disable-next-line react-hooks/refs
  const [responder] = useState(() => PanResponder.create({
    onStartShouldSetPanResponder: () => latest.current.active && !blocked.current,
    onMoveShouldSetPanResponder: () => false,
    onPanResponderGrant: () => beginRef.current(),
    onPanResponderMove: (_, state) => gesture.move(state.dy),
    onPanResponderRelease: () => gesture.release(),
    onPanResponderTerminationRequest: () => true,
    onPanResponderTerminate: cancel,
  }));
  const holding = phase === 'listening' || phase === 'cancelling';
  const cancelling = phase === 'cancelling';
  const pauseRecognition = props.voice?.pauseRecognition;
  useEffect(() => {pauseRecognition?.(cancelling);}, [cancelling, pauseRecognition]);
  const realProcessing = !!props.voice && ['preparing','saving','transcribing'].includes(props.voice.phase);
  const pending = processing || realProcessing || !!props.sending;
  const busy = holding || pending || phase === 'pressing';
  const hasSend = props.keyboard && !!props.text.trim();
  const mode = useTransition(props.keyboard ? 1 : 0, reduced);
  const sendMode = useTransition(hasSend ? 1 : 0, reduced);
  const focus = useTransition(focused ? 1 : 0, reduced, motion.release);
  const activeSurface = useTransition(holding && !cancelling ? 1 : 0, reduced);
  const cancelSurface = useTransition(cancelling ? 1 : 0, reduced);
  const pendingSurface = useTransition(pending ? 1 : 0, reduced);
  useLayoutEffect(() => {
    // Focus belongs to the mode change, not to the end of its visual transition.
    if (props.keyboard && props.active) input.current?.focus();
    else input.current?.blur();
  }, [props.keyboard, props.active]);
  const keyHandlers = Platform.OS === 'web' ? {
    onKeyDown: (e: {key: string; repeat: boolean; preventDefault: () => void}) => {
      if (e.key === 'Escape') {e.preventDefault(); gesture.cancel();}
      if (e.key === ' ' || e.key === 'Enter') {e.preventDefault(); if (!e.repeat) begin();}
    },
    onKeyUp: (e: {key: string; preventDefault: () => void}) => {
      if (e.key === ' ' || e.key === 'Enter') {e.preventDefault(); gesture.release();}
    },
    onFocus: () => setFocused(true),
    onBlur: () => {setFocused(false); cancel();},
  } : {};
  const label = cancelling ? '松开取消' : holding ? '松开转文字' : '按住说话';
  const pendingLabel = props.voice?.phase === 'preparing' ? '准备麦克风' : props.sending ? '发送中' : props.voice?.phase === 'saving' && props.voice.message.startsWith('正在取消') ? '取消中' : '正在转文字';
  // Preserve the last real operation until its visual exit has completed.
  if (pending && pendingCopy !== pendingLabel) setPendingCopy(pendingLabel);
  const hintKind: Hint['kind'] = cancelling ? 'cancelling' : holding ? 'listening' : 'notice';
  // The input itself owns recognition feedback. A second toast repeats the same
  // state, obscures conversation, and makes normal latency look like an error.
  const hint = cancelling ? '松开取消，移回继续' : pending ? '' : holding ? props.voice ? '上滑取消' : '上滑取消 · 手势示例' : props.notice || notice;
  return <View style={[s.wrap, {height: barHeight}]}>
    <FloatingHint text={hint} kind={hintKind} reduced={reduced}/>
    <View testID="intent-bar" style={[s.bar, {height: barHeight}]}>
      <Animated.View pointerEvents="none" style={[s.focusRing, {opacity: focus}]}/>
      <Animated.View pointerEvents="none" style={[s.surface, {backgroundColor: c.accentSoft, opacity: activeSurface}]}/>
      <Animated.View pointerEvents="none" style={[s.surface, {backgroundColor: c.dangerSoft, opacity: cancelSurface}]}/>
      {props.mediaActions !== false && <IconButton label="拍一张" variant="plain" onPress={props.onCamera} disabled={busy}><Camera size={22} strokeWidth={1.65} color={c.muted}/></IconButton>}
      <View style={[s.intent, {height: intentHeight}]}>
       <Animated.View
        aria-hidden={pending} accessibilityElementsHidden={pending} importantForAccessibility={pending ? 'no-hide-descendants' : 'auto'}
        style={[s.modeLayer, {opacity: pendingSurface.interpolate({inputRange: [0, 1], outputRange: [1, 0]})}]}>
       <Animated.View pointerEvents={props.keyboard ? 'none' : 'auto'}
        aria-hidden={props.keyboard} accessibilityElementsHidden={props.keyboard} importantForAccessibility={props.keyboard ? 'no-hide-descendants' : 'auto'}
        style={[s.modeLayer, {opacity: mode.interpolate({inputRange: [0, 1], outputRange: [1, 0]})}]}>
        <View
        {...responder.panHandlers} {...keyHandlers} accessible accessibilityRole="button" tabIndex={props.keyboard ? -1 : 0}
        accessibilityLabel={label} accessibilityHint={props.voice ? '按住说话，松开转为文字，上滑取消。也可双击开始，再双击结束。' : '按住说话，松开转为文字，上滑取消。本页仅预览手势。'}
        accessibilityState={{busy: pending, disabled: pending || !props.active}}
        accessibilityActions={[{name: 'activate', label: holding ? '结束语音' : '开始语音'}, {name: 'escape', label: '取消语音'}]}
        onAccessibilityAction={e => {if (e.nativeEvent.actionName === 'escape') gesture.cancel(); else if (e.nativeEvent.actionName === 'activate') {if (gesture.phase !== 'idle') gesture.release(); else begin();}}}
        style={[s.hold, {height: intentHeight}, Platform.OS === 'web' && {outlineWidth: 0}]}>
        <Text selectable={false} style={[s.holdText, holding && {color: c.accent}, cancelling && {color: c.danger}]}>{label}</Text>
        </View>
       </Animated.View>
       <Animated.View pointerEvents={props.keyboard ? 'auto' : 'none'}
        aria-hidden={!props.keyboard} accessibilityElementsHidden={!props.keyboard} importantForAccessibility={props.keyboard ? 'auto' : 'no-hide-descendants'}
        style={[s.modeLayer, {opacity: mode}]}>
        <Text aria-hidden pointerEvents="none" accessible={false} accessibilityElementsHidden importantForAccessibility="no-hide-descendants"
          onLayout={event => setWrappedText(event.nativeEvent.layout.height > 25)} style={s.measureText}>{props.text || ' '}</Text>
        <TextInput ref={input} testID="intent-text" accessibilityLabel="对 Pajio 说的话" placeholder="说一声，我来做…" placeholderTextColor={c.muted}
          {...(Platform.OS === 'web' ? {rows: 1, tabIndex: props.keyboard ? 0 : -1} : {numberOfLines: 2})}
          multiline scrollEnabled editable={props.keyboard && props.active && !pending} value={props.text} onChangeText={props.onText}
          onFocus={() => setFocused(true)} onBlur={() => setFocused(false)}
          selectionColor={c.accent} underlineColorAndroid="transparent"
          style={[s.input, {height: inputHeight, maxHeight: inputHeight, paddingVertical: wrappedText ? 0 : 11}, inputReset]}/>
       </Animated.View>
       </Animated.View>
       <Animated.View pointerEvents="none" testID="voice-processing" aria-hidden={!pending}
        accessibilityElementsHidden={!pending} importantForAccessibility={pending ? 'auto' : 'no-hide-descendants'}
        style={[s.modeLayer, s.processing, {opacity: pendingSurface}]}
        accessible accessibilityLabel={pendingCopy} accessibilityRole="progressbar" accessibilityState={{busy: pending}} accessibilityLiveRegion="polite">
        <ProcessingDots active={pending && props.active} reduced={reduced}/>
        <Text style={s.processingText}>{pendingCopy}</Text>
       </Animated.View>
      </View>
      <IconButton label={props.keyboard ? '切回语音' : '切换文字输入'} variant="plain" disabled={busy} onPress={() => {props.onEngage(); props.onKeyboard(!props.keyboard);}}>
        <CrossfadeIcon progress={mode} first={<Keyboard size={22} strokeWidth={1.65} color={c.muted}/>} second={<Mic size={21} strokeWidth={1.65} color={c.muted}/>}/>
      </IconButton>
      {(hasSend || props.mediaActions !== false) && <IconButton label={hasSend ? props.voice ? '发送消息' : '发送预览消息' : '添加照片、录音或记录'} variant="plain" size={44} disabled={busy || (hasSend && props.offline)} onPress={hasSend ? props.onSend : props.onAdd}>
        <CrossfadeIcon progress={sendMode} first={<Plus size={24} strokeWidth={1.6} color={c.muted}/>} second={<ArrowUp size={22} color={c.accent}/>}/>
      </IconButton>}
    </View>
  </View>;
}

const makeStyles = (c: AppColors) => StyleSheet.create({
  wrap: {position: 'relative', height: 58},
  bar: {height: 58, paddingHorizontal: 5, flexDirection: 'row', alignItems: 'center', gap: 1, backgroundColor: c.surface, borderWidth: 1, borderColor: c.line, borderRadius: 25},
  surface: {...fill, borderRadius: 22},
  focusRing: {position: 'absolute', top: -3, left: -3, right: -3, bottom: -3, borderWidth: 1, borderColor: c.line, borderRadius: 28},
  intent: {flex: 1, minWidth: 0, height: 46},
  modeLayer: {...fill, justifyContent: 'center'},
  hold: {height: 46, alignItems: 'center', justifyContent: 'center', borderRadius: 16},
  holdText: {fontSize: 16, lineHeight: 24, fontWeight: '500', color: c.ink},
  processing: {flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8},
  processingText: {fontSize: 15, lineHeight: 24, fontWeight: '400', color: c.muted},
  dots: {flexDirection: 'row', alignItems: 'center', gap: 3, width: 21, height: 16},
  dot: {width: 5, height: 5, borderRadius: 3, backgroundColor: c.accent},
  input: {height: 44, minHeight: 44, maxHeight: 44, width: '100%', paddingHorizontal: 7, margin: 0, borderWidth: 0, borderRadius: 14, fontSize: 16, lineHeight: 22, color: c.ink, textAlignVertical: 'top'},
  measureText: {position: 'absolute', left: 7, right: 7, top: 0, maxHeight: 44, overflow: 'hidden', fontSize: 16, lineHeight: 22, opacity: 0},
  glyph: {width: 24, height: 24},
  glyphLayer: {...fill, alignItems: 'center', justifyContent: 'center'},
  floating: {position: 'absolute', bottom: '100%', left: 4, right: 4, marginBottom: 10, alignItems: 'center', zIndex: 20},
  status: {maxWidth: '100%', minHeight: 36, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 7, paddingHorizontal: 13, paddingVertical: 8, borderRadius: 18, backgroundColor: c.surface, borderWidth: 1, borderColor: c.line},
  statusText: {flexShrink: 1, fontSize: 12, lineHeight: 18, color: c.muted, textAlign: 'center'},
});
