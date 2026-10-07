import {StyleSheet} from 'react-native';
import {LinearGradient} from 'expo-linear-gradient';
import {useAppTheme} from '../app-theme';

/** A quiet tonal field, like lamplight on warm fabric. No blue-to-peach daylight gradient. */
export function AppBackdrop() {
  const {colors: c} = useAppTheme();
  return <LinearGradient pointerEvents="none" colors={[c.canvas, c.canvas, c.glow]} locations={[0, .7, 1]} style={StyleSheet.absoluteFill}/>;
}
