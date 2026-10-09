import {useEffect, useMemo, useRef, useState} from 'react';
import {ActivityIndicator, Platform, StyleSheet, Text, TextInput, View} from 'react-native';
import DateTimePicker from '@react-native-community/datetimepicker';
import * as Crypto from 'expo-crypto';
import {ArrowLeft, CalendarDays, Clock3} from 'lucide-react-native';
import {ApiError} from './core';
import {storage} from './storage';
import {useAppTheme, useThemedStyles, type AppColors} from './app-theme';
import {PrimaryButton, TactilePressable} from './experience/primitives';
import {OngoingDetail, OngoingKind, OngoingManagementApi, scheduleRule} from './ongoing-management';
import {GoalDraft, GoalFormValues, OngoingCreateRequest, ScheduleDraft, ScheduleFormValues, goalDraft, initialScheduleForm, scheduleDraft, validTimezone, wallClock, wallTimeToInstant} from './ongoing-management-forms';

type Props = {api: OngoingManagementApi; scope: string; kind: OngoingKind; item?: OngoingDetail; prefill?: OngoingCreateRequest;
  onSaved: (item: OngoingDetail) => void; onCancel: () => void};
type PendingCreate = {version: 1; key: string; kind: OngoingKind; goal?: GoalDraft; schedule?: ScheduleDraft};
const blankGoal: GoalFormValues = {title: '', brief: '', boundaries: '', success: '', steps: ''};
const message = (cause: unknown) => cause instanceof Error ? cause.message : '暂时没有完成，请稍后重试。';
const isPending = (value: unknown, kind: OngoingKind): value is PendingCreate => {
  if (!value || typeof value !== 'object') return false;
  const entry = value as PendingCreate;
  return entry.version === 1 && entry.kind === kind && /^[A-Za-z0-9_-]{16,120}$/.test(entry.key) &&
    (kind === 'goals' ? !!entry.goal && typeof entry.goal.objective === 'string' && typeof entry.goal.boundaries === 'string' && typeof entry.goal.success_criteria === 'string' && Number.isInteger(entry.goal.max_steps) :
      !!entry.schedule && typeof entry.schedule.title === 'string' && typeof entry.schedule.instruction === 'string' && validTimezone(entry.schedule.timezone));
};

