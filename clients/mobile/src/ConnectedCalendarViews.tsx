import type {ComponentProps} from 'react';
import {View} from 'react-native';
import CalendarPanel from './CalendarPanel';
import TodayPanel from './TodayPanel';
import {dateKey} from './calendar';
import {moveDay} from './calendar-view-model';
import {seriesWindow} from './calendar-series-model';
import {useCalendarSeries} from './use-calendar-series';
import {CalendarSeriesStatus} from './CalendarSeriesStatus';
import {useLocalDate} from './use-local-date';

export function ConnectedCalendarPanel(props: ComponentProps<typeof CalendarPanel>) {
  const now = new Date(), anchor = props.selected || props.today || {year:now.getFullYear(),month:now.getMonth()+1,day:now.getDate()};
  const range = seriesWindow(anchor), series = useCalendarSeries(props.connection,range.start,range.end,props.isCurrent);
  return <View style={{gap:16}}><CalendarPanel {...props} records={[...props.records,...series.items]}/><CalendarSeriesStatus {...series}/></View>;
}
export function ConnectedTodayPanel({isCurrent,...props}: ComponentProps<typeof TodayPanel> & {isCurrent:()=>boolean}) {
  const today = useLocalDate(), now = new Date(), anchor = today || {year:now.getFullYear(),month:now.getMonth()+1,day:now.getDate()};
  const series = useCalendarSeries(props.connection,dateKey(anchor),dateKey(moveDay(anchor,1)),isCurrent);
  return <TodayPanel {...props} records={[...props.records,...series.items]} calendarStatus={<CalendarSeriesStatus {...series}/>} onRefreshRecords={async()=>{series.refresh();await props.onRefreshRecords?.();}}/>;
}
