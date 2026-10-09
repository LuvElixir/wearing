import {useState} from 'react';
import {Platform,Text,View} from 'react-native';
import DateTimePicker from '@react-native-community/datetimepicker';
import {useAppTheme} from './app-theme';
import {PrimaryButton,TactilePressable} from './experience/primitives';
import {civilDateLabel,civilPickerResult,civilPickerValue} from './series-date-fields';

type Props={label:string;value:string;allDay?:boolean;disabled?:boolean;onChange:(value:string)=>void};
export default function SeriesDateField({label,value,allDay=false,disabled=false,onChange}:Props){
  const {colors:c,mode}=useAppTheme(),[picker,setPicker]=useState<'date'|'time'|null>(null),[error,setError]=useState('');
  return <View style={{gap:8}}>
    <Text style={{color:c.ink,fontSize:15,fontWeight:'500'}}>{label}</Text>
    <View style={{flexDirection:'row',flexWrap:'wrap',gap:8}}>
      <TactilePressable accessibilityRole="button" accessibilityLabel={label+'日期，'+civilDateLabel(value)} disabled={disabled} onPress={()=>{setError('');setPicker('date');}} style={{minHeight:48,paddingHorizontal:16,borderRadius:14,backgroundColor:c.soft,justifyContent:'center',opacity:disabled?.5:1}}><Text style={{color:c.ink,fontSize:16}}>{civilDateLabel(value)}</Text></TactilePressable>
      {!allDay&&<TactilePressable accessibilityRole="button" accessibilityLabel={label+'时间，'+value.slice(11,16)} disabled={disabled} onPress={()=>{setError('');setPicker('time');}} style={{minHeight:48,paddingHorizontal:16,borderRadius:14,backgroundColor:c.soft,justifyContent:'center',opacity:disabled?.5:1}}><Text style={{color:c.ink,fontSize:16}}>{/T\d{2}:\d{2}$/.test(value)?value.slice(11,16):'选择时间'}</Text></TactilePressable>}
    </View>
    {picker&&!disabled&&<View><DateTimePicker value={civilPickerValue(value)} mode={picker} timeZoneName="UTC" minimumDate={new Date('1970-01-01T00:00:00Z')} maximumDate={new Date('2100-12-31T23:59:00Z')} locale="zh-CN" is24Hour themeVariant={mode==='night'?'dark':'light'} display={Platform.OS==='ios'?'spinner':'default'} onChange={(event,date)=>{
      if(Platform.OS!=='ios')setPicker(null);
      if(event.type==='set'&&date){try{onChange(civilPickerResult(value,date,picker,allDay));setError('');}catch(e){setError(e instanceof Error?e.message:'请选择有效日期。');}}
    }}/>{Platform.OS==='ios'&&<PrimaryButton label="选好了" tone="quiet" onPress={()=>setPicker(null)}/>}</View>}
    {!!error&&<Text accessibilityRole="alert" style={{color:c.danger}}>{error}</Text>}
  </View>;
}
