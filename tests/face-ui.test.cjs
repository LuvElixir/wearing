const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

test('conversation portraits render without media APIs or browser observers', () => {
  const window = {};
  // A static reply must also work when media/visibility APIs are unavailable.
  vm.runInNewContext(fs.readFileSync('src/wearing/web/face.js','utf8'), {window});
  const markup = window.wearingFaceMarkup();
  assert.match(markup, /role="img" aria-label="Pajio"/);
  assert.match(markup, /chat-portrait\.png/);
  assert.match(markup, /alt=""/);
  assert.doesNotMatch(markup, /<video|<button/);
  assert.equal(window.wearingFaceMarkup(), markup);
});
