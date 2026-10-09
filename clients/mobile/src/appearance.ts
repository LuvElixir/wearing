export type AppearancePreference = 'night' | 'day' | 'system';
export type AppMode = 'night' | 'day';
export const appearanceKey = 'appearance:v1';
export function appearancePreference(value: unknown): AppearancePreference {
  return value === 'day' || value === 'night' ? value : 'system';
}
export function resolveAppearance(preference: AppearancePreference, system: string | null | undefined): AppMode {
  return preference === 'system' ? system === 'light' ? 'day' : 'night' : preference;
}
export const palettes = {
  day: {
    canvas: '#F6F7F9', surface: '#FFFFFF', raised: '#FFFFFF', soft: '#ECEEF2',
    ink: '#202228', muted: '#565C68', faint: '#626975',
    action: '#24262B', actionPressed: '#383C44', onAction: '#FFFFFF',
    accent: '#3156C8', accentSoft: '#EDF1FF', accentInk: '#2545A5', onAccent: '#FFFFFF',
    line: '#DDE1E7', outline: '#737B89', danger: '#B42338', dangerSoft: '#FDEEF0',
    success: '#176449', successSoft: '#E8F3ED', attention: '#6546A2', attentionSoft: '#F2EDFB', scrim: 'rgba(20,22,26,.32)',
    dock: '#F6F7F9', portrait: '#ECEEF2', glow: '#F6F7F9',
  },
  night: {
    canvas: '#14161A', surface: '#1C1F25', raised: '#262A32', soft: '#282D36',
    ink: '#F0F2F5', muted: '#B8BEC9', faint: '#A4ACB9',
    action: '#E4E8EF', actionPressed: '#CDD4DF', onAction: '#181B20',
    accent: '#A3B7FF', accentSoft: '#263253', accentInk: '#D1DBFF', onAccent: '#14214B',
    line: '#353B46', outline: '#7A8596', danger: '#FFA7B3', dangerSoft: '#41252D',
    success: '#8FD6B0', successSoft: '#213B2E', attention: '#C8B1F2', attentionSoft: '#32273F', scrim: 'rgba(0,0,0,.60)',
    dock: '#14161A', portrait: '#282D36', glow: '#14161A',
  },
};
export type AppColors = typeof palettes.day;
/** Only a controlled enum is sent into the retained conversation; switching never reloads it. */
export function conversationThemeScript(mode: AppMode) {
  const value = mode === 'day' ? 'day' : 'night';
  return `if(document.documentElement){document.documentElement.dataset.appTheme='${value}';} true;`;
}
