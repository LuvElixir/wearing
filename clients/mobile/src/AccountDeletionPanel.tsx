import {useEffect, useLayoutEffect, useRef, useState} from 'react';
import {ActivityIndicator, Platform, Text, TextInput, View} from 'react-native';
import type {Connection} from './core';
import {useAppTheme} from './app-theme';
import {PrimaryButton} from './experience/primitives';
import {AccountDeletionClient, sameAccount, type DeletionPlan, type DeletionRecovery, type DeletionStatus} from './account-deletion-client';
import {loadDeletionRecovery, saveDeletionRecovery} from './account-deletion-native';
import {reauthenticateNativeForDeletion} from './native-session';
import {serviceFetch} from './transport';

export type AccountDeletionProps = {connection: Connection | null; onReauthenticated(next: Connection): Promise<void>; onFrozen(target: Connection): Promise<void>; isCurrent?(): boolean};
export default function AccountDeletionPanel(props: AccountDeletionProps) {
  const {colors: c} = useAppTheme();
  const [connection, setConnection] = useState(props.connection), [plan, setPlan] = useState<DeletionPlan | null>(null), [recovery, setRecovery] = useState<DeletionRecovery | null>(null), [status, setStatus] = useState<DeletionStatus | null>(null);
  const [error, setError] = useState(''), [busy, setBusy] = useState(false), [confirmation, setConfirmation] = useState('');
  const live = useRef(true), working = useRef(false), frozen = useRef(false), handlers = useRef(props);
  useLayoutEffect(() => {handlers.current = props;}, [props]);
  const alive = () => live.current && (handlers.current.isCurrent?.() ?? true);
  const line = {color: c.muted, fontSize: 14, lineHeight: 23};
  async function act(run: () => Promise<void>) {
    if (working.current) return;
    working.current = true; setBusy(true); setError('');
    try {await run();} catch (cause) {if (live.current) setError(cause instanceof Error ? cause.message : '暂时无法确认注销进度，请稍后刷新。');}
    finally {working.current = false; if (live.current) setBusy(false);}
  }
  async function reflect(value: DeletionStatus, saved: DeletionRecovery) {
    if (live.current) {setStatus(value); setRecovery(saved);}
    if (value.state !== 'not_submitted') {
      await saveDeletionRecovery({...saved, phase: 'submitted'}).catch(() => {});
      if (!frozen.current) {frozen.current = true; try {await handlers.current.onFrozen(saved.target);} catch (cause) {frozen.current = false; throw cause;}}
    }
  }
  async function refresh(saved = recovery) {
    if (saved) return reflect(await new AccountDeletionClient(saved.target, serviceFetch).status(saved), saved);
    if (!connection?.session?.accessToken) throw new Error('请先登录你的云端账户。');
    const result = await new AccountDeletionClient(connection, serviceFetch).plan();
    if (alive()) {setPlan(result); setConfirmation('');}
  }
  useEffect(() => {
    live.current = true;
    void act(async () => {
      const saved = await loadDeletionRecovery(props.connection);
      if (!live.current) return;
      if (saved) {setRecovery(saved); await refresh(saved);}
      else if (props.connection?.session?.accessToken) await refresh();
    });
    return () => {live.current = false;};
    // The host keys the panel by account. Reauth remains within that account.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  async function reauth() {
    if (!connection) return;
    const result = await reauthenticateNativeForDeletion(connection);
    if (!result || !alive()) return;
    if (!sameAccount(result, connection)) throw new Error('账户不一致，请重新开始。');
    setConnection(result);
    await handlers.current.onReauthenticated(result);
    const latest = await new AccountDeletionClient(result, serviceFetch).plan();
    if (live.current) {setPlan(latest); setRecovery(null); setStatus(null); setConfirmation('');}
  }
  async function submit() {
    if (!connection || !plan || confirmation !== 'DELETE' || !alive()) return;
    const api = new AccountDeletionClient(connection, serviceFetch);
    try {
      const accepted = await api.submit(plan, async saved => {
        await saveDeletionRecovery(saved);
        if (live.current) setRecovery(saved);
      });
      await reflect(accepted.status, accepted.recovery);
    } catch (cause) {
      // Keep the receipt view even if the response was lost; never repeat blindly.
      const saved = await loadDeletionRecovery(connection);
      if (live.current && saved) setRecovery(saved);
      throw cause;
    }
  }
  const submitted = status && status.state !== 'not_submitted';
  const completed = status?.state === 'completed';
  if (Platform.OS === 'web') return <Text style={line}>请在 Pajio App 中管理账户注销。</Text>;
  return <View style={{gap: 18}}>
    <Text style={{color: c.ink, fontSize: 23, fontWeight: '600'}}>注销账户</Text>
    {submitted ? <><Text style={{color: c.ink, fontSize: 18, fontWeight: '600'}}>{completed ? '账户清理已完成' : '申请已收到，等待完成清理'}</Text><Text style={line}>{completed ? '服务已核对登记范围内的个人空间内容、索引和备份清理结果。共享空间的其他成员内容保留；最小身份注销记录保留，用于阻止旧账户重新访问。' : '账户业务访问已停止。实际数据清理还在等待执行，当前尚未确认删除完成。'}</Text>{!completed ? <Text style={line}>{status.code === 'adapter_unconfigured' ? '清理服务尚未配置，申请与查询凭证已保存。' : '正在等待服务返回后续处理回执。'}</Text> : null}<Text selectable style={line}>申请编号：{status.id}</Text></> : <Text style={line}>注销会停止这个账户的业务访问。个人空间按下面的范围清理；共享空间只退出成员关系，其他成员的内容会保留。</Text>}
    {plan && !submitted ? <View style={{gap: 12, padding: 18, borderRadius: 20, backgroundColor: c.surface}}><Text style={{color: c.ink, fontWeight: '600'}}>本次涉及 {plan.tenants.length} 个空间</Text>{plan.tenants.map(row => <View key={row.tenant_id} style={{gap: 4}}><Text selectable style={{color: c.ink}}>{row.tenant_id}</Text><Text style={line}>{row.action === 'erase_private' ? '个人空间 · 清理账户内容、原件及索引；备份按实际回执处理' : row.action === 'leave_shared' ? '共享空间 · 退出你的成员关系，共同内容保留' : '归属尚未确认 · 暂不能注销'}</Text></View>)}{plan.blockers.length ? <Text style={{...line, color: c.danger}}>有 {plan.blockers.length} 项归属尚未就绪，需要服务方核对后才能提交。</Text> : null}<Text style={line}>手机中该账户的草稿、待同步内容和缓存也会清理。尚未同步的内容请先保存；相册和系统日历原始记录不会因此删除。</Text></View> : null}
    {recovery && !submitted ? <><Text style={line}>{status?.state === 'not_submitted' ? '服务尚未收到这次注销申请。可回到连接设置重新登录，再查看注销计划。' : '查询凭证已保存。先核对处理结果，避免重复提交。'}</Text><PrimaryButton label="查询注销状态" tone="quiet" disabled={busy} onPress={() => {void act(() => refresh());}}/></> : null}
    {!submitted && connection?.session?.accessToken && (!plan || plan.reauth_required || recovery) ? <PrimaryButton label="重新验证身份" disabled={busy} onPress={() => {void act(reauth);}}/> : null}
    {plan?.ready && !plan.reauth_required && !recovery && !submitted ? <><Text style={line}>确认全部范围后，输入 DELETE 再提交。提交后会退出此账户，可凭本机保存的凭证查看进度。</Text><TextInput value={confirmation} onChangeText={setConfirmation} editable={!busy} autoCapitalize="characters" autoCorrect={false} accessibilityLabel="输入 DELETE 确认注销" placeholder="DELETE" placeholderTextColor={c.muted} style={{borderWidth: 1, borderColor: c.line, color: c.ink, borderRadius: 14, padding: 14, fontSize: 17}}/><PrimaryButton label="确认注销账户" disabled={busy || confirmation !== 'DELETE'} onPress={() => {void act(submit);}}/></> : null}
    {submitted ? <PrimaryButton label="刷新清理进度" tone="quiet" disabled={busy} onPress={() => {void act(() => refresh());}}/> : !recovery && connection?.session?.accessToken ? <PrimaryButton label="刷新注销范围" tone="quiet" disabled={busy} onPress={() => {void act(() => refresh(null));}}/> : null}
    {busy ? <ActivityIndicator color={c.accent}/> : null}
    {error ? <Text accessibilityLiveRegion="polite" style={{...line, color: c.danger}}>{error}</Text> : null}
    <Text style={{...line, fontSize: 12}}>注销查询凭证只用于查看此申请，不会恢复业务访问。请保留本机数据，直至看到清理完成的正式结果。</Text>
  </View>;
}
