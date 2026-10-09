import {useCallback,useEffect,useLayoutEffect,useRef,useState,type ReactNode} from 'react';
import {ActivityIndicator,BackHandler,ScrollView,StyleSheet,Text,View} from 'react-native';
import {ArrowLeft,ArrowRight,BookOpen,BriefcaseBusiness,CalendarDays,Check,ChevronRight,GraduationCap,Heart,House,Mail,MessageCircle,Play,Store as StoreIcon,X} from 'lucide-react-native';
import * as Crypto from 'expo-crypto';
import {ApiError,scopeOf,type Connection} from './core';
import {accountWorkAllowed} from './account-work';
import {useAppTheme,useThemedStyles,type AppColors} from './app-theme';
import {Entrance,IconButton,PrimaryButton,TactilePressable} from './experience/primitives';
import {LivingPajamaBear} from './LivingPajamaBear';
import {OnboardingConnections,OnboardingSourceSummary} from './OnboardingConnections';
import {OnboardingActivity,OnboardingApi,OnboardingChanges} from './onboarding-client';
import {appChoices,detailChoices,emptyOnboarding,interestChoices,onboardingIssue,onboardingSample,roleChoices,toggleOnboardingSelection,toneChoices,type OnboardingSnapshot,type OnboardingValues} from './onboarding-model';
import {storage} from './storage';
import {serviceFetch} from './transport';
import type {OutfitId} from './wardrobe';

