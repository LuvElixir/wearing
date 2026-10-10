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
    canvas: '#F8F7F3', surface: '#FFFFFF', raised: '#FFFFFF', soft: '#EFEEE9',
    ink: '#25282B', muted: '#676D70', faint: '#737A7D',
    action: '#3D5B67', actionPressed: '#314D59', onAction: '#FFFFFF',
    accent: '#3D5B67', accentSoft: '#E7ECEE', accentInk: '#314D59', onAccent: '#FFFFFF',
    line: '#D8DCDB', outline: '#77858A', danger: '#B42338', dangerSoft: '#FDEEF0',
    success: '#176449', successSoft: '#E8F3ED', attention: '#6546A2', attentionSoft: '#F2EDFB', scrim: 'rgba(20,22,26,.32)',
    dock: '#F8F7F3', portrait: '#EFEEE9', glow: '#F8F7F3',
    selectionSurface: '#E7ECEE',
    selectionInk: '#314D59',
    selectionBorder: '#B5C5CB',
    selectionIndicator: '#3D5B67',
    focusRing: '#3D5B67',
    pressedSurface: '#E6E8E6',
    disabledSurface: '#EFEEE9',
    disabledInk: '#7C8385',
  },
  night: {
    canvas: '#191D22', surface: '#22282E', raised: '#2B333A', soft: '#2B333A',
    ink: '#EEEFEA', muted: '#B5BEC1', faint: '#A7B1B6',
    action: '#CBDCE2', actionPressed: '#AEC5CF', onAction: '#1C2E36',
    accent: '#A7C3CD', accentSoft: '#293B43', accentInk: '#D0E1E6', onAccent: '#1C2E36',
    line: '#414B52', outline: '#8B9DA5', danger: '#FFA7B3', dangerSoft: '#41252D',
    success: '#8FD6B0', successSoft: '#213B2E', attention: '#C8B1F2', attentionSoft: '#32273F', scrim: 'rgba(0,0,0,.60)',
    dock: '#191D22', portrait: '#2B333A', glow: '#191D22',
    selectionSurface: '#293B43',
    selectionInk: '#D0E1E6',
    selectionBorder: '#647F8B',
    selectionIndicator: '#A7C3CD',
    focusRing: '#A7C3CD',
    pressedSurface: '#35414A',
    disabledSurface: '#2B333A',
    disabledInk: '#85939A',
  },
};
export type AppColors = typeof palettes.day;
/** Only a controlled enum is sent into the retained conversation; switching never reloads it. */
export function conversationThemeScript(mode: AppMode) {
  const value = mode === 'day' ? 'day' : 'night';
  return `if(document.documentElement){document.documentElement.dataset.appTheme='${value}';} true;`;
}
