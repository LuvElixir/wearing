import {View} from 'react-native';
import {SvgXml} from 'react-native-svg';
import {wordmark, wordmarkRatio} from './brand';

const themedWordmark = wordmark.replace('fill="#202228"', 'fill="currentColor"');

/** Bundled outlines keep the identity consistent without loading a font. */
export function BrandWordmark({width = 80, color}: {width?: number; color: string}) {
  return <View accessible accessibilityRole="image" accessibilityLabel="Pajio">
    <SvgXml xml={themedWordmark} width={width} height={width / wordmarkRatio} color={color} accessible={false}/>
  </View>;
}
