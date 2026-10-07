import {useEffect, useRef} from 'react';
import {View} from 'react-native';
import {Button, Text} from 'react-native-paper';
import {conversationLink} from './conversationLink';
import type {ConversationProps} from './conversation-props';
import {AppDock} from './experience/AppDock';
export default function Conversation({connection, record, active = true, visible = true, reviewRequest, content, navigation}: ConversationProps) {
  const url = conversationLink(connection.endpoint, connection.identity, record, window.location.origin, reviewRequest);
  const opened = useRef<number | null>(null);
  useEffect(() => {
    if (!active || connection.development || reviewRequest?.target !== 'activity' || opened.current === reviewRequest.id) return;
    opened.current = reviewRequest.id;
    window.location.assign(url);
  }, [active, reviewRequest, url, connection.development]);
  if (connection.development) return <View style={{padding: 24, gap: 18}}><Text variant="headlineSmall">在 Expo App 中继续</Text><Text variant="bodyLarge">短期 LAN 配对用于手机开发验收。请在同一可信 Wi-Fi 下，用 Expo App 打开电脑提供的配对链接。</Text></View>;
  const activity = reviewRequest?.target === 'activity';
  return <View style={{flex:1}}>{visible ? <View style={{padding:24,gap:18,flex:1}}><Text variant="headlineSmall">{activity ? '回到这件事' : '接着和 Wearing 聊'}</Text><Text variant="bodyLarge">{activity ? '正在打开这件事的原对话。' : record ? '接着聊：' + record.title : '当前预览共用你的 Wearing 对话，打开后可以继续说。'}</Text><Button mode="contained" onPress={() => window.location.assign(url)}>{activity ? '打开这件事' : '打开对话'}</Button></View> : content}<AppDock>{navigation}</AppDock></View>;
}
