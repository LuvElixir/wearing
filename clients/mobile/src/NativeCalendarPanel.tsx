import {useCallback, useEffect, useMemo, useRef, useState} from 'react';
import {AppState, Linking, Platform, StyleSheet, Switch, Text, TextInput, View} from 'react-native';
import {requireOptionalNativeModule} from 'expo';
import * as Crypto from 'expo-crypto';
import {CalendarDays, ListChecks} from 'lucide-react-native';
import {useAppTheme, useThemedStyles, type AppColors} from './app-theme';
import {PrimaryButton, TactilePressable} from './experience/primitives';
import TimeField from './TimeField';
import {storage} from './storage';
import {requestNativeSync} from './native-sync-runtime';
import {withRecordDraft} from './record-editor';
import {calendarEventTime, nativeDraftError} from './nativeConnectionsModel';
import {NativeCalendarService, NativePermissionError, reminderAllDay, reminderDraft, reminderRevision, reminderTime, selectedNativeCalendarDraft, validateReminderDraft,
  type CalendarList, type NativeCalendarApi, type NativeEvent, type ReminderDraft, type ReminderIntent, type ReminderRow} from './native-calendar';

function nativeApi(): NativeCalendarApi | null {
  if (Platform.OS === 'web' || !requireOptionalNativeModule('ExpoCalendar')) return null;
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  return require('expo-calendar/legacy') as NativeCalendarApi;
}
const emptyDraft = (calendarId = ''): ReminderDraft => ({calendarId, title: '', notes: '', dueDate: null, allDay: false});
export function NativeCalendarPanel({scope, onDraft}: {scope: string; onDraft: (text: string) => void}) {
  const s = useThemedStyles(styles), {colors} = useAppTheme();
  const [events, setEvents] = useState<NativeEvent[]>([]), [selected, setSelected] = useState<string[]>([]), [days, setDays] = useState<7 | 30>(7), [eventsRead, setEventsRead] = useState(false);
  const [reminders, setReminders] = useState<ReminderRow[]>([]), [lists, setLists] = useState<CalendarList[]>([]), [remindersRead, setRemindersRead] = useState(false), [showCompleted, setShowCompleted] = useState(false);
  const [busy, setBusy] = useState(''), [error, setError] = useState(''), [notice, setNotice] = useState(''), [settings, setSettings] = useState(false);
  const [form, setForm] = useState<ReminderDraft | null>(null), [editing, setEditing] = useState<ReminderRow | null>(null), [deleting, setDeleting] = useState<ReminderRow | null>(null);
  const [pending, setPending] = useState<ReminderIntent | null>(null), [hydrated, setHydrated] = useState(false);
  const mounted = useRef(false), locked = useRef(false), readEvents = useRef(false), readReminders = useRef(false);
  const alive = useCallback(() => mounted.current, []);
  const api = useMemo(() => nativeApi(), []);
  // The constructor only stores this callback; native operations invoke it after user actions.
  // eslint-disable-next-line react-hooks/refs
  const service = useMemo(() => api ? new NativeCalendarService(api, Platform.OS, alive) : null, [api, alive]);
  const pendingKey = 'native-reminder-intent:v1:' + scope;
  const draftKey = 'native-reminder-draft:v1:' + scope;
  const [draftHydrated, setDraftHydrated] = useState(false);

  async function refreshEvents(range = days) {
    if (!service) return;
    const rows = await service.events(range);
    if (!mounted.current) return;
    setEvents(rows); setSelected(current => current.filter(key => rows.some(row => row.key === key))); setEventsRead(true); readEvents.current = true;
    requestNativeSync(scope);
  }
  async function refreshReminders() {
    if (!service) return;
    const data = await service.reminders();
    if (!mounted.current) return;
    setReminders(data.items); setLists(data.calendars); setRemindersRead(true); readReminders.current = true;
    requestNativeSync(scope);
  }
  useEffect(() => {
    mounted.current = true;
    storage.get<ReminderIntent>(pendingKey).then(value => {
      if (!mounted.current) return;
      if (value) {
        if (!/^[a-f0-9]{32}$/.test(value.requestId)) throw new Error('invalid reminder request');
        setPending({...value, draft: validateReminderDraft(value.draft)});
      }
      setHydrated(true);
    }).catch(() => {if (mounted.current) setError('上次提醒的保存请求未能读取，请重新打开此页后再创建。');});
    withRecordDraft(draftKey, () => storage.get<{form: ReminderDraft | null; editing: ReminderRow | null}>(draftKey)).then(value => {
      if (!mounted.current) return;
      if (value?.form) {
        const f = value.form;
        if (typeof f.title !== 'string' || typeof f.notes !== 'string' || typeof f.calendarId !== 'string' ||
          (f.dueDate !== null && !Number.isFinite(Date.parse(f.dueDate)))) throw new Error('invalid reminder draft');
        if (value.editing && (!value.editing.raw || reminderRevision(value.editing.raw) !== value.editing.revision)) throw new Error('invalid reminder revision');
        // Old drafts represented absent native allDay as false. Recover the unknown type from the original receipt.
        const editing = value.editing ? {...value.editing, allDay: reminderAllDay(value.editing.raw)} : null;
        setForm(editing?.allDay === null ? {...f, allDay: null} : f); setEditing(editing);
      }
      setDraftHydrated(true);
    }).catch(() => {if (mounted.current) setError('本机提醒草稿未能读取，请重新打开此页。');});
    // Permission revocation clears previews immediately; no fresh private data is read in the background.
    const listener = AppState.addEventListener('change', state => {
      if (state !== 'active' || !service || locked.current) return;
      if (readEvents.current) void service.permission('event', false).catch(() => {if (mounted.current) {setEvents([]); setSelected([]); setEventsRead(false); readEvents.current = false;}});
      if (readReminders.current) void service.permission('reminder', false).catch(() => {if (mounted.current) {setReminders([]); setLists([]); setRemindersRead(false); readReminders.current = false;}});
    });
    return () => {mounted.current = false; listener.remove();};
  }, [service, pendingKey, draftKey]);
  useEffect(() => {
    if (!draftHydrated) return;
    void withRecordDraft(draftKey, () => storage.put(draftKey, {form, editing})).catch(() => {
      if (mounted.current) setError('编辑仍在当前页面，但尚未保存在本机。请先保留此页。');
    });
  }, [draftKey, draftHydrated, form, editing]);

  async function run(label: string, work: () => Promise<void>) {
    if (locked.current) return;
    locked.current = true; setBusy(label); setError(''); setNotice(''); setSettings(false);
    try {await work();}
    catch (cause) {if (mounted.current) {setError(cause instanceof Error ? cause.message : '这次没有完成，请重新读取后再试。'); setSettings(cause instanceof NativePermissionError && cause.settings);}}
    finally {locked.current = false; if (mounted.current) setBusy('');}
  }
  const changeForm = (patch: Partial<ReminderDraft>) => setForm(value => value ? {...value, ...patch} : value);
  async function saveReminder() {
    if (!service || !form) return;
    const valid = validateReminderDraft(form);
    if (editing) {
      await service.updateReminder(editing, valid);
    } else {
      if (valid.allDay !== false) throw new Error('请在系统提醒事项中创建全天提醒，或改为指定时间后保存。');
      const intent = {requestId: Crypto.randomUUID().replaceAll('-', ''), draft: valid};
      await storage.put(pendingKey, intent);
      if (!mounted.current) return;
      setPending(intent);
      await service.createReminder(intent);
      await storage.put(pendingKey, null);
      if (mounted.current) setPending(null);
    }
    if (!mounted.current) return;
    setForm(null); setEditing(null); setNotice('已保存到系统提醒事项。'); await refreshReminders();
  }
  async function recoverReminder() {
    if (!service || !pending) return;
    await service.createReminder(pending);
    await storage.put(pendingKey, null);
    if (!mounted.current) return;
    setPending(null); setForm(null); setEditing(null); setNotice('已核对这次保存，系统里只有一份对应的提醒。'); await refreshReminders();
  }

  return <View style={s.root}>
    {!!error && <Text accessibilityRole="alert" style={s.error}>{error}</Text>}
    {!!notice && <Text accessibilityLiveRegion="polite" style={s.notice}>{notice}</Text>}
    {settings && <Action label="打开系统设置" busy={busy} run={run} work={() => Linking.openSettings()}/>}
    <View style={s.card}>
      <View style={s.row}><CalendarDays size={25} color={colors.ink}/><Text style={s.title}>系统日历</Text></View>
      <Text style={s.description}>查看日程，也可以直接在系统编辑器里添加、修改或删除。更改会写回手机日历。</Text>
      {!service ? <Text style={s.description}>请在包含日历能力的手机安装版中使用。</Text> : <>
        <Action label="新建系统日程" busy={busy} run={run} work={async () => {
          const text = await service.eventDialog(); if (mounted.current) setNotice(text); if (readEvents.current) await refreshEvents();
        }}/>
        <View style={s.row}>{([7, 30] as const).map(range => <TactilePressable key={range} accessibilityRole="radio" accessibilityState={{checked: days === range}} disabled={!!busy}
          onPress={() => {setDays(range); void run('读取日程', () => refreshEvents(range));}} style={[s.choice, days === range && s.chosen]}><Text style={s.body}>未来 {range} 天</Text></TactilePressable>)}</View>
        <Action label={eventsRead ? '刷新系统日程' : '允许并读取系统日程'} busy={busy} run={run} work={() => refreshEvents()}/>
        {eventsRead && !events.length && <Text style={s.description}>这段时间没有读到日程。</Text>}
        {events.map(event => <View key={event.key} style={s.section}>
          <View style={s.row}><Switch accessibilityLabel={`带入对话：${event.title}`} value={selected.includes(event.key)} disabled={!!busy}
            onValueChange={() => setSelected(value => value.includes(event.key) ? value.filter(key => key !== event.key) : [...value, event.key])}/><View style={s.grow}><Text style={s.body}>{event.title}</Text><Text style={s.description}>{calendarEventTime(event)} · {event.calendar}</Text></View></View>
          <Action label={event.writable ? '在系统日历中编辑' : '查看系统日程'} busy={busy} run={run} work={async () => {
            const result = await service.eventDialog(event); if (mounted.current) setNotice(result); await refreshEvents();
          }}/>
        </View>)}
        {!!selected.length && <Action label={`带入对话 · ${selected.length} 项`} busy={busy} run={run} work={async () => {
          await service.permission('event', false); const draft = selectedNativeCalendarDraft(events, selected), failure = nativeDraftError(draft);
          if (failure) throw new Error(failure); if (mounted.current && draft) onDraft(draft);
        }}/>}
      </>}
    </View>
    {Platform.OS === 'ios' && <View style={s.card}>
      <View style={s.row}><ListChecks size={25} color={colors.ink}/><Text style={s.title}>提醒事项</Text></View>
      <Text style={s.description}>直接保存到 iPhone 的提醒事项，可以修改、完成、重新打开或删除。</Text>
      {!service ? <Text style={s.description}>当前安装版未提供提醒事项能力，请更新后使用。</Text> : <>
        <Action label={remindersRead ? '刷新提醒事项' : '允许并读取提醒事项'} busy={busy} run={run} work={refreshReminders}/>
        {pending && <View style={s.section}><Text style={s.body}>有一次保存等待核对：{pending.draft.title}</Text><Text style={s.description}>{pending.draft.allDay === false ? '继续核对会找回已保存的提醒；如果尚未创建，会完成这次保存。' : '继续核对只查找已保存的提醒，不会重新创建全天提醒。具体时间请在系统提醒事项中查看。'}</Text>
          <Action label="核对并完成这次保存" busy={busy} run={run} work={recoverReminder}/></View>}
        {remindersRead && <>
          <Action label="新建提醒事项" busy={busy} run={run} disabled={!hydrated || !draftHydrated || !!pending || !lists.some(c => c.writable) || !!form} work={async () => {setEditing(null); setForm(emptyDraft(lists.find(c => c.writable)?.id));}}/>
          {!lists.some(c => c.writable) && <Text style={s.description}>没有可写入的提醒列表，请先在系统提醒事项中创建列表。</Text>}
          <View style={s.between}><Text style={s.body}>显示已完成</Text><Switch accessibilityLabel="显示已完成的提醒" value={showCompleted} onValueChange={setShowCompleted} disabled={!!busy}/></View>
          {reminders.filter(r => showCompleted || !r.completed).map(item => <View key={item.id} style={s.section}>
            <Text style={s.body}>{item.completed ? '已完成 · ' : ''}{item.title}</Text><Text style={s.description}>{reminderTime(item)} · {item.calendar}</Text>
            {!!item.notes && <Text style={s.description}>{item.notes}</Text>}
            {item.writable ? <>
              <Action label={item.completed ? '重新打开' : '标为完成'} busy={busy} run={run} work={async () => {
                await service.updateReminder(item, reminderDraft(item), !item.completed); if (mounted.current) setNotice(item.completed ? '已重新打开。' : '已完成。'); await refreshReminders();
              }}/>
              <View style={s.row}><TactilePressable style={s.link} disabled={!!busy || !draftHydrated || !!pending || !!form} onPress={() => {setEditing(item); setForm(reminderDraft(item));}}><Text style={s.linkText}>编辑</Text></TactilePressable>
                <TactilePressable style={s.link} disabled={!!busy || !!form} onPress={() => setDeleting(item)}><Text style={s.danger}>删除</Text></TactilePressable></View>
            </> : <Text style={s.description}>此列表只读</Text>}
            {deleting?.id === item.id && <View style={s.section}><Text style={s.body}>从系统提醒事项删除「{deleting.title}」？</Text>
              <Action label="确认删除这条提醒" busy={busy} run={run} danger work={async () => {await service.deleteReminder(deleting); if (mounted.current) {setDeleting(null); setNotice('已从系统提醒事项删除。');} await refreshReminders();}}/>
              <PrimaryButton label="保留" tone="quiet" disabled={!!busy} onPress={() => setDeleting(null)}/></View>}
          </View>)}
          {!reminders.filter(r => showCompleted || !r.completed).length && <Text style={s.description}>{showCompleted ? '还没有提醒事项。' : '当前没有未完成的提醒。'}</Text>}
        </>}
        {form && <View style={s.section}>
          <Text style={s.title}>{editing ? '编辑提醒' : '新建提醒'}</Text>
          {editing && reminders.find(r => r.id === editing.id && r.revision !== editing.revision) && <View style={s.section}>
            <Text style={s.description}>系统中的提醒已经改变。你的编辑仍在下面；继续前请查看列表中的最新内容。</Text>
            <PrimaryButton label="保留我的编辑，使用最新版本" tone="quiet" disabled={!!busy} onPress={() => setEditing(reminders.find(r => r.id === editing.id) || editing)}/>
          </View>}
          {!!pending && <Text style={s.description}>请先核对上方的保存结果，避免重复创建。</Text>}
          <TextInput style={s.input} value={form.title} onChangeText={title => changeForm({title})} editable={!busy && !pending} maxLength={300} accessibilityLabel="提醒标题" placeholder="提醒我做什么" placeholderTextColor={colors.muted}/>
          <TextInput style={[s.input, s.notes]} multiline value={form.notes} onChangeText={notes => changeForm({notes})} editable={!busy && !pending} maxLength={5000} accessibilityLabel="提醒备注" placeholder="补充说明" placeholderTextColor={colors.muted}/>
          {!editing && lists.filter(c => c.writable).map(c => <TactilePressable key={c.id} style={[s.choice, form.calendarId === c.id && s.chosen]} accessibilityRole="radio" accessibilityState={{checked: form.calendarId === c.id}} disabled={!!busy || !!pending}
            onPress={() => changeForm({calendarId: c.id})}><Text style={s.body}>{c.title}</Text></TactilePressable>)}
          <View style={s.between}><Text style={s.body}>设置日期</Text><Switch accessibilityLabel="为提醒设置日期" value={!!form.dueDate} disabled={!!busy || !!pending || !!editing?.dueDate || (!!editing && editing.allDay !== false)}
            onValueChange={value => changeForm({dueDate: value ? new Date().toISOString() : null})}/></View>
          {editing && editing.allDay !== false ? <Text style={s.description}>日期和全天设置保留系统原样；如需调整，请在系统提醒事项中修改。</Text>
            : form.dueDate && <View pointerEvents={busy || pending ? 'none' : 'auto'}><TimeField label="提醒日期与时间" value={new Date(form.dueDate)} onChange={value => changeForm({dueDate: value.toISOString()})}/></View>}
          {!editing && <Text style={s.description}>这里支持未设日期或指定时间的提醒。全天提醒请在系统提醒事项中设置。</Text>}
          {!editing && form.allDay !== false && <PrimaryButton label="改为指定时间提醒" tone="quiet" disabled={!!busy || !!pending} onPress={() => changeForm({allDay: false})}/>}
          {editing?.dueDate && <Text style={s.description}>如需移除已有日期，请在系统提醒事项中调整。</Text>}
          <Action label="保存到系统提醒事项" busy={busy} run={run} disabled={!hydrated || !draftHydrated || !!pending || !form.title.trim()} work={saveReminder}/>
          <PrimaryButton label="取消编辑" tone="quiet" disabled={!!busy} onPress={() => {setForm(null); setEditing(null);}}/>
        </View>}
      </>}
    </View>}
  </View>;
}

