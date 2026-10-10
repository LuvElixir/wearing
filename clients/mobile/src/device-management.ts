import {ApiError, Connection, connectionEndpoint, connectionHeaders} from './core';
import type {RemoteAccess} from './remote-device-model';

type Dict = Record<string, unknown>;
const object = (v: unknown): v is Dict => !!v && typeof v === 'object' && !Array.isArray(v);
const string = (v: unknown): v is string => typeof v === 'string';
const integer = (v: unknown): v is number => Number.isSafeInteger(v) && (v as number) >= 0;
const id = (v: unknown): v is string => string(v) && /^[a-zA-Z0-9][a-zA-Z0-9_-]{0,127}$/.test(v);
const revision = (v: unknown): v is string => string(v) && /^[a-f0-9]{64}$/.test(v);
const requestId = (v: unknown): v is string => string(v) && /^[a-f0-9]{32}$/.test(v);
const malformed = () => new ApiError('设备状态不完整，请重新检测后再操作。', 422);
function unique<T>(values: T[], key: (v: T) => string): T[] {if (new Set(values.map(key)).size !== values.length) throw malformed(); return values;}
function list(v: unknown): unknown[] {if (!Array.isArray(v)) throw malformed(); return v;}
export type DeviceResource = {resource_id: string; name: string; kind: 'computer' | 'android'; methods: string[]};
/** These are declared permissions, never proof an app is installed or a task succeeded. */
export function deviceCapabilityLabels(device: DeviceResource): string[] {
  const methods = new Set(device.methods), labels: string[] = [];
  if (methods.has('computer.observe') || methods.has('phone.mobile_take_screenshot') || methods.has('phone.mobile_list_elements_on_screen')) labels.push('查看屏幕');
  if (methods.has('computer.input')) labels.push('鼠标与键盘');
  if (methods.has('phone.mobile_click_on_screen_at_coordinates') || methods.has('phone.mobile_swipe_on_screen')) labels.push('点击与滑动');
  if (methods.has('phone.mobile_type_keys')) labels.push('键盘输入');
  if (methods.has('phone.mobile_list_apps')) labels.push('查看已安装应用');
  if (methods.has('phone.mobile_launch_app')) labels.push('打开应用');
  return labels;
}
export type DeviceOffer = {schema_version: 1; resources: DeviceResource[]};
export type InspectedResource = DeviceResource & {already_paired: boolean};
export type CloudDevice = DeviceResource & {connector_id: string; connected: boolean; online: boolean; paused: boolean;
  control_pending: boolean; control_generation: number; permission_revision: string; policy_revision: number; needs_review: boolean; last_seen_at: string | null};
export type DeviceReview = {command_id: string; resource_id: string; name: string; method: string; state: string; revision: string; can_review: boolean};
export type DeviceApproval = {approval_id: string; resource_id: string; action: Dict; reason: string; state: string; revision: string;
  can_decide: boolean; task_eligible: boolean; expires_at: string};
export type Connector = {installed: boolean; enrolled: boolean; active: boolean; phase: string; error: string};
export type LocalComputer = {installed: boolean | null; ready: boolean; accessibility: boolean; screen_recording: boolean; can_grant: boolean;
  held: boolean; error: string; connector: Connector};
export type LocalPhone = {state: string; connector: Connector; devices: {serial: string; state: string; model: string}[];
  resources: {resource_id: string; serial: string; name: string; enabled: boolean; online: boolean}[]};
export type PairingIntent = {request_id: string; offer: DeviceOffer; createdAt: number};
export type PermissionIntent = {request_id: string; resource_id: string; revision: string; mode: 'observe' | 'input'; delivery: 'connector'};
export type PermissionState = {state: 'pending' | 'applied' | 'expired' | 'superseded'; connected: boolean; policy_revision: number};

