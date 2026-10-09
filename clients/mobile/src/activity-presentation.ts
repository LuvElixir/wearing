import type {ActivityItem, ActivitySnapshot} from './core';

export type ActivityPresentation = {
  kind: 'attention' | 'active' | 'waiting' | 'result' | 'failed' | 'stopped' | 'closed' | 'unknown';
  label: string;
  action: string;
  tone: 'attention' | 'active' | 'success' | 'muted' | 'danger';
  icon: 'alert' | 'clock' | 'file' | 'check' | 'stop' | 'archive' | 'help';
  group: 'attention' | 'active' | 'waiting' | 'history';
};

/** The API's results bucket includes failed and stopped runs; it is not success evidence. */
export function activityPresentation(item: Pick<ActivityItem, 'status' | 'bucket' | 'label'>): ActivityPresentation {
  if (item.status === 'failed') return {kind: 'failed', label: '执行未完成', action: '查看原因', tone: 'danger', icon: 'alert', group: 'history'};
  if (item.status === 'stopped') return {kind: 'stopped', label: item.label === '已撤回' ? '已撤回' : '已停止', action: '查看记录', tone: 'muted', icon: 'stop', group: 'history'};
  if (item.status === 'closed_by_user') return {kind: 'closed', label: '已结案', action: '查看记录', tone: 'muted', icon: 'archive', group: 'history'};
  if (item.status === 'verified') return {kind: 'result', label: '已核对', action: '查看结果', tone: 'success', icon: 'check', group: 'history'};
  if (item.status === 'completed_unverified' || item.status === 'completed') return {kind: 'result', label: '结果已返回', action: '查看结果', tone: 'muted', icon: 'file', group: 'history'};
  if (item.bucket === 'attention') return {kind: 'attention', label: item.label || '需要查看', action: '查看这一步', tone: 'attention', icon: 'alert', group: 'attention'};
  if (item.bucket === 'active') return {kind: 'active', label: item.label || '正在推进', action: '查看进展', tone: 'active', icon: 'clock', group: 'active'};
  if (item.bucket === 'waiting') return {kind: 'waiting', label: item.label || '已排队', action: '查看这条安排', tone: 'muted', icon: 'clock', group: 'waiting'};
  return {kind: 'unknown', label: '状态待确认', action: '查看记录', tone: 'muted', icon: 'help', group: 'history'};
}

const groupOrder = [
  {key: 'attention', title: '等你处理'},
  {key: 'active', title: '正在推进'},
  {key: 'waiting', title: '已排队'},
  {key: 'history', title: '历史记录'},
] as const;

export function groupActivityItems(items: readonly ActivityItem[]) {
  const newestFirst = [...items].sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at));
  return groupOrder.map(group => ({...group, items: newestFirst.filter(item => activityPresentation(item).group === group.key)})).filter(group => group.items.length > 0);
}

/** Counts cover the full collection, including items omitted from the latest page. */
export function activityEntrySummary(snapshot: ActivitySnapshot): string {
  const {counts} = snapshot;
  if (counts.attention) return `${counts.attention} 件事等你处理`;
  if (counts.active) return `${counts.active} 件事正在推进${counts.waiting ? ` · ${counts.waiting} 件已排队` : ''}`;
  if (counts.waiting) return `${counts.waiting} 件事已排队`;
  if (snapshot.unread) return `${snapshot.unread} 条新进展`;
  return snapshot.total ? '最近交给我的事' : '交代过的事，从这里回看';
}
