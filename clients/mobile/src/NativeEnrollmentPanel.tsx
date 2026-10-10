import {useEffect, useRef, useState} from 'react';
import {Alert, AppState, StyleSheet, Text, TextInput, View} from 'react-native';
import {ArrowLeft, Eye, EyeOff, LockKeyhole} from 'lucide-react-native';
import {useAppTheme, useThemedStyles, type AppColors} from './app-theme';
import {BrandWordmark} from './BrandWordmark';
import {ApiError, type Connection} from './core';
import {type EnrollmentFlow, type EnrollmentSnapshot} from './enrollment-client';
import {accountCredentials, EnrollmentError, enrollmentErrorText, enrollmentFieldFor, inviteCode, type EnrollmentField} from './enrollment-model';
import {IconButton, PrimaryButton, TactilePressable} from './experience/primitives';
import {Segment} from './experience/selection';
import {createNativeEnrollment} from './native-session';

/* Flat, form-first admission: one clear step, with server-confirmed recovery kept intact. */
export function NativeEnrollmentPanel({disabled, onExisting, onConnected}: {disabled?: boolean; onExisting: () => Promise<void>; onConnected: (connection: Connection) => Promise<void>}) {
  const {colors: c} = useAppTheme(), s = useThemedStyles(makeStyles);
  const flowRef = useRef<EnrollmentFlow | null>(null);
  const [snapshot, setSnapshot] = useState<EnrollmentSnapshot>({recovery: null, result: null});
  const [code, setCode] = useState(''), [username, setUsername] = useState(''), [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false), [focus, setFocus] = useState<EnrollmentField | null>(null);
  const [now, setNow] = useState(Date.now);
  const [entry, setEntry] = useState<'invite' | 'existing'>('invite');
  const [busy, setBusy] = useState<'restore' | 'verify' | 'register' | 'status' | 'finish' | 'cancel' | 'login' | null>('restore');
  const [error, setError] = useState(''), [errorField, setErrorField] = useState<EnrollmentField>();
  const live = useRef(true), lock = useRef(false);
  const codeRef = useRef<TextInput>(null), usernameRef = useRef<TextInput>(null), passwordRef = useRef<TextInput>(null);
  useEffect(() => {
    live.current = true;
    const flow = createNativeEnrollment(); flowRef.current = flow;
    const current = () => live.current && flowRef.current === flow;
    void flow.restore().then(value => {if (current()) setSnapshot(value);}).catch(() => {
      if (current()) setError(enrollmentErrorText('enrollment_storage'));
    }).finally(() => {if (current()) setBusy(null);});
    const subscription = AppState.addEventListener('change', state => {if (state !== 'active') {setShowPassword(false); setFocus(null);}});
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => {live.current = false; flow.dispose(); subscription.remove(); clearInterval(timer);};
  }, []);
  const currentFlow = () => {const flow = flowRef.current; if (!flow) throw new EnrollmentError('enrollment_busy'); return flow;};
  const result = snapshot.result, pending = snapshot.recovery;
  const expired = !!pending && Date.parse(pending.expires_at) <= now;
  const account = !expired && (result?.status === 'verified' || (result?.status === 'rejected' && ['username_invalid', 'username_unavailable', 'password_invalid'].includes(result.code || '')));
  const recovery = !!pending && !account;
  const locked = !!disabled || !!busy;
  // Native unmount does not guarantee onBlur; clear the departing field explicitly.
  function clearInputFocus() {
    codeRef.current?.blur(); usernameRef.current?.blur(); passwordRef.current?.blur();
    setFocus(null);
  }
  function switchEntry(next: typeof entry) {clearInputFocus(); setEntry(next); clearError();}
  const clearError = () => {setError(''); setErrorField(undefined);};
  function showError(cause: unknown) {
    if (!live.current) return;
    const code = cause instanceof EnrollmentError ? cause.code : 'enrollment_unconfirmed';
    const field = cause instanceof EnrollmentError ? cause.field || enrollmentFieldFor(code) : undefined;
    setError(cause instanceof ApiError ? cause.message : enrollmentErrorText(code)); setErrorField(field);
    if (field) ({code: codeRef, username: usernameRef, password: passwordRef})[field].current?.focus();
  }
  function accept(value: EnrollmentSnapshot) {
    if (!live.current) return;
    clearInputFocus(); setSnapshot(value);
    if ((value.result?.status === 'rejected' || value.result?.status === 'verified') && value.result.code) showError(new EnrollmentError(value.result.code));
  }
  async function run(action: NonNullable<typeof busy>, work: () => Promise<void>) {
    if (!live.current || lock.current || disabled || busy) return;
    lock.current = true; setBusy(action); clearError();
    try {await work();}
    catch (cause) {if (live.current) {clearInputFocus(); setSnapshot(currentFlow().current()); showError(cause);}}
    finally {lock.current = false; if (live.current) setBusy(null);}
  }
  async function finish() {
    const next = await currentFlow().finish();
    if (live.current) {setPassword(''); setCode(''); await onConnected(next);}
  }
  function verify() {
    try {inviteCode(code);} catch (cause) {showError(cause); return;}
    void run('verify', async () => {const value = await currentFlow().verify(code); accept(value); if (live.current && value.result?.status === 'verified') {setCode(''); setFocus(null);}});
  }
  function register() {
    try {accountCredentials(username, password);} catch (cause) {showError(cause); return;}
    void run('register', async () => {
      const value = await currentFlow().register(username, password); accept(value);
      if (!live.current) return;
      if (!['rejected', 'verified'].includes(value.result?.status || '')) {setPassword(''); setShowPassword(false); setFocus(null);}
      if (value.result?.status === 'completed' && value.result.handoff) {setBusy('finish'); await finish();}
    });
  }
  function leave() {
    if (locked) return;
    Alert.alert('离开这次加入？', account ? '邀请码和密码不会保存在表单中。下次可重新开始。' : '离开不会撤销已提交的注册。如果账号已经创建，可以通过已有账号登录。', [
      {text: '继续留在这里', style: 'cancel'},
      {text: '离开', onPress: () => {void run('cancel', async () => {
        const flow = currentFlow();
        if (!expired) {
          try {
            const value = await flow.cancel(); accept(value);
            if (value.result?.status !== 'cancelled' && value.result?.status !== 'completed' && !value.result?.cancel_requested) throw new EnrollmentError('enrollment_unconfirmed');
          } catch (cause) {
            if (live.current) Alert.alert('服务还没有确认', '可以继续保留进度，或只移除这台手机的登录进度。移除不会撤销已提交的注册；下次请先尝试已有账号登录。', [
              {text: '保留进度', style: 'cancel'}, {text: '只移除本机进度', onPress: () => {void run('cancel', async () => {await currentFlow().forget(); if (live.current) {setSnapshot(currentFlow().current()); setCode(''); setPassword(''); setShowPassword(false); setFocus(null);}});}},
            ]);
            throw cause;
          }
        }
        await flow.forget();
        if (live.current) {setSnapshot(flow.current()); setCode(''); setPassword(''); setShowPassword(false); setFocus(null);}
      });}},
    ]);
  }
  const completed = result?.status === 'completed';
  return <View style={s.root}>
    <View style={s.wordmark}><BrandWordmark width={56} color={c.ink}/></View>
    <View style={s.form}>
      {pending ? <TactilePressable style={s.back} accessibilityLabel="离开这次加入" disabled={locked} onPress={leave}><ArrowLeft size={18} color={c.muted}/><Text style={s.backLabel}>返回</Text></TactilePressable> : null}
      <Text accessibilityRole="header" style={s.title}>{account ? '创建你的账号' : recovery ? completed ? '账号已准备好' : expired ? '这次加入已过期' : '确认一下进度' : '欢迎来到 Pajio'}</Text>
      <Text style={s.lead}>{account ? '设好账号和密码，就可以开始了。' : recovery ? completed ? '你的注册已完成，登录后开始。' : expired ? '若刚才提交过注册，可以尝试已有账号登录。' : '注册进度会留在这里。先确认结果，不必重新填写。' : '日常交给我，时间留给你。'}</Text>
      {!pending ? <View accessibilityRole="tablist" accessibilityLabel="加入或登录" style={s.tabs}>
        <Segment label="邀请码加入" selected={entry === 'invite'} disabled={locked} onPress={() => switchEntry('invite')}/>
        <Segment label="已有账号" selected={entry === 'existing'} disabled={locked} onPress={() => switchEntry('existing')}/>
      </View> : null}
      {!pending && entry === 'invite' ? <View style={s.fields}>
        <Text style={s.label}>邀请码</Text>
        <TextInput selectionColor={c.focusRing} cursorColor={c.focusRing} underlineColorAndroid="transparent" ref={codeRef} accessibilityLabel="邀请码" placeholder="输入邀请码" placeholderTextColor={c.muted} value={code} onChangeText={value => {setCode(value); clearError();}} onFocus={() => setFocus('code')} onBlur={() => setFocus(null)} editable={!locked}
          autoCapitalize="none" autoCorrect={false} autoComplete="off" textContentType="none" returnKeyType="go" onSubmitEditing={verify} style={[s.input, focus === 'code' && s.focused, errorField === 'code' && s.invalid]}/>
        <Text style={s.hint}>验证后，创建你的 Pajio 账号。</Text>
      </View> : account ? <View style={s.fields}>
        <Text style={s.label}>账号</Text>
        <TextInput selectionColor={c.focusRing} cursorColor={c.focusRing} underlineColorAndroid="transparent" ref={usernameRef} accessibilityLabel="账号" value={username} placeholder="怎么称呼你的账号" placeholderTextColor={c.muted} onChangeText={value => {setUsername(value); clearError();}} onFocus={() => setFocus('username')} onBlur={() => setFocus(null)} editable={!locked}
          autoCapitalize="none" autoCorrect={false} autoComplete="username-new" textContentType="username" returnKeyType="next" onSubmitEditing={() => passwordRef.current?.focus()} style={[s.input, focus === 'username' && s.focused, errorField === 'username' && s.invalid]}/>
        <Text style={s.hint}>4–32 位，字母开头，可用数字、点、横线或下划线。</Text>
        <Text style={[s.label, s.passwordLabel]}>密码</Text>
        <View style={[s.passwordField, focus === 'password' && s.focused, errorField === 'password' && s.invalid]}>
          <TextInput selectionColor={c.focusRing} cursorColor={c.focusRing} underlineColorAndroid="transparent" ref={passwordRef} accessibilityLabel="密码" value={password} placeholder="至少 12 个字符" placeholderTextColor={c.muted} onChangeText={value => {setPassword(value); clearError();}} onFocus={() => setFocus('password')} onBlur={() => setFocus(null)} editable={!locked}
            secureTextEntry={!showPassword} autoCapitalize="none" autoCorrect={false} autoComplete="new-password" textContentType="newPassword" returnKeyType="go" onSubmitEditing={register} style={s.passwordInput}/>
          <IconButton variant="plain" label={showPassword ? '隐藏密码' : '显示密码'} disabled={locked} onPress={() => setShowPassword(value => !value)}>{showPassword ? <EyeOff size={20} color={c.muted}/> : <Eye size={20} color={c.muted}/>}</IconButton>
        </View>
        <Text style={s.hint}>至少 12 个字符，请使用独立的登录密码。</Text>
      </View> : null}
      {error ? <Text accessibilityRole="alert" accessibilityLiveRegion="polite" style={s.error}>{error}</Text> : null}
      {result?.cancel_requested ? <Text style={s.hint}>已停止交付这次登录。注册仍可能完成，可稍后使用已有账号登录。</Text> : null}
      <View style={s.actions}>
        {!pending && entry === 'invite' ? <PrimaryButton style={s.primary} label={busy === 'verify' ? '正在核对邀请码…' : '继续'} loading={busy === 'verify' || busy === 'restore'} disabled={locked} onPress={verify}/> : !pending && entry === 'existing' ? <PrimaryButton style={s.primary} label={busy === 'login' ? '正在打开登录…' : '登录 Pajio'} loading={busy === 'login'} disabled={locked} onPress={() => {void run('login', onExisting);}}/> : account ?
          <PrimaryButton style={s.primary} label={busy === 'register' ? '正在准备账号…' : busy === 'finish' ? '正在登录…' : '创建账号，进入 Pajio'} loading={busy === 'register' || busy === 'finish'} disabled={locked} onPress={register}/> :
          completed && result.handoff ? <PrimaryButton style={s.primary} label="进入 Pajio" loading={busy === 'finish'} disabled={locked} onPress={() => {void run('finish', finish);}}/> :
          !expired && !completed ? <PrimaryButton style={s.primary} label="查询这次进度" loading={busy === 'status'} disabled={locked} onPress={() => {void run('status', async () => accept(await currentFlow().status()));}}/> : null}
        {recovery ? <TactilePressable accessibilityLabel="已有账号，登录" disabled={locked} style={s.existing} onPress={() => {void run('login', onExisting);}}><Text style={s.existingLabel}>已有账号？<Text style={s.existingAction}>登录</Text></Text></TactilePressable> : null}
      </View>
      {(!pending && entry === 'existing') || recovery ? <Text style={s.loginNote}>将在系统安全窗口验证账号，完成后返回 App。</Text> : account ? <View style={s.privacy}><LockKeyhole size={13} color={c.muted}/><Text style={s.loginNote}>密码用于登录，不会交给 Agent</Text></View> : null}
    </View>
  </View>;
}
const makeStyles = (c: AppColors) => StyleSheet.create({
  root: {width: '100%', maxWidth: 420, alignSelf: 'center', paddingTop: 0, paddingBottom: 32},
  wordmark: {alignItems: 'flex-start'}, form: {marginTop: 98},
  title: {fontSize: 32, lineHeight: 39, letterSpacing: -.8, fontWeight: '700', color: c.ink}, lead: {fontSize: 16, lineHeight: 26, color: c.muted, marginTop: 4},
  tabs: {flexDirection: 'row', borderBottomWidth: 1, borderBottomColor: c.line, marginTop: 24},
  fields: {marginTop: 29, gap: 8}, label: {fontSize: 14, lineHeight: 22, fontWeight: '500', color: c.ink},
  input: {outlineWidth:0,minHeight: 52, borderRadius: 12, paddingHorizontal: 16, paddingVertical: 14, borderWidth: 1, borderColor: c.line, backgroundColor: c.surface, fontSize: 16, lineHeight: 24, color: c.ink},
  focused: {borderColor: c.focusRing, outlineColor:c.focusRing,outlineStyle:'solid',outlineWidth:2,outlineOffset:2}, invalid: {borderColor: c.danger}, hint: {fontSize: 13, lineHeight: 22, color: c.muted, marginTop: 4}, passwordLabel: {marginTop: 10},
  passwordField: {flexDirection: 'row', alignItems: 'center', minHeight: 52, borderRadius: 12, borderWidth: 1, borderColor: c.line, paddingRight: 6, backgroundColor: c.surface},
  passwordInput: {outlineWidth:0,flex: 1, minWidth: 0, paddingHorizontal: 16, paddingVertical: 14, fontSize: 16, lineHeight: 24, color: c.ink},
  actions: {marginTop: 24, gap: 8}, primary: {minHeight: 52, borderRadius: 12},
  existing: {minHeight: 48, justifyContent: 'center', alignItems: 'center'}, existingLabel: {fontSize: 14, color: c.muted}, existingAction: {fontWeight: '600', color: c.accentInk},
  loginNote: {fontSize: 12, lineHeight: 20, color: c.muted, textAlign: 'center', marginTop: 16}, privacy: {marginTop: 0, flexDirection: 'row', justifyContent: 'center', gap: 6, alignItems: 'center'},
  error: {fontSize: 13, lineHeight: 21, color: c.danger, marginTop: 14},
  back: {minHeight: 44, flexDirection: 'row', alignItems: 'center', gap: 6, alignSelf: 'flex-start', marginBottom: 8}, backLabel: {fontSize: 13, color: c.muted},
});
