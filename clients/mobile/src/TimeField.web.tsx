import {View} from 'react-native';
import {Text} from 'react-native-paper';
export default function TimeField({label, value, onChange}: {label: string; value: Date; onChange: (date: Date) => void}) {
  const local = new Date(value.getTime() - value.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  return <View style={{gap: 8}}><Text>{label}</Text><input aria-label={label} type="datetime-local" value={local} style={{font: 'inherit', color: 'inherit', padding: 12, border: '1px solid #e5e7ed', borderRadius: 12, minHeight: 48, background: '#fff'}} onChange={e => {const next = new Date(e.target.value); if (Number.isFinite(next.getTime())) onChange(next);}}/></View>;
}
