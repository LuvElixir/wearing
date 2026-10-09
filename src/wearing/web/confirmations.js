(function (root) {
  "use strict";
  const esc = text => String(text ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const check = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m5 12 4 4L19 6"/></svg>';
  const recovery = task => `<div class="decision-actions"><button data-action="refresh" data-task="${esc(task)}">重新查看</button><button data-action="stop" data-task="${esc(task)}">结束本轮</button></div>`;
  function pending(task, approval, sending=false) {
    const card=approval.card;
    if(!card || approval.card_invalid) return `<section class="decision-card"><p class="decision-eyebrow">确认内容需要更新</p><p>这一步的信息还不完整。原操作没有获得确认，请重新查看运行状态。</p>${recovery(task)}</section>`;
    const available=approval.card_state==='pending' && !sending;
    const hint={sending:'正在核对决定是否送达。',unknown:'送达状态待核对，请勿重复提交。',answered:'已收到，正在继续。',expired:'确认已失效，请查看最新进展。'}[approval.card_state] || '';
    return `<section class="decision-card decision-prompt" aria-label="${esc(card.title)}" data-decision-card aria-busy="${sending}">
      <h3>${esc(card.title)}</h3><p class="decision-action">${esc(card.action)}</p>
      ${card.impact&&card.impact!==card.action?`<p class="decision-impact">${esc(card.impact)}</p>`:''}
      ${card.command?`<details class="decision-detail"><summary>查看实际操作</summary><pre>${esc(card.command)}</pre></details>`:''}
      <div class="decision-actions"><button class="primary" data-choice="once" data-task="${esc(task)}" data-request="${esc(approval.request_id)}" ${available?'':'disabled'}>${esc(card.confirm_label)}</button><button class="decision-decline" data-choice="deny" data-task="${esc(task)}" data-request="${esc(approval.request_id)}" ${available?'':'disabled'}>不执行</button></div>
      <p class="decision-hint" role="status" ${sending||hint?'':'hidden'}>${sending?'正在送出…':hint}</p><p class="decision-error" role="alert" hidden></p>
      ${!available&&!sending?recovery(task):''}
    </section>`;
  }
  function history(records, currentRequest) {
    return (records||[]).filter(r=>r.request_id!==currentRequest && r.state!=='pending').map(r=>{
      const approved=r.state==='answered' && r.choice!=='deny';
      const label=r.state==='answered'?(approved?'已确认':'本次不执行'):r.state==='expired'?'确认已结束':'决定送达状态待核对';
      return `<details class="decision-receipt" data-decision-state="${esc(r.state)}"><summary><span class="decision-receipt-icon" aria-hidden="true">${approved?check:'<svg viewBox="0 0 24 24"><path d="M6 12h12"/></svg>'}</span><span>${esc(r.card.title)}</span><span class="decision-receipt-state">${label}</span></summary><div><p>${esc(r.card.action)}</p><p class="decision-hint">${esc(r.card.impact)}</p><p class="decision-hint">${approved?'仅确认所列动作，执行结果看后续回应。':r.state==='answered'?'你的决定已送达，所列动作未获授权。':r.state==='expired'?'原确认已结束，不能再从这张卡片执行。':'原运行仍需核对，没有重新提交决定。'}</p></div></details>`;
    }).join('');
  }
  const api={pending,history};root.WearingConfirmations=api;
  if(typeof module!=='undefined')module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
