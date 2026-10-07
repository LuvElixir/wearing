import {useThemedStyles, type AppColors} from '../app-theme';
import type {ReactNode} from 'react';
import {StyleSheet, View} from 'react-native';


/** Shared by the interactive design and the connected App. No business state. */
export function AppDock({children}: {children: ReactNode}) {
  const s = useThemedStyles(makeStyles);

  return <View testID="wearing-app-dock" style={s.dock}>{children}</View>;
}
const makeStyles = (c: AppColors) => StyleSheet.create({
  dock: {marginHorizontal: 10, paddingHorizontal: 7, paddingTop: 7, paddingBottom: 5, marginBottom: 4, borderWidth: 1, borderColor: c.line,
    borderRadius: 31, backgroundColor: c.dock},
});