function resource(v: unknown): DeviceResource {
  if (!object(v) || !id(v.resource_id) || !string(v.name) || !v.name.trim() || v.name.length > 100 ||
    !['computer', 'android'].includes(String(v.kind)) || !Array.isArray(v.methods) || !v.methods.length || v.methods.length > 32 ||
    !v.methods.every(m => string(m) && /^[a-z][a-z0-9_.]{0,127}$/.test(m))) throw malformed();
  return {resource_id: v.resource_id, name: v.name, kind: v.kind as DeviceResource['kind'], methods: [...new Set(v.methods as string[])].sort()};
}
/** Input is a scope manifest only: never forward executable metadata or destinations. */
export function parseDeviceOffer(value: unknown): DeviceOffer {
  if (!object(value) || value.schema_version !== 1 || !Array.isArray(value.resources) || !value.resources.length || value.resources.length > 32) throw malformed();
  if (Object.keys(value).some(key => !['schema_version', 'resources'].includes(key))) throw new ApiError('请选择连接器导出的设备清单，不要使用配对凭据或其他文件。', 422);
  return {schema_version: 1, resources: unique(value.resources.map(resource), r => r.resource_id)};
}
const readMethods = new Set(['computer.status', 'computer.observe', 'phone.mobile_list_apps', 'phone.mobile_get_screen_size', 'phone.mobile_list_elements_on_screen', 'phone.mobile_take_screenshot']);
const phoneInputMethods = new Set(['phone.mobile_launch_app', 'phone.mobile_click_on_screen_at_coordinates', 'phone.mobile_press_button',
  'phone.mobile_swipe_on_screen', 'phone.mobile_type_keys', 'phone.mobile_set_text']);
