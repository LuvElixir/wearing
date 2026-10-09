const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function host(search) {
  const calls = [], window = {};
  const classes = new Set(), events = new Map(), viewport = {};
  const document = {
    documentElement: {classList: {add: x => {classes.add(x); calls.push(x);}, contains: x => classes.has(x)}},
    activeElement: {blur: () => calls.push('blur')},
    querySelector: selector => selector === 'meta[name="viewport"]' ? {setAttribute: (key, value) => {viewport[key] = value;}} : null,
    addEventListener: (name, callback) => events.set(name, callback),
    querySelectorAll: selector => {
      assert.equal(selector, 'video');
      return [{pause: () => calls.push('pause-first')}, {pause: () => calls.push('pause-second')}];
    },
    dispatchEvent: event => calls.push(event.type),
  };
  vm.runInNewContext(fs.readFileSync('src/wearing/web/mobile-host.js', 'utf8'),
    {window, document, location: {search}, URLSearchParams, Event});
  return {window, calls, document, events, viewport};
}

test('ordinary web pages never receive native host presentation state', () => {
  const {window, calls} = host('?identity=daily');
  assert.equal(window.WearingHost, undefined);
  assert.deepEqual(calls, []);
});

test('leaving an embedded conversation pauses media and dismisses keyboard once', () => {
  const {window, calls} = host('?host=mobile');
  const state = window.WearingHost;
  assert.equal(state.hidden, false);
  state.setActive(false);
  state.setActive(false);
  assert.equal(state.hidden, true);
  assert.deepEqual(calls, ['mobile-host', 'pause-first', 'pause-second', 'blur', 'wearing-host-visibility']);
  // Returning emits one event; individual consumers decide whether to resume.
  // A presentation signal must not unconditionally autoplay every video.
  state.setActive(true);
  state.setActive(true);
  assert.equal(state.hidden, false);
  assert.equal(calls.filter(x => x === 'wearing-host-visibility').length, 2);
  assert.equal(calls.filter(x => x === 'pause-first').length, 1);
});

test('background transition works before an input is focused', () => {
  const {window, calls, document} = host('?host=mobile');
  document.activeElement = null;
  window.WearingHost.setActive(false);
  assert.equal(window.WearingHost.hidden, true);
  assert.equal(calls.at(-1), 'wearing-host-visibility');
});

test('only App embedding disables layout zoom; ordinary browser viewport remains untouched', () => {
  const browser = host('?identity=daily');
  assert.deepEqual(browser.viewport, {}); assert.equal(browser.events.size, 0);
  const app = host('?host=mobile&composer=native');
  assert.match(app.viewport.content, /maximum-scale=1,user-scalable=no/);
  let prevented = 0;
  const event = {cancelable: true, preventDefault() {prevented++;}};
  app.events.get('gesturestart')(event);
  app.events.get('gesturechange')(event);
  app.events.get('dblclick')(event);
  app.events.get('touchmove')({...event, touches: [{}, {}]});
  assert.equal(prevented, 4);
  app.events.get('touchmove')({...event, touches: [{}]});
  assert.equal(prevented, 4, 'one finger scrolling and text selection are not blocked');
});

function conversationHost(records = []) {
  const events = new Map(), nodes = new Map(), observers = [], activity = [];
  function node(tag = 'div', classes = '') {
    const names = new Set(classes.split(' ').filter(Boolean)), handlers = new Map();
    const result = {tag, children: [], dataset: {}, attributes: {}, hidden: false, value: '', textContent: '',
      classList: {add: (...xs) => xs.forEach(x => names.add(x)), remove: (...xs) => xs.forEach(x => names.delete(x)), contains: x => names.has(x)},
      setAttribute(key, value) {this.attributes[key] = value;},
      append(...children) {this.children.push(...children);},
      addEventListener(key, fn) {handlers.set(key, fn);},
      fire(key, event = {}) {handlers.get(key)?.(event);},
      focus() {this.focused = true;}, blur() {this.focused = false;},
      scrollIntoView(options) {this.scrolled = options;},
      querySelectorAll(selector) {
        const selectors = selector.split(',').map(x => x.trim().slice(1));
        return this.children.flatMap(child => [...(selectors.some(x => child.classList.contains(x)) ? [child] : []), ...child.querySelectorAll(selector)]);
      },
      querySelector(selector) {return this.querySelectorAll(selector)[0] || null;},
    };
    Object.defineProperty(result, 'className', {set(value) {names.clear(); value.split(' ').filter(Boolean).forEach(x => names.add(x));}});
    return result;
  }
  const messages = node(), body = node(), root = node(), viewport = node();
  nodes.set('messages', messages); body.append(messages);
  const document = {documentElement: root, body, activeElement: null,
    querySelector: selector => selector.startsWith('meta') ? viewport : null,
    querySelectorAll: () => [], getElementById: id => nodes.get(id), createElement: node,
    addEventListener(name, fn) {const list = events.get(name) || []; list.push(fn); events.set(name, list);},
    dispatchEvent(event) {for (const fn of events.get(event.type) || []) fn(event);},
  };
  const context = {document, location: {search: '?host=mobile&composer=native'}, URLSearchParams, Event,
    window: {matchMedia: () => ({matches: false}), WearingActivity: {openTask: async id => activity.push(id)}},
    state: {messages: records}, notice() {}, MutationObserver: class {constructor(fn) {observers.push(fn);} observe() {}},
  };
  vm.runInNewContext(fs.readFileSync('src/wearing/web/mobile-host.js', 'utf8'), context);
  function paint(next = records) {
    context.state.messages = next; messages.children = [];
    for (const message of next) {
      const turn = node('section'); nodes.set(`${message.kind === 'goal_step' ? 'goal-turn' : 'task-turn'}-${message.turn.id}`, turn);
      for (const [klass, text] of [['user-bubble', message.content], ['assistant-copy', message.turn.output]]) {
        if (text) {const bubble = node('div', klass); bubble.textContent = text; turn.append(bubble);}
      }
      messages.append(turn);
    }
    observers.forEach(fn => fn());
  }
  paint(); document.dispatchEvent(new Event('DOMContentLoaded'));
  return {context, document, body, messages, paint, activity, nodes};
}

