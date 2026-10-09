import type {RemoteTransport} from './remote-device-model';
import {palettes} from './appearance';

/** App-owned viewer only. No service token, remote script, clipboard or persistent storage. */
export function remoteViewerDocument(transport: RemoteTransport, kind: 'computer' | 'android', expiresAt: number): string {
  const config = JSON.stringify({...transport, device_kind: kind, expires_at: expiresAt}).replace(/</g, '\\u003c');
  return `<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; media-src blob:; connect-src 'none'; img-src 'none'; form-action 'none'; base-uri 'none'"><style>html,body{margin:0;width:100%;height:100%;background:${palettes.night.canvas};overflow:hidden;overscroll-behavior:none}video{width:100%;height:100%;object-fit:contain;touch-action:none;user-select:none;-webkit-user-select:none}#shade{position:absolute;inset:0;background:${palettes.night.canvas};pointer-events:none}</style></head><body><video id="screen" autoplay playsinline muted></video><div id="shade"></div><script>
(() => {
  'use strict';
  const config = ${config};
  // Keep this inline: Hermes function.toString() does not preserve executable source.
  function pointInFrame(x,y,boxWidth,boxHeight,frameWidth,frameHeight) {
    if(![x,y,boxWidth,boxHeight,frameWidth,frameHeight].every(Number.isFinite)||[boxWidth,boxHeight,frameWidth,frameHeight].some(v=>v<=0))return null;
    const scale=Math.min(boxWidth/frameWidth,boxHeight/frameHeight),width=frameWidth*scale,height=frameHeight*scale;
    const left=(boxWidth-width)/2,top=(boxHeight-height)/2;
    if(x<left||x>=left+width||y<top||y>=top+height)return null;
    return {x:Math.floor((x-left)/scale),y:Math.floor((y-top)/scale)};
  }
  const video = document.getElementById('screen'), shade = document.getElementById('shade');
  let pc, channel, stopped=false, frozen=false, controlling=false, confirmed=false, shown=false, geometry=null, geometryAt=0, lastVideoAt=0;
  let seq=0, gesture=null, capabilities={}, heartbeat, watch, stats, pending=new Map(), latestMove=0;
  const post = value => {if (window.ReactNativeWebView) window.ReactNativeWebView.postMessage(JSON.stringify(value));};
  const scope = () => ({session_id:config.session_id,epoch:config.epoch,gateway_epoch:config.gateway_epoch});
  function stop(reason) {
    if(stopped)return; stopped=true; frozen=true; gesture=null; shade.style.display='block';
    clearInterval(heartbeat);clearInterval(watch);clearInterval(stats);pending.clear();
    if(channel)channel.close();if(pc)pc.close();video.pause();video.srcObject=null;
    post({type:'stopped',reason});
  }
  function canInput() {return controlling&&!stopped&&!frozen&&confirmed&&shown&&channel&&channel.readyState==='open'&&geometry&&Date.now()-geometryAt<1800&&Date.now()-lastVideoAt<2500&&video.videoWidth===geometry.width&&video.videoHeight===geometry.height;}
  function sendRaw(value) {
    if(stopped||!channel||channel.readyState!=='open')return false;
    if(channel.bufferedAmount>8192){stop('slow_connection');return false;}
    const text=JSON.stringify(value);if(new TextEncoder().encode(text).length>20480)return false;
    try{channel.send(text);return true;}catch{stop('connection_lost');return false;}
  }
  function input(action, values) {
    if(!canInput()){post({type:'notice',code:'frame_not_ready'});return;}
    const n=++seq;
    if(sendRaw({type:'input',...scope(),seq:n,frame_id:geometry.frame_id,action,...values}))pending.set(n,Date.now());
  }
  function frameShown() {
    if(stopped)return;lastVideoAt=Date.now();
    if(confirmed&&geometry&&video.videoWidth===geometry.width&&video.videoHeight===geometry.height){
      if(!shown){shown=true;post({type:'live',capabilities});}
      shade.style.display=frozen?'block':'none';
    } else {shown=false;shade.style.display='block';}
    if(video.requestVideoFrameCallback)video.requestVideoFrameCallback(frameShown);
  }
  function locate(e) {if(!geometry)return null;const b=video.getBoundingClientRect();return pointInFrame(e.clientX-b.left,e.clientY-b.top,b.width,b.height,geometry.width,geometry.height);}
  video.addEventListener('pointerdown',e=>{
    e.preventDefault();if(!canInput())return;
    if(gesture){stop('gesture_interrupted');return;}
    const p=locate(e);if(!p)return;video.setPointerCapture(e.pointerId);
    gesture={id:e.pointerId,start:p,last:p,at:Date.now(),width:geometry.width,height:geometry.height,button:e.button===2?2:0};
    if(capabilities.pointer)input('pointer',{phase:'down',...p,button:gesture.button});
  });
  video.addEventListener('pointermove',e=>{
    if(!gesture||gesture.id!==e.pointerId)return;e.preventDefault();
    const p=locate(e);if(!p||!canInput()||geometry.width!==gesture.width||geometry.height!==gesture.height){stop('geometry_changed');return;}
    gesture.last=p;if(capabilities.pointer&&Date.now()-latestMove>=30){latestMove=Date.now();input('pointer',{phase:'move',...p,button:gesture.button});}
  });
  video.addEventListener('pointerup',e=>{
    if(!gesture||gesture.id!==e.pointerId)return;e.preventDefault();const g=gesture;gesture=null;
    if(!canInput()||geometry.width!==g.width||geometry.height!==g.height){stop('geometry_changed');return;}
    const p=locate(e)||g.last;
    if(capabilities.pointer){input('pointer',{phase:'up',...p,button:g.button});return;}
    const distance=Math.hypot(p.x-g.start.x,p.y-g.start.y),duration=Math.max(80,Math.min(1500,Date.now()-g.at));
    if(distance<12&&duration<500)input('tap',p);
    else input('swipe',{...g.start,to_x:p.x,to_y:p.y,duration_ms:duration});
  });
  video.addEventListener('pointercancel',()=>{if(gesture)stop('gesture_interrupted');});
  video.addEventListener('contextmenu',e=>e.preventDefault());
  video.addEventListener('wheel',e=>{e.preventDefault();if(capabilities.scroll)input('scroll',{delta_x:Math.max(-1000,Math.min(1000,Math.round(e.deltaX))),delta_y:Math.max(-1000,Math.min(1000,Math.round(e.deltaY)))});},{passive:false});
  document.addEventListener('visibilitychange',()=>{if(document.hidden)stop('background');});
  window.addEventListener('pagehide',()=>stop('background'));
  window.addEventListener('offline',()=>stop('connection_lost'));
  window.pajioReceive = async message => {
    if(stopped||!message||typeof message!=='object')return;
    if(message.type==='stop'){stop('closed');return;}
    if(message.type==='freeze'){frozen=true;gesture=null;shade.style.display='block';return;}
    if(message.type==='control'){
      if(gesture){stop('gesture_interrupted');return;}
      controlling=message.enabled===true;post({type:'control',enabled:controlling});return;
    }
    if(message.type==='answer'){
      if(message.gateway_epoch!==config.gateway_epoch||typeof message.sdp!=='string'){stop('session_changed');return;}
      try{await pc.setRemoteDescription({type:'answer',sdp:message.sdp});}catch{stop('negotiation_failed');}return;
    }
    if(message.type==='key'&&typeof message.key==='string'&&message.key.length<=32){input('key',{key:message.key,phase:'down'});input('key',{key:message.key,phase:'up'});return;}
    if(message.type==='text'&&typeof message.text==='string'){
      if(capabilities.text!=='unicode'){post({type:'notice',code:'text_unavailable'});return;}
      if(new TextEncoder().encode(message.text).length>4096){post({type:'notice',code:'text_too_large'});return;}
      if(capabilities.text==='ascii'&&(!/^[\\x20-\\x7e]*$/.test(message.text)||message.text.includes('%'))){post({type:'notice',code:'ascii_only'});return;}
      input('text',{text:message.text});
    }
  };
  async function start(){
    if(typeof RTCPeerConnection==='undefined'){stop('webrtc_unavailable');return;}
    pc=new RTCPeerConnection({iceServers:config.ice_servers,bundlePolicy:'max-bundle'});
    pc.addTransceiver('video',{direction:'recvonly'});
    pc.ontrack=e=>{video.srcObject=e.streams[0]||new MediaStream([e.track]);video.play().catch(()=>stop('playback_failed'));};
    video.addEventListener('loadeddata',()=>{if(video.requestVideoFrameCallback)video.requestVideoFrameCallback(frameShown);else frameShown();});
    video.addEventListener('timeupdate',()=>{if(!video.requestVideoFrameCallback)frameShown();});
    pc.onconnectionstatechange=()=>{if(['failed','disconnected','closed'].includes(pc.connectionState))stop('connection_lost');};
    channel=pc.createDataChannel('pajio-control',{ordered:true});
    channel.onclose=()=>stop('connection_lost');channel.onerror=()=>stop('connection_lost');
    channel.onopen=()=>{sendRaw({type:'heartbeat',...scope()});heartbeat=setInterval(()=>sendRaw({type:'heartbeat',...scope()}),5000);};
    channel.onmessage=e=>{
      if(stopped||typeof e.data!=='string'||e.data.length>20480)return;let m;try{m=JSON.parse(e.data);}catch{stop('invalid_channel');return;}
      if(m.type==='ready'){
        if(m.session_id!==config.session_id||m.epoch!==config.epoch||m.gateway_epoch!==config.gateway_epoch){stop('session_changed');return;}
        confirmed=true;capabilities=m.capabilities||{};post({type:'channel_ready',capabilities});
      }else if(m.type==='frame'){
        if(m.gateway_epoch!==config.gateway_epoch||typeof m.frame_id!=='string'||m.frame_id.length>128||!Number.isInteger(m.width)||!Number.isInteger(m.height)||m.width<1||m.height<1||m.width>8192||m.height>8192){stop('invalid_frame');return;}
        if(m.geometry_revision!==undefined&&(!Number.isSafeInteger(m.geometry_revision)||m.geometry_revision<0)){stop('invalid_frame');return;}
        if(geometry&&(geometry.width!==m.width||geometry.height!==m.height||geometry.geometry_revision!==m.geometry_revision)){stop('geometry_changed');return;}
        geometry=m;geometryAt=Date.now();
      }else if(m.type==='input_ack'){pending.delete(m.seq);}
      else if(m.type==='error'){if(m.seq)pending.delete(m.seq);post({type:'notice',code:typeof m.code==='string'?m.code:'input_rejected'});if(!m.seq)stop('session_changed');}
    };
    watch=setInterval(()=>{
      if(stopped)return;
      if(Date.now()>config.expires_at*1000){stop('expired');return;}
      if(shown&&(Date.now()-geometryAt>2500||Date.now()-lastVideoAt>3000)){stop('stale_video');return;}
      for(const at of pending.values())if(Date.now()-at>2500){stop('input_unconfirmed');return;}
    },300);
    stats=setInterval(async()=>{try{if(stopped)return;const values=await pc.getStats();let rtt=null;values.forEach(v=>{if(v.type==='candidate-pair'&&v.state==='succeeded'&&v.nominated&&typeof v.currentRoundTripTime==='number')rtt=Math.round(v.currentRoundTripTime*1000);});if(rtt!==null)post({type:'quality',rtt_ms:rtt});}catch{}},3000);
    try{
      const offer=await pc.createOffer();await pc.setLocalDescription(offer);
      await new Promise((resolve,reject)=>{if(pc.iceGatheringState==='complete'){resolve();return;}const timer=setTimeout(()=>reject(new Error('ice timeout')),12000);pc.addEventListener('icegatheringstatechange',()=>{if(pc.iceGatheringState==='complete'){clearTimeout(timer);resolve();}});});
      if(!stopped)post({type:'offer',sdp:pc.localDescription.sdp});
    }catch{stop('negotiation_failed');}
  }
  start();
})();
</script></body></html>`;
}
