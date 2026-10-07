import {StyleSheet, Text, View} from 'react-native';
import {Moon, Sun, Smartphone, Check} from 'lucide-react-native';
import {useAppTheme, useThemedStyles, type AppColors} from './app-theme';
import {TactilePressable} from './experience/primitives';
const options = [{id: 'night', label: '晚安', Icon: Moon}, {id: 'day', label: '日光', Icon: Sun}, {id: 'system', label: '随系统', Icon: Smartphone}] as const;
export function AppearancePanel() {
  const {colors: c, preference, setPreference, ready, saving, error, reload} = useAppTheme();
  const s = useThemedStyles(makeStyles);
  return <View style={s.panel}>
    <Text style={s.heading}>喜欢怎样的光？</Text><Text style={s.caption}>夜晚柔和，白天明朗。</Text>
    <View style={s.choices} accessibilityRole="radiogroup" accessibilityLabel="外观">
      {options.map(({id, label, Icon}) => <TactilePressable key={id} disabled={!ready || saving} onPress={() => {void setPreference(id);}} accessibilityRole="radio" accessibilityState={{checked: preference === id}} accessibilityLabel={`${label}外观`} style={[s.option, preference === id && s.selected]}>
        <Icon size={21} color={preference === id ? c.accentInk : c.muted}/><Text style={s.label}>{label}</Text>{preference === id ? <Check size={12} color={c.accentInk} style={s.check}/> : null}
      </TactilePressable>)}
    </View>
    {error ? <TactilePressable onPress={reload} style={s.retry}><Text style={s.error}>{error}</Text></TactilePressable> : null}
  </View>;
}
const makeStyles = (c: AppColors) => StyleSheet.create({
  panel: {gap: 9, padding: 20, borderRadius: 26, backgroundColor: c.surface},
  heading: {fontSize: 18, lineHeight: 27, color: c.ink, fontWeight: '500'}, caption: {fontSize: 13, lineHeight: 21, color: c.muted},
  choices: {flexDirection: 'row', gap: 8, marginTop: 8}, option: {flex: 1, minHeight: 78, borderRadius: 19, gap: 8, alignItems: 'center', justifyContent: 'center', borderWidth: 1, borderColor: c.line}, selected: {backgroundColor: c.accentSoft, borderColor: c.accent},
  label: {fontSize: 13, color: c.ink}, check: {position: 'absolute', top: 8, right: 8}, retry: {minHeight: 44, justifyContent: 'center'}, error: {fontSize: 13, color: c.danger},
});
