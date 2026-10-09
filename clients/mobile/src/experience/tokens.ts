import {palettes} from '../appearance';

// Static interaction previews use the production daylight palette.
export const colors = palettes.day;

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
