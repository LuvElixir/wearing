import {StyleSheet, View} from 'react-native';
import {useAppTheme} from '../app-theme';

/** A stable reading field. Content and meaningful state supply the contrast. */
export function AppBackdrop() {
  const {colors: c} = useAppTheme();
  return <View pointerEvents="none" style={[StyleSheet.absoluteFill, {backgroundColor: c.canvas}]}/>;
}