function Action({label, work, busy, run, disabled = false, danger = false}: {label: string; work: () => Promise<void>; busy: string; disabled?: boolean; danger?: boolean; run: (label: string, work: () => Promise<void>) => Promise<void>}) {
  return <PrimaryButton label={label} loading={busy === label} disabled={!!busy || disabled} tone={danger ? 'danger' : 'quiet'} onPress={() => void run(label, work)}/>;
}
const styles = (c: AppColors) => StyleSheet.create({
  root: {gap: 16}, card: {padding: 20, borderRadius: 28, borderWidth: 1, borderColor: c.line, backgroundColor: c.surface, gap: 14},
  title: {fontSize: 19, lineHeight: 27, fontWeight: '600', color: c.ink}, body: {fontSize: 16, lineHeight: 24, color: c.ink}, description: {fontSize: 13, lineHeight: 22, color: c.muted},
  row: {flexDirection: 'row', alignItems: 'center', gap: 10, flexWrap: 'wrap'}, between: {flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 12}, grow: {flex: 1, gap: 4},
  section: {gap: 12, paddingTop: 16, borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: c.line},
  choice: {paddingHorizontal: 14, paddingVertical: 12, borderWidth: 1, borderColor: c.line, borderRadius: 14, minHeight: 44}, chosen: {borderColor: c.accent, backgroundColor: c.accentSoft},
  input: {minHeight: 48, padding: 14, color: c.ink, backgroundColor: c.soft, borderRadius: 14, fontSize: 16, lineHeight: 24}, notes: {minHeight: 100, textAlignVertical: 'top'},
  link: {paddingHorizontal: 12, minHeight: 44, justifyContent: 'center'}, linkText: {fontSize: 15, color: c.accent}, danger: {fontSize: 15, color: c.danger},
  error: {fontSize: 14, lineHeight: 22, color: c.danger}, notice: {fontSize: 14, lineHeight: 22, color: c.success},
});
