"use strict";
/* Pajio 链接收藏（Web）：kind=note 且 url 非空的 life 记录视图，绝不抓取网页。
   对齐 docs/evidence/pajio-core-20261007/bookmarks-contract.md：
   - GET /api/bookmarks?query=&archived=&limit=&cursor=：字面搜索（≤120 字）、每页 1–50 默认 30、
     签名游标（15 分钟/版本绑定）失效或记录变化 409 → 刷新重读；顺序 created_at DESC,id ASC。
   - 新建仍 POST /api/life（record 带 url）；编辑仍 PATCH /api/life/{id}（patch:{title,content,url}，
     url=null 显式移除收藏属性后仍是原笔记）；归档/恢复同 life 语义，均带 request_key 幂等。
   - URL 校验与 App bookmark-url.ts 同规则：仅完整 http(s)；拒绝空白/控制符/反斜线/编码控制符/
     登录凭据/带 @ 或 % 的 authority/无效端口。只解析，不 DNS、不抓取、不预览。
   - 「打开网页」在渲染前重验 URL，外链 target=_blank rel="noopener noreferrer"。 */
(() => {
  if (document.documentElement.classList.contains("mobile-host")) return;
  const $ = id => document.getElementById(id);
  const esc = text => String(text ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const tz = () => Intl.DateTimeFormat().resolvedOptions().timeZone || "Asia/Shanghai";
  const dayText = value => new Date(value).toLocaleDateString("zh-CN",{month:"numeric",day:"numeric"});

  function validateUrl(value){
    if(typeof value!=="string"||!value||value.length>4096||/[\x00-\x20\x7f\\]|%(?:0[0-9a-f]|1[0-9a-f]|7f)/i.test(value)||!/^https?:\/\//i.test(value))
      throw new Error("请填写完整的 http 或 https 网页链接，不要包含空白或控制字符。");
    const authority=value.match(/^https?:\/\/([^/?#]+)/i)?.[1];
    let url;try{url=new URL(value);}catch{throw new Error("网页链接不完整，请检查后再保存。");}
    if(!authority||/[%@]/.test(authority)||!url.hostname||url.username||url.password||url.port==="0")
      throw new Error("请使用不带登录凭据的网页链接。");
    return value;
  }
  function safeHost(value){try{return new URL(validateUrl(value)).hostname;}catch{return null;}}

  const ui = {identity:null, epoch:0, query:"", lists:{active:{items:[],next:null},archived:{items:[],next:null}},
    mode:"list", detail:null, createOpen:false, attempt:null};

  const createJournal = () => `pajio-bookmark-create:v1:${state.identityId}`;
  const editJournal = id => `pajio-bookmark-edit:v1:${state.identityId}:${id}`;
  const actionJournal = (id,action,revision) => `pajio-bookmark-action:v1:${state.identityId}:${id}:${action}:${revision}`;
  const store = {
    get(name){try{return JSON.parse(window.WearingStore.get(name)||"null");}catch{return null;}},
    set(name,value){try{window.WearingStore.set(name,JSON.stringify(value));}catch{}},
    remove(name){try{window.WearingStore.remove(name);}catch{}},
  };
  function setNote(text){const note=$("bm-note");if(note)note.textContent=text||"";}

  /* ---------- 列表 ---------- */
  async function loadList(which,reset=true){
    const identity=state.identityId,epoch=state.identityEpoch;
    const cursor=reset?null:ui.lists[which].next;
    if(reset)ui.lists[which]={items:[],next:null};
    else if(!cursor)return;
    const params=new URLSearchParams({archived:String(which==="archived"),limit:"30"});
    if(ui.query)params.set("query",ui.query);
    if(cursor)params.set("cursor",cursor);
    let data;
    try{data=await api("/api/bookmarks?"+params);}
    catch(error){
      if(identity!==state.identityId||epoch!==state.identityEpoch||error instanceof StaleIdentity)return;
      if(error.status===409){setNote("收藏列表已有变化，正在重新读取。");await loadList(which,true);return;}
      setNote(error.message||"收藏暂时读不到，可稍后再试。");
      return;
    }
    if(identity!==state.identityId||epoch!==state.identityEpoch)return;
    ui.lists[which]={items:[...ui.lists[which].items,...data.items],next:data.next_cursor||null};
    if(ui.mode==="list")paintList();
  }
  async function refresh(){setNote("");await Promise.all([loadList("active",true),loadList("archived",true)]);}

  function rowMarkup(item){
    const host=safeHost(item.url);
    const open=host?`<a class="text-button" href="${esc(item.url)}" target="_blank" rel="noopener noreferrer">打开网页</a>`:"";
    return `<div class="pj-card"><div><strong>${esc(item.title||host||"未命名收藏")}</strong>
      <small>${esc(host||"链接无效")}${item.updated_at?" · "+esc(dayText(item.updated_at)):""}${item.content?" · "+esc(item.content.slice(0,40))+(item.content.length>40?"…":""):""}</small></div>
      <span class="brief-actions">${open}<button class="text-button" type="button" data-bm-open="${esc(item.id)}">查看</button>
      ${item.deleted_at?`<button class="text-button" type="button" data-bm-restore="${esc(item.id)}" data-bm-revision="${item.revision}">恢复</button>`:""}</span></div>`;
  }

  function paintList(){
    const active=ui.lists.active,archived=ui.lists.archived;
    $("bm-body").innerHTML=`
      <div class="brief-tools"><input id="bm-search" type="search" maxlength="120" placeholder="按标题、备注或链接搜索" value="${esc(ui.query)}" aria-label="搜索收藏">
        <button class="text-button" type="button" id="bm-refresh">刷新</button></div>
      <button class="text-button" type="button" id="bm-create-toggle">${ui.createOpen?"收起新建":"新建收藏"}</button>
      ${ui.createOpen?createMarkup():""}
      <section class="pj-section"><p class="pj-section-title">收藏 · ${active.items.length}${active.next?"（已加载部分）":""}</p>
        ${active.items.map(rowMarkup).join("")||'<p class="pj-note">还没有收藏链接。保存一条，之后从这里打开。</p>'}
        ${active.next?`<button class="pj-load-more" type="button" data-bm-more="active">继续查看</button>`:""}
        ${active.items.length>=300?'<p class="pj-note">已加载较多收藏，请用搜索缩小范围后继续。</p>':""}
      </section>
      <details class="setup-guide"><summary>已归档的收藏 · ${archived.items.length}</summary>
        ${archived.items.map(rowMarkup).join("")||'<p class="pj-note">没有归档的收藏。</p>'}
        ${archived.next?`<button class="pj-load-more" type="button" data-bm-more="archived">继续查看</button>`:""}
      </details>
      <p class="pj-note">收藏只是保存链接；只有你点「打开网页」时才会由浏览器访问，保存不代表网页存在或安全。</p>`;
    const search=$("bm-search");
    let debounce=0;
    search.addEventListener("input",()=>{clearTimeout(debounce);debounce=setTimeout(()=>{ui.query=search.value.trim();refresh();},350);});
    $("bm-refresh").addEventListener("click",()=>busy($("bm-refresh"),refresh));
    $("bm-create-toggle").addEventListener("click",()=>{ui.createOpen=!ui.createOpen;paintList();});
    const form=$("bm-create-form");
    if(form)form.addEventListener("submit",event=>{event.preventDefault();saveCreate(form);});
  }

  function createMarkup(){
    return `<form id="bm-create-form" class="pj-panel">
      <label class="field-help" for="bm-create-url">网页链接（http 或 https）</label>
      <input id="bm-create-url" maxlength="4096" required placeholder="https://example.com/page">
      <label class="field-help" for="bm-create-title">标题 · 可不填，默认用网站名</label>
      <input id="bm-create-title" maxlength="200">
      <label class="field-help" for="bm-create-content">备注 · 可不填</label>
      <textarea id="bm-create-content" rows="3" maxlength="12000"></textarea>
      <p class="inline-feedback" role="status"></p>
      <button class="secondary msg-submit" type="submit">保存收藏</button></form>`;
  }

  async function saveCreate(form){
    const feedback=form.querySelector(".inline-feedback");
    let url;try{url=validateUrl(form.querySelector("#bm-create-url").value.trim());}
    catch(error){feedback.textContent=error.message;return;}
    const title=form.querySelector("#bm-create-title").value.trim()||new URL(url).hostname;
    const content=form.querySelector("#bm-create-content").value.trim();
    const record={kind:"note",title,content,url,timezone:tz()};
    // 幂等：完整请求先持久，失败/未知沿用同一编号取回（对齐 life_create 合同）。
    const body={request_key:window.WearingIds.uuid().replaceAll("-",""),record};
    store.set(createJournal(),{identity:state.identityId,body});
    busy(form.querySelector(".msg-submit"),async()=>{
      try{
        const receipt=await api("/api/life",{method:"POST",body:JSON.stringify(body)});
        if(!receipt||typeof receipt.id!=="string"||receipt.url!==url)throw new Error("回执与本次保存不一致，已保留请求，可安全重试取回。");
        store.remove(createJournal());
        ui.createOpen=false;
        await refresh();
        setNote("收藏已保存。");
      }catch(error){
        if(error&&error.status){store.remove(createJournal());feedback.textContent=error.message||"这次保存没有成功。";return;}
        feedback.textContent=(error.message||"结果未知。")+" 将用同一请求取回，不会重复保存。";
      }
    },feedback);
  }

  /* ---------- 详情 / 编辑 ---------- */
  function paintDetail(){
    const item=ui.detail;
    const host=safeHost(item.url);
    $("bm-body").innerHTML=`<p class="brief-actions"><button class="text-button" type="button" id="bm-back">← 返回收藏</button></p>
      <article class="pj-card"><div><strong>${esc(item.title||host||"收藏")}</strong>
        <small>${item.created_at?"收藏于 "+esc(dayText(item.created_at)):""} · 修订 ${item.revision}</small>
        ${item.url?`<p class="pj-note">${esc(item.url)}</p>`:'<p class="pj-note">这条已没有链接，是普通笔记。</p>'}
        ${host?`<a class="text-button" href="${esc(item.url)}" target="_blank" rel="noopener noreferrer">打开网页</a>`:""}</div></article>
      <form id="bm-edit-form" class="pj-panel">
        <label class="field-help" for="bm-edit-title">标题</label><input id="bm-edit-title" maxlength="200" value="${esc(item.title||"")}">
        <label class="field-help" for="bm-edit-url">网页链接 · 清空后保存即移除收藏属性，仍保留为笔记</label>
        <input id="bm-edit-url" maxlength="4096" value="${esc(item.url||"")}">
        <label class="field-help" for="bm-edit-content">备注</label>
        <textarea id="bm-edit-content" rows="4" maxlength="12000">${esc(item.content||"")}</textarea>
        <p class="inline-feedback" role="status"></p>
        <div class="brief-actions"><button class="secondary msg-submit" type="submit">保存修改</button></div>
      </form>
      <button class="text-button life-remove" type="button" id="bm-archive">移到最近移除</button>`;
    $("bm-back").addEventListener("click",()=>{ui.mode="list";ui.detail=null;paintList();});
    $("bm-edit-form").addEventListener("submit",event=>{event.preventDefault();saveEdit(event.currentTarget);});
    $("bm-archive").addEventListener("click",()=>{
      const button=$("bm-archive");
      button.dataset.confirm=String(Number(button.dataset.confirm||0)+1);
      if(button.dataset.confirm==="1"){button.textContent="确认移除？会进入最近移除，可恢复";setTimeout(()=>{if(button.dataset.confirm==="1"){button.dataset.confirm="";button.textContent="移到最近移除";}},4000);return;}
      button.dataset.confirm="";button.textContent="移到最近移除";
      busy(button,async()=>{
        await patchLife(item.id,item.revision,{},"archive");
        ui.mode="list";ui.detail=null;
        await refresh();
        setNote("收藏已移到最近移除；从这里或最近移除列表可以恢复。");
      });
    });
  }

  async function saveEdit(form){
    const feedback=form.querySelector(".inline-feedback");
    const item=ui.detail;
    const urlInput=form.querySelector("#bm-edit-url").value.trim();
    let url=null;
    if(urlInput){try{url=validateUrl(urlInput);}catch(error){feedback.textContent=error.message;return;}}
    const values={title:form.querySelector("#bm-edit-title").value.trim()||(url?new URL(url).hostname:item.title),content:form.querySelector("#bm-edit-content").value.trim(),url};
    if(!values.title){feedback.textContent="先给这条收藏一个标题。";return;}
    const patch=Object.fromEntries(Object.entries(values).filter(([key,value])=>JSON.stringify(value??null)!==JSON.stringify((key==="url"?item.url??null:item[key])??null)));
    if(!Object.keys(patch).length){feedback.textContent="还没有改动。";return;}
    // 幂等 attempt：同 base revision + patch 用固定 request_key，失败/未知重放完全相同请求。
    const attemptKey=`${item.id}:${item.revision}:${JSON.stringify(patch)}`;
    if(ui.attempt?.key!==attemptKey)ui.attempt={key:attemptKey,request_key:window.WearingIds.uuid().replaceAll("-","")};
    const body={revision:item.revision,request_key:ui.attempt.request_key,action:"edit",patch};
    store.set(editJournal(item.id),{identity:state.identityId,body});
    busy(form.querySelector(".msg-submit"),async()=>{
      try{
        const receipt=await api("/api/life/"+item.id,{method:"PATCH",body:JSON.stringify(body)});
        if(!receipt||receipt.id!==item.id||receipt.revision!==item.revision+1)throw new Error("回执与本次保存不一致，已保留请求，可安全重试取回。");
        store.remove(editJournal(item.id));
        ui.attempt=null;
        ui.detail=receipt;
        if(patch.url===null){ui.mode="list";ui.detail=null;await refresh();setNote("已移除链接属性；这条仍是你的笔记。");return;}
        setNote("修改已保存。");
        paintDetail();
      }catch(error){
        if(error&&error.status===409){
          feedback.textContent=(error.message||"这条收藏已在别处修改。")+" 已重新读取最新内容，请核对后再保存。";
          await reloadDetailKeepForm(form);
          return;
        }
        if(error&&error.status){store.remove(editJournal(item.id));ui.attempt=null;feedback.textContent=error.message||"这次保存没有成功。";return;}
        feedback.textContent=(error.message||"结果未知。")+" 将用同一请求取回，不会重复保存。";
      }
    },feedback);
  }

  async function reloadDetailKeepForm(form){
    const identity=state.identityId;
    let latest;try{latest=await api("/api/life/"+ui.detail.id);}catch{latest=null;}
    if(identity!==state.identityId||!latest)return;
    const keep={title:form.querySelector("#bm-edit-title").value,url:form.querySelector("#bm-edit-url").value,content:form.querySelector("#bm-edit-content").value};
    ui.detail=latest;paintDetail();
    const fresh=$("bm-edit-form");
    fresh.querySelector("#bm-edit-title").value=keep.title;
    fresh.querySelector("#bm-edit-url").value=keep.url;
    fresh.querySelector("#bm-edit-content").value=keep.content;
    fresh.querySelector(".inline-feedback").textContent=latest.deleted_at?"这条收藏已被归档，先恢复才能继续编辑。":"已读取最新修订 "+latest.revision+"；你的输入仍保留在上方。";
  }

  async function patchLife(id,revision,patch,action){
    const name=actionJournal(id,action,revision);
    let request_key=window.WearingStore.get(name);
    if(!/^[A-Za-z0-9_-]{1,120}$/.test(request_key||"")){request_key=window.WearingIds.uuid().replaceAll("-","");window.WearingStore.set(name,request_key);}
    const receipt=await api("/api/life/"+id,{method:"PATCH",body:JSON.stringify({revision,patch,action,request_key})});
    window.WearingStore.remove(name);
    return receipt;
  }

  /* ---------- 面板事件 ---------- */
  $("bm-body").addEventListener("click",event=>{
    const open=event.target.closest("[data-bm-open]");
    if(open){const item=[...ui.lists.active.items,...ui.lists.archived.items].find(i=>i.id===open.dataset.bmOpen);
      if(item){ui.mode="detail";ui.detail=structuredClone(item);ui.attempt=null;setNote("");paintDetail();}return;}
    const more=event.target.closest("[data-bm-more]");
    if(more){busy(more,loadList(more.dataset.bmMore,false),$("bm-note"));return;}
    const restore=event.target.closest("[data-bm-restore]");
    if(restore){
      restore.dataset.confirm=String(Number(restore.dataset.confirm||0)+1);
      if(restore.dataset.confirm==="1"){restore.textContent="确认恢复？";setTimeout(()=>{if(restore.dataset.confirm==="1"){restore.dataset.confirm="";restore.textContent="恢复";}},4000);return;}
      restore.dataset.confirm="";restore.textContent="恢复";
      busy(restore,async()=>{
        await patchLife(restore.dataset.bmRestore,Number(restore.dataset.bmRevision),{},"restore");
        await refresh();
        setNote("收藏已恢复。");
      });
    }
  });

  async function resumePending(){
    const pending=store.get(createJournal());
    if(!pending||pending.identity!==state.identityId)return;
    setNote("发现未确认的收藏保存，正在用同一请求取回…");
    try{
      const receipt=await api("/api/life",{method:"POST",body:JSON.stringify(pending.body)});
      if(receipt&&typeof receipt.id==="string"){store.remove(createJournal());setNote("上一次收藏保存已确认。");await refresh();}
    }catch(error){
      if(error&&error.status){store.remove(createJournal());setNote(`上一次保存没有成功：${error.message||"请核对后重试。"}`);}
      else setNote("上一次保存仍未确认，稍后会继续用同一请求取回。");
    }
  }

  async function open(){
    ui.identity=state.identityId;
    $("bm-body").innerHTML='<p class="life-empty">正在读取收藏……</p>';
    openPanel("bookmarks-panel");
    await resumePending();
    await refresh();
  }
  window.WearingBookmarks={open,validateUrl};
})();
