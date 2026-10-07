// App daylight palette, aligned to the selected Today references.
export const colors = {
  canvas: '#E3EAF1',
  surface: '#FFFFFF',
  soft: 'rgba(73, 88, 103, 0.07)',
  ink: '#252C30',
  muted: '#66747D',
  faint: '#66747D',
  accent: '#008CC8',
  accentSoft: 'rgba(55, 65, 73, 0.09)',
  accentInk: '#252C30',
  line: 'rgba(255, 255, 255, 0.76)',
  danger: '#B84343',
  dangerSoft: '#FBEFEE',
  success: '#347862',
  successSoft: '#EAF4EF',
  scrim: 'rgba(23, 31, 46, 0.24)',
} as const;

export const spacing = {xs: 4, sm: 8, md: 12, lg: 16, xl: 24, xxl: 32, section: 40} as const;
export const radii = {small: 12, control: 16, card: 24, sheet: 32, pill: 999} as const;
export const motion = {
  press: 110,
  release: 180,
  enter: 280,
  exit: 200,
  crossfade: 140,
  spring: {damping: 29, stiffness: 320, mass: 0.85},
} as const;