test('event chips come only from structured task receipts and preserve direct task navigation', async () => {
  const records = [
    {content: '帮我整理', turn: {id: 'task-a', status: 'running'}},
    {content: '你好', turn: {id: 'task-b', status: 'completed_unverified', output: '记忆已更新，任务已经开始'}},
    {kind: 'schedule_run', content: '简报', turn: {id: 'task-c', status: 'completed_unverified', output: '整理好了'}},
    {content: '攻击', turn: {id: '<script>', status: 'running'}},
  ];
  const h = conversationHost(records), chips = h.messages.querySelectorAll('.host-event-chip');
  assert.equal(chips.length, 2);
  assert.equal(chips[0].children[1].textContent, '任务进行中');
  assert.equal(chips[1].children[1].textContent, '定时任务有新结果');
  assert.equal(h.nodes.get('task-turn-task-b').querySelector('.host-event-chip'), null, 'assistant prose cannot fabricate memory or task state');
  chips[0].fire('click'); await Promise.resolve(); assert.deepEqual(h.activity, ['task-a']);
  h.paint([{content: '帮我整理', turn: {id: 'task-a', status: 'completed_unverified', output: '已回复'}}]);
  assert.equal(h.messages.querySelectorAll('.host-event-chip').length, 0, 'completed ordinary replies do not leave a stale running chip');
});

test('search inspects loaded user/assistant text literally, navigates and clears on exit', () => {
  const h = conversationHost([
    {content: '<script> 今天', turn: {id: 'task-a', status: 'completed_unverified', output: '今天的安排'}},
    {content: '另外一件事', turn: {id: 'task-b', status: 'completed_unverified', output: '明天再说'}},
  ]);
  h.context.window.WearingHost.openSearch();
  const panel = h.body.children.at(-1), input = panel.children[0].children[0], navigation = panel.children[1];
  input.value = '今天'; input.fire('input');
  assert.equal(h.messages.querySelectorAll('.host-search-match').length, 2);
  assert.equal(navigation.children[0].textContent, '1 / 2');
  navigation.children[2].fire('click'); assert.equal(navigation.children[0].textContent, '2 / 2');
  input.value = '<script>'; input.fire('input'); assert.equal(h.messages.querySelectorAll('.host-search-match').length, 1);
  input.value = '未出现'; input.fire('input'); assert.equal(navigation.children[0].textContent, '没有找到');
  assert.equal(navigation.children[2].disabled, true);
  h.context.window.WearingHost.closeSearch(); assert.equal(panel.hidden, true);
  assert.equal(h.messages.querySelectorAll('.host-search-match').length, 0);
});

test('mobile styling removes duplicate and opaque controls without hiding approvals or accessibility text scaling', () => {
  const css = fs.readFileSync('src/wearing/web/mobile-host.css', 'utf8');
  assert.match(css, /\.native-composer-host #activity-return/);
  assert.match(css, /\.native-composer-host #messages \[data-verify\]/);
  assert.match(css, /\.native-composer-host #messages \[data-goal-source\]/);
  assert.doesNotMatch(css, /(?:\.approval|\.decision-card|\[data-desktop-decision\]|\[data-action\])\s*\{[^}]*display\s*:\s*none/);
  assert.doesNotMatch(css, /text-size-adjust\s*:\s*none/);
  assert.match(css, /\.native-composer-host input,\.native-composer-host textarea,\.native-composer-host select\{font-size:calc\(16px \* var\(--app-font-scale,1\)\)\}/);
  assert.match(css, /\.host-event-chip\{[^}]*min-height:44px/);
  assert.match(css, /\.host-search-navigation button\{min-height:44px/);
  assert.doesNotMatch(css, /\bzoom\s*:/);
});
