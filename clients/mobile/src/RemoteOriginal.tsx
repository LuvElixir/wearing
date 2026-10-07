import {useState} from 'react';
import {Image, View} from 'react-native';
import {Button, Text} from 'react-native-paper';
import {useAudioPlayer, useAudioPlayerStatus} from 'expo-audio';
import {connectionEndpoint, connectionHeaders, type Connection} from './core';
type OriginalSource = {uri: string; headers: Record<string, string>};
function AudioOriginal({source, name, connection}: {source: OriginalSource; name: string; connection: Connection}) {
  const player = useAudioPlayer(source); const status = useAudioPlayerStatus(player);
  const [error, setError] = useState('');
  async function toggle() {
    if (status.playing) {player.pause(); return;}
    try {
      connectionHeaders(connection); setError('');
      if (status.didJustFinish) await player.seekTo(0);
      player.play();
    } catch (failure) {setError(failure instanceof Error ? failure.message : '原录音暂时无法播放，请检查连接。');}
  }
  return <View style={{marginVertical: 12}}><Text>{name}</Text><Button onPress={toggle}>{status.playing ? '暂停录音' : '听听原录音'}</Button>{error ? <Text accessibilityLiveRegion="polite">{error}</Text> : null}</View>;
}
export default function RemoteOriginal({connection, asset}: {connection: Connection; asset: {id: string; mime: string; name: string}}) {
  let source: OriginalSource;
  try {
    const uri = new URL('/api/life/assets/' + encodeURIComponent(asset.id) + '?identity=' + encodeURIComponent(connection.identity), connectionEndpoint(connection)).toString();
    source = {uri, headers: {...connectionHeaders(connection), 'X-Wearing-Identity': connection.identity}};
  } catch (failure) {return <View style={{marginVertical: 12}}><Text>{asset.name}</Text><Text>{failure instanceof Error ? failure.message : '原件暂时无法读取，请检查连接。'}</Text></View>;}
  if (asset.mime.startsWith('audio/')) return <AudioOriginal source={source} name={asset.name} connection={connection}/>;
  return <View style={{gap: 8, marginVertical: 12}}><Image source={source} accessibilityLabel={asset.name} style={{width: '100%', height: 240, resizeMode: 'contain'}}/><Text>{asset.name}</Text></View>;
}