export function selectedDeviceOffer(resources: InspectedResource[], selected: string[], input: string[]): DeviceOffer {
  const picked = new Set(selected), writable = new Set(input);
  const values = resources.filter(r => picked.has(r.resource_id));
  if (values.length !== picked.size || values.some(r => r.already_paired)) throw new ApiError('接入选择已变化，请重新读取设备清单。', 409);
  return parseDeviceOffer({schema_version: 1, resources: values.map(r => ({...resource(r), methods: r.methods.filter(m => writable.has(r.resource_id) || readMethods.has(m))}))});
}
export function parseCloudDevice(value: unknown): CloudDevice {
  const r = resource(value);
  if (!object(value) || !id(value.connector_id) || !revision(value.permission_revision) || !integer(value.control_generation) ||
    !integer(value.policy_revision) || value.policy_revision < 1 ||
    !['connected', 'online', 'paused', 'control_pending', 'needs_review'].every(k => typeof value[k] === 'boolean') ||
    (value.last_seen_at !== null && (!string(value.last_seen_at) || !Number.isFinite(Date.parse(value.last_seen_at))))) throw malformed();
  return {...r, connector_id: value.connector_id, permission_revision: value.permission_revision, policy_revision: value.policy_revision,
    control_generation: value.control_generation, connected: value.connected as boolean, online: value.online as boolean,
    paused: value.paused as boolean, control_pending: value.control_pending as boolean, needs_review: value.needs_review as boolean, last_seen_at: value.last_seen_at as string | null};
}
export function deviceStatus(d: CloudDevice): string {
  if (d.paused) return d.control_pending ? '暂停已送达云端，等待设备确认' : '已暂停';
  if (d.control_pending) return '等待设备确认恢复';
  if (d.needs_review) return '旧动作需要核对';
  if (d.online) {
    const writable = d.kind === 'computer' ? d.methods.includes('computer.input') : d.methods.some(method => phoneInputMethods.has(method));
    if (writable) return '在线 · 可以协助操作';
    return d.methods.every(method => readMethods.has(method)) ? '在线 · 仅观察' : '在线 · 权限待确认';
  }
  return d.connected ? '连接器在线 · 设备未就绪' : '设备离线';
}
/** A private-session pause can only be released by the existing explicit return flow. */
export function deviceControlAction(device: CloudDevice, access: RemoteAccess | null): 'pause' | 'resume' | 'return' | 'wait' | 'check' {
  if (device.control_pending) return 'wait';
  if (!device.paused) return 'pause';
  if (!access || access.resource_id !== device.resource_id) return 'check';
  if (access.supported && access.control_generation !== device.control_generation) return 'check';
  if (access.state === 'handoff_pending' || access.state === 'return_pending') return 'wait';
  if (access.state === 'paused' || access.state === 'human_private') return 'return';
  return access.state === 'agent_ready' || !access.supported ? 'resume' : 'check';
}
function connector(value: unknown): Connector {
  if (!object(value) || (value.installed !== undefined && typeof value.installed !== 'boolean') || !string(value.phase)) throw malformed();
  return {installed: value.installed === true, enrolled: value.enrolled === true, active: value.active === true,
    phase: value.phase, error: string(value.error) ? value.error : ''};
}
function computer(value: unknown): LocalComputer {
  if (!object(value) || ![true, false, null].includes(value.installed as boolean | null) || typeof value.ready !== 'boolean') throw malformed();
  return {installed: value.installed as boolean | null, ready: value.ready, accessibility: value.accessibility === true,
    screen_recording: value.screen_recording === true, can_grant: value.can_grant === true,
    held: object(value.control) && value.control.holder === 'human', error: string(value.error) ? value.error : '', connector: connector(value.connector)};
}
function phone(value: unknown): LocalPhone {
  if (!object(value) || !string(value.state)) throw malformed();
  return {state: value.state, connector: connector(value.connector), devices: unique(list(value.devices).map(v => {
    if (!object(v) || !string(v.serial) || !v.serial || !string(v.state)) throw malformed();
    return {serial: v.serial, state: v.state, model: string(v.model) ? v.model : 'Android 手机'};
  }), r => r.serial), resources: unique(list(value.resources).map(v => {
    if (!object(v) || !id(v.resource_id) || !string(v.serial) || !string(v.name) || typeof v.enabled !== 'boolean' || typeof v.online !== 'boolean') throw malformed();
    return {resource_id: v.resource_id, serial: v.serial, name: v.name, enabled: v.enabled, online: v.online};
  }), r => r.resource_id)};
}
function approval(v: unknown): DeviceApproval {
  if (!object(v) || !id(v.approval_id) || !id(v.resource_id) || !revision(v.revision) || !object(v.action) || !string(v.reason) ||
    !string(v.state) || typeof v.can_decide !== 'boolean' || typeof v.task_eligible !== 'boolean' || !string(v.expires_at) || !Number.isFinite(Date.parse(v.expires_at))) throw malformed();
  return {approval_id: v.approval_id, resource_id: v.resource_id, revision: v.revision, action: v.action, reason: v.reason,
    state: v.state, can_decide: v.can_decide, task_eligible: v.task_eligible, expires_at: v.expires_at};
}
export function approvalDescription(a: DeviceApproval): string {
  const value = (key: string) => string(a.action[key]) ? a.action[key] : '';
  const action = value('action');
  return [value('app'), ({click: '点击', set_value: '填写', type: '输入', key: '按键', scroll: '滚动'} as Record<string, string>)[action] || '操作',
    value('element_label'), value('value') || value('text') || value('keys') || value('direction')].filter(Boolean).join(' · ');
}
export function canDecide(a: DeviceApproval, now = Date.now()): boolean {return a.state === 'awaiting_user' && a.can_decide && Date.parse(a.expires_at) > now;}
function review(v: unknown): DeviceReview {
  if (!object(v) || !id(v.command_id) || !id(v.resource_id) || !revision(v.revision) || !string(v.name) || !string(v.method) ||
    !['unknown', 'device_error'].includes(String(v.state)) || typeof v.can_review !== 'boolean') throw malformed();
  return {command_id: v.command_id, resource_id: v.resource_id, revision: v.revision, name: v.name, method: v.method, state: String(v.state), can_review: v.can_review};
}

