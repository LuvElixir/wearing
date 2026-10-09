import {useCallback, useEffect, useRef, useState} from 'react';
import {ActivityIndicator, StyleSheet, Text, View} from 'react-native';
import {ChartNoAxesColumn, RefreshCw} from 'lucide-react-native';
import {Connection} from './core';
import {AppColors, useAppTheme, useThemedStyles} from './app-theme';
import {PrimaryButton, TactilePressable} from './experience/primitives';
import {loadUsage, minutesLabel, moneyLabel, tokenLabel, UsageCost, UsageResource, UsageSnapshot} from './usage-model';

function UsageContent({connection, fetcher}: {connection: Connection; fetcher?: typeof fetch}) {
  const {colors} = useAppTheme(), s = useThemedStyles(styles);
  const [data, setData] = useState<UsageSnapshot | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState('');
  const active = useRef(true), sequence = useRef(0);
  const refresh = useCallback(async () => {
    const ticket = ++sequence.current; setBusy(true); setError('');
    try {const result = await loadUsage(connection, fetcher); if (active.current && sequence.current === ticket) setData(result);}
    catch (error) {if (active.current && sequence.current === ticket) setError(error instanceof Error ? error.message : '暂时无法读取用量。');}
    finally {if (active.current && sequence.current === ticket) setBusy(false);}
  }, [connection, fetcher]);
  useEffect(() => {const generation = sequence; active.current = true; void Promise.resolve().then(() => {if (active.current) return refresh();}); return () => {active.current = false; generation.current++;};}, [refresh]);
  function resource(title: string, row: UsageResource) {return <View style={s.card}><View style={s.line}><Text style={s.name}>{title}</Text><Text style={s.number}>剩余 {row.remaining} 次</Text></View><Text style={s.copy}>已计入 {row.calls} 次 / 试用上限 {row.limit} 次</Text><View accessibilityLabel={`${title}，已使用 ${row.calls} 次，共 ${row.limit} 次`} style={s.track}><View style={[s.fill, {width: `${row.limit ? Math.min(100, row.calls / row.limit * 100) : 100}%`}]}/></View><Text style={s.copy}>{row.active ? `${row.active} 次正在处理 · ` : ''}最多同时处理 {row.concurrency} 次</Text>{row.uncertain ? <Text style={s.copy}>{row.uncertain} 次结果待核对，已保留额度占用，避免中断后重复执行。</Text> : null}</View>;}
  return <View style={s.panel}><View style={s.line}><ChartNoAxesColumn size={25} color={colors.accent}/><Text style={s.title}>执行用量</Text><TactilePressable accessibilityLabel="刷新执行用量" disabled={busy} onPress={() => {void refresh();}} style={s.refresh}><RefreshCw size={20} color={colors.ink}/></TactilePressable></View>{busy ? <View style={s.line}><ActivityIndicator color={colors.accent}/><Text style={s.copy}>正在核对用量…</Text></View> : null}{error ? <><Text style={s.error} accessibilityLiveRegion="polite">{error}</Text><PrimaryButton label="重新读取" tone="quiet" disabled={busy} onPress={() => {void refresh();}}/></> : null}
    {data?.mode === 'not_enabled' ? <View style={s.card}><Text style={s.name}>当前运行服务未启用试用限额</Text><Text style={s.copy}>这里暂不提供完整的调用统计。模型与语音费用请以对应服务商账单为准。</Text></View> : data ? <><Text style={s.copy}>这台运行服务下的所有身份共享试用额度。一次任务可能调用模型多次；失败或中断的请求也会计入。</Text>{resource('模型请求', data.resources.model)}{resource('语音识别', data.resources.speech)}<View style={s.card}><Text style={s.name}>语音时长</Text><Text style={s.number}>剩余 {minutesLabel(data.resources.speech.ms_remaining)}</Text><Text style={s.copy}>共 {minutesLabel(data.resources.speech.ms_limit)} · 正在处理的录音先预留时长，识别完成后按实际音频长度结算。</Text></View>{data.resources.model.remaining === 0 || data.resources.speech.remaining === 0 || data.resources.speech.ms_remaining === 0 ? <View style={s.card}><Text style={s.name}>部分执行额度已用完</Text><Text style={s.copy}>对应的新调用会停止。你仍可阅读对话、取回已有结果和原件，也可以暂停正在进行的任务。</Text></View> : null}{data.cost ? <ModelBudget cost={data.cost}/> : null}<View style={s.card}><Text style={s.name}>当前身份 · 供应商已返回的 tokens</Text><View style={s.line}><Text style={s.copy}>输入</Text><Text style={s.value}>{tokenLabel(data.identity_usage.input_tokens)}</Text></View><View style={s.line}><Text style={s.copy}>输出</Text><Text style={s.value}>{tokenLabel(data.identity_usage.output_tokens)}</Text></View>{data.identity_usage.unreported_model_calls ? <Text style={s.copy}>另有 {data.identity_usage.unreported_model_calls} 次模型请求没有完整用量回执，可能仅有部分 tokens 回执。</Text> : null}<Text style={s.copy}>{data.cost ? '模型金额按这些回执与服务方配置费率估算，最终费用以供应商账单为准。' : '尚未配置可核对的价格，暂不显示金额。模型请求仍受试用次数限制。'}</Text></View><Text style={s.foot}>更新于 {new Date(data.observed_at * 1000).toLocaleTimeString('zh-CN')} · 试用额度不会因重启或切换身份重置。</Text></> : null}
  </View>;
}
function ModelBudget({cost}: {cost: UsageCost}) {
  const s = useThemedStyles(styles);
  const amount = (value: number) => moneyLabel(value, cost.currency);
  return <View style={s.card}>
    <Text style={s.name}>模型预算 · 按配置估算</Text>
    <Text style={s.number}>剩余 {amount(cost.remaining_micros)}</Text>
    <Text style={s.copy}>这台运行服务共享，共 {amount(cost.budget_micros)}。每次调用先预留额度，收到完整用量回执后核算。</Text>
    <View style={s.line}><Text style={s.copy}>已按回执估算</Text><Text style={s.value}>{amount(cost.settled_estimate_micros)}</Text></View>
    <View style={s.line}><Text style={s.copy}>正在预留</Text><Text style={s.value}>{amount(cost.active_reserved_micros)}</Text></View>
    {cost.uncertain_reserved_micros ? <><View style={s.line}><Text style={s.copy}>待核对，保留预留</Text><Text style={s.value}>{amount(cost.uncertain_reserved_micros)}</Text></View><Text style={s.copy}>部分调用中断或缺少完整用量，尚不能确认未使用的额度。</Text></> : null}
    {cost.unpriced_calls ? <Text style={s.copy}>{cost.unpriced_calls} 次请求缺少价格，未计入金额；以上不是完整费用。</Text> : null}
    {cost.upper_bound_calls ? <Text style={s.copy}>{cost.upper_bound_calls} 次请求未返回缓存明细，已按较高输入费率保守估算。</Text> : null}
    {cost.overrun_calls ? <Text style={s.copy}>有 {cost.overrun_calls} 次用量超出当时的预留范围，需要服务方核对配置。</Text> : null}
    <Text style={s.foot}>当前价格版本 {cost.price_version} · 仅含已定价的模型调用，不含语音和设备费用。此处不是供应商账单，价格更新不会清零已占用额度。</Text>
  </View>;
}
export function UsagePanel(props: {connection: Connection; fetcher?: typeof fetch}) {return <UsageContent key={`${props.connection.endpoint}-${props.connection.identity}-${props.connection.session?.credentialId || props.connection.development?.expiresAt || ''}`} {...props}/>;}
const styles = (c: AppColors) => StyleSheet.create({panel: {gap: 16}, line: {flexDirection: 'row', alignItems: 'center', gap: 12}, title: {color: c.ink, fontSize: 23, fontWeight: '600', flex: 1}, refresh: {padding: 12}, card: {backgroundColor: c.surface, borderRadius: 24, padding: 20, gap: 12}, name: {color: c.ink, fontSize: 17, fontWeight: '600', flex: 1}, copy: {color: c.muted, fontSize: 14, lineHeight: 22}, number: {color: c.ink, fontSize: 17, fontWeight: '600'}, value: {color: c.ink, fontSize: 14, flex: 1, textAlign: 'right'}, error: {color: c.danger, fontSize: 14, lineHeight: 22}, track: {height: 6, backgroundColor: c.line, borderRadius: 3, overflow: 'hidden'}, fill: {height: 6, backgroundColor: c.accent, borderRadius: 3}, foot: {color: c.muted, fontSize: 12, lineHeight: 20}});