export default function TaskManagementForm({api, scope, kind, item, prefill, onSaved, onCancel}: Props) {
  const {colors: c, mode} = useAppTheme(), s = useThemedStyles(makeStyles);
  const [goal, setGoal] = useState<GoalFormValues>({...blankGoal, title: prefill?.title || '', brief: prefill?.instruction || ''});
  const [schedule, setSchedule] = useState(() => initialScheduleForm(prefill, item));
  const [base, setBase] = useState(item), [pending, setPending] = useState<PendingCreate | null>(null);
  const [loading, setLoading] = useState(!item), [saving, setSaving] = useState(false), [restoreError, setRestoreError] = useState(false);
  const [error, setError] = useState(''), [notice, setNotice] = useState(''), [conflict, setConflict] = useState(false);
  const [settled, setSettled] = useState(false);
  const [picker, setPicker] = useState<'date' | 'time' | null>(null), [restoreGeneration, setRestoreGeneration] = useState(0);
  const session = useRef({live: true, busy: false});
  const savedReceipt = useRef<OngoingDetail | null>(null);
  const storageKey = `ongoing-create:${scope}|${kind}`;
  useEffect(() => {
    const current = {live: true, busy: false}; session.current = current;
    return () => {current.live = false;};
  }, [api]);
  useEffect(() => {
    if (item) return;
    let live = true;
    storage.get<unknown>(storageKey).then(value => {
      if (!live || value === null) return;
      if (!isPending(value, kind)) throw new Error('本机有一份未确认的草稿，但内容不完整。请先回列表核对，勿重复创建。');
      setPending(value); setNotice('上次提交尚未确认。先取回那次回执，避免重复安排。');
      if (value.goal) {
        const [title, ...brief] = value.goal.objective.split('\n\n');
        setGoal({title, brief: brief.join('\n\n'), boundaries: value.goal.boundaries, success: value.goal.success_criteria, steps: String(value.goal.max_steps)});
      } else if (value.schedule) {
        const spec = value.schedule;
        setSchedule(initialScheduleForm(undefined, {title: spec.title, schedule: spec}));
      }
    }).catch(cause => {if (live) {setError(message(cause)); setRestoreError(true);}})
      .finally(() => {if (live) setLoading(false);});
    return () => {live = false;};
  }, [item, kind, storageKey, restoreGeneration]);
  const locked = saving || loading || !!pending || restoreError;
  const updateGoal = (key: keyof GoalFormValues, value: string) => setGoal(previous => ({...previous, [key]: value}));
  const updateSchedule = <K extends keyof ScheduleFormValues>(key: K, value: ScheduleFormValues[K]) => setSchedule(previous => ({...previous, [key]: value}));
  const pickerValue = useMemo(() => {
    try {return new Date(wallTimeToInstant(schedule.date, schedule.time, schedule.timezone));} catch {return new Date();}
  }, [schedule.date, schedule.time, schedule.timezone]);
  const save = async () => {
    const current = session.current;
    if (!current.live || current.busy || loading || restoreError || conflict) return;
    let goalSpec: GoalDraft | undefined, scheduleSpec: ScheduleDraft | undefined;
    try {
      if (kind === 'goals') goalSpec = pending?.goal || goalDraft(goal);
      else scheduleSpec = pending?.schedule || scheduleDraft(schedule, base?.schedule?.draft);
    } catch (cause) {setError(message(cause)); return;}
    current.busy = true; setSaving(true); setError(''); setPicker(null);
    let submitted = false;
    try {
      if (savedReceipt.current) {
        await storage.put(storageKey, null);
        if (current.live) onSaved(savedReceipt.current);
        return;
      }
      let receipt: OngoingDetail;
      if (base) {
        submitted = true;
        receipt = await api.editSchedule(base, scheduleSpec!);
      } else {
        const intent: PendingCreate = pending || {version: 1, key: Crypto.randomUUID(), kind, ...(goalSpec ? {goal: goalSpec} : {schedule: scheduleSpec})};
        // Persist the exact request before any network write. Returning to this identity recovers its key.
        await storage.put(storageKey, intent);
        if (!current.live) return;
        setPending(intent); submitted = true;
        receipt = goalSpec ? await api.createGoal(goalSpec, intent.key) : await api.createSchedule(scheduleSpec!, intent.key);
        savedReceipt.current = receipt;
        if (current.live) setSettled(true);
        await storage.put(storageKey, null);
      }
      if (current.live) onSaved(receipt);
    } catch (cause) {
      if (!current.live) return;
      if (base && submitted) {
        setConflict(true); setError(message(cause) + ' 请先读取最新安排，草稿会保留。');
      } else if (savedReceipt.current) {
        setNotice('服务端已保存。本机草稿状态暂未清理，重试只会完成本机收尾。'); setError(message(cause));
      } else if (submitted && cause instanceof ApiError && [400, 401, 403, 404, 422].includes(cause.status)) {
        try {await storage.put(storageKey, null); if (current.live) setPending(null);} catch {setNotice('本机草稿仍在，重新打开后会继续核对这次提交。');}
        if (current.live) setError(message(cause));
      } else {
        setError(message(cause));
        if (submitted) setNotice('还没拿到保存回执。内容已保留，重试会查询同一次提交，不会新建第二份。');
      }
    } finally {current.busy = false; if (current.live) setSaving(false);}
  };
  const reloadLatest = async () => {
    const current = session.current;
    if (!base || current.busy || !current.live) return;
    current.busy = true; setSaving(true); setError('');
    try {
      const latest = await api.detail('schedules', base.id);
      if (!current.live) return;
      const desired = scheduleDraft(schedule, base.schedule?.draft, 0);
      if (JSON.stringify(latest.schedule?.draft) === JSON.stringify(desired)) {onSaved(latest); return;}
      if (latest.status === 'cancelled') {setError('这项安排已结束，不能修改。你的草稿仍在这里，可返回查看。'); return;}
      setBase(latest); setConflict(false); setNotice('已读取最新安排，未提交你的草稿。请核对下方内容后再次保存。');
    } catch (cause) {if (current.live) setError(message(cause));}
    finally {current.busy = false; if (current.live) setSaving(false);}
  };
  return <View style={s.panel}>
    <TactilePressable accessibilityLabel={item ? '取消修改，返回详情' : '返回安排列表'} disabled={saving} onPress={onCancel} style={s.back}><ArrowLeft size={18} color={c.ink}/><Text style={s.link}>{item ? '返回详情' : '返回列表'}</Text></TactilePressable>
    <Text accessibilityRole="header" style={s.title}>{item ? '修改定时安排' : kind === 'goals' ? '新的持续目标' : '新的定时安排'}</Text>
    <Text style={s.secondary}>{kind === 'goals' ? '先把要做的事和边界写清。保存后，你可以在详情里开始推进。' : item ? '修改会影响后续执行，已开始的本轮仍按原来的安排进行。' : '选好时间并保存，届时自动执行，结果留在进展和对话里。'}</Text>
    {loading ? <ActivityIndicator accessibilityLabel="正在读取未确认草稿" color={c.accent}/> : null}
    {notice ? <Text style={s.notice} accessibilityLiveRegion="polite">{notice}</Text> : null}
    {error ? <Text style={s.error} accessibilityLiveRegion="polite">{error}</Text> : null}
    {restoreError ? <PrimaryButton label="重新读取本机草稿" tone="quiet" onPress={() => {setLoading(true); setError(''); setRestoreError(false); setRestoreGeneration(value => value + 1);}}/> : null}
    {kind === 'goals' ? <View style={s.card}>
      <Input title="目标名称" value={goal.title} onChange={value => updateGoal('title', value)} placeholder="例如：安排好下个月的搬家" maxLength={120} disabled={locked}/>
      <Input title="具体要求" value={goal.brief} onChange={value => updateGoal('brief', value)} placeholder="背景、偏好，以及已有的信息（选填）" multiline maxLength={1900} disabled={locked}/>
      <Input title="允许做什么，哪些要先问你" value={goal.boundaries} onChange={value => updateGoal('boundaries', value)} placeholder="例如：可以查资料做比较；预订、付款前先问我" multiline maxLength={2000} disabled={locked}/>
      <Input title="做到什么算完成" value={goal.success} onChange={value => updateGoal('success', value)} placeholder="例如：交付一份有日期、报价和联系人的搬家计划" multiline maxLength={2000} disabled={locked}/>
      <Input title="最多推进多少轮" value={goal.steps} onChange={value => updateGoal('steps', value.replace(/[^0-9]/g, ''))} placeholder="填写 1–1000 的整数" maxLength={4} number disabled={locked}/>
      <Text style={s.caption}>一轮是一次实际推进。达到约定轮次后会停下来，只有你明确增加才继续。</Text>
    </View> : <View style={s.card}>
      <Input title="安排名称" value={schedule.title} onChange={value => updateSchedule('title', value)} placeholder="例如：每日优先事项简报" maxLength={100} disabled={locked}/>
      <Input title="届时要做的事" value={schedule.instruction} onChange={value => updateSchedule('instruction', value)} placeholder="写清信息来源、范围和你希望收到的结果" maxLength={6000} multiline disabled={locked}/>
      <Text style={s.label}>重复方式</Text><View accessibilityRole="radiogroup" style={s.choices}>
        {([{id: 'once', title: '一次'}, {id: 'daily', title: '每天'}, {id: 'weekly', title: '每周'}] as const).map(option => <TactilePressable key={option.id} accessibilityRole="radio" accessibilityState={{checked: schedule.repeat === option.id, disabled: locked}} disabled={locked} onPress={() => updateSchedule('repeat', option.id)} style={[s.choice, schedule.repeat === option.id && s.selected]}><Text style={s.choiceText}>{option.title}</Text></TactilePressable>)}
        {item && initialScheduleForm(undefined, item).repeat === 'existing' ? <TactilePressable accessibilityRole="radio" accessibilityState={{checked: schedule.repeat === 'existing', disabled: locked}} disabled={locked} onPress={() => updateSchedule('repeat', 'existing')} style={[s.choice, schedule.repeat === 'existing' && s.selected]}><Text style={s.choiceText}>保留原规则</Text></TactilePressable> : null}
      </View>
      {schedule.repeat === 'existing' && base ? <Text style={s.secondary}>{scheduleRule(base)}。保留原有触发范围和执行限制。</Text> : <>
        {schedule.repeat === 'weekly' ? <View accessibilityRole="radiogroup" style={s.choices}>{[1, 2, 3, 4, 5, 6, 0].map(day => <TactilePressable key={day} accessibilityRole="radio" accessibilityLabel={'每周' + '日一二三四五六'[day]} accessibilityState={{checked: schedule.weekday === day, disabled: locked}} disabled={locked} onPress={() => updateSchedule('weekday', day)} style={[s.day, schedule.weekday === day && s.selected]}><Text style={s.choiceText}>{'日一二三四五六'[day]}</Text></TactilePressable>)}</View> : null}
        <Text style={s.label}>执行时间</Text><View style={s.choices}>
          {schedule.repeat === 'once' ? <TactilePressable accessibilityLabel={'选择执行日期，' + schedule.date} disabled={locked || !validTimezone(schedule.timezone)} onPress={() => setPicker('date')} style={s.clock}><CalendarDays size={18} color={c.accent}/><Text style={s.choiceText}>{schedule.date}</Text></TactilePressable> : null}
          <TactilePressable accessibilityLabel={'选择执行时间，' + schedule.time} disabled={locked || !validTimezone(schedule.timezone)} onPress={() => setPicker('time')} style={s.clock}><Clock3 size={18} color={c.accent}/><Text style={s.choiceText}>{schedule.time}</Text></TactilePressable>
        </View>
        {picker && validTimezone(schedule.timezone) ? <View><DateTimePicker value={pickerValue} mode={picker} timeZoneName={schedule.timezone} is24Hour locale="zh-CN" themeVariant={mode === 'night' ? 'dark' : 'light'} display={Platform.OS === 'ios' ? 'spinner' : 'default'} onChange={(event, date) => {
          if (Platform.OS !== 'ios') setPicker(null);
          if (event.type === 'set' && date) {const wall = wallClock(date, schedule.timezone); setSchedule(previous => ({...previous, ...(picker === 'date' ? {date: wall.date} : {time: wall.time})}));}
        }}/>{Platform.OS === 'ios' ? <PrimaryButton label="选好了" tone="quiet" onPress={() => setPicker(null)}/> : null}</View> : null}
      </>}
      <Input title="时区" value={schedule.timezone} onChange={value => {setPicker(null); updateSchedule('timezone', value);}} placeholder="Asia/Shanghai" maxLength={100} disabled={locked}/>
      <Text style={s.caption}>上面的时间按这个时区执行；每天和每周安排会保持当地钟点。服务需保持在线。</Text>
      {item && initialScheduleForm(undefined, item).repeat === 'existing' && schedule.repeat !== 'existing' ? <Text style={s.notice}>保存后会用所选时间替换原来的触发规则。</Text> : null}
      {base?.status === 'finished' ? <Text style={s.notice}>这项安排已执行过。保存新的时间后，将重新开启后续执行。</Text> : null}
    </View>}
    {conflict ? <PrimaryButton label="读取最新安排，保留草稿" tone="quiet" loading={saving} onPress={() => {void reloadLatest();}}/> :
      <PrimaryButton label={settled ? '完成保存收尾' : pending ? '取回这次保存回执' : item ? '保存修改' : kind === 'goals' ? '保存目标约定' : '保存并开启安排'} loading={saving} disabled={loading || restoreError} onPress={() => {void save();}}/>}
    {pending ? <Text style={s.caption}>这次提交已单独保留在当前身份下。切换页面再回来，也会继续核对同一份安排。</Text> : null}
  </View>;
}
function Input({title, value, onChange, placeholder, maxLength, multiline, number, disabled}: {title: string; value: string; onChange: (value: string) => void; placeholder: string; maxLength: number; multiline?: boolean; number?: boolean; disabled: boolean}) {
  const {colors: c} = useAppTheme(), s = useThemedStyles(makeStyles);
  return <View style={s.field}><Text style={s.label}>{title}</Text><TextInput accessibilityLabel={title} value={value} onChangeText={onChange} editable={!disabled} multiline={multiline} maxLength={maxLength} placeholder={placeholder} placeholderTextColor={c.muted} keyboardType={number ? 'number-pad' : 'default'} autoCapitalize="none" style={[s.input, multiline && s.multiline, disabled && {opacity: .65}]}/></View>;
}
const makeStyles = (c: AppColors) => StyleSheet.create({
  panel: {gap: 14}, back: {flexDirection: 'row', alignItems: 'center', gap: 8, minHeight: 44}, link: {fontSize: 15, color: c.accent},
  title: {fontSize: 24, lineHeight: 34, fontWeight: '600', color: c.ink}, label: {fontSize: 15, lineHeight: 24, fontWeight: '500', color: c.ink},
  secondary: {fontSize: 14, lineHeight: 23, color: c.muted}, caption: {fontSize: 12, lineHeight: 20, color: c.muted},
  card: {backgroundColor: c.surface, borderWidth: 1, borderColor: c.line, borderRadius: 22, padding: 18, gap: 18}, field: {gap: 8},
  input: {minHeight: 50, borderWidth: 1, borderColor: c.line, borderRadius: 12, padding: 13, fontSize: 16, lineHeight: 24, color: c.ink, backgroundColor: c.canvas},
  multiline: {minHeight: 100, textAlignVertical: 'top'}, choices: {flexDirection: 'row', flexWrap: 'wrap', gap: 8},
  choice: {minHeight: 44, paddingHorizontal: 16, justifyContent: 'center', borderRadius: 13, borderWidth: 1, borderColor: c.line, backgroundColor: c.canvas},
  day: {width: 40, height: 44, justifyContent: 'center', alignItems: 'center', borderRadius: 12, borderWidth: 1, borderColor: c.line, backgroundColor: c.canvas},
  selected: {borderColor: c.accent, backgroundColor: c.accentSoft}, choiceText: {fontSize: 15, color: c.ink},
  clock: {flexDirection: 'row', alignItems: 'center', gap: 9, minHeight: 48, paddingHorizontal: 14, borderRadius: 13, backgroundColor: c.canvas},
  error: {fontSize: 14, lineHeight: 23, color: c.danger}, notice: {fontSize: 14, lineHeight: 23, color: c.accent},
});
