export type AppearancePreference = 'night' | 'day' | 'system';
export type AppMode = 'night' | 'day';
export const appearanceKey = 'appearance:v1';
export function appearancePreference(value: unknown): AppearancePreference {
  return value === 'day' || value === 'system' ? value : 'night';
}
export function resolveAppearance(preference: AppearancePreference, system: string | null | undefined): AppMode {
  return preference === 'system' ? system === 'light' ? 'day' : 'night' : preference;
}
export const palettes = {
  day: {
    canvas: '#F3ECE2', surface: '#FCF8F2', raised: '#FFFDF8', soft: '#EAE0D3',
    ink: '#3B312D', muted: '#6E6056', faint: '#6E6056',
    accent: '#8B5E40', accentSoft: '#E5D3BF', accentInk: '#4A3427', onAccent: '#FFFAF3',
    line: '#DCCEC0', danger: '#A83F40', dangerSoft: '#F6E3DE',
    success: '#436B53', successSoft: '#E0EADD', scrim: 'rgba(39,30,28,.32)',
    dock: '#F9F2E8', portrait: '#E7D8C7', glow: '#E5CBAA',
  },
  night: {
    canvas: '#24232A', surface: '#302D34', raised: '#3B343B', soft: '#393139',
    ink: '#F0E4D5', muted: '#BCAEAA', faint: '#BCAEAA',
    accent: '#E4BC91', accentSoft: '#514035', accentInk: '#F0D1AF', onAccent: '#30251D',
    line: '#51444A', danger: '#F0AB9F', dangerSoft: '#503539',
    success: '#A4C7AF', successSoft: '#314339', scrim: 'rgba(12,10,14,.62)',
    dock: '#2B282F', portrait: '#655248', glow: '#49372F',
  },
};
export type AppColors = typeof palettes.day;
/** Only a controlled enum is sent into the retained conversation; switching never reloads it. */
export function conversationThemeScript(mode: AppMode) {
  const value = mode === 'day' ? 'day' : 'night';
  return `if(document.documentElement){document.documentElement.dataset.appTheme='${value}';} true;`;
}
