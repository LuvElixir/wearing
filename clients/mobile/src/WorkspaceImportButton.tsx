import React, {useEffect, useRef, useState} from 'react';
import {ActivityIndicator, Text, View} from 'react-native';
import * as DocumentPicker from 'expo-document-picker';
import * as Crypto from 'expo-crypto';
import {File} from 'expo-file-system';
import {Upload} from 'lucide-react-native';
import {Connection, scopeOf} from './core';
import {keepMedia, storage} from './storage';
import {serviceFetch} from './transport';
import {IMPORT_LIMIT, ImportRequest, uploadWorkspace} from './workspace-import';
import {WorkspaceFile} from './personal-hub';
import {useAppTheme} from './app-theme';
import {TactilePressable} from './experience/primitives';

export function WorkspaceImportButton({connection, onImported}: {connection: Connection; onImported: (file: WorkspaceFile) => void}) {
  const {colors:c} = useAppTheme(), key = 'workspace-import:' + scopeOf(connection);
  const [pending, setPending] = useState<ImportRequest | null>(null), [busy,setBusy]=useState(false), [ready,setReady]=useState(false), [error,setError]=useState('');
  const live=useRef(true), lock=useRef(false);
  useEffect(()=>{live.current=true;void storage.get<ImportRequest>(key).then(value=>{if(live.current){setPending(value);setReady(true);}}).catch(()=>{if(live.current)setError('暂时无法读取待导入文件，请重新打开文件夹。');});return()=>{live.current=false;};},[key]);
  async function run() {
    if(lock.current||!ready)return;lock.current=true;setBusy(true);setError('');
    try {
      let request=pending;
      if(!request){
        const result=await DocumentPicker.getDocumentAsync({type:'*/*',multiple:false,copyToCacheDirectory:true});
        if(result.canceled||!live.current)return;
        const item=result.assets[0],source=new File(item.uri);
        if(!source.size||source.size>IMPORT_LIMIT)throw new Error('请选择非空且不超过 20 MB 的文件。');
        if(!item.name.trim()||/[\\/\u0000-\u001f]/.test(item.name)||item.name.startsWith('.'))throw new Error('请使用普通文件名后再导入。');
        const id=Crypto.randomUUID(),media=await keepMedia(item.uri,{id,name:item.name,mime:item.mimeType||'application/octet-stream',size:source.size},connection);
        request={id,name:item.name,mediaId:media.id,size:media.size};
        await storage.put(key,request);
        if(!live.current)return;setPending(request);
      }
      const file=await uploadWorkspace(connection,request,await storage.blob(request.mediaId),serviceFetch);
      await storage.put(key,null);
      if(live.current){setPending(null);onImported(file);}
    }catch(cause){if(live.current)setError(cause instanceof Error?cause.message:'暂时无法导入文件。');}
    finally{lock.current=false;if(live.current)setBusy(false);}
  }
  return <View style={{gap:8}}><TactilePressable accessibilityLabel={pending?'重试导入'+pending.name:'从手机导入文件'} disabled={busy||!ready} onPress={()=>void run()} style={{minHeight:48,flexDirection:'row',alignItems:'center',gap:10,padding:14,borderRadius:14,backgroundColor:c.surface}}>{busy?<ActivityIndicator color={c.accent}/>:<Upload size={21} color={c.accent}/>}<Text style={{color:c.ink,flex:1}}>{busy?'正在导入…':pending?'重试导入 · '+pending.name:'从手机导入文件'}</Text></TactilePressable>{pending&&!busy?<TactilePressable accessibilityLabel="放弃本次待导入请求" onPress={()=>{if(lock.current)return;lock.current=true;void storage.put(key,null).then(()=>{if(live.current){setPending(null);setError('');}}).catch(()=>{if(live.current)setError('待导入请求未清除，请重试。');}).finally(()=>{lock.current=false;});}} style={{minHeight:44,justifyContent:'center'}}><Text style={{color:c.muted}}>不再重试这份文件</Text></TactilePressable>:null}{error?<Text accessibilityLiveRegion="polite" style={{color:c.danger,lineHeight:22}}>{error}</Text>:null}<Text style={{color:c.muted,fontSize:12}}>PDF、文档、表格等，每份最多 20 MB。导入后可打开原件或交给 Pajio 阅读。</Text></View>;
}
