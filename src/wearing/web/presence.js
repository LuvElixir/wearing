"use strict";
// A continuous loop on one decode surface; the second prepares state changes.
// Keep the last decoded frame visible until its replacement is actually ready.
class WearingPresence {
  constructor({stage,poster,videos,preference,onReduced=()=>{}}) {
    Object.assign(this,{stage,poster,videos,preference,onReduced});
    this.mode="idle";this.visible=true;this.hidden=document.hidden;this.manifest=null;
    this.serial=0;this.current=null;this.pending=null;this.broken=new Set();
    this.lastAttention=0;
    for(const video of videos){video.muted=true;video.loop=true;video.controls=false;video.setAttribute("disablepictureinpicture","");}
    preference.addEventListener("change",()=>this.sync());
    document.addEventListener("visibilitychange",()=>{this.hidden=document.hidden;this.sync();});
    this.observer=new IntersectionObserver(entries=>{this.visible=entries[0].isIntersecting;this.sync();},{threshold:.1});
    this.observer.observe(stage);
  }
  configure(manifest){this.manifest=manifest;this.poster.src=manifest.poster;this.sync();}
  stopped(){return this.preference.matches||this.hidden||!this.visible;}
  descriptor(name){return this.manifest?.states?.[name]||(name==="working"&&this.manifest?.video?{src:this.manifest.video}:null);}
  rest(){
    this.serial++;this.pending=null;this.current=null;
    for(const video of this.videos){video.pause();video.hidden=true;video.onended=null;}
    this.poster.hidden=false;this.stage.dataset.motion="rest";
  }
  setState(mode){
    if(mode===this.mode)return;
    this.mode=mode;
    // Ordinary state changes finish the gesture. A handoff freezes it immediately,
    // but keeps that decoded image in place while the waiting clip loads.
    if(this.current)this.current.video.loop=this.current.name===mode&&mode!=="attention";
    if(this.stopped()){this.sync();return;}
    if(mode==="waiting"){
      this.current?.video.pause();this.perform(mode);
    }else if(!this.current&&!this.pending)this.perform(mode);
    else if(this.current?.video.ended&&!this.pending)this.perform(mode);
  }
  sync(){
    this.onReduced(this.preference.matches);
    if(this.preference.matches){this.rest();return;}
    if(this.stopped()){
      this.serial++;this.pending=null;
      for(const video of this.videos)video.pause();
      return;
    }
    if(this.mode==="waiting"&&this.current?.name!=="waiting"&&!this.pending){this.perform(this.mode);return;}
    if(this.current&&!this.current.video.ended){
      const {video}=this.current;
      video.play().then(()=>{if(this.stopped()||this.current?.video!==video)video.pause();})
        .catch(()=>{if(this.current?.video===video)this.rest();});
    }else if(!this.pending)this.perform(this.mode);
  }
  attention(){
    if(this.stopped()||this.current?.name==="attention"||this.pending?.name==="attention"||Date.now()-this.lastAttention<1800)return false;
    if(!this.descriptor("attention"))return false;
    this.lastAttention=Date.now();this.perform("attention");return true;
  }
  perform(name){
    if(this.stopped()||this.pending?.name===name)return;
    const clip=this.descriptor(name);
    if(!clip?.src||this.broken.has(clip.src)){this.rest();return;}
    const serial=++this.serial;
    const video=this.videos.find(v=>v!==this.current?.video)||this.videos[0];
    video.pause();video.hidden=true;video.onended=null;video.poster=this.manifest.poster;
    this.pending={name,video};
    const fail=()=>{
      if(serial!==this.serial)return;
      this.broken.add(clip.src);this.rest();
    };
    const reveal=()=>{
      if(serial!==this.serial)return;
      if(this.stopped()){video.pause();return;}
      const previous=this.current?.video;
      video.hidden=false;this.poster.hidden=true;
      if(previous&&previous!==video){previous.pause();previous.hidden=true;}
      this.current={name,video};this.pending=null;this.stage.dataset.motion=name;
      video.loop=name===this.mode&&name!=="attention";
      video.onended=()=>{
        if(this.current?.video!==video||this.pending||this.stopped())return;
        // Native looping handles stable states without source resets, poster
        // reveals, or timers. The boundary only swaps a queued state/one-shot.
        if(name!==this.mode||name==="attention")this.perform(this.mode);
        else {video.currentTime=0;video.play().catch(fail);}
      };
    };
    const ready=()=>{
      if(serial!==this.serial||this.stopped())return;
      video.play().then(()=>{
        if(serial!==this.serial)return;
        if(this.stopped()){video.pause();return;}
        if(video.requestVideoFrameCallback)video.requestVideoFrameCallback(reveal);else reveal();
      }).catch(fail);
    };
    video.loop=name===this.mode&&name!=="attention";
    video.onerror=fail;video.onloadeddata=ready;
    video.src=clip.src;video.load();
  }
}
