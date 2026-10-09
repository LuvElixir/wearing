import {useAppTheme} from './app-theme';
import {Image, StyleProp, View, ViewStyle} from 'react-native';
import {bearFrame} from './bear-registration';
import {defaultOutfit, OutfitId} from './wardrobe';

const sources = {
  'mist-blue': require('../assets/bear/mist-blue.png'),
  'cream-moon': require('../assets/bear/cream-moon.png'),
  'peach-check': require('../assets/bear/peach-check.png'),
  'oat-knit': require('../assets/bear/oat-knit.png'),
  'cocoa-moon': require('../assets/bear/cocoa-moon.png'),
  'butter-cloud': require('../assets/bear/butter-cloud.png'),
  'sage-check': require('../assets/bear/sage-check.png'),
  'rose-dot': require('../assets/bear/rose-dot.png'),
};

/** Bundled alpha assets work offline. The same source supplies portrait and full-body views. */
export function PajamaBear({outfit = defaultOutfit, size = 220, portrait = false, style, onLoad, onError}: {outfit?: OutfitId; size?: number; portrait?: boolean; style?: StyleProp<ViewStyle>; onLoad?: () => void; onError?: () => void}) {
  const {colors: c} = useAppTheme();

  return <View accessible={false} accessibilityElementsHidden importantForAccessibility="no-hide-descendants" pointerEvents="none"
    style={[{width: size, height: size, overflow: 'hidden'}, portrait && {borderRadius: size / 2, backgroundColor: c.portrait}, style]}>
    <Image source={sources[outfit]} resizeMode="contain" fadeDuration={0} accessible={false} onLoad={onLoad} onError={onError}
      style={{position: 'absolute', ...bearFrame(outfit, size, portrait)}}/>
  </View>;
}
