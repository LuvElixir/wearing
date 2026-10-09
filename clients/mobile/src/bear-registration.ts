import type {OutfitId} from './wardrobe';

// Alpha > 100 bounding boxes, measured from the bundled 1254px source assets.
// Registration is a view transform: original artwork stays untouched.
export const bearBounds: Record<OutfitId, readonly [number, number, number, number]> = {
  'mist-blue': [254, 62, 966, 1220], 'cream-moon': [240, 38, 970, 1236],
  'peach-check': [251, 46, 957, 1219], 'oat-knit': [246, 40, 956, 1207],
  'cocoa-moon': [223, 32, 983, 1217], 'butter-cloud': [226, 38, 980, 1231],
  'sage-check': [232, 44, 955, 1218], 'rose-dot': [236, 47, 978, 1216],
};

export function bearFrame(outfit: OutfitId, size: number, portrait = false) {
  const [left, top, right, bottom] = bearBounds[outfit];
  const scale = size * .91 / (bottom - top);
  const width = 1254 * scale;
  const frame = {width, height: width, left: size / 2 - (left + right) / 2 * scale, top: size * .955 - bottom * scale};
  if (!portrait) return frame;
  // Head and collar fill small UI slots, instead of shrinking a whole teddy into them.
  const zoom = 1.92;
  return {width: width * zoom, height: width * zoom, left: size / 2 + (frame.left - size / 2) * zoom, top: frame.top * zoom - size * .05};
}
