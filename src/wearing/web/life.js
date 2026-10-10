"use strict";
(() => {
  const el = id => document.getElementById(id);
  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone || "Asia/Shanghai";
  const life = {identity:null, view:"chat", items:[], version:null, loading:false, loadError:null, captureKind:"note", captureKey:null, editor:null, createKey:null, calendar:null, calendarView:innerWidth<700?"listWeek":"dayGridMonth", calendarDate:null, dragging:false};
  const draftFields=["life-edit-title","life-edit-content","life-edit-all-day","life-edit-start","life-edit-end","life-edit-list","life-edit-completed","life-edit-due"];
  function fieldValues(){return Object.fromEntries(draftFields.map(id=>[id,el(id).type==="checkbox"?el(id).checked:el(id).value]));}
  function draftKey(record){return `wearing-life-editor:${life.identity}:${record.id||"new-"+record.kind}`;}
  function rememberEditor(){if(!life.editor||el("life-editor").hidden)return;try{const key=draftKey(life.editor),values=fieldValues();if(JSON.stringify(values)===life.editorInitial)sessionStorage.removeItem(key);else sessionStorage.setItem(key,JSON.stringify({record:life.editor,values,createKey:life.createKey,initial:life.editorInitial}));}catch{}}
  function forgetEditor(record){try{sessionStorage.removeItem(draftKey(record));}catch{}}
  function rememberCapture(){if(!life.identity)return;try{sessionStorage.setItem(`wearing-life-capture:${life.identity}`,JSON.stringify({text:el("life-capture-text").value,kind:life.captureKind,start:el("life-capture-start").value,end:el("life-capture-end").value,key:life.captureKey}));}catch{}}
  function restoreCapture(){try{const draft=JSON.parse(sessionStorage.getItem(`wearing-life-capture:${life.identity}`)||"null");if(draft&&["note","task","event"].includes(draft.kind)){document.querySelector(`[data-life-kind="${draft.kind}"]`).click();el("life-capture-text").value=draft.text||"";el("life-capture-start").value=draft.start||"";el("life-capture-end").value=draft.end||"";life.captureKey=draft.key||null;}}catch{}}
  const names = {event:"日程", task:"任务", note:"笔记"};
  const headings = {today:["今天","真实任务的进展、结果，和需要你处理的事。"], capture:["补记记录","也可以直接核对和修改已有内容。"], calendar:["日历","核对时间和安排，有变化可以直接修改。"], tasks:["任务","交给 Pajio 的事、待办与定时安排。"], notes:["笔记","查看原话和整理后的内容，随时修正。"], trash:["最近移除。","想留下的记录，随时可以恢复。"], memory:["记忆","Pajio 为当前身份记下的事与文件。"], me:["我的","账户、连接与能力，都来自真实状态。"]};
  const pad = n => String(n).padStart(2,"0");
  const localDay = d => `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}`;
  const localInput = value => {if(!value)return "";const d=new Date(value);return `${localDay(d)}T${pad(d.getHours())}:${pad(d.getMinutes())}`;};
  const humanDate = value => new Date(value).toLocaleDateString("zh-CN",{month:"long",day:"numeric"});
  const timeText = value => new Date(value).toLocaleTimeString("zh-CN",{hour:"2-digit",minute:"2-digit",hour12:false});
  function timed(value){if(!value)throw new Error("请先填好开始和结束时间。");const d=new Date(value);if(!Number.isFinite(d.valueOf()))throw new Error("时间格式不完整，请重新选择。");return d.toISOString();}
  function defaultTimes(day=null){const d=day?new Date(day+"T09:00"):new Date();d.setSeconds(0,0);if(!day){d.setMinutes(Math.ceil(d.getMinutes()/30)*30);if(d<=new Date())d.setMinutes(d.getMinutes()+30);}const end=new Date(d.valueOf()+3600000);return [localInput(d),localInput(end)];}
  function feedback(message,error=false,undo=null){const box=el("life-feedback");box.hidden=!message;box.classList.toggle("is-error",error);box.replaceChildren(document.createTextNode(message));if(undo){const button=document.createElement("button");button.textContent=undo.label;button.addEventListener("click",()=>run(button,undo.action));box.append(button);}}
  async function run(button,action){button.disabled=true;try{await action();}catch(error){if(!(error instanceof StaleIdentity))feedback(error.message||"暂时没保存成功，请稍后重试。",true);}finally{button.disabled=false;}}
  async function load(force=false){
    if(!state.token||life.loading)return;
    if(life.identity!==state.identityId)identityChanged();
    const identity=state.identityId;life.loading=true;
    try{const query=new URLSearchParams({include_deleted:"true"});if(!force&&life.version!==null)query.set("after",life.version);const snapshot=await api("/api/life?"+query);
      if(identity!==life.identity)return;
      if(life.loadError&&el("life-feedback").textContent===life.loadError)feedback("");life.loadError=null;
      if(snapshot.unchanged)return;
      life.items=snapshot.items;life.version=snapshot.version;render();
    }catch(error){if(!(error instanceof StaleIdentity)){const message="记录暂时没打开，可以稍后再试。";feedback(message,true);life.loadError=message;el("life-content").setAttribute("aria-busy","false");}}
    finally{life.loading=false;}
  }
  function identityChanged(){
    const initialText=life.identity===null?el("life-capture-text").value:"";
    rememberCapture();rememberEditor();
    life.identity=state.identityId;state.lifeFocus=null;renderContext();life.items=[];life.version=null;life.captureKey=null;life.editor=null;life.createKey=null;el("life-capture-text").value="";feedback("");closeEditor();window.WearingViews?.reset?.();window.WearingSeries?.reset?.();window.WearingPajio?.identityChanged?.(state.identityId);
    window.WearingCapture?.identityChanged();
    restoreCapture();
    if(initialText){el("life-capture-text").value=initialText;rememberCapture();}
    if(life.calendar){life.calendar.destroy();life.calendar=null;}
    el("life-content").replaceChildren();el("life-content").setAttribute("aria-busy","true");
    const p=document.createElement("p");p.className="life-empty";p.textContent="正在打开这个身份的记录……";el("life-content").append(p);
  }
  const reviewViews=["calendar","tasks","notes"];
  const reviewByIdentity=new Map();
  const scrollPositions=new Map();
  function openReview(){
    let view=reviewByIdentity.get(state.identityId);
    if(!view)try{view=sessionStorage.getItem('wearing-review:'+state.identityId);}catch{}
    setView(reviewViews.includes(view)?view:"calendar");
  }
  function setView(view){
    if(!["chat","today","capture","calendar","tasks","notes","trash","memory","me"].includes(view))view="chat";
    if(el("review-panel").open)el("review-panel").close();
    if(view!==life.view)scrollPositions.set(state.identityId+':'+life.view,window.scrollY);
    if(reviewViews.includes(view)){reviewByIdentity.set(state.identityId,view);try{sessionStorage.setItem('wearing-review:'+state.identityId,view);}catch{}}
    feedback("");
    const previous=life.view;
    life.view=view;document.body.dataset.view=view;document.body.classList.toggle("life-mode",view!=="chat");el("life-main").hidden=view==="chat";el("conversation-main").hidden=view!=="chat";
    updateCompactEntry();
    window.WearingCapture?.viewChanged(view);
    document.querySelector(".skip-link").setAttribute("href",view==="chat"?"#conversation-main":"#life-main");
    document.querySelectorAll("[data-life-view]").forEach(button=>{if(button.dataset.lifeView===view)button.setAttribute("aria-current","page");else button.removeAttribute("aria-current");});
    try{sessionStorage.setItem("wearing-life-view",view);}catch{}
    const restoreScroll=()=>requestAnimationFrame(()=>{if(life.view===view)window.scrollTo({top:scrollPositions.get(state.identityId+':'+view)||0,behavior:'instant'});});
    if(previous!==view)restoreScroll();
    if(view==="chat"){rememberEditor();return;}
    const heading=headings[view];el("life-title").textContent=heading[0];el("life-subtitle").textContent=heading[1];
    el("life-capture-form").hidden=view!=="capture";el("life-greeting-avatar").hidden=view!=="capture";el("life-add").hidden=view!=="calendar";
    el("life-add").textContent={calendar:"手动补充日程",tasks:"手动补充任务",notes:"手动补充笔记"}[view]||"新建";
    el("life-series-add").hidden=view!=="calendar";
    closeEditor();render();load();
  }
  function taskRow(item){return `<div class="life-row ${item.completed?"is-complete":""}"><button class="life-toggle" aria-pressed="${item.completed}" aria-label="${item.completed?"重新打开":"完成"}：${esc(item.title)}" data-life-complete="${item.id}"><span>${item.completed?'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m5 12 4 4L19 6"/></svg>':""}</span></button><button class="life-row-main" data-life-open="${item.id}"><strong>${esc(item.title)}</strong><small>${esc(item.due_at?humanDate(item.due_at)+" "+timeText(item.due_at)+" 截止":item.list_name)}</small></button></div>`;}
  function eventRow(item){return `<div class="life-row"><span class="life-time">${item.all_day?"全天":esc(timeText(item.start_at))}</span><button class="life-row-main" data-life-open="${item.id}"><strong>${esc(item.title)}</strong><small>${esc(item.all_day?"留给这一天":timeText(item.start_at)+" – "+timeText(item.end_at))}</small></button></div>`;}
  function noteRow(item){const preview=item.content.startsWith(item.title)?item.content.slice(item.title.length).trim():item.content;return `<button class="life-note-item" data-life-open="${item.id}" ${life.editor?.id===item.id?'aria-current="true"':""}><strong>${esc(item.title)}</strong>${preview?`<p>${esc(preview.slice(0,140))}${preview.length>140?"…":""}</p>`:""}${item.capture?`<span class="capture-meta">${esc(window.WearingCapture?.stages[item.capture.state]||"附有原件")}</span>`:""}<time datetime="${esc(item.updated_at)}">${esc(humanDate(item.updated_at))}</time></button>`;}
  function empty(message){return `<p class="life-empty">${esc(message)}</p>`;}
  function render(){
    if(life.version===null||life.dragging)return;
    el("life-content").setAttribute("aria-busy","false");
    if(life.editor?.id){const latest=life.items.find(item=>item.id===life.editor.id);window.WearingCapture?.renderOriginals(latest||life.editor);if(latest&&!latest.deleted_at&&latest.revision!==life.editor.revision&&JSON.stringify(fieldValues())===life.editorInitial){life.editor=null;openEditor(latest);}}
    const items=life.items.filter(i=>!i.deleted_at), today=localDay(new Date());
    const tasks=items.filter(i=>i.kind==="task");const events=items.filter(i=>i.kind==="event").sort((a,b)=>a.start_at.localeCompare(b.start_at));const notes=items.filter(i=>i.kind==="note");
    el("life-list-names").innerHTML=[...new Set(tasks.map(i=>i.list_name))].map(name=>`<option value="${esc(name)}"></option>`).join("");
    if(life.view==="chat")return;
    if(life.view!=="calendar"&&life.calendar){life.calendar.destroy();life.calendar=null;}
    if(life.view==="memory"||life.view==="me"||life.view==="today"){window.WearingViews?.render(life.view,el("life-content"));return;}
    if(life.view==="calendar"){renderCalendarViews(events);return;}
    if(life.view==="capture"){
      const dayStart=new Date(today+"T00:00"),dayEnd=new Date(dayStart);dayEnd.setDate(dayEnd.getDate()+1);
      const agenda=events.filter(i=>i.all_day?i.start_at<=today&&i.end_at>today:new Date(i.start_at)<dayEnd&&new Date(i.end_at)>dayStart);
      const smallTasks=tasks.filter(i=>!i.completed).slice(0,6);
      el("life-content").innerHTML=`<div class="life-today"><section><div class="life-section-heading"><h2>${esc(new Date().toLocaleDateString("zh-CN",{month:"long",day:"numeric",weekday:"long"}))}</h2><button class="text-button" data-life-new="event">安排一件小事</button></div>${agenda.length?agenda.map(eventRow).join(""):empty("今天还很空。散步、打个电话，先给一件小事留点时间。")}</section><section><div class="life-section-heading"><h2>惦记着的事</h2><button class="text-button" data-life-new="task">加一件</button></div>${smallTasks.length?smallTasks.map(taskRow).join(""):empty("想起来的事先放这里。做完一件，就轻一点。")}${tasks.filter(i=>!i.completed).length>6?'<button class="text-button" data-life-go="tasks">看看全部任务</button>':""}</section></div><section class="life-notes-recent"><div class="life-section-heading"><h2>最近记下的</h2><button class="text-button" data-life-go="notes">打开笔记</button></div>${notes.length?notes.slice(0,3).map(noteRow).join(""):empty("一个还没成形的想法，也可以先留在这里。")}</section>`;
    }else if(life.view==="tasks"){
      const lists=[...new Set(tasks.map(i=>i.list_name))].sort();
      el("life-content").innerHTML=`<div id="agent-tasks-section" aria-label="交给 Pajio 的事"></div>`+(lists.length?lists.map(name=>{const group=tasks.filter(i=>i.list_name===name).sort((a,b)=>Number(a.completed)-Number(b.completed));return `<section class="life-task-group"><h2>${esc(name)}</h2>${group.map(taskRow).join("")}</section>`;}).join(""):empty("还没有待办。交代的事和 Pajio 整理出的任务会出现在这里。"));
      window.WearingViews?.renderTasks(document.getElementById("agent-tasks-section"));
      if(!document.getElementById("task-lists-section")){const listsSection=document.createElement("div");listsSection.id="task-lists-section";listsSection.setAttribute("aria-label","我的清单");document.getElementById("agent-tasks-section").after(listsSection);}
      window.WearingViews?.renderTaskLists?.(document.getElementById("task-lists-section"));
    }else if(life.view==="notes"){
      el("life-content").innerHTML=notes.length?notes.map(noteRow).join(""):empty("还没有笔记。Pajio 整理出的想法和资料会出现在这里。");
    }else if(life.view==="trash"){
      const archived=life.items.filter(i=>i.deleted_at);
      el("life-content").innerHTML=archived.length?archived.map(i=>`<div class="life-row"><div class="life-row-main"><strong>${esc(i.title)}</strong><small>${esc(names[i.kind])} · ${esc(humanDate(i.deleted_at))} 移除</small></div><button class="secondary" data-life-restore="${i.id}">恢复</button></div>`).join(""):empty("没有移除的记录。移除后会留在这里，方便找回来。");
    }
  }
  const calViews={mode:sessionStorage.getItem("pajio-cal-view")||"month",anchor:new Date(),selected:null,shown:100};
  function saveCalMode(mode){calViews.mode=mode;try{sessionStorage.setItem("pajio-cal-view",mode);}catch{}}
  function dayKey(d){return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}`;}
  function endOfDayExclusive(item){if(!item.all_day)return new Date(item.end_at);const d=new Date(item.end_at+"T00:00");return isNaN(d)?new Date(item.end_at):d;}
  function eventOnDay(item,date){const dayStart=new Date(dayKey(date)+"T00:00"),dayEnd=new Date(dayStart);dayEnd.setDate(dayEnd.getDate()+1);
    if(item.all_day){const start=new Date(item.start_at+"T00:00"),end=endOfDayExclusive(item);return start<dayEnd&&end>dayStart;}
    return new Date(item.start_at)<dayEnd&&endOfDayExclusive(item)>dayStart;}
  function renderCalendarViews(events){
    // innerHTML 会替换容器；旧 FullCalendar 实例必须先销毁，否则同视图重渲染（数据轮询更新）会把网格画进已脱离的旧容器。
    if(life.calendar){life.calendar.destroy();life.calendar=null;}
    const all=events.filter(i=>!i.deleted_at);
    // 月视图沿用 FullCalendar；周/议程为原生条目列表
    if(calViews.mode==="month"){el("life-content").innerHTML='<div class="life-calendar"><div class="life-calendar-views" aria-label="日历视图"><button class="text-button" data-cal-view="dayGridMonth" aria-pressed="true">月</button><button class="text-button" data-cal-view="timeGridWeek" aria-pressed="false">周</button><button class="text-button" data-cal-view="agenda" aria-pressed="false">议程</button></div><div id="life-calendar-root"></div></div><p class="life-help">点日期安排日程，点日程修改。重复日程用右上「重复日程」管理；打开日程可按开始时间设置提醒。</p>';
      mountFullCalendar(all);return;}
    const isWeek=calViews.mode==="timeGridWeek";
    const anchor=new Date(calViews.anchor);
    const days=[];const start=new Date(anchor);
    if(isWeek){const dow=(start.getDay()+6)%7;start.setDate(start.getDate()-dow);for(let i=0;i<7;i++){const d=new Date(start);d.setDate(start.getDate()+i);days.push(d);}}
    else{for(let i=0;i<30;i++){const d=new Date(anchor);d.setDate(anchor.getDate()+i);days.push(d);}}
    // 去重：同一记录跨多日只计一次
    const seen=new Set();let rows="";
    let rendered=0;
    const entries=[];
    for(const d of days){
      const dayEvents=all.filter(i=>eventOnDay(i,d));
      if(!dayEvents.length)continue;
      const allDayFirst=dayEvents.filter(i=>i.all_day).concat(dayEvents.filter(i=>!i.all_day));
      entries.push({date:new Date(d),items:allDayFirst});
    }
    for(const entry of entries){
      if(rendered>=calViews.shown)break;
      rows+=`<p class="life-section-heading" role="heading"><h2>${entry.date.toLocaleDateString("zh-CN",{month:"long",day:"numeric",weekday:"long"})}</h2></p>`;
      for(const item of entry.items){
        if(rendered>=calViews.shown)break;
        if(!seen.has(item.id)){seen.add(item.id);}
        const spansDays=!item.all_day&&endOfDayExclusive(item)-new Date(item.start_at)>86400000;
        const timeLabel=item.all_day?"全天":spansDays?"此前开始":pad(new Date(item.start_at).getHours())+":"+pad(new Date(item.start_at).getMinutes());
        rows+=`<div class="life-row"><span class="life-time">${timeLabel}</span><button class="life-row-main" data-life-open="${item.id}"><strong>${esc(item.title)}</strong><small>${spansDays?"延续至次日 / "+pad(new Date(item.end_at).getHours())+":"+pad(new Date(item.end_at).getMinutes()):item.all_day?"留给这一天":""}</small></button></div>`;
        rendered++;
      }
    }
    el("life-content").innerHTML=`<div class="life-calendar"><div class="life-calendar-views" aria-label="日历视图"><button class="text-button" data-cal-view="dayGridMonth" aria-pressed="false">月</button><button class="text-button" data-cal-view="timeGridWeek" aria-pressed="${isWeek}">周</button><button class="text-button" data-cal-view="agenda" aria-pressed="${!isWeek}">议程</button></div>
      <div class="cal-nav"><button class="text-button" data-cal-prev>上一${isWeek?"周":"段"}</button><button class="text-button" data-cal-today>回到今天</button><button class="text-button" data-cal-next>下一${isWeek?"周":"段"}</button></div>
      <div class="cal-entries">${rows||'<p class="life-empty">这个范围还没有日程。</p>'}</div>
      ${rendered>=calViews.shown?`<button class="text-button" data-cal-more>继续查看（已显示 ${rendered} 条，去重后共 ${seen.size} 条）</button>`:""}
      </div><p class="life-help">议程从所选日期起连续三十天；跨日日程分别展示但总数按记录去重。</p>`;
    const windowEnd=new Date(days[days.length-1]);windowEnd.setDate(windowEnd.getDate()+1);
    window.WearingSeries?.decorate?.(dayKey(days[0]),dayKey(windowEnd));
  }
  function mountFullCalendar(all){
    const switchers=el("life-content").querySelectorAll("[data-cal-view]");
    switchers.forEach(b=>b.addEventListener("click",()=>{saveCalMode(b.dataset.calView==="dayGridMonth"?"month":b.dataset.calView==="timeGridWeek"?"timeGridWeek":"agenda");calViews.shown=100;renderCalendarViews(all.map(i=>i));}));
    buildCalendar(all);
  }
  function buildCalendar(all){
    if(life.calendar&&el("life-calendar-root")){life.calendar.batchRendering(()=>{life.calendar.removeAllEvents();all.forEach(item=>life.calendar.addEvent(calendarEvent(item)));});return;}
    life.calendar=new FullCalendar.Calendar(el("life-calendar-root"),{initialView:"dayGridMonth",locale:"zh-cn",firstDay:1,height:"auto",contentHeight:560,headerToolbar:{left:"title",center:"",right:"prev,next"},allDayText:"全天",noEventsContent:"这一周还没有安排。",editable:true,selectable:true,selectMirror:true,dayMaxEvents:3,nowIndicator:true,events:all.map(calendarEvent),
      eventClick:info=>{const record=life.items.find(i=>i.id===info.event.id);if(record)openEditor(record);else window.WearingSeries?.openInstance?.(info.event.id);},
      dateClick:info=>{const day=info.dateStr.slice(0,10);openEditor(null,"event",day);},
      select:info=>{openEditor(null,"event",info.startStr.slice(0,10));if(!info.allDay){el("life-edit-start").value=localInput(info.startStr);el("life-edit-end").value=localInput(info.endStr);}life.calendar.unselect();},
      eventDragStart:()=>life.dragging=true,eventResizeStart:()=>life.dragging=true,
      eventDrop:moveEvent,eventResize:moveEvent,
      eventDragStop:()=>life.dragging=false,eventResizeStop:()=>life.dragging=false,
      datesSet:info=>{document.querySelectorAll("[data-cal-view]").forEach(b=>b.setAttribute("aria-pressed",b.dataset.calView===info.view.type));window.WearingSeries?.decorate?.(dayKey(info.view.currentStart),dayKey(info.view.currentEnd));},
    });life.calendar.render();
  }
  function renderCalendar(events){
    if(life.calendar&&el("life-calendar-root")){life.calendar.batchRendering(()=>{life.calendar.removeAllEvents();events.forEach(item=>life.calendar.addEvent(calendarEvent(item)));});return;}
    el("life-content").innerHTML='<div class="life-calendar"><div class="life-calendar-views" aria-label="日历视图"><button class="text-button" data-cal-view="dayGridMonth" aria-pressed="false">月</button><button class="text-button" data-cal-view="timeGridWeek" aria-pressed="false">周</button><button class="text-button" data-cal-view="listWeek" aria-pressed="false">一周安排</button><button class="text-button" data-cal-today>回到今天</button></div><div id="life-calendar-root"></div></div><p class="life-help">点日期安排日程，点日程修改。桌面上也可以拖动调整时间。打开日程可按开始时间设置提醒。</p>';
    life.calendar=new FullCalendar.Calendar(el("life-calendar-root"),{initialView:life.calendarView,initialDate:life.calendarDate||new Date(),locale:"zh-cn",firstDay:1,height:"auto",contentHeight:560,headerToolbar:{left:"title",center:"",right:"prev,next"},allDayText:"全天",noEventsContent:"这一周还没有安排。给一件小事留点时间吧。",editable:true,selectable:true,selectMirror:true,dayMaxEvents:3,nowIndicator:true,events:events.map(calendarEvent),
      eventClick:info=>openEditor(life.items.find(i=>i.id===info.event.id)),
      dateClick:info=>{const day=info.dateStr.slice(0,10);openEditor(null,"event",day);},
      select:info=>{openEditor(null,"event",info.startStr.slice(0,10));if(!info.allDay){el("life-edit-start").value=localInput(info.startStr);el("life-edit-end").value=localInput(info.endStr);}life.calendar.unselect();},
      eventDragStart:()=>life.dragging=true,eventResizeStart:()=>life.dragging=true,
      eventDrop:moveEvent,eventResize:moveEvent,
      eventDragStop:()=>life.dragging=false,eventResizeStop:()=>life.dragging=false,
      datesSet:info=>{life.calendarView=info.view.type;life.calendarDate=info.view.currentStart;document.querySelectorAll("[data-cal-view]").forEach(b=>b.setAttribute("aria-pressed",b.dataset.calView===info.view.type));},
    });life.calendar.render();
  }
  function calendarEvent(item){return {id:item.id,title:item.title,start:item.start_at,end:item.end_at,allDay:item.all_day,color:"#4562dc",textColor:"#fff",extendedProps:{revision:item.revision}};}
  async function moveEvent(info){
    life.dragging=true;const record=life.items.find(i=>i.id===info.event.id);
    try{const patch={start_at:info.event.allDay?info.event.startStr.slice(0,10):info.event.start.toISOString(),end_at:info.event.allDay?info.event.endStr.slice(0,10):info.event.end.toISOString(),all_day:info.event.allDay};
      const saved=await api("/api/life/"+record.id,{method:"PATCH",body:JSON.stringify({revision:info.event.extendedProps.revision,patch})});feedback("日程时间已调整。",false,{label:"撤销",action:async()=>{await change(saved,{start_at:record.start_at,end_at:record.end_at,all_day:record.all_day});feedback("已恢复原来的时间。");}});
    }catch(error){info.revert();if(!(error instanceof StaleIdentity))feedback(error.message,true);}finally{life.dragging=false;await load(true);}
  }
  function closeEditor(){rememberEditor();life.editor=null;life.createKey=null;el("life-editor").hidden=true;el("life-workspace").classList.remove("has-editor");el("life-edit-reminder").replaceChildren();}
  function openEditor(record=null,kind="note",day=null){
    if(record?.deleted_at)return;
    rememberEditor();
    life.editor=record?structuredClone(record):{kind,timezone:tz};life.createKey=window.WearingIds.uuid();kind=life.editor.kind;
    el("life-editor").hidden=false;el("life-workspace").classList.add("has-editor");el("life-editor-heading").textContent=(record?"编辑 ":"新增 ")+names[kind];
    el("life-edit-title").value=record?.title||"";el("life-edit-content").value=record?.content||"";
    el("life-event-fields").hidden=kind!=="event";el("life-task-fields").hidden=kind!=="task";
    el("life-edit-all-day").checked=record?.all_day||false;setEditorTimeType();
    const times=defaultTimes(day);el("life-edit-start").value=record?.all_day?record.start_at:(localInput(record?.start_at)||times[0]);el("life-edit-end").value=record?.all_day?record.end_at:(localInput(record?.end_at)||times[1]);
    el("life-edit-list").value=record?.list_name||"待办";el("life-edit-completed").checked=record?.completed||false;el("life-edit-due").value=localInput(record?.due_at);
    el("life-edit-timezone").textContent=kind==="event"||kind==="task"?`时间以当前设备时区 ${tz} 显示。`:"";
    el("life-edit-archive").hidden=!record;el("life-edit-agent").hidden=!record;el("life-edit-error").hidden=true;el("life-edit-reload").hidden=true;el("life-latest").hidden=true;life.life409=null;
    life.editorInitial=JSON.stringify(fieldValues());
    try{const draft=JSON.parse(sessionStorage.getItem(draftKey(life.editor))||"null");if(draft){life.editor=draft.record;life.createKey=draft.createKey;life.editorInitial=draft.initial;el("life-edit-start").type=el("life-edit-end").type=draft.values["life-edit-all-day"]?"date":"datetime-local";for(const id of draftFields){if(el(id).type==="checkbox")el(id).checked=Boolean(draft.values[id]);else el(id).value=draft.values[id]||"";}feedback("还没保存的编辑，替你留着了。");}}catch{}
    window.WearingCapture?.renderOriginals(record);
    renderReminder();
    if(innerWidth<700)el("life-editor").scrollIntoView({block:"start",behavior:state.motionPaused?"instant":"smooth"});
    el("life-edit-title").focus({preventScroll:true});
  }
  function setEditorTimeType(){const allDay=el("life-edit-all-day").checked;for(const id of ["life-edit-start","life-edit-end"]){const input=el(id),old=input.value;input.type=allDay?"date":"datetime-local";input.value=allDay?old.slice(0,10):(old?old.slice(0,10)+"T09:00":"");}if(allDay&&el("life-edit-start").value&&el("life-edit-end").value<=el("life-edit-start").value){const end=new Date(el("life-edit-start").value+"T00:00");end.setDate(end.getDate()+1);el("life-edit-end").value=localDay(end);}el("life-edit-start").required=life.editor?.kind==="event";el("life-edit-end").required=life.editor?.kind==="event";}
  function editorDraft(){const kind=life.editor.kind, record={kind,title:el("life-edit-title").value.trim(),content:el("life-edit-content").value.trim(),timezone:tz};
    if(kind==="event"){record.all_day=el("life-edit-all-day").checked;record.start_at=record.all_day?el("life-edit-start").value:timed(el("life-edit-start").value);record.end_at=record.all_day?el("life-edit-end").value:timed(el("life-edit-end").value);}
    if(kind==="task"){record.list_name=el("life-edit-list").value.trim()||"待办";record.completed=el("life-edit-completed").checked;record.due_at=el("life-edit-due").value?timed(el("life-edit-due").value):null;}return record;
  }
  // 记录提醒（record-reminders 合同）：开关与提前量单独保存，不随表单提交；双 CAS 由服务端裁决。
  function renderReminder(){
    const host=el("life-edit-reminder"),record=life.editor;
    if(!record||!record.id||record.kind==="note"){host.replaceChildren();return;}
    window.WearingReminders?.render(host,record.id,record.revision,{anchor:record.kind==="task"?record.due_at:record.start_at,all_day:record.kind==="event"&&record.all_day,completed:record.kind==="task"&&record.completed,deleted:Boolean(record.deleted_at),label:record.kind==="task"?"截止时间":"开始时间"});
  }
  async function change(record,patch={},action="edit"){
    const body={revision:record.revision,patch,action};
    const journalKey=action==="edit"?null:`pajio-life-action:v1:${life.identity}:${record.id}:${action}:${record.revision}`;
    if(journalKey){
      // 归档/恢复幂等（offline-record-lifecycle 合同）：request_key 先经 WearingStore 持久，失败/未知沿用同 key 取原回执。
      let request_key=window.WearingStore.get(journalKey);
      if(!/^[A-Za-z0-9_-]{1,120}$/.test(request_key||"")){request_key=window.WearingIds.uuid().replaceAll("-","");window.WearingStore.set(journalKey,request_key);}
      body.request_key=request_key;
    }
    const result=await api("/api/life/"+record.id,{method:"PATCH",body:JSON.stringify(body)});
    if(journalKey)window.WearingStore.remove(journalKey);
    await load(true);return result;
  }
  function savedFeedback(record){feedback(`已记下这条${names[record.kind]}。`,false,{label:"和 Pajio 聊聊",action:async()=>talkAbout(record)});}
  function renderContext(){const focus=state.lifeFocus;el("life-chat-context").hidden=!focus;el("life-chat-title").textContent=focus?names[focus.kind]+" · "+focus.title:"";}
  function talkAbout(record){setView("chat");activateComposer({identity:state.identityId,life:{id:record.id,revision:record.revision,kind:record.kind,title:record.title}},"我们一起看看这条"+names[record.kind]+"。");el("message-input").focus();el("message-input").scrollIntoView({block:"center"});}
  document.querySelectorAll("[data-life-view]").forEach(button=>button.addEventListener("click",()=>setView(button.dataset.lifeView)));
  el("life-add").addEventListener("click",()=>openEditor(null,{calendar:"event",tasks:"task",notes:"note"}[life.view]));
  el("life-trash").addEventListener("click",()=>setView(life.view==="trash"?"today":"trash"));
  el("life-editor-close").addEventListener("click",closeEditor);el("life-edit-all-day").addEventListener("change",setEditorTimeType);
  document.querySelectorAll("[data-life-kind]").forEach(button=>button.addEventListener("click",()=>{life.captureKind=button.dataset.lifeKind;life.captureKey=null;document.querySelectorAll("[data-life-kind]").forEach(b=>b.setAttribute("aria-pressed",b===button));el("life-capture-times").hidden=life.captureKind!=="event";el("life-capture-start").required=el("life-capture-end").required=life.captureKind==="event";el("life-capture-help").textContent={note:"先留住想法，不必马上整理。",task:"先记成任务，完成后可以勾选。",event:"明确开始和结束时间，记进你自己的日历。"}[life.captureKind];if(life.captureKind==="event"){const times=defaultTimes();el("life-capture-start").value=times[0];el("life-capture-end").value=times[1];}}));
  el("life-capture-text").addEventListener("input",()=>{life.captureKey=null;rememberCapture();});
  for(const id of ["life-capture-start","life-capture-end"])el(id).addEventListener("input",()=>{life.captureKey=null;rememberCapture();});
  el("life-editor-form").addEventListener("input",rememberEditor);
  el("life-capture-form").addEventListener("submit",event=>{event.preventDefault();run(el("life-capture-save"),async()=>{
    await window.WearingCapture?.prepare();
    const text=el("life-capture-text").value.trim(),media=window.WearingCapture?.hasFiles();
    if(!text&&!media)throw new Error("先写下一点内容，或者放一份图片、录音吧。");
    life.captureKey ||= window.WearingIds.uuid();rememberCapture();const kind=life.captureKind;
    const record={kind,title:text?text.split("\n")[0].slice(0,200):"随手记下的",content:media||kind==="note"||text.length>200||text.includes("\n")?text:"",timezone:tz};
    if(kind==="event"){record.start_at=timed(el("life-capture-start").value);record.end_at=timed(el("life-capture-end").value);}
    const saved=media?await window.WearingCapture.submit(record,life.captureKey):await api("/api/life",{method:"POST",body:JSON.stringify({record,request_key:life.captureKey})});
    el("life-capture-text").value="";life.captureKey=null;rememberCapture();await load(true);savedFeedback(saved);
  });});
  el("life-editor-form").addEventListener("submit",async event=>{event.preventDefault();const button=el("life-edit-save");button.disabled=true;el("life-edit-error").hidden=true;const editor=life.editor;
    try{const record=editorDraft();let saved;if(editor.id){const patch=Object.fromEntries(Object.entries(record).filter(([key,value])=>JSON.stringify(value)!==JSON.stringify(editor[key])));
      // 幂等 attempt：同一 base revision+patch 用固定 request_key，网络失败重试重放完全相同请求（对齐 offline-record-edits 合同）。
      const attemptKey=editor.id+":"+editor.revision+":"+JSON.stringify(patch);
      if(life.editAttempt?.key!==attemptKey)life.editAttempt={key:attemptKey,request_key:window.WearingIds.uuid()};
      saved=await api("/api/life/"+editor.id,{method:"PATCH",body:JSON.stringify({revision:editor.revision,patch,request_key:life.editAttempt.request_key})});
      life.editAttempt=null;await load(true);}else{saved=await api("/api/life",{method:"POST",body:JSON.stringify({record,request_key:life.createKey})});await load(true);}forgetEditor(editor);life.editor=null;openEditor(saved);feedback(`${names[saved.kind]} 已保存。`);}
    catch(error){if(!(error instanceof StaleIdentity)){el("life-edit-error").textContent=error.message;el("life-edit-error").hidden=false;el("life-edit-reload").hidden=!(editor.id&&error.status===409);}}
    finally{button.disabled=false;}
  });
  // 409 恢复：并排展示最新版本，明确二选一（对齐 App RecordDetail 合同）——
  // 「保留我的输入」沿用当前表单内容、仅换用最新 revision；「采用最新内容」载入最新版本。
  function apply409Choice(action, latest){
    if(action==="keep"){
      life.editor={...latest};
      life.editorInitial=null;
      el("life-edit-error").hidden=true;
      el("life-latest").hidden=true;
      feedback("已保留你的输入，核对后再保存。");
      return;
    }
    forgetEditor(life.editor);
    life.editor=null;
    if(latest.deleted_at){closeEditor();feedback("这条记录已在最近移除；需要时可以恢复。");}
    else openEditor(latest);
  }
  el("life-latest").addEventListener("click",event=>{
    const keep=event.target.closest("[data-life-409-keep]"),latestButton=event.target.closest("[data-life-409-latest]");
    if(keep&&life.life409)apply409Choice("keep",life.life409);
    else if(latestButton&&life.life409)apply409Choice("latest",life.life409);
  });
  el("life-edit-reload").addEventListener("click",()=>run(el("life-edit-reload"),async()=>{const current=await api("/api/life/"+life.editor.id);life.life409=current;const panel=el("life-latest");panel.hidden=false;panel.replaceChildren(document.createTextNode(`最新版本：${current.title}\n${current.content}\n${current.deleted_at?"这条记录已被移除。":"你的输入仍在上方，可保留或采用最新内容。"}`));const keep=document.createElement("button");keep.type="button";keep.className="secondary";keep.setAttribute("data-life-409-keep","1");keep.textContent="保留我的输入";keep.hidden=!!current.deleted_at;const latestButton=document.createElement("button");latestButton.type="button";latestButton.className="secondary";latestButton.setAttribute("data-life-409-latest","1");latestButton.textContent=current.deleted_at?"收起这条记录":"采用最新内容";panel.append(keep,latestButton);}));
  el("life-edit-agent").addEventListener("click",()=>talkAbout(life.editor));
  el("life-edit-archive").addEventListener("click",()=>{
    const button=el("life-edit-archive");
    // 先说明范围再确认（offline-record-lifecycle 合同）：移入最近移除，原件与未保存编辑保留，可随时恢复。
    button.dataset.confirm=String(Number(button.dataset.confirm||0)+1);
    if(button.dataset.confirm==="1"){button.textContent="确认移除？会进入最近移除，可恢复";setTimeout(()=>{if(button.dataset.confirm==="1"){button.dataset.confirm="";button.textContent="移到最近移除";}},4000);return;}
    button.dataset.confirm="";button.textContent="移到最近移除";
    run(button,async()=>{const original=life.editor;const saved=await change(original,{},"archive");closeEditor();forgetEditor(original);feedback("已放到最近移除。",false,{label:"撤销",action:async()=>{await change(saved,{},"restore");feedback("记录已恢复。");}});});
  });
  el("life-content").addEventListener("click",async event=>{
    const target=event.target.closest("button");if(!target)return;
    if(target.dataset.lifeOpen){const item=life.items.find(i=>i.id===target.dataset.lifeOpen);if(item)openEditor(item);}
    if(target.dataset.lifeNew)openEditor(null,target.dataset.lifeNew);
    if(target.dataset.lifeGo)setView(target.dataset.lifeGo);
    if(target.dataset.lifeComplete)run(target,async()=>{const item=life.items.find(i=>i.id===target.dataset.lifeComplete);await change(item,{completed:!item.completed});});
    if(target.dataset.lifeRestore){
      target.dataset.confirm=String(Number(target.dataset.confirm||0)+1);
      if(target.dataset.confirm==="1"){target.textContent="确认恢复？回到原列表";setTimeout(()=>{if(target.dataset.confirm==="1"){target.dataset.confirm="";target.textContent="恢复";}},4000);return;}
      target.dataset.confirm="";target.textContent="恢复";
      run(target,async()=>{const item=life.items.find(i=>i.id===target.dataset.lifeRestore);await change(item,{},"restore");feedback("记录已恢复。");});
    }
    if(target.dataset.calView)life.calendar?.changeView(target.dataset.calView);
    if(target.hasAttribute("data-cal-today"))life.calendar?.today();
  });
  document.querySelector(".wordmark").addEventListener("click",()=>setView("chat"));
  function quickCapture(){
    rememberEditor();setView("capture");
    el("life-capture-form").scrollIntoView({block:"center",behavior:"instant"});
    el("life-capture-text").focus({preventScroll:true});
  }
  window.addEventListener("wearing:quick-capture",quickCapture);
  async function openFromLink(){
    const query=new URLSearchParams(location.search),id=query.get("life_record");
    if(!id){const requested=query.get("view");setView(["calendar","tasks","notes","capture","today","memory","me"].includes(requested)?requested:"chat");return;}
    if(life.identity!==state.identityId)identityChanged();
    try{
      if(!/^life_[a-f0-9]{32}$/.test(id))throw new Error("记录入口不完整");
      const record=await api("/api/life/"+id);if(record.deleted_at)throw new Error("这条记录已移除");
      talkAbout(record);
      const revision=Number(query.get("life_revision"));if(Number.isInteger(revision)&&revision>0&&record.revision!==revision)notice("这条记录已经更新，已接上最新版本。");
    }catch(error){setView("chat");notice("这条记录暂时没打开，请返回原记录核对后再继续。",true);}
  }
  window.WearingLife={quickCapture,identityChanged,openReview,openView:setView,renderContext,openFromLink,refresh:()=>load(true),calendar:()=>life.calendar};
  // 非聊天阅读页的紧凑输入入口：回到聊天继续同一份草稿，不新开输入面。
  function updateCompactEntry(){
    const entry=el("compact-entry");
    if(!entry)return;
    // App 宿主由原生壳提供紧凑输入，这里不重复入口。
    const show=!["chat","capture"].includes(life.view)&&!document.documentElement.classList.contains("mobile-host");
    entry.hidden=!show;
    if(!show)return;
    const draft=el("message-input").value.trim();
    el("compact-entry-label").innerHTML=draft?`<strong>继续草稿</strong> · ${esc(draft.slice(0,40))}${draft.length>40?"…":""}`:"<strong>交代一件事</strong>";
  }
  el("compact-entry").addEventListener("click",()=>{setView("chat");el("message-input").focus();el("message-input").scrollIntoView({block:"center",behavior:"instant"});});
  document.addEventListener("wearing-composer-state",updateCompactEntry);
  el("life-chat-clear").addEventListener("click",()=>{activateComposer({identity:state.identityId});el("message-input").focus();});
  el("life-chat-title").addEventListener("click",()=>run(el("life-chat-title"),async()=>{const record=await api("/api/life/"+state.lifeFocus.id);setView({note:"notes",task:"tasks",event:"calendar"}[record.kind]);openEditor(record);}));
  setView("chat");
  setInterval(()=>{if(!document.hidden&&!window.WearingHost?.hidden&&window.WearingDeletion?.workAllowed?.()!==false){if(life.identity!==state.identityId&&state.token)identityChanged();if(!life.dragging)load();}},1800);
  window.addEventListener("focus",()=>load());
  window.addEventListener("beforeunload",()=>{rememberCapture();rememberEditor();});
  const visibility=()=>{if(document.hidden||window.WearingHost?.hidden){rememberCapture();rememberEditor();}else load();};
  document.addEventListener("visibilitychange",visibility);
  document.addEventListener("wearing-host-visibility",visibility);
})();