type Props={connection:Connection;outfit:OutfitId;isCurrent:()=>boolean;onComplete:()=>void;onClose:()=>void};
const steps=['见个面','你的日常','常用应用','兴趣与表达','带上资料','确认偏好'];
export default function OnboardingPanel(props:Props){return <Content key={scopeOf(props.connection)+'|'+(props.connection.session?.credentialId||'local')} {...props}/>;}
function Content({connection,outfit,isCurrent,onComplete,onClose}:Props){
  const {colors:c}=useAppTheme(),s=useThemedStyles(styles);
  const [snapshot,setSnapshot]=useState<OnboardingSnapshot|null>(null),[values,setValues]=useState<OnboardingValues>(emptyOnboarding),[step,setStep]=useState(0);
  const [loading,setLoading]=useState(true),[busy,setBusy]=useState(false),[error,setError]=useState(''),[pending,setPending]=useState(false),[conflict,setConflict]=useState(false),[branch,setBranch]=useState(false),[localConflict,setLocalConflict]=useState(false);
  const locked=useRef(false),fields=useRef({values,step});
  const [session]=useState(()=>new OnboardingActivity(()=>isCurrent()&&accountWorkAllowed(connection)));
  const active=session.active;
  const [api]=useState(()=>new OnboardingApi(connection,serviceFetch,active));
  const [changes]=useState(()=>new OnboardingChanges(storage,api,active));
  useLayoutEffect(()=>{session.update(()=>isCurrent()&&accountWorkAllowed(connection));fields.current={values,step};},[session,isCurrent,connection,values,step]);
  const load=useCallback(async()=>{
    if(locked.current||!active())return;locked.current=true;setLoading(true);setError('');
    try{
      const [fresh,draft,request]=await Promise.all([api.load(),changes.draft(),changes.pending()]);if(!active())return;
      setSnapshot(fresh);setPending(!!request);setConflict(false);
      const saved=request||draft;
      setLocalConflict(!request&&!!draft&&draft.revision!==fresh.revision);
      setValues(saved?.values||fresh.values);setStep(saved?.step??(fresh.status==='completed'?5:fresh.step));
    }catch(cause){if(active())setError(onboardingIssue(cause));}
    finally{locked.current=false;if(active())setLoading(false);}
  },[active,api,changes]);
  useEffect(()=>{session.mount();void Promise.resolve().then(()=>load());return()=>{session.stop();};},[session,load]); // Session is keyed by account/identity.
  const retain=async(nextValues:OnboardingValues,nextStep=step)=>{
    if(!snapshot||!active())return;
    try{await changes.retain({version:1,revision:snapshot.revision,step:nextStep,values:nextValues});}
    catch(cause){if(active())setError(onboardingIssue(cause));}
  };
  const choose=(next:OnboardingValues)=>{if(busy||pending||loading||localConflict||!active())return;setValues(next);setError('');void retain(next);};
  const go=(next:number)=>{if(busy||pending||loading||localConflict||!active())return;setStep(next);setError('');void retain(values,next);};
  const close=async()=>{
    if(loading){onClose();return;}
    if(locked.current)return;locked.current=true;setBusy(true);
    try{if(snapshot&&!pending)await changes.retain({version:1,revision:snapshot.revision,...fields.current});if(active())onClose();}
    catch(cause){if(active())setError(onboardingIssue(cause));}
    finally{locked.current=false;if(active())setBusy(false);}
  };
  const save=async(status:'draft'|'completed'|'skipped',nextStep:number,retry=false)=>{
    if(!snapshot||locked.current||!active())return;
    // Editing a confirmed profile remains local until explicit confirmation.
    if(status==='draft'&&snapshot.status!=='draft'&&!retry){go(nextStep);return;}
    locked.current=true;setBusy(true);setError('');setConflict(false);
    try{
      const receipt=await changes.save(retry?undefined:{revision:snapshot.revision,request_key:Crypto.randomUUID(),status,step:nextStep,values:status==='skipped'?emptyOnboarding():values});
      if(!active())return;setSnapshot(receipt);setPending(false);setValues(receipt.values);setStep(receipt.step);
      if(receipt.status==='completed'||receipt.status==='skipped')onComplete();
    }catch(cause){if(active()){const unresolved=await changes.pending().catch(()=>null);if(active()){setError(onboardingIssue(cause));setPending(!!unresolved);setConflict(cause instanceof ApiError&&cause.status===409);}}}
    finally{locked.current=false;if(active())setBusy(false);}
  };
  const resolve=async(useSaved:boolean)=>{
    if(locked.current||!active())return;locked.current=true;setBusy(true);setError('');
    try{
      const fresh=await api.load();if(!active())return;
      if(conflict)await changes.resolveConflict(fresh);
      const next=useSaved?fresh.values:values;const nextStep=useSaved?fresh.status==='completed'?5:fresh.step:step;
      await changes.retain({version:1,revision:fresh.revision,step:nextStep,values:next});if(!active())return;
      setSnapshot(fresh);setValues(next);setStep(nextStep);setLocalConflict(false);setPending(false);setConflict(false);
    }catch(cause){if(active())setError(onboardingIssue(cause));}
    finally{locked.current=false;if(active())setBusy(false);}
  };
  const back=()=>{if(busy)return;if(step>0&&!pending&&!localConflict)go(step-1);else void close();};
  const backRef=useRef(back);useLayoutEffect(()=>{backRef.current=back;});
  useEffect(()=>{const listener=BackHandler.addEventListener('hardwareBackPress',()=>{if(branch)return false;backRef.current();return true;});return()=>listener.remove();},[branch]);
  const disabled=busy||pending||loading||localConflict;
  const labelFor=(choices:readonly {id:string;label:string}[],selected:string[])=>choices.filter(row=>selected.includes(row.id)).map(row=>row.label).join('、')||'暂时跳过';
  const roleIcons:ReactNode[]=[<BriefcaseBusiness key="work" size={23} color={c.ink}/>,<GraduationCap key="study" size={23} color={c.ink}/>,<House key="independent" size={23} color={c.ink}/>,<StoreIcon key="business" size={23} color={c.ink}/>,<Heart key="care" size={23} color={c.ink}/>];
  const appIcon=(id:string)=>id==='calendar'?<CalendarDays size={21} color={c.ink}/>:id==='mail'?<Mail size={21} color={c.ink}/>:['douyin','bilibili'].includes(id)?<Play size={21} color={c.ink}/>:id==='xiaohongshu'?<BookOpen size={21} color={c.ink}/>:<MessageCircle size={21} color={c.ink}/>;
  return <View style={s.screen}>
    <View style={s.top}><IconButton label={step?'上一步':'退出初始设置'} variant="plain" onPress={back} disabled={busy||branch}><ArrowLeft size={23} color={c.ink}/></IconButton><View style={s.progress} accessibilityLabel={`初始设置，第 ${step+1} 步，共 6 步`}>{steps.map((_,index)=><View key={index} style={[s.tick,{backgroundColor:index<=step?c.accent:c.line}]}/>)}</View><IconButton label="稍后继续" variant="plain" onPress={()=>void close()} disabled={busy}><X size={21} color={c.muted}/></IconButton></View>
    <ScrollView key={step} contentContainerStyle={s.scroll} maximumZoomScale={1} minimumZoomScale={1} pinchGestureEnabled={false}>
      {loading?<View style={s.loading}><ActivityIndicator color={c.accent}/><Text style={s.copy}>正在读取你的设置</Text></View>:!snapshot?<View style={s.card}><Text style={s.title}>稍后再认识，也可以。</Text><Text style={s.copy}>{error}</Text><PrimaryButton label="重新读取" onPress={()=>void load()}/><PrimaryButton label="先进入产品" tone="quiet" onPress={onClose}/></View>:<Entrance transitionKey={step} style={s.page}>
        <Text style={s.eyebrow}>{steps[step]} · {step+1} / 6</Text>
        {step===0?<>
          <View style={s.hero}><LivingPajamaBear outfit={outfit} size={164} portrait={false}/></View>
          <Text style={s.title}>你好，我是 Pajio。</Text><Text style={s.lead}>点几下，让我更懂你的日常。{ '\n'}不必先想好，要交给我什么。</Text>
          <View style={s.card}><Text style={s.label}>你可以这样用我</Text><View style={s.example}><CalendarDays size={22} color={c.accent}/><View style={s.words}><Text style={s.optionTitle}>把安排放在一起</Text><Text style={s.copy}>连接你选择的日历，在「今天」查看。</Text></View></View><View style={s.example}><BookOpen size={22} color={c.accent}/><View style={s.words}><Text style={s.optionTitle}>读懂你交给我的资料</Text><Text style={s.copy}>分享链接或文件，需要时帮你整理。</Text></View></View><Text style={s.caption}>能力示例 · 现在还没有读取你的资料</Text></View>
        </>:null}
        {step===1?<><Text style={s.title}>你的日常里，{ '\n'}有哪些角色？</Text><Text style={s.lead}>可以同时选几个，也可以暂时跳过。最多 3 项。</Text><View style={s.stack}>{roleChoices.map((item,index)=><Choice key={item.id} selected={values.roles.includes(item.id)} disabled={disabled||values.roles.length>=3&&!values.roles.includes(item.id)} label={item.label} icon={roleIcons[index]} onPress={()=>choose({...values,roles:toggleOnboardingSelection(values.roles,item.id,3)})}/>)}</View><Text style={s.caption}>这些是你当前的选择，之后随时能改。</Text></>:null}
        {step===2?<><Text style={s.title}>平时常用{ '\n'}哪些应用？</Text><Text style={s.lead}>选熟悉的就好，用来推荐合适的资料入口。</Text><View style={s.grid}>{appChoices.map(item=><Choice key={item.id} compact selected={values.apps.includes(item.id)} disabled={disabled} label={item.label} icon={appIcon(item.id)} onPress={()=>choose({...values,apps:toggleOnboardingSelection(values.apps,item.id,10)})}/>)}</View><Text style={s.caption}>点选不会登录应用，也不会读取聊天、浏览或收藏历史。</Text></>:null}
        {step===3?<><Text style={s.title}>什么值得{ '\n'}多看一眼？</Text><Text style={s.lead}>选几个愿意了解的话题，最多 5 项。</Text><View style={s.chips}>{interestChoices.map(item=><Choice key={item.id} chip selected={values.interests.includes(item.id)} disabled={disabled||values.interests.length>=5&&!values.interests.includes(item.id)} label={item.label} onPress={()=>choose({...values,interests:toggleOnboardingSelection(values.interests,item.id,5)})}/>)}</View>
          <View style={s.card}><Text style={s.label}>回答长一点，还是短一点？</Text><View style={s.chips}>{detailChoices.map(item=><Choice key={item.id} chip single selected={values.reply_detail===item.id} disabled={disabled} label={item.label} onPress={()=>choose({...values,reply_detail:values.reply_detail===item.id?null:item.id})}/>)}</View><Text style={s.label}>更喜欢怎样的语气？</Text><View style={s.chips}>{toneChoices.map(item=><Choice key={item.id} chip single selected={values.reply_tone===item.id} disabled={disabled} label={item.label} onPress={()=>choose({...values,reply_tone:values.reply_tone===item.id?null:item.id})}/>)}</View><Text style={s.caption}>表达示例 · 未选择时使用默认</Text><Text style={s.sample}>{onboardingSample(values)}</Text></View>
        </>:null}
        {step===4?<><Text style={s.title}>带上现成资料，{ '\n'}少一些反复说明。</Text><OnboardingConnections connection={connection} values={values} isCurrent={active} onBranchChange={setBranch}/></>:null}
        {step===5?<><View style={s.summaryHeading}><LivingPajamaBear outfit={outfit} size={80}/><View style={s.words}><Text style={s.title}>先这样认识你。</Text><Text style={s.copy}>只记下你选的内容，随时可以调整。</Text></View></View><View style={s.card}>
          <Summary label="日常角色" value={labelFor(roleChoices,values.roles)} edit={()=>go(1)} disabled={disabled}/>
          <Summary label="常用应用" value={labelFor(appChoices,values.apps)} edit={()=>go(2)} disabled={disabled}/>
          <Summary label="关注的话题" value={labelFor(interestChoices,values.interests)} edit={()=>go(3)} disabled={disabled}/>
          <Summary label="回答方式" value={[detailChoices.find(item=>item.id===values.reply_detail)?.label||'默认长度',toneChoices.find(item=>item.id===values.reply_tone)?.label||'默认语气'].join(' · ')} edit={()=>go(3)} disabled={disabled}/>
          <Summary label="资料连接" value="查看或调整来源" edit={()=>go(4)} disabled={disabled}/>
          <OnboardingSourceSummary connection={connection} isCurrent={active} feishu={values.apps.includes('feishu')}/>
        </View><Text style={s.copy}>确认后，这些初始偏好会帮助 Pajio 理解你的日常、调整回答和简报关注。选择常用应用不代表已连接，资料是否可用以授权页为准。</Text><Text style={s.caption}>不会因为完成引导而自动执行任务或开启通知。你可以在「我的 → 初始偏好」修改。</Text></>:null}
        {localConflict||conflict?<View style={s.problem}><Text style={s.copy}>另一处保存了更新的偏好。你的本机选择仍保留，请选择以哪份继续核对。</Text><PrimaryButton label="保留本机选择，重新核对" tone="quiet" disabled={busy} onPress={()=>void resolve(false)}/><PrimaryButton label="使用已保存的最新偏好" tone="quiet" disabled={busy} onPress={()=>void resolve(true)}/></View>:null}
        {error?<Text accessibilityRole="alert" style={s.error}>{error}</Text>:null}
        {pending&&!conflict?<View style={s.problem}><Text style={s.copy}>上一次保存还没有确认，先取回结果再继续。你的选择已保留。</Text><PrimaryButton label="重试同一次保存" loading={busy} onPress={()=>void save('draft',step,true)}/></View>:null}
      </Entrance>}
    </ScrollView>
    {snapshot&&!loading&&!branch?<View style={s.footer}>
      <PrimaryButton label={step===0?'开始认识':step===5?'确认并进入 Pajio':'继续'} leading={step===5?<Check size={18} color={c.onAccent}/>:<ArrowRight size={18} color={c.onAccent}/>} disabled={disabled} loading={busy} onPress={()=>void save(step===5?'completed':'draft',Math.min(5,step+1))}/>
      {step===0&&snapshot.status==='draft'?<TactilePressable disabled={busy||pending||localConflict} accessibilityLabel="跳过初始设置，进入产品" onPress={()=>void save('skipped',0)} style={s.skip}><Text style={s.copy}>先进去看看</Text></TactilePressable>:step>0&&step<4&&!(step===1?values.roles.length:step===2?values.apps.length:values.interests.length||values.reply_detail||values.reply_tone)?<TactilePressable disabled={disabled} accessibilityLabel="这一项暂时不补充" onPress={()=>void save('draft',step+1)} style={s.skip}><Text style={s.copy}>这一项暂时不补充</Text></TactilePressable>:<Text style={[s.caption,{textAlign:'center'}]}>当前身份的选择 · 可随时返回修改</Text>}
    </View>:null}
  </View>;
}
function Choice({label,selected,disabled,icon,onPress,compact,chip,single}:{label:string;selected:boolean;disabled?:boolean;icon?:ReactNode;onPress:()=>void;compact?:boolean;chip?:boolean;single?:boolean}){
  const {colors:c}=useAppTheme(),s=useThemedStyles(styles);
  return <TactilePressable accessibilityRole={single?'radio':'checkbox'} accessibilityState={{checked:selected}} accessibilityLabel={label} disabled={disabled} onPress={onPress} style={[s.choice,compact&&s.compact,chip&&s.chip,selected&&s.selected]}>{icon?<View style={s.glyph}>{icon}</View>:null}<Text style={[s.choiceText,selected&&{color:c.accentInk}]}>{label}</Text>{!chip?<View style={[s.check,selected&&{backgroundColor:c.accent,borderColor:c.accent}]}>{selected?<Check size={13} color={c.onAccent}/>:null}</View>:null}</TactilePressable>;
}
function Summary({label,value,edit,disabled}:{label:string;value:string;edit:()=>void;disabled:boolean}){const {colors:c}=useAppTheme(),s=useThemedStyles(styles);return <TactilePressable accessibilityLabel={`修改${label}，${value}`} disabled={disabled} onPress={edit} style={s.summary}><View style={s.words}><Text style={s.caption}>{label}</Text><Text style={s.optionTitle}>{value}</Text></View><ChevronRight size={18} color={c.muted}/></TactilePressable>;}
const styles=(c:AppColors)=>StyleSheet.create({
  screen:{flex:1},top:{flexDirection:'row',alignItems:'center',paddingHorizontal:14,paddingTop:4,gap:20},progress:{flex:1,flexDirection:'row',gap:5},tick:{height:3,flex:1,borderRadius:2},
  scroll:{flexGrow:1,padding:24,paddingTop:16,maxWidth:600,width:'100%',alignSelf:'center'},page:{gap:18},eyebrow:{fontSize:12,lineHeight:20,color:c.muted,letterSpacing:.5},
  title:{fontSize:29,lineHeight:39,fontWeight:'500',letterSpacing:-.65,color:c.ink},lead:{fontSize:16,lineHeight:26,color:c.muted},copy:{fontSize:14,lineHeight:23,color:c.muted},caption:{fontSize:12,lineHeight:20,color:c.muted},label:{fontSize:15,lineHeight:23,fontWeight:'500',color:c.ink},
  hero:{alignItems:'center',marginTop:-8,marginBottom:-8},card:{padding:20,borderRadius:24,backgroundColor:c.surface,borderWidth:1,borderColor:c.line,gap:17},example:{flexDirection:'row',alignItems:'center',gap:14},words:{flex:1,gap:5},optionTitle:{fontSize:16,lineHeight:24,color:c.ink},
  stack:{gap:10},grid:{flexDirection:'row',flexWrap:'wrap',gap:10},chips:{flexDirection:'row',flexWrap:'wrap',gap:8},choice:{minHeight:60,padding:14,borderRadius:18,borderWidth:1,borderColor:c.line,backgroundColor:c.surface,flexDirection:'row',alignItems:'center',gap:11},compact:{width:'48%',flexGrow:1,maxWidth:'49%',minHeight:65,padding:12,gap:8},chip:{minHeight:44,paddingHorizontal:14,paddingVertical:10,borderRadius:16},selected:{backgroundColor:c.accentSoft,borderColor:c.accent},choiceText:{fontSize:15,lineHeight:23,color:c.ink,flexShrink:1},glyph:{width:25,alignItems:'center'},check:{width:17,height:17,borderRadius:9,borderWidth:1,borderColor:c.line,alignItems:'center',justifyContent:'center',marginLeft:'auto'},
  sample:{fontSize:15,lineHeight:25,color:c.ink,padding:14,borderRadius:14,backgroundColor:c.soft},summaryHeading:{flexDirection:'row',alignItems:'center',gap:14},summary:{minHeight:58,flexDirection:'row',alignItems:'center',gap:14},
  footer:{paddingHorizontal:24,paddingTop:12,paddingBottom:10,gap:8,borderTopWidth:StyleSheet.hairlineWidth,borderTopColor:c.line,maxWidth:600,width:'100%',alignSelf:'center'},skip:{minHeight:44,alignItems:'center',justifyContent:'center'},loading:{flex:1,alignItems:'center',justifyContent:'center',gap:16},problem:{gap:12,padding:16,borderRadius:18,backgroundColor:c.soft},error:{fontSize:14,lineHeight:23,color:c.danger},
});
