const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const tokens = JSON.parse(fs.readFileSync('design/brand/pajio/interaction-tokens.json', 'utf8'));
const read = p => fs.readFileSync(p, 'utf8');
const css = read('src/wearing/web/pajio.css');
const desktop = read('clients/desktop/frontend/connection.css');
const views = read('src/wearing/web/views.js');
const names = {canvas:'page',selectionSurface:'selection-surface',selectionInk:'selection-ink',selectionBorder:'selection-border',selectionIndicator:'selection-indicator',focusRing:'focus-ring',pressedSurface:'pressed-surface',disabledSurface:'disabled-surface',disabledInk:'disabled-ink'};
for (const theme of ['day','night']) test(`${theme} Web and desktop tokens match canonical contract`,()=> {
  for (const [key,value] of Object.entries(tokens[theme])) {
    const name=names[key]||key.replace(/[A-Z]/g,c=>'-'+c.toLowerCase());
    assert.ok(css.includes(`--${name}:${value}`), `web ${theme} ${name}`);
    assert.ok(desktop.includes(`--${name==='page'?'canvas':name}:${value}`), `desktop ${theme} ${name}`);
  }
});
test('radio semantics and explicit selected check are present; wardrobe stays a preview until save',()=> {
  assert.doesNotMatch(views,/role="radio" aria-pressed/);
  assert.match(views,/role="radiogroup" aria-label="外观"/);
  assert.match(views,/button\.setAttribute\("aria-checked", String\(selected\)\)/);
  assert.match(views,/class="wardrobe-check"/);
  assert.match(views,/await wardrobe\.save\(preview\(\)\)/);
});
test('radio arrow keys wrap, skip disabled choices, and leave other keys untouched',()=> {
  const source=views.slice(views.indexOf('  function handleRadioKey'),views.indexOf('  document.addEventListener("keydown", handleRadioKey)'));
  const context={}; vm.runInNewContext(source,context);
  let focus=null, clicks=0, prevented=0;
  const group={querySelectorAll:()=>choices};
  const choices=[0,1,2].map(id=>({id,disabled:id===1,getAttribute:()=>null,closest:()=>group,focus:()=>{focus=id;},click:()=>clicks++}));
  const event=key=>({key,target:{closest:()=>choices[2]},preventDefault:()=>prevented++});
  context.handleRadioKey(event('ArrowRight')); assert.equal(focus,0); assert.equal(clicks,1);
  context.handleRadioKey(event('ArrowLeft')); assert.equal(focus,0); assert.equal(clicks,2);
  context.handleRadioKey(event('End')); assert.equal(focus,2); assert.equal(clicks,3);
  context.handleRadioKey(event('Tab')); assert.equal(clicks,3); assert.equal(prevented,3);
  choices[2].disabled=true; context.handleRadioKey(event('ArrowLeft')); assert.equal(clicks,3);
});
test('selection is not keyboard focus and all custom rules exclude the mobile host',()=> {
  assert.match(css,/outline:2px solid var\(--focus-ring\);outline-offset:2px/);
  assert.match(css,/width:20px;height:2px;border-radius:2px;background:var\(--selection-indicator\)/);
  assert.match(css,/prefers-reduced-motion:reduce/);
  for(const m of css.replace(/\/\*[\s\S]*?\*\//g,'').matchAll(/([^{}]+)\{/g)) {
    const selector=m[1].trim(); if(!selector.startsWith('@')) assert.match(selector,/:not\(\.mobile-host\)/);
  }
});
