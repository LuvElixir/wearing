import {test} from 'node:test';
import assert from 'node:assert/strict';
import {appearancePreference, conversationThemeScript, palettes, resolveAppearance} from './appearance';
test('night is the first-use choice; manual choices override the device', () => {
  assert.equal(appearancePreference(undefined), 'night');
  assert.equal(appearancePreference('corrupt'), 'night');
  assert.equal(resolveAppearance('day','dark'),'day');
  assert.equal(resolveAppearance('night','light'),'night');
  assert.equal(resolveAppearance('system','light'),'day');
  assert.equal(resolveAppearance('system','dark'),'night');
  assert.equal(resolveAppearance('system',null),'night');
});
function luminance(hex: string) {
  const values=hex.slice(1).match(/../g)!.map(value=>parseInt(value,16)/255).map(value=>value<=.04045?value/12.92:((value+.055)/1.055)**2.4);
  return values[0]*.2126+values[1]*.7152+values[2]*.0722;
}
function contrast(a:string,b:string) {const x=luminance(a),y=luminance(b);return (Math.max(x,y)+.05)/(Math.min(x,y)+.05);}
test('small reading text and primary actions stay legible in both palettes', () => {
  for (const [mode,c] of Object.entries(palettes)) {
    for(const background of [c.canvas,c.surface,c.soft,c.dock])for(const foreground of [c.ink,c.muted]) assert.ok(contrast(background,foreground)>=4.5,`${mode} ${foreground}/${background}`);
    assert.ok(contrast(c.accent,c.onAccent)>=4.5);
    assert.ok(contrast(c.accentSoft,c.accentInk)>=4.5);
  }
});
test('conversation appearance uses a bounded enum and does not reload or replace a draft',()=>{
  assert.match(conversationThemeScript('night'),/dataset.appTheme='night'/);
  assert.match(conversationThemeScript('day'),/dataset.appTheme='day'/);
  assert.doesNotMatch(conversationThemeScript('night'),/location|reload|draft|innerHTML/);
});
