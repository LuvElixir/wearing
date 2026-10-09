import {useEffect, useMemo, useRef, useState} from 'react';
import {ActivityIndicator, StyleSheet, Text, View} from 'react-native';
import * as Crypto from 'expo-crypto';
import {Connection, scopeOf} from './core';
import {DecisionClient, decisionLabel, PendingDecision} from './pending-decisions';
import {storage} from './storage';
import {serviceFetch} from './transport';
import {AppColors, useAppTheme, useThemedStyles} from './app-theme';
import {PrimaryButton, TactilePressable} from './experience/primitives';

function Decisions({connection,onTask}: {connection:Connection;onTask:(id:string)=>void}) {
  const {colors:c}=useAppTheme(), s=useThemedStyles(styles);
  const client=useMemo(()=>new DecisionClient(connection,storage,()=>Crypto.randomUUID(),serviceFetch),[connection]);
  const [items,setItems]=useState<PendingDecision[]>([]),[loading,setLoading]=useState(true),[busy,setBusy]=useState(''),[error,setError]=useState('');
  const session=useRef({live:true,busy:false});
  useEffect(()=>{const turn={live:true,busy:false};session.current=turn;void client.list().then(rows=>{if(turn.live)setItems(rows);}).catch(()=>{if(turn.live)setError('暂时读不到待确认事项，请重试。');}).finally(()=>{if(turn.live)setLoading(false);});return()=>{turn.live=false;};},[client]);
  async function refresh() {const turn=session.current;if(turn.busy)return;turn.busy=true;setLoading(true);setError('');try{const rows=await client.list();if(turn.live)setItems(rows);}catch(reason){if(turn.live)setError(reason instanceof Error?reason.message:'暂时读不到待确认事项。');}finally{turn.busy=false;if(turn.live)setLoading(false);}}
  async function resume(row:PendingDecision) {const turn=session.current;if(turn.busy)return;turn.busy=true;setBusy(row.id);setError('');try{const receipt=await client.resume(row);if(turn.live)onTask(receipt.taskId);}catch(reason){if(turn.live)setError(reason instanceof Error?reason.message:'暂时无法继续，请重试。');}finally{turn.busy=false;if(turn.live)setBusy('');}}
  const visible=items.filter(item=>['pending','sending','unknown','needs_recheck','recovering','executing','execution_unknown'].includes(item.state));
  if(!loading&&!error&&!visible.length)return null;
  return <View style={s.group}><View style={s.heading}><Text style={s.title}>等你决定</Text><TactilePressable accessibilityLabel="刷新待确认事项" disabled={loading||!!busy} onPress={()=>{void refresh();}} style={s.refresh}><Text style={s.link}>刷新</Text></TactilePressable></View>
    {loading?<ActivityIndicator color={c.accent}/>:null}{error?<Text accessibilityLiveRegion="polite" style={s.error}>{error}</Text>:null}
    {visible.map(row=><View key={row.id} style={s.card}><Text style={s.caption}>{decisionLabel(row)}</Text><Text style={s.title}>{row.card.title}</Text><Text style={s.copy}>{row.card.action}</Text><Text style={s.copy}>{row.card.impact}</Text>
      {row.can_resume?<><Text style={s.copy}>原确认已结束。继续后会先检查最新情况，需要执行时会再次请你确认。</Text><PrimaryButton label={busy===row.id?'正在继续…':'重新核对并继续'} disabled={loading||!!busy} onPress={()=>{void resume(row);}}/></>:null}
      <PrimaryButton label={row.recovery_task_id?'查看继续处理的进展':'查看原任务'} tone="quiet" disabled={!!busy} onPress={()=>onTask(row.recovery_task_id||row.task_id)}/>
    </View>)}
  </View>;
}
export default function PendingDecisionsPanel(props:{connection:Connection;onTask:(id:string)=>void}) {return <Decisions key={scopeOf(props.connection)+'|'+(props.connection.session?.credentialId||props.connection.development?.expiresAt||'')} {...props}/>;}
const styles=(c:AppColors)=>StyleSheet.create({group:{gap:12},heading:{flexDirection:'row',alignItems:'center',justifyContent:'space-between'},title:{fontSize:17,fontWeight:'600',color:c.ink},refresh:{padding:12},link:{fontSize:13,color:c.accent},card:{backgroundColor:c.surface,borderColor:c.line,borderWidth:1,borderRadius:22,padding:20,gap:12},caption:{fontSize:12,color:c.accent},copy:{fontSize:14,lineHeight:23,color:c.muted},error:{fontSize:14,lineHeight:22,color:c.danger}});
