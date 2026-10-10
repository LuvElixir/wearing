import {useState} from 'react';
import {Linking, StyleSheet, Text, View} from 'react-native';
import {useAppTheme} from './app-theme';
import {TactilePressable} from './experience/primitives';

const pages = [
  {label: '隐私说明', url: 'https://pajio.luckyloading.com/privacy'},
  {label: '测试支持', url: 'https://pajio.luckyloading.com/support'},
] as const;

/** Public fixed destinations: never append account, invite, or session state. */
export function PublicInformationLinks() {
  const {colors} = useAppTheme();
  const [error, setError] = useState('');
  async function open(url: typeof pages[number]['url']) {
    setError('');
    try {await Linking.openURL(url);}
    catch {setError('暂时无法打开。可联系 tiancaimiaosan233@gmail.com。');}
  }
  return <View style={s.root}>
    <View style={s.links}>{pages.map(page => <TactilePressable key={page.url} accessibilityRole="link" style={s.link} onPress={() => {void open(page.url);}}>
      <Text style={[s.label, {color: colors.muted}]}>{page.label}</Text>
    </TactilePressable>)}</View>
    {error ? <Text accessibilityLiveRegion="polite" style={[s.error, {color: colors.danger}]}>{error}</Text> : null}
  </View>;
}
const s = StyleSheet.create({
  root: {marginTop: 16}, links: {flexDirection: 'row', justifyContent: 'center', flexWrap: 'wrap', gap: 8},
  link: {minHeight: 44, paddingHorizontal: 12, justifyContent: 'center'}, label: {fontSize: 12, lineHeight: 20, textDecorationLine: 'underline'},
  error: {fontSize: 12, lineHeight: 20, textAlign: 'center'},
});
