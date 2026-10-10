import {Segment} from './experience/selection';
import {useEffect,useMemo,useRef,useState} from 'react';
import {StyleSheet,Text,View} from 'react-native';
import {ChevronLeft,ChevronRight,Plus,SlidersHorizontal} from 'lucide-react-native';
import {type Connection,type RecordItem,scopeOf} from './core';
import {dateKey,type CalendarDate} from './calendar';
import {calendarDays,calendarGroups,calendarViewKey,calendarViewPreferences,dayTitle,eventDayTime,eventsForDay,moveDay,type CalendarView,type CalendarViewPreferences} from './calendar-view-model';
import {filterCalendarRecords} from './calendar-sources';
import {useCalendarSources} from './use-calendar-sources';
import {CalendarSourceFilter} from './CalendarSourceFilter';
import MonthCalendar from './MonthCalendar';
import {useAppTheme} from './app-theme';
import {PrimaryButton,TactilePressable} from './experience/primitives';
import {storage} from './storage';

type Props={connection:Connection;records:RecordItem[];selected:CalendarDate|null;today:CalendarDate|null;isCurrent:()=>boolean;onSelect:(day:CalendarDate)=>void;onRecord:(item:RecordItem)=>void;onCreate:(day:CalendarDate)=>void;onNative:()=>void;onSeriesCreate?:(day:CalendarDate)=>void};
export default function CalendarPanel(props:Props){return <Panel key={scopeOf(props.connection)+'|'+(props.connection.session?.credentialId||'')} {...props}/>;}
function Panel({connection,records,selected,today,isCurrent,onSelect,onRecord,onCreate,onNative,onSeriesCreate}:Props){
  const {colors:c}=useAppTheme(),scope=scopeOf(connection),alive=useRef(false),choice=useRef(0);
  const [preferences,setPreferences]=useState<CalendarViewPreferences>({version:1,view:'month',source:'all'}),[ready,setReady]=useState(false),[error,setError]=useState(''),[limit,setLimit]=useState(100);
  const refreshKey=records.filter(r=>r.kind==='event').map(r=>r.id+':'+r.revision).join('|');
  const sources=useCalendarSources(connection,refreshKey,isCurrent);
  useEffect(()=>{alive.current=true;const ticket=choice.current;
    void storage.get<CalendarViewPreferences>(calendarViewKey(scope)).then(saved=>{if(alive.current&&ticket===choice.current){setPreferences(calendarViewPreferences(saved));setReady(true);}}).catch(()=>{if(alive.current){setReady(true);setError('未能读取上次日历视图，当前使用月历。');}});
    return()=>{alive.current=false;};
  },[scope]);
  function change(patch:Partial<CalendarViewPreferences>){
    if(!ready||!isCurrent())return;const ticket=++choice.current;const next={...preferences,...patch};setPreferences(next);setLimit(100);setError('');
    void storage.put(calendarViewKey(scope),next).catch(()=>{if(alive.current&&ticket===choice.current)setError('这次视图选择尚未保存在本机。');});
  }
  const events=useMemo(()=>filterCalendarRecords(records,preferences.source,sources.index),[records,preferences.source,sources.index]);
  const view=preferences.view,days=useMemo(()=>selected?calendarDays(view,selected):[],[selected,view]);
  const content=useMemo(()=>calendarGroups(events,days,limit),[events,days,limit]),range=days.length?`${days[0].year} 年 ${days[0].month} 月 ${days[0].day} 日 — ${days.at(-1)!.year!==days[0].year?days.at(-1)!.year+' 年 ':''}${days.at(-1)!.month} 月 ${days.at(-1)!.day} 日`:'';
  const sourceByRecord=useMemo(()=>new Map((sources.index?.records||[]).map(row=>[row.record_id,row])),[sources.index]);
  function select(day:CalendarDate){setLimit(100);onSelect(day);}
  const views:{id:CalendarView;label:string}[]=[{id:'month',label:'月'},{id:'week',label:'周'},{id:'agenda',label:'议程'}];
  return <View style={{gap:18}}>
    <View accessibilityRole="tablist" style={{flexDirection:'row',borderBottomWidth:1,borderBottomColor:c.line}}>{views.map(item=><Segment key={item.id}  selected={view===item.id} accessibilityLabel={item.label+'视图'} disabled={!ready} onPress={()=>change({view:item.id})} style={{flex:1,minHeight:44,borderRadius:13,alignItems:'center',justifyContent:'center',backgroundColor:view===item.id?c.surface:'transparent'}}><Text style={{fontSize:15,fontWeight:view===item.id?'600':'400',color:view===item.id?c.ink:c.muted}}>{item.label}</Text></Segment>)}</View>
    <CalendarSourceFilter index={sources.index} value={preferences.source} onChange={source=>change({source})} stale={sources.stale} error={sources.error} busy={sources.busy} onRefresh={sources.refresh}/>
    <Text style={{fontSize:12,lineHeight:20,color:c.muted}}>时间按本机时区显示 · {Intl.DateTimeFormat().resolvedOptions().timeZone}。系统来源是最近同步的副本。</Text>
    {view==='month'?<MonthCalendar selected={selected} today={today} onSelect={select} eventCount={day=>eventsForDay(events,day).length}/>:selected?<>
      <View style={{flexDirection:'row',gap:8,alignItems:'center',justifyContent:'space-between'}}><Text accessibilityRole="header" accessibilityLiveRegion="polite" style={{flex:1,fontSize:16,lineHeight:25,color:c.ink,fontWeight:'600'}}>{range}</Text>
        <TactilePressable accessibilityLabel="回到今天" disabled={!today} onPress={()=>{if(today)select(today);}} style={styles.control}><Text style={{color:c.accentInk,fontSize:13}}>今天</Text></TactilePressable>
        <TactilePressable accessibilityLabel={view==='week'?'上一周':'上一个 30 天'} onPress={()=>select(moveDay(selected,view==='week'?-7:-30))} style={styles.control}><ChevronLeft size={20} color={c.ink}/></TactilePressable>
        <TactilePressable accessibilityLabel={view==='week'?'下一周':'下一个 30 天'} onPress={()=>select(moveDay(selected,view==='week'?7:30))} style={styles.control}><ChevronRight size={20} color={c.ink}/></TactilePressable>
      </View>
      <Text style={{fontSize:13,color:c.muted}}>{content.unique} 项日程{view==='agenda'?' · 连续 30 天':''} · 跨日安排会在相关日期各显示一次</Text>
    </>:null}
    {content.groups.filter(group=>view!=='agenda'||group.total>0).map(group=><View key={dateKey(group.day)} style={{gap:10}}>
      <Text accessibilityRole="header" style={{fontSize:16,lineHeight:25,fontWeight:'600',color:c.ink}}>{dayTitle(group.day,today)}{group.total?' · '+group.total+' 项':''}</Text>
      {group.items.map(item=>{const origin=sourceByRecord.get(item.id);return <TactilePressable key={item.id} accessibilityLabel={item.title+'，'+eventDayTime(item,group.day)} onPress={()=>onRecord(item)} style={{padding:16,minHeight:70,borderRadius:16,backgroundColor:c.surface,borderWidth:StyleSheet.hairlineWidth,borderColor:c.line,gap:7}}>
        <Text style={{fontSize:13,color:c.muted}}>{eventDayTime(item,group.day)}</Text><Text style={{fontSize:17,lineHeight:26,fontWeight:'500',color:c.ink}}>{item.title}</Text>
        {origin&&<Text style={{fontSize:12,lineHeight:19,color:c.muted}}>{origin.title}{origin.state==='conflict'?' · 保留你在 Pajio 的修改':origin.state==='unseen'?' · 最近一次读取未看到，副本仍保留':''}</Text>}
      </TactilePressable>;})}
      {group.total===0&&<Text style={{fontSize:14,lineHeight:22,color:c.muted}}>没有已同步的安排。</Text>}
      {group.total>group.items.length&&<Text style={{fontSize:12,lineHeight:20,color:c.muted}}>还有 {group.total-group.items.length} 项，点下方继续查看。</Text>}
    </View>)}
    {view==='agenda'&&content.total===0&&selected&&<Text style={{fontSize:14,lineHeight:23,color:c.muted}}>这个 30 天范围没有已同步的安排。</Text>}
    {content.shown<content.total&&<PrimaryButton label={`继续查看（已显示 ${content.shown} / ${content.total} 个日期条目）`} tone="quiet" onPress={()=>setLimit(v=>v+100)}/>}
    <PrimaryButton label="补充日程" disabled={!selected} leading={<Plus size={18} color={c.ink}/>} onPress={()=>{if(selected)onCreate(selected);}}/>
    {onSeriesCreate&&<PrimaryButton label="重复日程与系列" disabled={!selected} tone="quiet" onPress={()=>{if(selected)onSeriesCreate(selected);}}/>}
    <PrimaryButton label="管理系统日历与同步来源" tone="quiet" leading={<SlidersHorizontal size={18} color={c.ink}/>} onPress={onNative}/>
    {!!error&&<Text accessibilityRole="alert" style={{fontSize:13,lineHeight:21,color:c.danger}}>{error}</Text>}
  </View>;
}
const styles=StyleSheet.create({control:{minWidth:44,minHeight:44,alignItems:'center',justifyContent:'center'}});
