import {Text,View} from 'react-native';
import {useAppTheme} from './app-theme';
import {PrimaryButton} from './experience/primitives';
import type {SeriesQuery} from './calendar-series-model';
export function CalendarSeriesStatus({snapshot,stale,busy,error,refresh}:{snapshot:SeriesQuery|null;stale:boolean;busy:boolean;error:string;refresh:()=>void}){
  const {colors:c}=useAppTheme();return <View style={{gap:8}}>
    <Text style={{color:c.muted,fontSize:12,lineHeight:20}}>{snapshot?`重复日程${stale?'为上次读取':'已读取'} · ${new Date(snapshot.checked_at).toLocaleString('zh-CN')}`:busy?'正在读取重复日程…':'重复日程尚未读取，本页不代表全部安排。'}</Text>
    {snapshot?.truncated&&<Text style={{color:c.muted,fontSize:12,lineHeight:20}}>重复日程已达本次 1000 条上限，仅展示部分安排；可缩短查看范围。</Text>}
    {!!error&&<Text accessibilityLiveRegion="polite" style={{color:c.muted,fontSize:12,lineHeight:20}}>{error}</Text>}
    {(error||stale)&&<PrimaryButton label="更新重复日程" tone="quiet" disabled={busy} onPress={refresh}/>}
  </View>;
}
