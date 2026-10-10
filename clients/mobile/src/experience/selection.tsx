import {type ReactNode} from 'react';
import {StyleSheet, Switch as NativeSwitch, Text, View, type StyleProp, type SwitchProps, type ViewStyle} from 'react-native';
import {Circle, CircleDot, Square, SquareCheckBig} from 'lucide-react-native';
import {useAppTheme, useThemedStyles, type AppColors} from '../app-theme';
import {TactilePressable} from './primitives';

type ChoiceProps = {selected:boolean; onPress:()=>void; label?:string; children?:ReactNode; disabled?:boolean; multiple?:boolean; style?:StyleProp<ViewStyle>; accessibilityLabel?:string; accessibilityHint?:string; variant?:'row'|'chip'|'card'};
/** Presentation only: callers retain draft, acknowledgement and authorization semantics. */
export function Choice({selected,onPress,label,children,disabled,multiple=false,style,accessibilityLabel,accessibilityHint,variant='row'}:ChoiceProps){
 const {colors:c}=useAppTheme(),s=useThemedStyles(styles);
 const Mark=multiple?(selected?SquareCheckBig:Square):(selected?CircleDot:Circle);
 return <TactilePressable accessibilityRole={multiple?'checkbox':'radio'} accessibilityState={{checked:selected}} accessibilityLabel={accessibilityLabel||label} accessibilityHint={accessibilityHint} disabled={disabled} onPress={onPress}
  style={[s.choice,variant==='card'&&s.card,variant==='chip'&&s.chip,style,{borderColor:selected?c.selectionBorder:c.line,backgroundColor:disabled?c.disabledSurface:selected?c.selectionSurface:c.surface}]}>
  {children || (label ? <Text style={[s.label,{color:disabled?c.disabledInk:selected?c.selectionInk:c.ink}]}>{label}</Text> : null)}
  <View pointerEvents="none" accessible={false} accessibilityElementsHidden style={variant==='card'?s.cardMark:undefined}><Mark size={variant==='chip'?17:20} color={disabled?c.disabledInk:selected?c.selectionIndicator:c.outline}/></View>
 </TactilePressable>;
}
export function Segment({selected,onPress,label,children,disabled,style,accessibilityLabel}: {selected:boolean;onPress:()=>void;label?:string;children?:ReactNode;disabled?:boolean;style?:StyleProp<ViewStyle>;accessibilityLabel?:string}){
 const {colors:c}=useAppTheme(),s=useThemedStyles(styles);
 return <TactilePressable accessibilityRole="tab" accessibilityLabel={accessibilityLabel||label} accessibilityState={{selected}} disabled={disabled} onPress={onPress} style={[s.segment,style,{backgroundColor:'transparent',borderRadius:0,borderWidth:0,boxShadow:'none'}]}>
  {children||<Text style={[s.segmentText,{color:disabled?c.disabledInk:selected?c.ink:c.muted,fontWeight:selected?'600':'400'}]}>{label}</Text>}
  <View pointerEvents="none" style={[s.indicator,{backgroundColor:selected?c.selectionIndicator:'transparent'}]}/>
 </TactilePressable>;
}
/** Keep the OS switch semantics; use one palette for draft switches and real settings. */
export function StateSwitch(props:SwitchProps){const {colors:c}=useAppTheme();return <NativeSwitch {...props} trackColor={{false:c.outline,true:c.selectionIndicator}} thumbColor={c.surface} ios_backgroundColor={c.soft}/>;}
export function ToggleRow({label,value,onValueChange,disabled,hint}:{label:string;value:boolean;onValueChange:(value:boolean)=>void;disabled?:boolean;hint?:string}){
 const s=useThemedStyles(styles);return <View style={s.toggle}><View style={s.words}><Text style={s.label}>{label}</Text>{hint?<Text style={s.hint}>{hint}</Text>:null}</View><StateSwitch accessibilityLabel={label} value={value} onValueChange={onValueChange} disabled={disabled}/></View>;
}

const styles=(c:AppColors)=>StyleSheet.create({
 choice:{minHeight:48,paddingHorizontal:14,paddingVertical:12,borderWidth:1,borderRadius:14,gap:12,flexDirection:'row',alignItems:'center',justifyContent:'space-between'},
 chip:{minHeight:44,paddingHorizontal:13,paddingVertical:10,borderRadius:13,gap:8},card:{flexDirection:'column',paddingTop:22},cardMark:{position:'absolute',right:10,top:10},
 label:{fontSize:15,lineHeight:23,color:c.ink,flexShrink:1},hint:{fontSize:13,lineHeight:21,color:c.muted},
 segment:{flex:1,minHeight:48,paddingHorizontal:10,justifyContent:'center',alignItems:'center',position:'relative'},segmentText:{fontSize:15,lineHeight:23},indicator:{position:'absolute',bottom:0,width:42,height:3,borderRadius:2},toggle:{minHeight:52,flexDirection:'row',alignItems:'center',justifyContent:'space-between',gap:16},words:{flex:1,gap:4},
});
