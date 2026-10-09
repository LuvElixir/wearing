import {useAppTheme, useThemedStyles, type AppColors} from './app-theme';
import {useEffect, useState} from 'react';
import {Animated, Easing, Platform, StyleSheet, Text, View} from 'react-native';
import {ChevronLeft, ChevronRight} from 'lucide-react-native';
import {dateKey, monthWeeks, moveMonth, type CalendarDate} from './calendar';
import {motion} from './experience/tokens';
import {TactilePressable, useReducedMotion} from './experience/primitives';
import {ContentTransition} from './experience/ContentTransition';

type Props = {
  selected: CalendarDate | null;
  today: CalendarDate | null;
  onSelect: (date: CalendarDate) => void;
  eventCount?: (date: CalendarDate) => number;
};
const weekdays = ['一', '二', '三', '四', '五', '六', '日'];

function CalendarDay({date, column, active, current, count, reduced, onSelect}: {
  date: CalendarDate; column: number; active: boolean; current: boolean; count: number; reduced: boolean;
  onSelect: Props['onSelect'];
}) {
  const s = useThemedStyles(makeStyles);

  const [selection] = useState(() => new Animated.Value(active ? 1 : 0));
  useEffect(() => {
    selection.stopAnimation();
    if (reduced) {selection.setValue(active ? 1 : 0); return;}
    const animation = Animated.timing(selection, {
      toValue: active ? 1 : 0, duration: active ? motion.release : motion.crossfade,
      easing: Easing.out(Easing.cubic), useNativeDriver: Platform.OS !== 'web', isInteraction: false,
    });
    animation.start();
    return () => animation.stop();
  }, [active, reduced, selection]);
  return <TactilePressable accessibilityRole="button" accessibilityState={{selected: active}} aria-pressed={active}
    accessibilityLabel={`${date.year}年${date.month}月${date.day}日，星期${weekdays[column]}${current ? '，今天' : ''}，${count ? `${count} 项安排` : '没有安排'}`}
    onPress={() => onSelect(date)} pressScale={0.98} style={s.cell}>
    <View pointerEvents="none" accessible={false} accessibilityElementsHidden importantForAccessibility="no-hide-descendants"
      style={[s.day, current && s.current]}>
      <Text style={[s.number, current && s.currentNumber]}>{date.day}</Text>
      <View style={[s.dot, {opacity: count ? 1 : 0}]}/>
      <Animated.View style={[s.selection, {opacity: selection}]}>
        <Text style={[s.number, s.white]}>{date.day}</Text>
        <View style={[s.dot, s.whiteDot, {opacity: count ? 1 : 0}]}/>
      </Animated.View>
    </View>
  </TactilePressable>;
}

/** A shared month view for real records and the explicitly labelled experience preview. */
export default function MonthCalendar({selected, today, onSelect, eventCount = () => 0}: Props) {
  const {colors: c} = useAppTheme();
  const s = useThemedStyles(makeStyles);

  const reduced = useReducedMotion();
  if (!selected) return <View style={s.loading}><Text style={s.weekday}>正在打开日历…</Text></View>;
  const selectedKey = dateKey(selected), todayKey = today && dateKey(today);
  return <View style={s.calendar}>
    <View style={s.header}>
      <Text accessibilityRole="header" accessibilityLiveRegion="polite" style={s.title}>{selected.year} 年 {selected.month} 月</Text>
      <View style={s.controls}>
        <TactilePressable accessibilityRole="button" accessibilityLabel="回到今天" disabled={!today}
          onPress={() => {if (today) onSelect(today);}} style={s.today}>
          <Text style={s.todayText}>今天</Text>
        </TactilePressable>
        <TactilePressable accessibilityRole="button" accessibilityLabel="上个月" onPress={() => onSelect(moveMonth(selected, -1))}
          style={s.arrow}><ChevronLeft size={20} strokeWidth={1.65} color={c.muted}/></TactilePressable>
        <TactilePressable accessibilityRole="button" accessibilityLabel="下个月" onPress={() => onSelect(moveMonth(selected, 1))}
          style={s.arrow}><ChevronRight size={20} strokeWidth={1.65} color={c.muted}/></TactilePressable>
      </View>
    </View>
    <View style={s.week}>{weekdays.map(day => <Text key={day} style={s.weekday}>{day}</Text>)}</View>
    <ContentTransition changeKey={`${selected.year}-${selected.month}`}>
    {monthWeeks(selected).map((week, index) => <View key={index} style={s.week}>
      {week.map((date, column) => {
        if (!date) return <View key={'empty-' + column} style={s.cell}/>;
        const key = dateKey(date), active = key === selectedKey, current = key === todayKey, count = eventCount(date);
        return <CalendarDay key={key} date={date} column={column} active={active} current={current}
          count={count} reduced={reduced} onSelect={onSelect}/>;
      })}
    </View>)}
    </ContentTransition>
  </View>;
}

const makeStyles = (c: AppColors) => StyleSheet.create({
  calendar: {marginTop: 16, marginBottom: 8},
  loading: {minHeight: 300, alignItems: 'center', justifyContent: 'center'},
  header: {minHeight: 52, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 4, marginBottom: 8},
  title: {fontSize: 18, lineHeight: 26, fontWeight: '600', color: c.ink, flexShrink: 1},
  controls: {flexDirection: 'row', alignItems: 'center'},
  today: {minHeight: 44, minWidth: 44, paddingHorizontal: 6, alignItems: 'center', justifyContent: 'center', borderRadius: 14},
  todayText: {fontSize: 13, color: c.accentInk},
  arrow: {minWidth: 44, minHeight: 44, alignItems: 'center', justifyContent: 'center', borderRadius: 14},
  week: {flexDirection: 'row'},
  weekday: {flex: 1, textAlign: 'center', color: c.muted, fontSize: 12, lineHeight: 28},
  cell: {flex: 1, minHeight: 48, alignItems: 'center', justifyContent: 'center', borderRadius: 16},
  day: {width: 40, maxWidth: '100%', height: 42, borderRadius: 15, borderWidth: 1, borderColor: 'transparent', alignItems: 'center', justifyContent: 'center', gap: 3},
  number: {fontSize: 16, lineHeight: 22, fontVariant: ['tabular-nums'], color: c.ink},
  current: {borderColor: c.accent},
  currentNumber: {color: c.accentInk, fontWeight: '600'},
  selection: {position: 'absolute', top: 0, bottom: 0, left: 0, right: 0, borderRadius: 14, backgroundColor: c.accent, alignItems: 'center', justifyContent: 'center', gap: 3},
  white: {color: c.surface},
  dot: {width: 3, height: 3, borderRadius: 2, backgroundColor: c.accent},
  whiteDot: {backgroundColor: c.surface},
});
