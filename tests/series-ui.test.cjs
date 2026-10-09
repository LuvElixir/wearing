const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');

const read=path=>fs.readFileSync(path,'utf8');
const html=read('src/wearing/web/index.html');
const css=read('src/wearing/web/pajio.css');
const series=read('src/wearing/web/series.js');
const reminders=read('src/wearing/web/reminders.js');
const life=read('src/wearing/web/life.js');
const briefings=read('src/wearing/web/briefings.js');

test('all touched web modules compile as scripts (regex tests cannot catch syntax errors)',()=>{
  for(const [name,source] of [['series',series],['reminders',reminders],['life',life],['briefings',briefings]])
    assert.doesNotThrow(()=>new vm.Script(source,{filename:name+'.js'}),`${name}.js must parse`);
});

test('calendar-series shell: panel dialog, calendar entry button, editor reminder host, script order',()=>{
  assert.match(html,/<dialog id="series-panel"/);
  assert.match(html,/id="series-note"/);
  assert.match(html,/id="series-body"/);
  assert.match(html,/id="life-series-add"[^>]*data-series-manage/);
  assert.match(html,/id="life-edit-reminder"/);
  assert.ok(html.indexOf('reminders.js')<html.indexOf('series.js'));
  assert.ok(html.indexOf('series.js')<html.indexOf('life.js?v='));
  // 新样式全部按 App 宿主门控。
  for(const match of css.replace(/\/\*[\s\S]*?\*\//g,'').matchAll(/([^{}]+)\{/g)){
    const selector=match[1].trim();
    if(selector.startsWith('@'))continue;
    if(/se-grid|se-week|reminder-box|series-agenda-section/.test(selector))
      assert.match(selector+' ',/:not\(\.mobile-host\)/,`rule must be web-only: ${selector.slice(0,60)}`);
  }
});

test('series module is inert in the App host and speaks only the single calendar-series entry point',()=>{
  assert.match(series,/classList\.contains\("mobile-host"\)\) return;/);
  assert.ok(!/api\("(?!\/api\/calendar-series)/.test(series),'only /api/calendar-series requests');
  for(const action of ['list','get','query','create','update','archive','restore','override','cancel','reset'])
    assert.ok(series.includes(`action:"${action}"`),`missing action ${action}`);
  // SeriesCommand 闭集：多余字段 422，动作只带各自字段。
  assert.match(series,/action:"update",series_id:panel\.series\.id,revision:panel\.series\.revision,request_key:newKey\(\),draft/);
  assert.match(series,/action:"override",series_id:panel\.series\.id,revision:panel\.series\.revision,request_key:newKey\(\),occurrence_key:panel\.occurrence\.key,template/);
  assert.match(series,/action:"cancel",series_id:panel\.series\.id,revision:panel\.series\.revision,request_key:newKey\(\),occurrence_key:panel\.occurrence\.key\}/);
  assert.match(series,/action:"reset",series_id:seriesReset,revision:series\.revision,request_key:newKey\(\),occurrence_key:seriesKey/);
  assert.match(series,/action:"create",request_key:newKey\(\),draft/);
  // 派生实例按 recurrence_<32hex>_<YYYYMMDD> 转入系列面板，不交给普通记录编辑。
  assert.match(series,/recurrence_\(\[a-f0-9\]\{32\}\)_\(\\d\{8\}\)/);
  // 查询结果只合并展示；月视图事件不可拖拽改期（普通记录路径）。
  assert.match(series,/action:"query",start,end,timezone:deviceTz\(\)/);
  assert.match(series,/editable:false/);
});

test('series mutations persist the request key before HTTP and replay the same command on unknown results',()=>{
  assert.match(series,/writeJournal\(slot,\{identity:state\.identityId,command\}\);/);
  assert.match(series,/const receipt=await post\(command\);/);
  assert.match(series,/pajio-series-pending:v1/);
  assert.match(series,/window\.WearingStore\.get\(journalName\(slot\)\)/);
  assert.match(series,/clearJournal\(slot\);/);
  assert.match(series,/上一次修改仍未确认，稍后会继续用同一请求取回。/);
  assert.match(series,/上一次修改没有保存：/);
});

test('series request ledger is multi-slot: same intent reuses the original key, each entry resumes its own slots',()=>{
  // 槽名 = 动作:系列|new:次日期；同意图（忽略 request_key 的指纹相同）沿用原编号重放。
  assert.match(series,/const slotOf = command => `\$\{command\.action\}:\$\{command\.series_id\|\|"new"\}:\$\{command\.occurrence_key\|\|""\}`;/);
  assert.match(series,/const journalName = slot => `pajio-series-pending:v1:\$\{state\.identityId\}:\$\{slot\}`;/);
  assert.match(series,/const fingerprint = command => JSON\.stringify\(\{\.\.\.command,request_key:undefined\}\)/);
  assert.match(series,/command=pending\.command;  \/\/ 同意图沿用原请求编号：失败\/未知重放完全相同请求/);
  assert.match(series,/try\{await post\(pending\.command\);\}catch\{\}  \/\/ 换内容前尽力结算同槽旧账/);
  // 三个入口各自恢复自己的槽：管理（create）、编辑器（update/archive/restore）、实例（override/cancel/reset）。
  assert.match(series,/resumePending\(\["create"\]\)/);
  assert.match(series,/resumePending\(\[`update:\$\{seriesId\}`,`archive:\$\{seriesId\}`,`restore:\$\{seriesId\}`\]\)/);
  assert.match(series,/resumePending\(\[`override:\$\{"series_\"\+match\[1\]\}:\$\{key\}`,`cancel:\$\{"series_\"\+match\[1\]\}:\$\{key\}`,`reset:\$\{"series_\"\+match\[1\]\}:\$\{key\}`\]\)/);
  // 旧单槽键一次性迁移。
  assert.match(series,/旧单槽键（第十九轮之前）一次性迁移：尽力结算后移除。/);
  assert.doesNotMatch(series,/ponytail: 单槽请求账本/);
});

test('series 409 keeps the editor input and offers the documented dual choice',()=>{
  assert.match(series,/你的输入仍保留，可先读取最新版本再核对。/);
  assert.match(series,/读取最新版本/);
  assert.match(series,/保留我的输入/);
  assert.match(series,/采用最新内容/);
  assert.match(series,/已保留你的输入并换用最新修订号，核对后再保存。/);
  assert.match(series,/新规则会遗漏已有例外|保留这些例外/);
});

test('occurrence view separates this-once from whole-series and keeps cancelled states honest',()=>{
  assert.match(series,/修改仅这一次/);
  assert.match(series,/取消这一次/);
  assert.match(series,/恢复这一次的原规则|恢复原规则/);
  assert.match(series,/查看整个系列/);
  assert.match(series,/已单独取消/);
  assert.match(series,/这一次的提醒/);
  assert.match(series,/修改已保存，但回读失败/);
  assert.match(series,/重新读取/);
  // 无模板字符串内联样式或内联事件（CSP）。
  for(const source of [series,reminders])assert.doesNotMatch(source,/onclick=|style="/);
});

test('record reminders use the closed target set, dual CAS body, and honest delivery wording',()=>{
  assert.match(reminders,/classList\.contains\("mobile-host"\)\) return;/);
  assert.match(reminders,/life_\[a-f0-9\]\{32\}\|recurrence_\[a-f0-9\]\{32\}_\\d\{8\}/);
  assert.ok(!/api\("(?!\/api\/record-reminders\/)/.test(reminders),'only record-reminders requests');
  assert.match(reminders,/revision:Number\(host\.dataset\.rmRevision\|\|0\),record_revision:recordRevision,/);
  assert.match(reminders,/advance_minutes:Number\(host\.querySelector\("\.rm-advance"\)\.value\)/);
  assert.match(reminders,/request_key:window\.WearingIds\.uuid\(\)/);
  assert.match(reminders,/pajio-reminder-request:v1/);
  assert.match(reminders,/writeJournal\(target,body\);/);
  assert.match(reminders,/将用同一请求取回，不会重复设置。/);
  assert.match(reminders,/不代表手机已展示/);
  assert.match(reminders,/已重新读取最新设置，请核对后再保存。/);
  // 不可开提醒的边界按合同文案如实说明。
  assert.match(reminders,/已完成的记录不再提醒/);
  assert.match(reminders,/全天日程没有具体开始时间，不能提醒/);
  assert.match(reminders,/先保存\$\{ctx\.label\|\|""\}的具体时间，才能开启提醒。/);
  for(const [minutes] of [[0],[5],[15],[30],[60],[1440]])assert.ok(reminders.includes(`[${minutes},`));
});

test('life archive/restore carries a persisted request key only for lifecycle actions',()=>{
  const start=life.indexOf('async function change('),end=life.indexOf('function savedFeedback(');
  const fn=life.slice(start,end);
  assert.match(fn,/journalKey=action==="edit"\?null:/);
  assert.match(fn,/window\.WearingStore\.set\(journalKey,request_key\)/);
  assert.match(fn,/body\.request_key=request_key;/);
  assert.match(fn,/window\.WearingStore\.remove\(journalKey\);/);
  assert.match(fn,/pajio-life-action:v1/);
  // 移除先说明范围并二次确认；恢复同样确认。
  assert.match(life,/确认移除？会进入最近移除，可恢复/);
  assert.match(life,/确认恢复？回到原列表/);
  // 编辑器挂提醒、身份切换清系列面板、日历实例路由与查询窗口。
  assert.match(life,/renderReminder\(\)/);
  assert.match(life,/window\.WearingSeries\?\.reset\?\.\(\)/);
  assert.match(life,/window\.WearingSeries\?\.openInstance\?\.\(info\.event\.id\)/);
  assert.match(life,/window\.WearingSeries\?\.decorate\?\.\(dayKey\(info\.view\.currentStart\),dayKey\(info\.view\.currentEnd\)\)/);
  assert.match(life,/window\.WearingSeries\?\.decorate\?\.\(dayKey\(days\[0\]\),dayKey\(windowEnd\)\)/);
  assert.match(life,/el\("life-series-add"\)\.hidden=view!=="calendar"/);
  assert.match(life,/calendar:\(\)=>life\.calendar/);
});

test('briefing automation panel saves the closed field set with persisted request key',()=>{
  assert.match(briefings,/brief-automation/);
  assert.match(briefings,/api\("\/api\/briefing-automation"\)/);
  assert.match(briefings,/pajio-brief-auto-request:v1/);
  assert.match(briefings,/writeAutoJournal\(body\);/);
  assert.match(briefings,/preferences_revision: prefRevision/);
  assert.match(briefings,/grace_minutes: Number\(form\.querySelector\("\.ba-grace"\)\.value\)/);
  assert.match(briefings,/自动安排使用偏好版本/);
  assert.match(briefings,/需要重新保存|请重新保存自动安排/);
  assert.match(briefings,/最近回执 · 最多 7 条/);
  assert.match(briefings,/slice\(0, 7\)/);
  assert.match(briefings,/保存不会立即生成简报/);
  assert.match(briefings,/上一次自动安排保存已确认。/);
  assert.match(briefings,/\[30, 60, 120\]\.map/);
});
