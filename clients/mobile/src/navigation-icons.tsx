import {Platform} from 'react-native';
import Svg, {Path, Rect, Text as SvgText} from 'react-native-svg';
import {Orbit, MessageCircle} from 'lucide-react-native';
import {useLocalDate} from './use-local-date';

/** Shared glyphs: the caller owns color, interaction, labels and selected state. */
export type NavigationIconProps = {color: string; size?: number; strokeWidth?: number};

export function ChatIcon({color, size = 22, strokeWidth = 1.65}: NavigationIconProps) {
  return <MessageCircle color={color} size={size} strokeWidth={strokeWidth}/>;
}

export function MemoryIcon({color, size = 22, strokeWidth = 1.65}: NavigationIconProps) {
  return <Orbit color={color} size={size} strokeWidth={strokeWidth}/>;
}

export function CalendarDateIcon({day, color, size = 22, strokeWidth = 1.65}: NavigationIconProps & {day?: number}) {
  return <Svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color}
    strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
    <Rect x={3.5} y={5} width={17} height={16} rx={2.5}/>
    <Path d="M8 3v4M16 3v4M3.5 9h17"/>
    <SvgText x={12} y={18.25} fill={color} stroke="none" textAnchor="middle"
      fontFamily={Platform.OS === 'ios' ? 'System' : 'sans-serif'} fontSize={10.5} fontWeight="600">{day}</SvgText>
  </Svg>;
}

export function LocalCalendarIcon(props: NavigationIconProps) {
  const date = useLocalDate();
  return <CalendarDateIcon {...props} day={date?.day}/>;
}