/** Revisions fence state changes. Network failures are never automatically retried. */
export class DeviceManagementApi {
  private token = '';
  private readonly connection: Connection;
  constructor(connection: Connection, private readonly fetcher: typeof fetch = fetch) {this.connection = {...connection,
    ...(connection.development ? {development: {...connection.development}} : {}), ...(connection.session ? {session: {...connection.session}} : {})};}
  private async request(path: string, body?: unknown, retry = true): Promise<unknown> {
    const mutation = body !== undefined;
    if (mutation && !this.token) await this.bootstrap();
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(), path.endsWith('/permissions') && path.startsWith('/api/computer') ? 45000 : 20000);
    try {
      const response = await this.fetcher(new URL(path, connectionEndpoint(this.connection)).toString(), {method: mutation ? 'POST' : 'GET', signal: controller.signal, redirect: 'error',
        headers: {...connectionHeaders(this.connection), 'X-Wearing-Identity': this.connection.identity,
          ...(mutation ? {'Content-Type': 'application/json', 'X-Wearing-Token': this.token} : {})}, ...(mutation ? {body: JSON.stringify(body)} : {})});
      if (response.status === 403 && mutation && retry) {await this.bootstrap(); return this.request(path, body, false);}
      const result: unknown = await response.json().catch(() => {throw new ApiError('没有收到完整回执，请先重新检测设备状态。', mutation ? 0 : 422);});
      if (!response.ok) throw new ApiError(object(result) && string(result.detail) ? result.detail : '设备操作未完成，请重新检测后再试。', response.status);
      return result;
    } catch (error) {
      if (error instanceof ApiError) throw error;
      throw new ApiError(mutation ? '未收到设备回执，请先重新检测状态，再决定是否重试。' : '暂时连不上设备服务，请检查连接后重试。');
    } finally {clearTimeout(timer);}
  }
  async bootstrap(): Promise<'local' | 'cloud'> {
    const v = await this.request('/api/bootstrap');
    if (!object(v) || v.version !== '0.2.0' || !['local', 'cloud'].includes(String(v.deployment)) || !string(v.token) || !v.token ||
      !Array.isArray(v.identities) || !v.identities.some(i => object(i) && i.id === this.connection.identity)) throw malformed();
    this.token = v.token; return v.deployment as 'local' | 'cloud';
  }
  async cloudDevices(): Promise<CloudDevice[]> {
    const v = await this.request('/api/devices'); if (!object(v)) throw malformed();
    return unique(list(v.devices).map(parseCloudDevice), d => d.resource_id);
  }
  async approvals(): Promise<DeviceApproval[]> {
    const v = await this.request('/api/devices/input-approvals'); if (!object(v)) throw malformed();
    return unique(list(v.approvals).map(approval), a => a.approval_id);
  }
  async reviews(): Promise<DeviceReview[]> {
    const v = await this.request('/api/devices/reviews'); if (!object(v)) throw malformed();
    return unique(list(v.reviews).map(review), r => r.command_id);
  }
  async control(d: CloudDevice, paused: boolean): Promise<void> {
    const v = await this.request('/api/devices/control', {resource_id: d.resource_id, paused, expected_generation: d.control_generation});
    if (!object(v) || v.resource_id !== d.resource_id || v.paused !== paused || v.generation !== d.control_generation + 1) throw malformed();
  }
  async inspect(offer: DeviceOffer): Promise<InspectedResource[]> {
    const sent = parseDeviceOffer(offer), v = await this.request('/api/devices/offer', sent);
    if (!object(v)) throw malformed();
    const rows = unique(list(v.resources).map(r => {if (!object(r) || typeof r.already_paired !== 'boolean') throw malformed(); return {...resource(r), already_paired: r.already_paired};}), r => r.resource_id);
    if (JSON.stringify(rows.map(resource)) !== JSON.stringify(sent.resources)) throw malformed();
    return rows;
  }
  async pair(intent: PairingIntent): Promise<void> {
    if (!requestId(intent.request_id)) throw malformed();
    const v = await this.request('/api/devices/pair', {request_id: intent.request_id, offer: parseDeviceOffer(intent.offer)});
    if (!object(v) || v.expires_in !== 600) throw malformed();
    this.validateBundle(v.bundle, intent.offer);
  }
  private validateBundle(v: unknown, offer: DeviceOffer): Dict {
    if (!object(v) || v.identity_id !== this.connection.identity || !id(v.tenant_id) || !string(v.code) || !/^[A-Za-z0-9_-]{43}$/.test(v.code) ||
      !string(v.connector_id) || !/^connector_[a-f0-9]{32}$/.test(v.connector_id) || v.pairing_generation !== 1 ||
      !integer(v.policy_revision) || v.policy_revision < 1 || !string(v.ca_pem) || !string(v.endpoint)) throw malformed();
    const url = new URL(v.endpoint);
    if (url.protocol !== 'https:' || url.username || url.password || !['', '/'].includes(url.pathname) || url.search || url.hash) throw malformed();
    const order = (rows: DeviceResource[]) => JSON.stringify([...rows].sort((a, b) => a.resource_id.localeCompare(b.resource_id)));
    if (order(list(v.resources).map(resource)) !== order(offer.resources.map(resource))) throw malformed();
    return v;
  }
  async pairingBytes(intent: PairingIntent): Promise<Uint8Array> {
    if (!requestId(intent.request_id)) throw malformed();
    const v = this.validateBundle(await this.request(`/api/devices/pair/${intent.request_id}/download`), intent.offer);
    return new TextEncoder().encode(JSON.stringify(v, null, 2));
  }
  async permission(intent: PermissionIntent): Promise<void> {
    if (!requestId(intent.request_id) || !id(intent.resource_id) || !revision(intent.revision) || !['observe', 'input'].includes(intent.mode) || intent.delivery !== 'connector') throw malformed();
    const v = await this.request('/api/devices/permissions', intent);
    if (!object(v) || v.request_id !== intent.request_id || v.expires_in !== 600 || !integer(v.policy_revision) || v.policy_revision < 2) throw malformed();
  }
  async permissionStatus(request: string): Promise<PermissionState> {
    if (!requestId(request)) throw malformed();
    const v = await this.request(`/api/devices/permissions/${request}`);
    if (!object(v) || !['pending', 'applied', 'expired', 'superseded'].includes(String(v.state)) || typeof v.connected !== 'boolean' || !integer(v.policy_revision)) throw malformed();
    return v as unknown as PermissionState;
  }
  async decide(a: DeviceApproval, choice: 'once' | 'task' | 'deny'): Promise<void> {
    if (!canDecide(a) || !['once', 'task', 'deny'].includes(choice) || (choice === 'task' && !a.task_eligible)) throw new ApiError('这一步已变化或过期，请刷新后再确认。', 409);
    const v = await this.request('/api/devices/input-approvals', {approval_id: a.approval_id, revision: a.revision, choice});
    if (!object(v) || v.approval_id !== a.approval_id || !string(v.state) || v.state === 'awaiting_user') throw malformed();
  }
  async review(r: DeviceReview, note: string, checked: boolean): Promise<void> {
    const text = note.trim();
    if (!r.can_review || !checked || text.length < 5 || text.length > 2000) throw new ApiError('请先查看设备，确认旧动作已结束，并写下至少五个字的实际结果。', 422);
    const v = await this.request('/api/devices/reviews', {command_id: r.command_id, revision: r.revision, note: text, checked});
    if (!object(v) || v.reviewed !== true || v.replayed !== false) throw malformed();
  }
  async refreshTools(): Promise<string> {
    const v = await this.request('/api/devices/refresh-tools', {}); if (!object(v) || !string(v.message)) throw malformed(); return v.message;
  }
  async localComputer(force = false) {return computer(await this.request(force ? '/api/computer/refresh' : '/api/computer', force ? {} : undefined));}
  async localPhone() {return phone(await this.request('/api/phone'));}
  async computerAction(action: 'prepare' | 'permissions' | 'bind' | 'pause' | 'resume'): Promise<void> {
    if (!['prepare', 'permissions', 'bind', 'pause', 'resume'].includes(action)) throw malformed();
    const v = await this.request(`/api/computer/${action}`, {});
    if (!object(v)) throw malformed();
    if (action === 'bind') computer(v);
    if (action === 'prepare') connector(v);
    if (action === 'permissions' && !string(v.message)) throw malformed();
    // Control receipts vary by platform. Always re-read the authoritative status in the panel.
  }
  async phoneAction(action: 'prepare' | 'bind' | 'pause' | 'resume', target?: string): Promise<void> {
    if (!['prepare', 'bind', 'pause', 'resume'].includes(action) || (action !== 'prepare' && (!target || target.length > 256))) throw malformed();
    const v = await this.request(`/api/phone/${action}`, action === 'prepare' ? {} : action === 'bind' ? {serial: target} : {resource_id: target});
    if (!object(v)) throw malformed();
    if (action === 'bind' || action === 'resume') phone(v);
    if (action === 'prepare') connector(v);
    if (action === 'pause' && !string(v.message)) throw malformed();
  }
}
