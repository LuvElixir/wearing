import {ApiError} from './core';

export const roleChoices = [
  {id:'employed',label:'在职工作'}, {id:'student',label:'在校学习'},
  {id:'independent',label:'自由职业'}, {id:'business',label:'经营自己的事业'}, {id:'caregiver',label:'照顾家庭'},
] as const;
export const appChoices = [
  {id:'wechat',label:'微信'}, {id:'douyin',label:'抖音'}, {id:'xiaohongshu',label:'小红书'},
  {id:'bilibili',label:'哔哩哔哩'}, {id:'feishu',label:'飞书'}, {id:'dingtalk',label:'钉钉'},
  {id:'wecom',label:'企业微信'}, {id:'mail',label:'邮箱'}, {id:'calendar',label:'系统日历'}, {id:'github',label:'GitHub'},
] as const;
export const interestChoices = [
  {id:'technology',label:'科技与 AI'}, {id:'career',label:'工作与成长'}, {id:'design',label:'设计与创作'},
  {id:'reading',label:'阅读'}, {id:'travel',label:'旅行'}, {id:'food',label:'美食'},
  {id:'fitness',label:'运动'}, {id:'culture',label:'文化与娱乐'}, {id:'finance',label:'商业与财经'},
] as const;
export const detailChoices = [{id:'brief',label:'简短结论'}, {id:'balanced',label:'适量解释'}, {id:'detailed',label:'展开说明'}] as const;
export const toneChoices = [{id:'natural',label:'自然'}, {id:'warm',label:'温和'}, {id:'direct',label:'直接'}] as const;
export type OnboardingValues = {
  roles: (typeof roleChoices[number]['id'])[];
  apps: (typeof appChoices[number]['id'])[];
  interests: (typeof interestChoices[number]['id'])[];
  reply_detail: typeof detailChoices[number]['id'] | null;
  reply_tone: typeof toneChoices[number]['id'] | null;
};
export type OnboardingStatus = 'draft' | 'completed' | 'skipped';
export type OnboardingSnapshot = {
  schema:1; identity_id:string; revision:number; status:OnboardingStatus; step:number;
  values:OnboardingValues; confirmed_at:string|null; updated_at:string|null;
  source:'self_selected'; recommend_onboarding:boolean;
};
export type OnboardingRequest = Pick<OnboardingSnapshot,'revision'|'status'|'step'|'values'> & {request_key:string};
export const emptyOnboarding = ():OnboardingValues => ({roles:[],apps:[],interests:[],reply_detail:null,reply_tone:null});
export const onboardingDraftKey = (scope:string) => `onboarding-draft:v1:${scope}`;
export const onboardingPendingKey = (scope:string) => `onboarding-request:v1:${scope}`;
export const onboardingIssue = (cause:unknown) => cause instanceof ApiError ? cause.message : '暂时没能保存。选择已留在这台手机，请重试。';
const object = (value:unknown):value is Record<string,unknown> => !!value && typeof value==='object' && !Array.isArray(value);
const bad = () => new ApiError('偏好回执无法核对，请重新读取。',422);
const integer = (value:unknown,min:number,max=Number.MAX_SAFE_INTEGER):value is number => Number.isSafeInteger(value) && (value as number)>=min && (value as number)<=max;
const stamp = (value:unknown) => value===null || typeof value==='string' && Number.isFinite(Date.parse(value));
function selections<T extends string>(value:unknown, choices:readonly {id:T}[],limit:number):T[] {
  if(!Array.isArray(value)||value.length>limit||new Set(value).size!==value.length||value.some(item=>!choices.some(choice=>choice.id===item)))throw bad();
  return choices.filter(choice=>value.includes(choice.id)).map(choice=>choice.id);
}
export function onboardingValues(value:unknown):OnboardingValues {
  if(!object(value)||value.reply_detail!==null&&!detailChoices.some(item=>item.id===value.reply_detail)||value.reply_tone!==null&&!toneChoices.some(item=>item.id===value.reply_tone))throw bad();
  return {roles:selections(value.roles,roleChoices,3),apps:selections(value.apps,appChoices,10),interests:selections(value.interests,interestChoices,5),reply_detail:value.reply_detail as OnboardingValues['reply_detail'],reply_tone:value.reply_tone as OnboardingValues['reply_tone']};
}
export function onboardingRequest(value:unknown):OnboardingRequest {
  if(!object(value)||!integer(value.revision,0)||!integer(value.step,0,5)||!['draft','completed','skipped'].includes(String(value.status))||typeof value.request_key!=='string'||!/^[A-Za-z0-9_-]{16,120}$/.test(value.request_key))throw bad();
  return {revision:value.revision,status:value.status as OnboardingStatus,step:value.step,values:onboardingValues(value.values),request_key:value.request_key};
}
export function onboardingSnapshot(value:unknown,identity:string):OnboardingSnapshot {
  if(!object(value)||value.schema!==1||value.identity_id!==identity||!integer(value.revision,0)||!integer(value.step,0,5)||!['draft','completed','skipped'].includes(String(value.status))||!stamp(value.confirmed_at)||!stamp(value.updated_at)||value.source!=='self_selected'||typeof value.recommend_onboarding!=='boolean'||value.status==='completed'&&value.confirmed_at===null)throw bad();
  return {...value,values:onboardingValues(value.values)} as OnboardingSnapshot;
}
export function toggleOnboardingSelection<T>(items:T[],item:T,limit:number):T[] {
  return items.includes(item)?items.filter(value=>value!==item):items.length<limit?[...items,item]:items;
}
export function onboardingSample(values:OnboardingValues):string {
  const start=values.reply_tone==='warm'?'我们可以一起':values.reply_tone==='direct'?'先':'可以先';
  return start+(values.reply_detail==='brief'?'确认时间，再整理要准备的材料。':values.reply_detail==='detailed'?'核对日程里的时间与地点，再把材料分成“已经有”和“还需要准备”两组，最后逐项检查是否遗漏。':'核对时间与地点，再整理要带的材料，最后检查是否遗漏。');
}
export function shouldEnterOnboarding(snapshot:OnboardingSnapshot,screen:string,authenticated:boolean):boolean {
  return authenticated && snapshot.recommend_onboarding && snapshot.status==='draft' && screen==='conversation';
}
