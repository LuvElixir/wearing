import {useState} from 'react';
import {ScrollView,Text,View} from 'react-native';
import {Check,ChevronDown,RefreshCw} from 'lucide-react-native';
import {useAppTheme} from './app-theme';
import {TactilePressable} from './experience/primitives';
import {calendarSources,type CalendarSourceIndex} from './calendar-sources';

export function CalendarSourceFilter({index,value,onChange,stale,error,busy,onRefresh}:{index:CalendarSourceIndex|null;value:string;onChange:(v:string)=>void;stale:boolean;error:string;busy:boolean;onRefresh:()=>void}) {
  const {colors:c}=useAppTheme(),[open,setOpen]=useState(false),[limit,setLimit]=useState(30),sources=calendarSources(index);
  const label=value==='all'?'全部来源':value==='other'?'其他记录':sources.find(s=>s.id===value)?.title||'上次选择的来源';
  const options=[{id:'all',title:'全部来源'},{id:'other',title:'其他记录'},...sources];
  return <View style={{gap:8}}>
    <View style={{flexDirection:'row',alignItems:'center',gap:8}}>
      <TactilePressable accessibilityLabel={'筛选日历来源：'+label} accessibilityState={{expanded:open}} onPress={()=>setOpen(v=>!v)} style={{minHeight:44,paddingHorizontal:14,borderRadius:14,backgroundColor:c.surface,borderWidth:1,borderColor:c.line,flexDirection:'row',alignItems:'center',gap:10,flex:1}}><Text numberOfLines={2} style={{fontSize:14,color:c.ink,flex:1}}>{label}</Text><ChevronDown size={18} color={c.muted}/></TactilePressable>
      <TactilePressable accessibilityLabel="刷新日历来源" disabled={busy} onPress={onRefresh} style={{width:44,height:44,alignItems:'center',justifyContent:'center'}}><RefreshCw size={18} color={busy?c.muted:c.ink}/></TactilePressable>
    </View>
    {open&&<ScrollView nestedScrollEnabled style={{maxHeight:320,borderRadius:16,borderWidth:1,borderColor:c.line,backgroundColor:c.surface}} contentContainerStyle={{padding:8}}><View accessibilityRole="radiogroup">{options.slice(0,limit).map(option=><TactilePressable key={option.id} accessibilityRole="radio" accessibilityState={{checked:value===option.id}} onPress={()=>{onChange(option.id);setOpen(false);}} style={{padding:12,minHeight:44,flexDirection:'row',alignItems:'center',gap:12}}><Text style={{flex:1,color:c.ink,fontSize:15}}>{option.title}</Text>{value===option.id&&<Check size={18} color={c.accent}/>}</TactilePressable>)}</View>{options.length>limit&&<TactilePressable onPress={()=>setLimit(n=>n+30)} style={{minHeight:44,padding:12}}><Text style={{color:c.accentInk}}>继续查看来源</Text></TactilePressable>}</ScrollView>}
    {(open||value==='other')&&<Text style={{fontSize:12,lineHeight:19,color:c.muted}}>其他记录没有当前账户的系统来源标记，可能包含手动添加和其他导入。筛选只影响这里的显示。</Text>}
    {index&&stale&&<Text style={{fontSize:12,lineHeight:19,color:c.muted}}>来源为上次读取 · {new Date(index.checked_at).toLocaleString('zh-CN')}</Text>}
    {index?.truncated&&<Text style={{fontSize:12,lineHeight:19,color:c.muted}}>来源标记仅加载最近 1000 条，其余记录可能尚未分类。</Text>}
    {!!error&&<Text accessibilityLiveRegion="polite" style={{fontSize:12,lineHeight:19,color:c.muted}}>{error} 日程仍可按全部来源查看。</Text>}
  </View>;
}
