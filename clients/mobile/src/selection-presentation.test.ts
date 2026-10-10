import {test, after} from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,readFileSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join,resolve} from 'node:path';
import {createRequire} from 'node:module';
import {build} from 'esbuild';
import {palettes} from './appearance';
const temp=mkdtempSync(join(tmpdir(),'pajio-selection-test-'));
after(()=>rmSync(temp,{recursive:true,force:true}));
const moduleFile=join(temp,'render.cjs');
const prepared=build({stdin:{contents:`import React from 'react';import {renderToStaticMarkup} from 'react-dom/server';import {Choice,Segment,StateSwitch} from './src/experience/selection';export function render(kind,props){return renderToStaticMarkup(React.createElement({choice:Choice,segment:Segment,toggle:StateSwitch}[kind],props));}`,resolveDir:process.cwd(),loader:'tsx'},bundle:true,platform:'node',format:'cjs',outfile:moduleFile,jsx:'automatic',alias:{'react-native':'react-native-web'},resolveExtensions:['.web.tsx','.web.ts','.web.js','.tsx','.ts','.js','.json'],plugins:[{name:'theme-only',setup(b){b.onResolve({filter:/app-theme$/},()=>({path:'theme',namespace:'fixture'}));b.onLoad({filter:/.*/,namespace:'fixture'},()=>({contents:`import {palettes} from ${JSON.stringify(resolve('src/appearance.ts'))};export const useAppTheme=()=>({colors:palettes.day});export const useThemedStyles=f=>f(palettes.day);`,loader:'js',resolveDir:process.cwd()}));}}]});
async function render(kind:string,props:Record<string,unknown>){await prepared;return createRequire(import.meta.url)(moduleFile).render(kind,props) as string;}
test('shared single and multiple choices emit actual RN Web checked semantics, including disabled state',async()=>{
 const single=await render('choice',{label:'单选',selected:true,onPress:()=>{}});
 assert.match(single,/role="radio"/);assert.match(single,/aria-checked="true"/);assert.doesNotMatch(single,/aria-selected/);
 const multiple=await render('choice',{label:'多选',multiple:true,selected:false,disabled:true,onPress:()=>{}});
 assert.match(multiple,/role="checkbox"/);assert.match(multiple,/aria-checked="false"/);assert.match(multiple,/aria-disabled="true"/);
});
test('navigation tabs expose selection independently of checks and OS switches keep switch semantics',async()=>{
 const tab=await render('segment',{label:'日历',selected:true,onPress:()=>{}});assert.match(tab,/role="tab"/);assert.match(tab,/aria-selected="true"/);assert.doesNotMatch(tab,/aria-checked/);
 const toggle=await render('toggle',{accessibilityLabel:'启用',value:true,onValueChange:()=>{}});assert.match(toggle,/role="switch"/);assert.match(toggle,/checked/);
});
test('every canonical interaction token matches the native palette without widening Metro imports',()=>{
 const contract=JSON.parse(readFileSync(resolve('../../design/brand/pajio/interaction-tokens.json'),'utf8'));
 for(const mode of ['day','night'] as const)for(const [key,value] of Object.entries(contract[mode]))assert.equal((palettes[mode] as Record<string,string>)[key],value,mode+' '+key);
});
