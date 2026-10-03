// Exercise media races and state transitions without external services.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('src/wearing/web/presence.js','utf8');
function setup(reduced=false){
  const handlers={},timers=new Map();let timerId=0,visibility;
  const preference={matches:reduced,addEventListener:(event,cb)=>handlers.preference=cb};
  const document={hidden:false,addEventListener:(event,cb)=>handlers[event]=cb};
  const stage={dataset:{}},poster={hidden:false};
  const videos=[0,1].map(()=>({paused:true,hidden:true,ended:false,src:'',playCount:0,
    setAttribute(){},load(){this.ended=false;},play(){this.paused=false;this.playCount++;return Promise.resolve();},pause(){this.paused=true;},
    requestVideoFrameCallback(cb){this.frame=cb;}}));
  const context={document,Date,IntersectionObserver:class{constructor(cb){visibility=cb;}observe(){}},
    clearTimeout:id=>timers.delete(id),setTimeout:cb=>{timers.set(++timerId,cb);return timerId;}};
  vm.createContext(context);vm.runInContext(source+'\nthis.Player=WearingPresence;',context);
  const player=new context.Player({stage,poster,videos,preference});
  player.configure({poster:'/anchor.png',states:Object.fromEntries(['idle','attention','thinking','listening','working','waiting'].map(n=>[n,{src:`/${n}.mp4`}]))});
  async function loaded(){const video=player.pending.video;video.onloadeddata();await Promise.resolve();video.frame();return video;}
  return {player,poster,stage,videos,handlers,preference,document,timers,loaded,visibility:v=>visibility([{isIntersecting:v}])};
}
(async()=>{
  const x=setup(true);assert.ok(x.videos.every(v=>v.playCount===0));assert.equal(x.poster.hidden,false);
  x.preference.matches=false;x.handlers.preference();const idle=await x.loaded();
  assert.equal(x.poster.hidden,true);assert.equal(x.stage.dataset.motion,'idle');
  assert.equal(idle.loop,true,'idle loops natively without poster swaps');
  for(let i=0;i<3;i++){idle.ended=true;idle.onended();assert.equal(x.poster.hidden,true);assert.equal(x.player.current.video,idle);assert.equal(x.player.pending,null);}
  idle.ended=false;
  x.player.setState('listening');assert.equal(idle.loop,false,'finish current loop before a queued state');assert.equal(x.player.current.name,'idle','normal state changes finish the current gesture');
  idle.ended=true;idle.onended();const listen=await x.loaded();assert.equal(listen.hidden,false);assert.ok(x.videos.filter(v=>v!==listen).every(v=>v.hidden));
  assert.equal(x.player.attention(),true);assert.equal(listen.hidden,false,'attention keeps the previous decoded frame until ready');const attention=await x.loaded();assert.equal(x.player.attention(),false,'clicks never stack');
  x.player.setState('thinking');assert.equal(x.player.current.name,'attention');
  attention.ended=true;attention.onended();assert.equal(x.player.pending.name,'thinking');await x.loaded();
  x.player.setState('waiting');assert.equal(x.poster.hidden,true,'handoff holds the decoded frame, without flashing the poster');assert.equal(x.player.current.video.paused,true);await x.loaded();
  x.document.hidden=true;x.handlers.visibilitychange();assert.ok(x.videos.every(v=>v.paused));
  x.document.hidden=false;x.handlers.visibilitychange();await Promise.resolve();
  x.visibility(false);assert.ok(x.videos.every(v=>v.paused));x.visibility(true);await Promise.resolve();
  x.preference.matches=true;x.handlers.preference();assert.ok(x.videos.every(v=>v.hidden));assert.equal(x.poster.hidden,false);
  x.preference.matches=false;x.handlers.preference();await x.loaded();
  x.player.rest();x.player.setState('working');const stale=x.player.pending.video.onloadeddata;
  x.player.setState('waiting');stale();await Promise.resolve();assert.equal(x.player.pending.name,'waiting','stale readiness cannot win');
  const broken=x.player.pending.video;broken.onerror();assert.equal(x.poster.hidden,false);
  x.player.sync();assert.equal(x.player.pending,null,'broken source does not spin or retry');
  x.player.setState('idle');const calm=await x.loaded();calm.ended=true;calm.onended();assert.equal(x.poster.hidden,true);assert.equal(x.timers.size,0,'loops never introduce a still interval');
  calm.ended=false;x.player.setState('thinking');x.player.setState('idle');assert.equal(calm.loop,true,'returning to the current state cancels a queued change');
  const y=setup();await y.loaded();
  y.player.setState('waiting');y.document.hidden=true;y.handlers.visibilitychange();y.document.hidden=false;y.handlers.visibilitychange();assert.equal(y.player.pending.name,'waiting');await y.loaded();
  const hidden=y.videos.find(v=>v.hidden);const oldFrame=hidden.frame;y.player.setState('working');y.player.current.video.ended=true;y.player.current.video.onended();await y.loaded();oldFrame?.();assert.equal(y.player.current.video.paused,false,'late frame callbacks cannot pause a reused surface');
  const html=fs.readFileSync('src/wearing/web/index.html','utf8');
  assert.doesNotMatch(html,/motion-toggle|character-reaction|<video[^>]*\scontrols[\s>]/);
  console.log('PASS: decoded swaps, attention debounce, state return, handoff, hidden/offscreen/reduced motion, stale load, failure fallback, continuous native loops, no poster between actions, no player controls');
})().catch(e=>{console.error(e);process.exitCode=1;});
