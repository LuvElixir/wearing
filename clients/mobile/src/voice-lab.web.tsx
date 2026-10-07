import {StyleSheet, Text, View} from 'react-native';

// Platform resolution keeps native SQLite and its WASM out of the browser build.
export default function VoiceLabUnavailable() {
  return <View style={s.page}><Text>无可用页面</Text></View>;
}
const s = StyleSheet.create({page: {flex: 1, alignItems: 'center', justifyContent: 'center'}});
