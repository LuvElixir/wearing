import {Choice} from './experience/selection';
import {StyleSheet, Text, View} from 'react-native';
import {Moon, Sun, Smartphone} from 'lucide-react-native';
import {useAppTheme, useThemedStyles, type AppColors} from './app-theme';
import {TactilePressable} from './experience/primitives';
const options = [{id: 'day', label: '浅色', Icon: Sun}, {id: 'night', label: '深色', Icon: Moon}, {id: 'system', label: '跟随系统', Icon: Smartphone}] as const;
export function AppearancePanel() {
  const {colors: c, preference, setPreference, ready, saving, error, reload} = useAppTheme();
  const s = useThemedStyles(makeStyles);
  return <View style={s.panel}>
    <Text style={s.heading}>外观</Text><Text style={s.caption}>跟随系统时，随设备的显示设置切换。</Text>
    <View style={s.choices} accessibilityRole="radiogroup" accessibilityLabel="外观">
      {options.map(({id, label, Icon}, index) => <Choice key={id} disabled={!ready || saving} onPress={() => {void setPreference(id);}}  selected={preference === id} accessibilityLabel={`${label}外观`} style={[s.option, index < options.length - 1 && s.divider]}>
        <Icon size={20} color={c.muted}/><Text style={s.label}>{label}</Text>
      </Choice>)}
    </View>
    {error ? <TactilePressable onPress={reload} style={s.retry}><Text style={s.error}>{error}</Text></TactilePressable> : null}
  </View>;
}
const makeStyles = (c: AppColors) => StyleSheet.create({
  panel: {gap: 8, padding: 18, borderRadius: 18, backgroundColor: c.surface, borderWidth: StyleSheet.hairlineWidth, borderColor: c.line},
  heading: {fontSize: 18, lineHeight: 27, color: c.ink, fontWeight: '500'}, caption: {fontSize: 13, lineHeight: 21, color: c.muted},
  choices: {marginTop: 6, gap: 8}, option: {minHeight: 52, flexDirection: 'row', gap: 12, alignItems: 'center', paddingVertical: 10}, divider: {borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: c.line},
  label: {flex: 1, fontSize: 15, lineHeight: 23, color: c.ink}, retry: {minHeight: 44, justifyContent: 'center'}, error: {fontSize: 13, color: c.danger},
});
