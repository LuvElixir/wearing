import {useThemedStyles, type AppColors} from '../app-theme';
import type {ReactNode} from 'react';
import {StyleSheet, View} from 'react-native';


/** Shared by the interactive design and the connected App. No business state. */
export function AppDock({children}: {children: ReactNode}) {
  const s = useThemedStyles(makeStyles);

  return <View testID="wearing-app-dock" style={s.dock}>{children}</View>;
}
const makeStyles = (c: AppColors) => StyleSheet.create({
  dock: {paddingHorizontal: 12, paddingTop: 8, paddingBottom: 4, backgroundColor: c.dock},
});
