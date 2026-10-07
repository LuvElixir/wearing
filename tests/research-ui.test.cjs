const {test} = require('node:test');
const assert = require('node:assert/strict');
const {researchMarkup} = require('../src/wearing/web/research.js');
test('sources are escaped, safe, timestamped and collapsed', () => {
  const html = researchMarkup({items: [{status:'read', title:'<img onerror=x>', url:'https://example.org', observed_at:'2026-10-05T01:00:00Z',cached:true}, {status:'found',title:'bad',url:'javascript:alert(1)'}]});
  assert.ok(html.includes('&lt;img onerror=x&gt;'));
  assert.ok(html.includes('noopener noreferrer'));
  assert.ok(html.includes('已读取 · 缓存'));
  assert.ok(!html.includes('javascript:'));
  assert.ok(!html.includes(' open'));
});
test('empty receipts are quiet; lost receipts explain missing evidence', () => {
  assert.equal(researchMarkup({items:[]}), '');
  assert.ok(researchMarkup({items:[],unavailable:true}).includes('当前列表可能不完整'));
});
test('read sources appear once before search-only leads', () => {
  const html = researchMarkup({items:[{status:'found',title:'Found',url:'https://a.example'}, {status:'found',title:'Original title',url:'https://b.example'}, {status:'read',title:'Less descriptive title',url:'https://b.example'}]});
  assert.equal((html.match(/href="https:\/\/b.example/g)||[]).length, 1);
  assert.ok(html.indexOf('Original title') < html.indexOf('Found'));
});
test('app observations retain separate reads, escape text and stay collapsed', () => {
  const base={kind:'app',status:'observed',package:'app',resource_id:'phone_1',title:'抖音',observed_at:'2026-10-06T01:00:00Z'};
  const html=researchMarkup({items:[{...base,observation_id:'a',lines:['<img src=x onerror=alert(1)>','评论内容']},
    {...base,observation_id:'b',lines:['新页面'],truncated:true}]},'task-a');
  assert.ok(html.includes('1 个 App') && html.includes('2 次查看'));
  assert.ok(html.includes('&lt;img src=x onerror=alert(1)&gt;'));
  assert.ok(html.includes('只保留了部分文字') && html.includes('新页面'));
  assert.ok(!html.includes(' open') && !html.includes('<img'));
  assert.ok(html.includes('task-a:phone_1:app:a'));
});
test('a screenshot is a capture record, not a read source or local file link', () => {
  const html=researchMarkup({items:[{kind:'app',status:'frame',title:'手机截图',detail:'已取得一张画面；不代表已理解图片或完整视频。'}]});
  assert.ok(html.includes('手机截图') && html.includes('不代表'));
  assert.ok(!html.includes('已读取') && !html.includes('href='));
});
