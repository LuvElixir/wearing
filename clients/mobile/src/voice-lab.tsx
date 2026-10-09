import {useRef, useState} from 'react';
import {Keyboard, Platform, ScrollView, StyleSheet, Text, View} from 'react-native';
import {SafeAreaProvider, SafeAreaView} from 'react-native-safe-area-context';
import * as SQLite from 'expo-sqlite';
import {createSqliteState, createSqliteStore, type SqliteState} from './sqlite-store';
import {IntentComposer, type VoiceInputDriver} from './experience/IntentComposer';
import {AppDock} from './experience/AppDock';
import {TactilePressable} from './experience/primitives';
import {colors as c} from './experience/tokens';
import {voiceErrorMessage} from './voice-diagnostics';

// Intentionally separate from storage.ts: this route must never open a user's database.
const QA_DATABASE = 'wearing-voice-qa.db';
function qaStore() {
  const runtime = globalThis as typeof globalThis & {__wearingVoiceQaStateV1?: SqliteState};
  const state = runtime.__wearingVoiceQaStateV1 ??= createSqliteState();
  return createSqliteStore(() => SQLite.openDatabaseAsync(QA_DATABASE, {useNewConnection: true}), state);
}

function VoiceLab() {
  const [phase, setPhase] = useState<VoiceInputDriver['phase']>('idle');
  const [text, setText] = useState(''), [keyboard, setKeyboard] = useState(false), [notice, setNotice] = useState('');
  const [result, setResult] = useState('尚未运行'), [running, setRunning] = useState(false), [height, setHeight] = useState(0);
  const busy = useRef(false);
  const reset = () => {setPhase('idle'); setNotice('');};
  const finish = () => {setPhase('idle'); setNotice('示例转写完成'); setText('这是用于检查输入栏的合成文字。');};
  const cancel = () => {setPhase('idle'); setNotice('已取消');};
  const error = () => {
    setPhase('idle');
    setNotice(voiceErrorMessage(new Error('FunctionCallException: SQLite Error code 5: database is locked'), '识别未完成，可以重试。'));
  };
  const start = () => {setKeyboard(false); Keyboard.dismiss(); setNotice(''); setPhase('transcribing');};
  const voice: VoiceInputDriver = {
    phase, ready: true, canStart: phase === 'idle', message: '',
    start: () => {setNotice(''); setPhase('recording');}, commit: start,
    cancel, interrupt: () => setPhase('idle'),
  };
  const run = async () => {
    if (busy.current) return;
    busy.current = true; setRunning(true); setResult('运行中 · 200 次操作');
    const started = performance.now();
    try {
      const store = qaStore(), operations: Promise<unknown>[] = [];
      // All 200 calls are submitted without awaiting. Identical keys deliberately
      // collide, and both members of each batch must match its exact sequence.
      for (let sequence = 1; sequence <= 50; sequence++) {
        operations.push(store.put('qa:head', {sequence, phase: 'draft'}));
        operations.push(store.batch([['qa:head', {sequence, phase: 'committed'}], ['qa:copy', {sequence, phase: 'committed'}]]));
        for (const key of ['qa:head', 'qa:copy']) operations.push(store.get<{sequence: number; phase: string}>(key).then(value => {
          if (value?.sequence !== sequence || value.phase !== 'committed') throw new Error('原子性或写入顺序不一致');
        }));
      }
      const results = await Promise.allSettled(operations);
      const failures = results.filter(value => value.status === 'rejected');
      const elapsed = Math.round(performance.now() - started);
      setResult(failures.length ? `FAIL · ${failures.length} / 200 失败 · ${elapsed} ms` : `PASS · 200 / 200 · ${elapsed} ms`);
    } catch {setResult('FAIL · 测试库未能完成初始化');}
    finally {busy.current = false; setRunning(false);}
  };
  return <SafeAreaView style={s.page}>
    <ScrollView contentContainerStyle={s.content} keyboardShouldPersistTaps="handled">
      <Text style={s.eyebrow}>开发验证 · 合成状态</Text>
      <Text style={s.title}>输入与保存</Text>
      <Text style={s.description}>仅检查原生存储与界面状态；不录音、不发网络请求，不代表真机语音识别结果。</Text>
      <View style={s.card}>
        <Text style={s.heading}>隔离存储检查</Text>
        <Text style={s.caption}>{QA_DATABASE}</Text>
        <Text testID="voice-lab-result" accessibilityLiveRegion="polite" style={s.result}>{result}</Text>
        <TactilePressable accessibilityLabel="运行 200 次存储检查" onPress={run} disabled={running} style={s.primary}>
          <Text style={s.primaryText}>运行 200 次存储检查</Text>
        </TactilePressable>
      </View>
      <View style={s.card}>
        <Text style={s.heading}>合成输入状态</Text>
        <View style={s.controls}>
          {[['预览转写状态', start], ['完成', finish], ['取消', cancel], ['错误', error], ['重置', reset]] .map(([label, action]) =>
            <TactilePressable key={label as string} accessibilityLabel={label as string} onPress={action as () => void} style={s.control}>
              <Text style={s.controlText}>{label as string}</Text>
            </TactilePressable>)}
        </View>
        <Text testID="voice-lab-height" style={s.caption}>当前栏高度 {height} pt · 状态 {phase}</Text>
        <Text style={s.caption}>完成仅放入合成草稿。切换文字可检查编辑模式；发送按钮只清空合成草稿。</Text>
      </View>
    </ScrollView>
    <View style={s.dockSpace}>
      <AppDock>
        <View onLayout={event => setHeight(event.nativeEvent.layout.height)}>
          <IntentComposer active offline={false} keyboard={keyboard} text={text} voice={voice} notice={notice}
            scopeKey="voice-lab-synthetic" onKeyboard={setKeyboard} onText={setText} onAppend={value => setText(value)}
            onSend={() => {setText(''); setNotice('示例文字已清空，未发送');}}
            onAdd={() => setNotice('此处仅预览输入控件')} onCamera={() => setNotice('此处不启用相机')} onEngage={() => {}}/>
        </View>
      </AppDock>
    </View>
  </SafeAreaView>;
}

