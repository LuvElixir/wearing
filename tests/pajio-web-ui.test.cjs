const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const read = path => fs.readFileSync(path, 'utf8');
const html = read('src/wearing/web/index.html');
const css = read('src/wearing/web/pajio.css');
const pajio = read('src/wearing/web/pajio.js');
const views = read('src/wearing/web/views.js');
const life = read('src/wearing/web/life.js');
const app = read('src/wearing/web/app.js');

test('web shell loads Pajio brand and theme assets beside the App host assets', () => {
  assert.match(html, /pajio\.css\?v=\d+/);
  assert.match(html, /pajio\.js\?v=\d+/);
  assert.ok(html.indexOf('now.css') < html.indexOf('pajio.css'));
  assert.ok(html.indexOf('mobile-host.css') < html.indexOf('pajio.css'));
  assert.ok(html.indexOf('now.js') < html.indexOf('pajio.js') && html.indexOf('pajio.js') < html.indexOf('views.js'));
  assert.match(html, /<title>Pajio · 你的个人 AI 助手<\/title>/);
  assert.match(html, /<html lang="zh-CN" data-app-theme="day">/);
  // 首帧主题脚本不得触碰 App 宿主的主题桥。
  const boot = html.slice(html.indexOf('首帧按已保存外观'), html.indexOf('})();', html.indexOf('首帧按已保存外观')));
  assert.match(boot, /get\('host'\)==='mobile'/);
  assert.match(html, /pajio-icon\.png\?v=\d+/);
});

test('five entries are chat, today, tasks, memory and me with the real today view', () => {
  const nav = html.slice(html.indexOf('class="app-nav"'), html.indexOf('</nav>'));
  const order = [...nav.matchAll(/data-life-view="([a-z]+)"/g)].map(m => m[1]);
  assert.deepEqual(order, ['chat', 'today', 'tasks', 'memory', 'me']);
  assert.match(nav, /data-pajio-chip/);
  assert.match(nav, /id="nav-goal-badge"/);
  assert.match(nav, /id="nav-today-day"/);
  assert.match(html, /id="open-search"/);
  assert.match(html, /id="nav-settings"/);
  assert.match(html, /id="compact-entry"/);
  // 旧入口保留在 DOM 中：共享 now.js 仍依赖它们绑定 App host 的跳转。
  assert.match(html, /id="open-review"/);
  assert.match(html, /id="open-tools"/);
  // today 是独立视图；补记表单仍在 capture。
  assert.match(life, /"today","capture","calendar","tasks","notes","trash","memory","me"/);
  assert.match(life, /life\.view==="memory"\|\|life\.view==="me"\|\|life\.view==="today"/);
  assert.match(life, /updateCompactEntry/);
  assert.match(life, /classList\.contains\("mobile-host"\)/);
});

