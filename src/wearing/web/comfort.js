/* Short, interruptible feedback. Data and permissions remain with their owners. */
(() => {
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
  const running = new WeakMap();
  const ease = 'cubic-bezier(.22,1,.36,1)';
  function stop(node) { running.get(node)?.cancel(); running.delete(node); }
  function enter(node) {
    if (!node) return;
    stop(node);
    if (reduced.matches || !node.animate) return;
    const animation = node.animate([{opacity:.5,transform:'translateY(7px)'},{opacity:1,transform:'translateY(0)'}],{duration:240,easing:ease});
    running.set(node,animation);
    animation.finished.catch(() => {}).finally(() => {if(running.get(node)===animation)running.delete(node);});
  }
  window.WearingMotion = {
    open(node) {stop(node);if(!node.open)node.showModal();enter(node);},
    close(node) {
      stop(node);
      if (!node.open) return;
      if (reduced.matches || !node.animate) {node.close();return;}
      const animation=node.animate([{opacity:1,transform:'translateY(0)'},{opacity:0,transform:'translateY(8px)'}],{duration:160,easing:'ease-out'});
      running.set(node,animation);
      animation.finished.then(()=>{if(running.get(node)===animation){running.delete(node);node.close();}}).catch(()=>{});
    }
  };
  document.querySelectorAll('dialog').forEach(node => {
    node.addEventListener('cancel',event=>{event.preventDefault();window.WearingMotion.close(node);});
    node.addEventListener('close',()=>stop(node));
  });
  const input=document.getElementById('life-capture-text');
  const more=document.getElementById('capture-more');
  const toggle=document.getElementById('capture-more-toggle');
  const kindLabel=document.getElementById('capture-kind-label');
  const syncKind=()=>{const selected=document.querySelector('[data-life-kind][aria-pressed="true"]');if(selected&&kindLabel)kindLabel.textContent=selected.dataset.lifeKind==='note'?'随手记':selected.textContent;};
  syncKind();
  document.querySelectorAll('[data-life-kind]').forEach(button=>new MutationObserver(syncKind).observe(button,{attributes:true,attributeFilter:['aria-pressed']}));
  toggle?.addEventListener('click',()=>{if(document.querySelector('#capture-more .is-recording')&&!more.hidden)return;more.hidden=!more.hidden;toggle.setAttribute('aria-expanded',String(!more.hidden));if(!more.hidden)enter(more);});
  document.querySelectorAll('[data-life-kind]').forEach(button=>button.addEventListener('click',()=>{
    document.getElementById('capture-kind-label').textContent=button.dataset.lifeKind==='note'?'随手记':button.textContent;
    if(!document.querySelector('#capture-more .is-recording')){more.hidden=true;toggle.setAttribute('aria-expanded','false');}
  }));
  const resize=()=>{if(!input||input.hidden)return;input.style.height='auto';input.style.height=Math.min(240,Math.max(78,input.scrollHeight))+'px';};
  input?.addEventListener('input',resize);
  document.getElementById('life-capture-form')?.addEventListener('reset',()=>requestAnimationFrame(resize));
  document.addEventListener('click',event=>{
    const button=event.target.closest('[data-life-view]');
    if(!button)return;
    requestAnimationFrame(()=>{
      const main=document.getElementById(button.dataset.lifeView==='chat'?'conversation-main':'life-main');
      if(!button.closest(".review-switcher"))enter(main);
      resize();
    });
  });
  document.addEventListener('keydown',event=>{
    if(event.isComposing||document.querySelector('dialog[open]')||!(event.metaKey||event.ctrlKey))return;
    if(event.key.toLowerCase()==='k'){
      const target=document.body.classList.contains('life-mode')?input:document.querySelector('.composer textarea');
      if(target && target.getClientRects().length){event.preventDefault();target.focus();}
    }
    if(event.key==='Enter'&&event.target===input){
      const save=document.getElementById('life-capture-save');
      if(save&&!save.disabled){event.preventDefault();input.form.requestSubmit(save);}
    }
  });
  reduced.addEventListener?.('change',()=>{if(reduced.matches)document.getAnimations().forEach(animation=>{if(animation.effect?.target)stop(animation.effect.target);});});
})();
