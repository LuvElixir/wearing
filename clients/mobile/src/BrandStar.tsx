import type {StyleProp, ViewStyle} from 'react-native';
import Svg, {Path} from 'react-native-svg';

/** A single four-point mark, reserved for the product identity. */
export function BrandStar({size = 24, color, style}: {size?: number; color: string; style?: StyleProp<ViewStyle>}) {
  return <Svg width={size} height={size} viewBox="0 0 24 24" style={style} accessible={false}>
    <Path d="M12 2C12.8 8.8 14.6 11.2 20 12C14.6 12.8 12.8 15.2 12 22C11.2 15.2 9.4 12.8 4 12C9.4 11.2 11.2 8.8 12 2Z" fill={color}/>
  </Svg>;
}
