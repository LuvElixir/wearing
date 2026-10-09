const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

test('artifact metadata stays inert and empty results stay quiet', () => {
  const node = {addEventListener(){}};
  const context = {window:{}, document:{getElementById:()=>node, addEventListener(){}}};
  vm.runInNewContext(fs.readFileSync('src/wearing/web/artifacts.js','utf8'), context);
  assert.equal(context.window.artifactMarkup(), '');
  const html = context.window.artifactMarkup([{
    id:'x" onclick="steal()', title:'<script>steal()</script>', summary:'<img src=x onerror=steal()>',
    revision:1, presentation:'diagram',
  }]);
  assert(!html.includes('<script>'));
  assert(!html.includes('<img src=x'));
  assert(html.includes('&lt;script&gt;'));
  assert(html.includes('data-artifact="x&quot; onclick=&quot;steal()"'));
  assert(html.includes('关系图 · 版本 1'));
});