export default function VoiceLabRoute() {
  if (!__DEV__ || Platform.OS === 'web') return <View style={s.unavailable}><Text>无可用页面</Text></View>;
  return <SafeAreaProvider><VoiceLab/></SafeAreaProvider>;
}

const s = StyleSheet.create({
  page: {flex: 1, backgroundColor: c.canvas}, unavailable: {flex: 1, alignItems: 'center', justifyContent: 'center'},
  content: {padding: 24, gap: 16, paddingBottom: 80}, eyebrow: {fontSize: 12, lineHeight: 18, color: c.muted},
  title: {fontSize: 28, lineHeight: 36, fontWeight: '600', color: c.ink},
  description: {fontSize: 14, lineHeight: 22, color: c.muted}, card: {padding: 20, borderRadius: 24, backgroundColor: c.surface, gap: 12},
  heading: {fontSize: 17, lineHeight: 24, fontWeight: '500', color: c.ink}, caption: {fontSize: 12, lineHeight: 18, color: c.muted},
  result: {fontSize: 16, lineHeight: 24, fontWeight: '500', color: c.ink},
  primary: {minHeight: 48, borderRadius: 16, backgroundColor: c.accent, alignItems: 'center', justifyContent: 'center'},
  primaryText: {fontSize: 15, lineHeight: 22, fontWeight: '500', color: c.surface},
  controls: {flexDirection: 'row', flexWrap: 'wrap', gap: 8},
  control: {paddingHorizontal: 14, minHeight: 44, borderRadius: 14, alignItems: 'center', justifyContent: 'center', backgroundColor: c.soft},
  controlText: {fontSize: 14, lineHeight: 20, color: c.ink}, dockSpace: {paddingBottom: 12},
});
