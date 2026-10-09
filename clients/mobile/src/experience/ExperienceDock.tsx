import {useEffect, useRef, useState} from 'react';
import {router, usePathname} from 'expo-router';
import {StyleSheet, Text} from 'react-native';
import {SafeAreaView} from 'react-native-safe-area-context';
import {Camera, FileText} from 'lucide-react-native';
import {BottomNavigation, type BottomNavigationPage} from './BottomNavigation';
import {IntentComposer} from './IntentComposer';
import {MotionPresence} from './MotionPresence';
import {Sheet, TactilePressable} from './primitives';
import {useDemo} from './state';
import {colors as c} from './tokens';
import {AppDock} from './AppDock';

/** Persistent chrome: routing changes the content, never reconstructs the input. */
export function ExperienceDock() {
  const d = useDemo(), path = usePathname();
  const [add, setAdd] = useState(false), [notice, setNotice] = useState(''), [noticeVisible,setNoticeVisible]=useState(false);
  const timer = useRef<ReturnType<typeof setTimeout>|undefined>(undefined);
  const page = path.split('/').pop();
  const selected: BottomNavigationPage = page==='review'?'review':page==='goals'||page==='goal'?'goals':page==='memory'?'memory':page==='companion'?'companion':page==='now'||page==='conversation'||page==='experience'?'now':d.lastTab;
  useEffect(() => () => clearTimeout(timer.current), []);
  const tell = (value: string) => {
    clearTimeout(timer.current); setNotice(value);setNoticeVisible(true);
    timer.current = setTimeout(() => setNoticeVisible(false), 2300);
  };
  if (page === 'welcome') return null;
  return <SafeAreaView edges={['bottom']} style={s.safe}>
    <AppDock>
      <MotionPresence visible={noticeVisible} style={s.notice}><Text style={s.noticeText}>{notice}</Text></MotionPresence>
      <IntentComposer scopeKey={path} active={!add&&!d.composerSuspended} offline={d.offline} keyboard={d.keyboard} text={d.text}
        onKeyboard={d.setKeyboard} onText={d.setText} onAppend={d.appendDraft}
        onEngage={()=>d.setInputEngaged(true)} onAdd={()=>setAdd(true)}
        onCamera={()=>tell('拍照入口预览；真机版会打开相机')}
        onSend={()=>{if(d.send(d.text)){d.setLastTab('now');d.setKeyboard(false);router.replace('/experience/conversation');}}}/>
      <BottomNavigation selected={selected} onSelect={target=>{
        d.setLastTab(target);
        const destination=target==='now'?(d.messages.length?'/experience/conversation':'/experience'):'/experience/'+target;
        if(path!==destination)router.replace(destination as '/experience');
      }}/>
    </AppDock>
    <Sheet visible={add} onDismiss={()=>setAdd(false)} title="添加" subtitle="本次仅预览入口，不读取照片或文件。">
      <TactilePressable accessibilityLabel="拍一张" onPress={()=>{setAdd(false);tell('拍照入口预览；真机版会打开相机');}} style={s.row}><Camera size={23} color={c.ink}/><Text style={s.rowLabel}>拍一张</Text></TactilePressable>
      <TactilePressable accessibilityLabel="照片与文件" onPress={()=>{setAdd(false);tell('文件入口预览；真机版会打开选择器');}} style={s.row}><FileText size={23} color={c.ink}/><Text style={s.rowLabel}>照片与文件</Text></TactilePressable>
    </Sheet>
  </SafeAreaView>;
}

const s=StyleSheet.create({
  safe:{backgroundColor:c.canvas},
  notice:{position:'absolute',left:16,right:16,bottom:138,alignItems:'center',zIndex:8},
  noticeText:{paddingHorizontal:15,paddingVertical:9,borderRadius:16,backgroundColor:c.ink,color:c.surface,fontSize:12,lineHeight:18},
  row:{minHeight:64,flexDirection:'row',alignItems:'center',gap:15,paddingHorizontal:4},
  rowLabel:{fontSize:16,lineHeight:24,color:c.ink},
});
