import {useState,type ReactNode} from 'react';
import {Linking,StyleSheet,Text,View} from 'react-native';
import {ShieldCheck} from 'lucide-react-native';
import {useAppTheme,useThemedStyles,type AppColors} from './app-theme';
import {PrimaryButton,TactilePressable} from './experience/primitives';
import {AI_PRIVACY_URL,type AIConsentAction,type AIConsentSnapshot} from './ai-consent-client';
import {PublicInformationLinks} from './PublicInformationLinks';

type Props={snapshot:AIConsentSnapshot|null;busy:boolean;error:string;onRefresh:()=>void;onChange:(action:AIConsentAction)=>void;onBack?:()=>void;onData:()=>void;onDelete:()=>void;account:ReactNode};
export function AIConsentPanel({snapshot,busy,error,onRefresh,onChange,onBack,onData,onDelete,account}:Props){
  const {colors:c}=useAppTheme(),s=useThemedStyles(styles);const [showAccount,setShowAccount]=useState(false),[linkError,setLinkError]=useState('');
  const accepted=snapshot?.accepted===true;
  return <View style={s.root}>
    {onBack?<TactilePressable onPress={onBack} style={s.textButton}><Text style={s.link}>返回</Text></TactilePressable>:null}
    <View style={s.symbol}><ShieldCheck size={26} color={c.accentInk}/></View>
    <Text accessibilityRole="header" style={s.title}>{accepted?'AI 服务与数据授权':'开始使用 AI 之前'}</Text>
    <Text style={s.lead}>由你决定，哪些信息可以交给 AI 处理。</Text>
    {snapshot?<View style={s.card}>
      <Text style={s.heading}>{snapshot.provider.name} · 第三方 AI 服务</Text>
      <Text style={s.body}>{snapshot.disclosure.purpose}</Text>
      <Text style={s.label}>处理任务时可能发送</Text>
      {snapshot.disclosure.data_categories.map((item,index)=><View key={index} style={s.item}><Text style={s.bullet}>·</Text><Text style={[s.body,{flex:1}]}>{item}</Text></View>)}
      <Text style={s.note}>{snapshot.disclosure.withdrawal}</Text>
      <TactilePressable accessibilityRole="link" style={s.textButton} onPress={()=>{setLinkError('');void Linking.openURL(AI_PRIVACY_URL).catch(()=>setLinkError('暂时无法打开 DeepSeek 隐私政策，请稍后再试。'));}}><Text style={s.link}>查看 DeepSeek 隐私政策</Text></TactilePressable>
    </View>:<Text style={s.body}>{busy?'正在读取当前服务与授权状态…':'请先核对当前服务的说明，再决定是否同意。'}</Text>}
    {error||linkError?<Text accessibilityRole="alert" accessibilityLiveRegion="polite" style={s.error}>{error||linkError}</Text>:null}
    {snapshot?<>
      {accepted?<Text accessibilityLiveRegion="polite" style={s.note}>你已允许此 AI 服务处理任务所需的信息。</Text>:null}
      <PrimaryButton label={busy?'正在核对…':accepted?'撤回 AI 数据授权':'同意交给 DeepSeek 处理'} disabled={busy} loading={busy} onPress={()=>onChange(accepted?'revoke':'accept')}/>
    </>:<PrimaryButton label={busy?'正在核对…':'刷新授权状态'} loading={busy} disabled={busy} onPress={onRefresh}/>}
    <Text style={s.note}>暂不同意也可以查看和导出已有数据，或管理账户。只有主动同意后，才会开始新的 AI 处理。</Text>
    <View style={s.actions}><TactilePressable style={s.textButton} onPress={onData}><Text style={s.link}>查看与导出我的数据</Text></TactilePressable><TactilePressable style={s.textButton} onPress={onDelete}><Text style={s.link}>注销账户</Text></TactilePressable></View>
    <TactilePressable style={s.textButton} onPress={()=>setShowAccount(v=>!v)}><Text style={s.link}>{showAccount?'收起账户选项':'重新登录或退出账户'}</Text></TactilePressable>
    {showAccount?<View style={s.account}>{account}</View>:null}
    <PublicInformationLinks/>
  </View>;
}
const styles=(c:AppColors)=>StyleSheet.create({root:{width:'100%',maxWidth:480,alignSelf:'center',paddingBottom:28,gap:16},symbol:{width:54,height:54,borderRadius:18,backgroundColor:c.accentSoft,alignItems:'center',justifyContent:'center',marginTop:12},title:{fontSize:28,lineHeight:38,fontWeight:'600',color:c.ink},lead:{fontSize:15,lineHeight:25,color:c.muted},card:{backgroundColor:c.surface,borderWidth:1,borderColor:c.line,borderRadius:22,padding:20,gap:12},heading:{fontSize:17,lineHeight:25,fontWeight:'600',color:c.ink},body:{fontSize:14,lineHeight:24,color:c.ink},label:{fontSize:13,lineHeight:21,color:c.muted,marginTop:8},item:{flexDirection:'row',gap:8},bullet:{fontSize:18,color:c.muted,lineHeight:24},note:{fontSize:13,lineHeight:22,color:c.muted},link:{fontSize:14,lineHeight:22,color:c.accentInk},textButton:{minHeight:44,justifyContent:'center',paddingVertical:10},actions:{flexDirection:'row',flexWrap:'wrap',gap:20},error:{fontSize:13,lineHeight:22,color:c.danger},account:{paddingTop:18,borderTopWidth:1,borderColor:c.line}});
