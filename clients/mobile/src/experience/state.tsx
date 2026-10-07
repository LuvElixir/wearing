/** Demonstration state only: no API, microphone, analytics or account side effects. */
import {createContext, useContext, useState, type ReactNode} from 'react';
import type {CalendarDate} from '../calendar';
export type Page = 'now'|'conversation'|'review'|'goals'|'goal'|'memory'|'companion'|'settings'|'result'|'brief'|'welcome';
export const pages: {id: Page;label:string;detail:string}[] = [
  {id:'now',label:'聊天',detail:'接着聊想法，也看看新的进展'},
  {id:'conversation',label:'对话与决定',detail:'说清意图，看结果，做决定'},
  {id:'review',label:'日历与笔记',detail:'回看与纠正已整理的内容'},
  {id:'goals',label:'任务与定时',detail:'知道事情推进到了哪里'},
  {id:'brief',label:'晚间简报',detail:'回顾安排与目标的新进展'},
  {id:'memory',label:'记忆',detail:'了解什么、从哪来、可纠正'},
  {id:'companion',label:'Wearing',detail:'一起经历的事情，有迹可循'},
  {id:'settings',label:'连接与设置',detail:'能力状态和安静时段'},
  {id:'welcome',label:'初次见面',detail:'先说一件想交给它的事'},
];
type MainPage = 'now'|'review'|'goals'|'memory'|'companion';
type Demo = {lastTab:MainPage;setLastTab:(p:MainPage)=>void;composerSuspended:boolean;setComposerSuspended:(b:boolean)=>void;inputEngaged:boolean;setInputEngaged:(b:boolean)=>void;text:string;setText:(s:string)=>void;appendDraft:(s:string)=>void;keyboard:boolean;setKeyboard:(b:boolean)=>void;messages:string[];send:(s:string)=>boolean;tab:'日历'|'笔记';setTab:(s:'日历'|'笔记')=>void;calendarDate:CalendarDate|null;setCalendarDate:(date:CalendarDate|null)=>void;goalTab:'任务'|'定时';setGoalTab:(s:'任务'|'定时')=>void;route:number;setRoute:(n:number)=>void;search:string;setSearch:(s:string)=>void;todoDone:boolean;setTodoDone:(b:boolean)=>void;note:string;setNote:(s:string)=>void;memory:string;setMemory:(s:string)=>void;goalPaused:boolean;setGoalPaused:(b:boolean)=>void;scheduled:boolean;setScheduled:(b:boolean)=>void;decision:'pending'|'accepted'|'declined';setDecision:(s:'pending'|'accepted'|'declined')=>void;quiet:boolean;setQuiet:(b:boolean)=>void;offline:boolean;setOffline:(b:boolean)=>void;reset:()=>void};
const Context=createContext<Demo|null>(null);
export function DemoProvider({children}:{children:ReactNode}) {
 const [lastTab,setLastTab]=useState<MainPage>('now');
 const [composerSuspended,setComposerSuspended]=useState(false),[inputEngaged,setInputEngaged]=useState(false);
 const [text,setText]=useState(''),[messages,setMessages]=useState<string[]>([]),[tab,setTab]=useState<Demo['tab']>('日历');
 const [keyboard,setKeyboard]=useState(false),[calendarDate,setCalendarDate]=useState<CalendarDate|null>(null),[goalTab,setGoalTab]=useState<Demo['goalTab']>('任务'),[route,setRoute]=useState(0),[search,setSearch]=useState('');
 const [todoDone,setTodoDone]=useState(false),[note,setNote]=useState('周末想去人少一点的地方。想慢慢走，也想留点时间发呆。');
 const [memory,setMemory]=useState('旅行时偏爱安静、松弛的安排。'),[goalPaused,setGoalPaused]=useState(false),[scheduled,setScheduled]=useState(true);
 const [decision,setDecision]=useState<Demo['decision']>('pending'),[quiet,setQuiet]=useState(true),[offline,setOffline]=useState(false);
 const appendDraft=(s:string)=>{if(s.trim()){setText(old=>old.trim()?old+'\n'+s.trim():s.trim());setKeyboard(true);}};
 const send=(s:string)=>{if(!s.trim()||offline)return false;setMessages(old=>[...old,s.trim()]);setText('');return true;};
 const reset=()=>{setText('');setMessages([]);setTab('日历');setKeyboard(false);setCalendarDate(null);setGoalTab('任务');setRoute(0);setSearch('');setTodoDone(false);setNote('周末想去人少一点的地方。想慢慢走，也想留点时间发呆。');setMemory('旅行时偏爱安静、松弛的安排。');setGoalPaused(false);setScheduled(true);setDecision('pending');setQuiet(true);setOffline(false);};
 return <Context.Provider value={{lastTab,setLastTab,composerSuspended,setComposerSuspended,inputEngaged,setInputEngaged,text,setText,appendDraft,keyboard,setKeyboard,messages,send,tab,setTab,calendarDate,setCalendarDate,goalTab,setGoalTab,route,setRoute,search,setSearch,todoDone,setTodoDone,note,setNote,memory,setMemory,goalPaused,setGoalPaused,scheduled,setScheduled,decision,setDecision,quiet,setQuiet,offline,setOffline,reset}}>{children}</Context.Provider>;
}
export function useDemo(){const value=useContext(Context);if(!value)throw Error('Missing demonstration provider');return value;}
