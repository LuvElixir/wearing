import {useState} from 'react';
import {Platform, View} from 'react-native';
import DateTimePicker from '@react-native-community/datetimepicker';
import {Button, Text} from 'react-native-paper';
import {useAppTheme} from './app-theme';
export default function TimeField({label, value, onChange}: {label: string; value: Date; onChange: (date: Date) => void}) {
  const {mode: appearance} = useAppTheme();
  const [mode, setMode] = useState<'date' | 'time' | null>(null);
  return <View><Text>{label}</Text><View style={{flexDirection: 'row', flexWrap: 'wrap'}}><Button onPress={() => setMode('date')}>{value.toLocaleDateString('zh-CN')}</Button><Button onPress={() => setMode('time')}>{value.toLocaleTimeString('zh-CN', {hour: '2-digit', minute: '2-digit'})}</Button></View>{mode && <DateTimePicker value={value} mode={mode} is24Hour themeVariant={appearance === 'night' ? 'dark' : 'light'} display={Platform.OS === 'ios' ? 'spinner' : 'default'} onChange={(event, date) => {setMode(null); if (event.type === 'set' && date) onChange(date);}}/>}</View>;
}
