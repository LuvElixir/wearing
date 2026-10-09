import {createContext, useContext, useEffect, useMemo, useRef, useState, type ReactNode} from 'react';
import {useColorScheme} from 'react-native';
import {storage} from './storage';
import {appearanceKey, appearancePreference, palettes, resolveAppearance, type AppColors, type AppearancePreference, type AppMode} from './appearance';
export type {AppColors} from './appearance';
type ThemeContext = {colors: AppColors; mode: AppMode; preference: AppearancePreference; ready: boolean; saving: boolean; error: string; setPreference: (value: AppearancePreference) => Promise<void>; reload: () => void};
const Context = createContext<ThemeContext>({colors: palettes.night, mode: 'night', preference: 'system', ready: false, saving: false, error: '', setPreference: async () => {}, reload: () => {}});

export function AppThemeProvider({children}: {children: ReactNode}) {
  const system = useColorScheme();
  const [preference, setSelected] = useState<AppearancePreference>('system');
  const [ready, setReady] = useState(false), [saving, setSaving] = useState(false), [error, setError] = useState(''), [retry, setRetry] = useState(0);
  const busy = useRef(false);
  useEffect(() => {
    let live = true;
    storage.get<{preference?: unknown}>(appearanceKey).then(value => {
      if (live) {setSelected(appearancePreference(value?.preference)); setReady(true); setError('');}
    }).catch(() => {if (live) setError('暂时没能读取外观设置，请重试。');});
    return () => {live = false;};
  }, [retry]);
  async function setPreference(value: AppearancePreference) {
    if (!ready || busy.current) return;
    busy.current = true; setSaving(true); setError('');
    try {await storage.put(appearanceKey, {preference: value}); setSelected(value);}
    catch {setError('外观还没保存好，请再试一次。');}
    finally {busy.current = false; setSaving(false);}
  }
  const mode = resolveAppearance(preference, system);
  return <Context.Provider value={{colors: palettes[mode], mode, preference, ready, saving, error, setPreference, reload: () => setRetry(value => value + 1)}}>{children}</Context.Provider>;
}
export const useAppTheme = () => useContext(Context);
export function useThemedStyles<T>(factory: (colors: AppColors) => T): T {
  const {colors} = useAppTheme();
  return useMemo(() => factory(colors), [colors, factory]);
}
