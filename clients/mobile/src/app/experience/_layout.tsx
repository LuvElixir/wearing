import {Stack, router, usePathname} from 'expo-router';
import {Image, KeyboardAvoidingView, Platform, ScrollView, StyleSheet, Text, useWindowDimensions, View} from 'react-native';
import {SafeAreaProvider} from 'react-native-safe-area-context';
import {ArrowUpRight} from 'lucide-react-native';
import {DemoProvider, pages} from '../../experience/state';
import {TactilePressable, useReducedMotion} from '../../experience/primitives';
import {ExperienceDock} from '../../experience/ExperienceDock';
import {ExperienceFocus} from '../../experience/ExperienceFocus';
import {colors as c} from '../../experience/tokens';
/** MODE: Operate. THESIS: one intent entrance with layered review; a personal agent in hand.
 * OWN-WORLD: Pajio cobalt, white, quiet grouped surfaces and the approved 3D companion.
 * STORY: say a thought, understand progress, decide once, return without losing context.
 * FIRST VIEWPORT: greeting and one current matter above a thumb-reachable voice composer.
 * FORM: extend the established native client; supplied Today references inform hierarchy.
 * FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, and DESIGN.md.
 */
function Preview(){
 const {width,height}=useWindowDimensions(),path=usePathname(),reduce=useReducedMotion();
 const wide=Platform.OS==='web'&&width>=860,framed=Platform.OS==='web'&&width>=500;
 return <View style={[s.outer,framed&&s.wide]}>
  {wide&&<View style={s.rail}><View style={s.brand}><Image source={require('../../../assets/icon.png')} style={s.mark}/><Text style={s.brandName}>Pajio</Text></View><Text style={s.headline}>你先休息。{ '\n'}这件事我来。</Text><Text style={s.intro}>iPhone 交互预览{ '\n'}点开、返回、说一句，感受完整的路径。</Text><ScrollView showsVerticalScrollIndicator={false} style={{maxHeight:height-320}}>{pages.map(page=>{const url=page.id==='now'?'/experience':'/experience/'+page.id;return <TactilePressable key={page.id} accessibilityLabel={'预览'+page.label} onPress={()=>router.replace(url as '/experience')} style={[s.nav,path===url&&s.navActive]}><Text style={[s.navTitle,path===url&&s.activeText]}>{page.label}</Text><ArrowUpRight size={16} color={path===url?c.accent:c.muted}/></TactilePressable>;})}</ScrollView><Text style={s.disclaimer}>所有内容为体验示例。{ '\n'}操作仅在预览内生效，不录音、不下单。</Text></View>}
  <View style={[s.device,framed&&{width:430,height:Math.min(900,height-40),flex:0,flexGrow:0,flexShrink:0,flexBasis:'auto',borderRadius:36,overflow:'hidden',boxShadow:'0 20px 80px rgba(34,46,82,0.10)'}]}>
   <View style={s.notice}><Text style={s.noticeText}>交互预览 · 示例内容</Text></View>
   <KeyboardAvoidingView behavior={Platform.OS==='ios'?'padding':undefined} style={{flex:1}}><ExperienceFocus/><View style={{flex:1}}><Stack screenOptions={{headerShown:false,animation:'fade',animationDuration:reduce?0:180,gestureEnabled:true,contentStyle:{backgroundColor:c.canvas}}}/></View><ExperienceDock/></KeyboardAvoidingView>
  </View>
 </View>;
}
export default function ExperienceLayout(){return <SafeAreaProvider><DemoProvider><Preview/></DemoProvider></SafeAreaProvider>;}
const s=StyleSheet.create({outer:{flex:1,backgroundColor:c.canvas},wide:{flexDirection:'row',alignItems:'center',justifyContent:'center',gap:80,padding:20,backgroundColor:'#f0f2f7'},device:{flex:1,backgroundColor:c.canvas},rail:{width:290,alignSelf:'center',gap:16},brand:{flexDirection:'row',gap:9,alignItems:'center'},mark:{width:30,height:30,borderRadius:8},brandName:{fontSize:22,fontWeight:'700',color:c.ink,letterSpacing:-.6},headline:{fontSize:38,fontWeight:'600',lineHeight:49,letterSpacing:-1,color:c.ink,marginTop:12},intro:{fontSize:14,lineHeight:23,color:c.muted},nav:{minHeight:44,paddingHorizontal:14,borderRadius:12,flexDirection:'row',alignItems:'center',justifyContent:'space-between',marginBottom:4},navActive:{backgroundColor:'#ffffff'},navTitle:{fontSize:14,color:c.muted},activeText:{color:c.accent,fontWeight:'600'},disclaimer:{fontSize:12,lineHeight:20,color:c.muted},notice:{alignItems:'center',paddingTop:8,paddingBottom:5,backgroundColor:c.canvas},noticeText:{fontSize:11,color:c.muted,letterSpacing:.3}});