test('every Pajio style rule is gated away from the App host', () => {
  const stripped = css.replace(/\/\*[\s\S]*?\*\//g, '');
  for (const match of stripped.matchAll(/([^{}]+)\{/g)) {
    const selector = match[1].trim();
    if (selector.startsWith('@')) continue;
    assert.match(selector + ' ', /:not\(\.mobile-host\)/, `rule must be web-only: ${selector.slice(0, 80)}`);
  }
  assert.doesNotMatch(css, /acceeb|ffe0bb|f4e7d9/i);
  assert.match(css, /\[data-app-theme="night"\]/);
  assert.match(css, /--page:#191D22/);
});

test('appearance and wardrobe persist with the shared keys and v2 shape', () => {
  assert.match(pajio, /classList\.contains\("mobile-host"\)\) return;/);
  assert.match(pajio, /appearance:v1/);
  assert.match(pajio, /wardrobe:v\$\{version\}:web:/);
  assert.match(pajio, /version === 1 && isOutfit\(legacy\.outfit\)/);
  assert.match(pajio, /mist-blue/);
  assert.equal((pajio.match(/id: "[a-z-]+", name:/g) || []).length, 8);
});

test('views.js stays inert inside the App host; conversation locate stays in-page, global search uses the real API', () => {
  assert.match(views, /classList\.contains\("mobile-host"\)\) return;/);
  const search = views.slice(views.indexOf('---------- 对话搜索'));
  // 当前对话内定位（findMatches）零请求；跨对象分区按 search-contract 调 GET /api/search。
  const locate = search.slice(search.indexOf('function findMatches'), search.indexOf('function openSearch'));
  assert.ok(!/api\(/.test(locate), 'conversation locate must be a pure in-page lookup');
  assert.ok(search.includes('api("/api/search?" + params)'), 'global cross-object search uses the real endpoint');
  assert.ok(search.includes('/api/search/messages/'), 'message deep link fetches owned message detail');
});

test('task pagination appends pages, dedupes and keeps totals separate', () => {
  const start = views.indexOf('function appendActivityPage'), end = views.indexOf('async function renderTasks');
  const fn = views.slice(start, end);
  const context = {};
  vm.runInNewContext(fn, context);
  const append = context.appendActivityPage;
  const item = id => ({task_id: id, bucket: 'results'});
  const base = {items: [item('a'), item('b')], checked_at: 't0', total: 9, unread: 2, counts: {attention: 0, active: 0, waiting: 0, results: 9}, filtered_total: 9, next_cursor: 'c1', has_more: true};
  const next = {items: [item('b'), item('c')], checked_at: 't1', total: 9, unread: 2, counts: {attention: 0, active: 0, waiting: 0, results: 9}, filtered_total: 9, next_cursor: null, has_more: false};
  const merged = append(base, next);
  assert.equal(merged.items.map(i => i.task_id).join(','), 'a,b,c');
  assert.equal(merged.items.length, 3);
  assert.equal(merged.filtered_total, 9);
  assert.equal(merged.next_cursor, null);
  assert.equal(merged.checked_at, 't1');
});

test('task pagination keeps content on 409 and separates loaded from total counts', () => {
  assert.match(views, /cause\?\.status === 409/);
  assert.match(views, /列表已有变化，点刷新后继续查看。当前内容仍会保留。/);
  assert.match(views, /已显示 \$\{snapshot\.items\.length\} \/ \$\{snapshot\.filtered_total \?\? snapshot\.total\} 项/);
  assert.match(views, /fetchActivity\(\{limit: 20, cursor: base\.next_cursor\}\)/);
  assert.match(views, /expired \? load\(\) : loadMore\(\)/);
});

test('chat replies still carry no per-reply verify or goal-source shortcuts', () => {
  const markup = app.slice(app.indexOf('function turnMarkup('), app.indexOf('async function loadConversation'));
  assert.ok(!markup.includes('data-goal-source'));
  assert.match(app, /\$\{turnActions\(t,true\)\}/);
  assert.match(markup, /note-saved/);
  assert.match(app, /· Pajio`;/);
});

test('account summary is real, not a membership card', () => {
  assert.match(views, /me-account/);
  assert.doesNotMatch(views, /me-card-backdrop|wardrobe:v2:premium|Pro ·/);
  assert.match(views, /模型服务 · /);
});

test('brand assets: original five-path wordmark; favicon uses the selected C icon', () => {
  // 新字标：原创 5 条填充 path，viewBox 12 20 574 240（比例 574/240）。
  assert.match(html, /viewBox="12 20 574 240"/);
  assert.equal((html.slice(html.indexOf('class="app-nav"') - 2000).match(/fill-rule="evenodd"/g) || []).length >= 5, true);
  assert.equal((pajio.match(/fill-rule="evenodd"/g) || []).length, 5);
  assert.match(pajio, /Math\.round\(width \* 240 \/ 574\)/);
  // 用户已选定图标 C（被窝里的睡衣小熊）：favicon/launcher 使用定稿 C 图标。
  assert.match(html, /pajio-icon\.png\?v=\d+/);
  assert.match(pajio, /const starPath =/);
  // 不采用 icon-studies 候选或旧 Nunito 字标；隐藏的历史 DOM 元素不属于本轮替换范围。
  const head = html.slice(0, html.indexOf('</head>'));
  assert.ok(!/icon-studies|bear-head|chat-portrait/.test(head));
  assert.ok(!/translate\(-5\.32 74\.76\)/.test(html + pajio));
});

test('follow-ups: navigation stays reachable, wordmark is filled and sized, copy delegates', () => {
  // 长对话中导航与唯一进展入口保持可达（粘性顶栏 + 进展入口钉在顶栏下方，不新增第二块）。
  assert.match(css, /html:not\(\.mobile-host\) \.app-header\{position:sticky;top:0/);
  assert.match(css, /#activity-return\{position:sticky;top:calc\(var\(--pajio-header\)/);
  // 通用 svg 规则（20×20、fill:none）不得压垮轮廓字标：显式尺寸与实心填充。
  assert.match(css, /\.pajio-wordmark\{fill:currentColor;stroke:none/);
  assert.match(css, /\.app-header \.pajio-wordmark\{width:72px;height:30px\}/);
  assert.match(css, /\.me-account-top \.pajio-wordmark\{width:76px;height:32px\}/);
  // 交代式入口文案对齐 App；鼓励闲聊的旧引导不再出现在活跃输入面。
  assert.match(html, /说一声，我来做…/);
  assert.match(app, /说一声，我来做。/);
  assert.ok(!/想到哪儿，聊到哪儿|我在，接着说|想做些什么/.test(html + app));
});

test('Hypit motion: idle only for the mist-blue top bear; wardrobe film only for the blue-cream pair', () => {
  // 素材已进入 web/motion。
  for (const file of ['mist-blue-idle.mp4', 'mist-blue-poster.jpg', 'blue-to-cream.mp4', 'cream-to-blue.mp4']) {
    assert.ok(fs.existsSync(`src/wearing/web/motion/${file}`), file);
  }
  // 顶部进展熊 idle：静音、内联、无控件、23 秒一次、隐藏/离屏/减少动态暂停并落 poster。
  assert.match(pajio, /mist-blue-idle\.mp4/);
  assert.match(pajio, /class="living-video" muted playsinline preload="auto" disablepictureinpicture/);
  const living = pajio.slice(pajio.indexOf('function mountLivingBear'));
  assert.ok(!/ controls/.test(living), 'no native controls on the idle video');
  assert.match(pajio, /23 \* 1000/);
  assert.match(pajio, /reducedMotion\.matches/);
  assert.match(pajio, /IntersectionObserver/);
  assert.match(pajio, /visibilitychange/);
  assert.match(pajio, /living-poster/);
  assert.ok(pajio.includes('video.classList.add("is-live")'), 'video reveals only after a real rendered frame');
  assert.match(pajio, /size \* 1\.92, height: size \* 1\.92, left: -size \* \.46, top: -size \* \.04/);
  assert.ok(!/poster\.hidden/.test(pajio), 'poster is a permanent base layer, never hidden');
  // 只有雾蓝使用动作；其它睡衣保持静图。
  assert.match(pajio, /if \(outfit === "mist-blue"\) livingChips\.set\(node, mountLivingBear\(node\)\)/);
  // 衣橱影片：仅蓝↔奶油双向，失败/结束提交目标静图，快速连点取消回退，不自动保存。
  assert.match(views, /filmPair = \(from, to\)/);
  assert.match(views, /blue-to-cream" : "cream-to-blue/);
  assert.match(views, /video\.addEventListener\("error", finish\)/);
  assert.match(views, /clearFilm\(\); commit\(pending\)/);
  assert.ok(!/autoSave|auto-save/.test(views));
});

test('CSP compliance: no inline style attributes in generated bear markup; sizes applied via CSSOM', () => {
  // 服务端 CSP style-src 'self' 会拦截标记里的 style 属性（真实桌面回归根因）。
  const markupFn = pajio.slice(pajio.indexOf('const bearMarkup'), pajio.indexOf('function hydrateBear'));
  assert.ok(!/style="/.test(markupFn), 'bearMarkup must not emit style attributes');
  assert.match(pajio, /span\.style\.width = size \+ "px"/);
  assert.match(pajio, /img\.style\.left = frame\.left \+ "px"/);
  assert.match(pajio, /MutationObserver\(hydrateSoon\)/);
  const livingFn = pajio.slice(pajio.indexOf('function mountLivingBear'), pajio.indexOf('const livingChips'));
  assert.ok(!/style="/.test(livingFn), 'living bear markup must not emit style attributes');
  assert.match(livingFn, /node\.style\.width = frame\.width/);
  // views.js 生成标记同样不带内联样式（含 swatch、衣橱入口、影片层）。
  assert.ok(!/style="/.test(views), 'views.js templates must not emit style attributes');
  assert.match(views, /el\.style\.background = el\.dataset\.swatch/);
});
