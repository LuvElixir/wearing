const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const css=fs.readFileSync('src/wearing/web/mobile-host.css','utf8');
const canonical=JSON.parse(fs.readFileSync('design/brand/pajio/interaction-tokens.json','utf8'));
function rules(text=css){return [...text.replace(/\/\*[\s\S]*?\*\//g,'').matchAll(/([^{}]+)\{([^{}]*)\}/g)].map(([,selector,body])=>({selector:selector.trim(),values:Object.fromEntries(body.split(';').filter(x=>x.includes(':')).map(x=>{const i=x.indexOf(':');return [x.slice(0,i).trim(),x.slice(i+1).trim()];}))}));}
function declarations(selector,text=css){const matches=rules(text).filter(r=>r.selector===selector);assert.ok(matches.length,'selector exists: '+selector);return Object.assign({},...matches.map(r=>r.values));}
function cssKey(name){return '--'+name.replace(/[A-Z]/g,c=>'-'+c.toLowerCase());}
test('Core-served embedded page mirrors every canonical native day/night token and keeps transparent composition',()=>{
 for(const mode of ['day','night']){
  const vars=declarations('.mobile-host'+(mode==='night'?'[data-app-theme="night"]':''));
  for(const [key,value] of Object.entries(canonical[mode]))assert.equal(vars[cssKey(key)],value,mode+' '+key);
 }
 const aliases=declarations('.mobile-host');assert.equal(aliases['--host-soft'],'var(--soft)');assert.equal(aliases['--host-panel'],'var(--canvas)');assert.equal(aliases['--blue'],'var(--accent)');
 assert.equal(declarations('.native-composer-host')['--page'],'transparent');
 assert.doesNotMatch(css,/#(?:3156c8|a3b7ff|edf1ff|93a4eb)\b/i);
});
test('native theme bridge selects the mirrored scope without navigation, storage writes, or a draft reload',()=>{
 const source=fs.readFileSync('clients/mobile/src/appearance.ts','utf8');
 const body=source.match(/export function conversationThemeScript\(mode: AppMode\) \{([\s\S]*?)\n\}/)[1];
 const bridge=new Function('mode',body);
 for(const mode of ['day','night','untrusted']){
  const document={documentElement:{dataset:{}}};vm.runInNewContext(bridge(mode),{document});
  assert.equal(document.documentElement.dataset.appTheme,mode==='day'?'day':'night');
 }
 vm.runInNewContext(bridge('night'),{document:{documentElement:null}});
 const host=fs.readFileSync('src/wearing/web/mobile-host.js','utf8');
 assert.match(host,/classList\.add\('mobile-host'\)/);assert.match(host,/classList\.add\('native-composer-host'\)/);
});
test('embedded focus remains independent from current search and checked choices',()=>{
 const current=declarations('.native-composer-host .host-search-current');
 assert.equal(current.background,'var(--selection-surface)');assert.equal(current.color,'var(--selection-ink)');
 assert.equal(current['box-shadow'],'inset 3px 0 0 var(--selection-indicator)');
 const focus=rules().find(r=>r.selector.includes('html.mobile-host #activity-panel button:focus-visible'));
 assert.equal(focus.values.outline,'2px solid var(--focus-ring)');assert.equal(focus.values['outline-offset'],'2px');assert.equal(focus.values['box-shadow'],'none');
 const checked=declarations('html.mobile-host :is(.se-week,.schedule-kind-options) label:has(input:checked)');
 assert.equal(checked['border-color'],'var(--selection-border)');assert.equal(checked.background,'var(--selection-surface)');
 const calendar=declarations('html.mobile-host .life-calendar #life-calendar-root');
 assert.equal(calendar['--fc-monarch-ring-color'],'var(--focus-ring)');assert.equal(calendar['--fc-monarch-selected'],'var(--selection-surface)');
});
function contrast(a,b){
 const luminance=hex=>{const channels=hex.match(/[a-f\d]{2}/gi).map(x=>parseInt(x,16)/255).map(x=>x<=.04045?x/12.92:((x+.055)/1.055)**2.4);return channels.reduce((v,x,i)=>v+x*[.2126,.7152,.0722][i],0);};
 const values=[luminance(a),luminance(b)].sort((x,y)=>y-x);return (values[0]+.05)/(values[1]+.05);
}
test('embedded review tabs override the real light parent surface in night mode, including readable inactive text',()=>{
 const now=fs.readFileSync('src/wearing/web/now.css','utf8');
 assert.equal(declarations('.review-switcher',now).background,'#f0f2f7','regression precondition: inherited parent is light');
 const container=declarations('html.mobile-host :is(.review-switcher,.life-calendar-views)');
 assert.equal(container.background,'var(--canvas)');
 const button=declarations('html.mobile-host :is(.review-switcher,.life-calendar-views) button');
 assert.equal(button.background,'transparent');assert.equal(button.color,'var(--muted)');
 const selected=declarations('html.mobile-host .review-switcher button[aria-current="page"],html.mobile-host .life-calendar-views button[aria-pressed="true"]');
 assert.equal(selected.color,'var(--selection-ink)');assert.equal(selected.background,'transparent');
 const indicator=declarations('html.mobile-host .review-switcher button[aria-current="page"]::after,html.mobile-host .life-calendar-views button[aria-pressed="true"]::after');
 assert.equal(indicator.background,'var(--selection-indicator)');
 for(const mode of ['day','night']){
  const t=canonical[mode];assert.ok(contrast(t.muted,t.canvas)>=4.5,mode+' inactive label');assert.ok(contrast(t.selectionInk,t.canvas)>=4.5,mode+' selected label');assert.ok(contrast(t.selectionIndicator,t.canvas)>=3,mode+' indicator');
 }
 const panel=declarations('html.mobile-host .schedule-form');assert.equal(panel.background,'var(--soft)');assert.equal(panel.color,'var(--ink)');
 for(const mode of ['day','night'])assert.ok(contrast(canonical[mode].ink,canonical[mode].soft)>=4.5,mode+' schedule form');
});
test('primary, pressed and disabled embedded actions have separate high contrast theme tokens',()=>{
 const action=declarations('html.mobile-host :is(.primary,.send-button)');
 assert.equal(action.background,'var(--action)');assert.equal(action.color,'var(--on-action)');
 const pressed=declarations('html.mobile-host :is(.primary,.send-button):active:not(:disabled)');assert.equal(pressed.background,'var(--action-pressed)');
 const disabled=rules().find(r=>r.selector.includes('html.mobile-host :is(button,input,textarea,select):disabled'));
 assert.equal(disabled.values.background,'var(--disabled-surface)');assert.equal(disabled.values.color,'var(--disabled-ink)');assert.equal(disabled.values.opacity,'1');
});
test('all added palette/control selectors are host scoped and preserve gesture/approval boundaries',()=>{
 const added=css.split('/* Reachable conversation/review controls.')[1].split('*/')[1];
 for(const rule of rules(added))assert.ok(rule.selector.split(/,\s*(?=html)/).every(selector=>selector.startsWith('html.mobile-host ')),rule.selector);
 for(const rule of rules(added)){assert.notEqual(rule.values.display,'none');if(rule.values['pointer-events']==='none')assert.ok(rule.selector.endsWith('::after'));}
 assert.equal(declarations('.native-composer-host')['touch-action'],'pan-x pan-y');
 assert.match(css,/@media\(prefers-reduced-motion:reduce\)/);
});

test('standalone Web and authentication aliases match the same canonical contract',()=>{
 const web=fs.readFileSync('src/wearing/web/pajio.css','utf8');
 const auth=fs.readFileSync('src/wearing/web/auth/auth.css','utf8').split('@media(prefers-color-scheme:dark)');
 const aliases={bg:'canvas',card:'surface',field:'surface',ink:'ink',muted:'muted',line:'line','focus-ring':'focusRing',button:'action','button-pressed':'actionPressed','button-ink':'onAction','selection-surface':'selectionSurface','selection-ink':'selectionInk','selection-border':'selectionBorder','selection-indicator':'selectionIndicator','pressed-surface':'pressedSurface','disabled-surface':'disabledSurface','disabled-ink':'disabledInk'};
 for(const [index,mode] of ['day','night'].entries()){
  const values=declarations('html:not(.mobile-host)'+(mode==='night'?'[data-app-theme="night"]':''),web);
  for(const [key,value] of Object.entries(canonical[mode]))assert.equal(values[key==='canvas'?'--page':cssKey(key)],value,'Web '+mode+' '+key);
  const page=declarations(':root',auth[index]);
  for(const [alias,key] of Object.entries(aliases))assert.equal(page['--'+alias],canonical[mode][key],'Auth '+mode+' '+key);
 }
});
