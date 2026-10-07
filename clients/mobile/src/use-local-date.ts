import {useEffect, useState} from 'react';
import {AppState, Platform} from 'react-native';

export type LocalDate = {year: number; month: number; day: number};
const localDate = (date: Date): LocalDate => ({
  year: date.getFullYear(), month: date.getMonth() + 1, day: date.getDate(),
});

/** Device-local date, refreshed at the next local midnight and on foreground return. */
export function useLocalDate(): LocalDate | null {
  // Static web exports must not bake the build machine's date into hydration.
  const [date, setDate] = useState<LocalDate | null>(() => Platform.OS === 'web' ? null : localDate(new Date()));
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined;
    let alive = true;
    let foreground = AppState.currentState == null || AppState.currentState === 'active';
    const web = Platform.OS === 'web' && typeof document !== 'undefined';
    const stopTimer = () => {clearTimeout(timer); timer = undefined;};
    const refresh = () => {
      stopTimer();
      if (!alive) return;
      const now = new Date();
      const next = localDate(now);
      setDate(previous => previous?.year === next.year && previous.month === next.month && previous.day === next.day ? previous : next);
      if (!foreground || (web && document.visibilityState === 'hidden')) return;
      // Construct local midnight rather than adding 24h: DST days may be 23h or 25h.
      const midnight = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1);
      timer = setTimeout(refresh, Math.max(25, midnight.getTime() - now.getTime() + 25));
    };
    const subscription = AppState.addEventListener('change', state => {
      foreground = state === 'active';
      if (foreground) refresh(); else stopTimer();
    });
    const visibilityChanged = () => {
      if (document.visibilityState === 'hidden') stopTimer(); else refresh();
    };
    if (web) {
      window.addEventListener('focus', refresh);
      document.addEventListener('visibilitychange', visibilityChanged);
    }
    refresh();
    return () => {
      alive = false;
      stopTimer();
      subscription.remove();
      if (web) {
        window.removeEventListener('focus', refresh);
        document.removeEventListener('visibilitychange', visibilityChanged);
      }
    };
  }, []);
  return date;
}
