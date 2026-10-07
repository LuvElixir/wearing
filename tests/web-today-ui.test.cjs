const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');

const read = path => fs.readFileSync(path, 'utf8');
const html = read('src/wearing/web/index.html');
const css = read('src/wearing/web/today.css');
const views = read('src/wearing/web/views.js');
const life = read('src/wearing/web/life.js');
const app = read('src/wearing/web/app.js');

test('web shell loads the Today migration assets beside the App host assets', () => {
  assert.match(html, /today\.css\?v=\d+/);
  assert.match(html, /views\.js\?v=\d+/);
  // 共享页同时服务 App WebView：宿主样式与本轮网页主题都在，网页主题在宿主样式之后加载。
  assert.ok(html.indexOf('now.css') < html.indexOf('today.css'));
  assert.ok(html.indexOf('mobile-host.css') < html.indexOf('today.css'));
  assert.ok(html.indexOf('now.js') < html.indexOf('views.js'));
});

test('five entries are chat, today, tasks, memory and me in that order', () => {
  const nav = html.slice(html.indexOf('class="app-nav"'), html.indexOf('</nav>'));
  const order = [...nav.matchAll(/data-life-view="([a-z]+)"/g)].map(m => m[1]);
  assert.deepEqual(order, ['chat', 'capture', 'tasks', 'memory', 'me']);
  assert.match(nav, /id="nav-goal-badge"/);
  assert.match(nav, /id="nav-today-day"/);
  assert.match(html, /id="open-search"/);
  assert.match(html, /id="nav-settings"/);
  // 旧入口保留在 DOM 中：共享 now.js 仍依赖它们绑定 App host 的跳转。
  assert.match(html, /id="open-review"/);
  assert.match(html, /id="open-tools"/);
});

test('every Today style rule is gated away from the App host', () => {
  const stripped = css.replace(/\/\*[\s\S]*?\*\//g, '');
  for (const match of stripped.matchAll(/([^{}]+)\{/g)) {
    const selector = match[1].trim();
    if (selector.startsWith('@')) continue;
    assert.match(
      selector + ' ',
      /:not\(\.mobile-host\)/,
      `rule must be scoped to ordinary web: ${selector.slice(0, 80)}`,
    );
  }
  assert.match(css, /linear-gradient\(180deg,#acceeb 0%,#dfe8f1 49%,#f4e7d9 79%,#ffe0bb 100%\)/i);
});

test('today alias and the new views integrate through life.js only on the normal web branch', () => {
  assert.match(life, /if\(view==="today"\)view="capture"/);
  assert.match(life, /"memory","me"\]\.includes\(view\)/);
  assert.match(life, /window\.WearingViews\?\.render\(life\.view,el\("life-content"\)\)/);
});

test('views.js stays inert inside the App host and its search never calls APIs', () => {
  assert.match(views, /classList\.contains\("mobile-host"\)\) return;/);
  assert.match(views, /window\.WearingViews\s*=/);
  const search = views.slice(views.indexOf('---------- 对话搜索'));
  assert.ok(!/api\(/.test(search), 'search must be a pure in-page lookup');
});

test('chat replies no longer carry per-reply verify or goal-source shortcuts', () => {
  const actions = app.slice(app.indexOf('function turnActions('), app.indexOf('function turnMarkup('));
  assert.match(actions, /if\(verify&&turn\.status==="completed_unverified"\)/);
  assert.ok(!actions.includes('data-goal-source'), 'goal-source must not render in chat turns');
  const markup = app.slice(app.indexOf('function turnMarkup('), app.indexOf('async function loadConversation'));
  assert.ok(!markup.includes('data-goal-source'));
  assert.ok(!markup.includes('turnActions(turn,isGoal'));
  // 核对入口只保留在旧任务详情；回执与澄清表单原样保留。
  assert.match(app, /\$\{turnActions\(t,true\)\}/);
  assert.match(markup, /note-saved/);
  assert.ok(!app.includes('closest("[data-goal-source]")'));
});

test('unread goal updates surface on the tasks navigation badge', () => {
  assert.match(app, /\$\("nav-goal-badge"\)/);
  assert.match(app, /\.app-nav \[data-life-view="tasks"\]/);
});
