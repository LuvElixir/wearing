"use strict";
/* Pajio 网页/桌面外观与个性化：日夜主题、八套睡衣衣橱、品牌字标与单星。
   数值与语义对齐 clients/mobile/src/appearance.ts 与 wardrobe.ts（只读参考）。
   App 宿主（?host=mobile）不进入本模块：主题由原生壳经 data-app-theme 桥接。 */
(() => {
  if (document.documentElement.classList.contains("mobile-host")) return;
  const $ = id => document.getElementById(id);

  /* ---------- 日夜外观：浅色 / 深色 / 跟随系统，选择持久保存 ---------- */
  const appearanceKey = "appearance:v1";
  const systemDark = matchMedia("(prefers-color-scheme: dark)");
  const theme = (() => {
    let preference = "system", ready = false, saving = false, error = "";
    const listeners = new Set();
    const read = () => {
      try {
        const saved = JSON.parse(localStorage.getItem(appearanceKey) || "null");
        preference = saved?.preference === "day" || saved?.preference === "night" ? saved.preference : "system";
      } catch { error = "暂时没能读取外观设置，请重试。"; }
      ready = true;
    };
    const mode = () => preference === "system" ? (systemDark.matches ? "night" : "day") : preference;
    const apply = () => {
      const value = mode();
      document.documentElement.dataset.appTheme = value;
      $("theme-color-meta")?.setAttribute("content", value === "night" ? "#191D22" : "#F8F7F3");
      listeners.forEach(listener => listener());
    };
    const onSystem = () => { if (preference === "system") apply(); };
    systemDark.addEventListener?.("change", onSystem);
    async function setPreference(value) {
      if (!ready || saving || !["day", "night", "system"].includes(value)) return false;
      saving = true; error = "";
      try {
        localStorage.setItem(appearanceKey, JSON.stringify({preference: value}));
        preference = value;
        apply();
        return true;
      } catch { error = "外观还没保存好，请再试一次。"; return false; }
      finally { saving = false; }
    }
    read(); apply();
    return {
      get preference() { return preference; }, get mode() { return mode(); },
      get ready() { return ready; }, get saving() { return saving; }, get error() { return error; },
      setPreference, subscribe: listener => { listeners.add(listener); return () => listeners.delete(listener); },
      reload: () => { error = ""; read(); apply(); },
    };
  })();

  /* ---------- 八套睡衣小熊：预览后显式保存，按身份隔离 ---------- */
  const outfits = [
    {id: "mist-blue", name: "雾蓝条纹", detail: "细条纹、奶油滚边，熟悉的柔软。", swatch: "#A9B9CC"},
    {id: "cream-moon", name: "奶油月牙", detail: "把一弯小月亮，收进睡衣口袋。", swatch: "#E8D7B9"},
    {id: "peach-check", name: "杏桃方格", detail: "杏桃格纹，配一圈小小的花瓣领。", swatch: "#DDB0A0"},
    {id: "oat-knit", name: "燕麦针织", detail: "软软的针织纹理，像刚晒好的毯子。", swatch: "#CABBA6"},
    {id: "cocoa-moon", name: "热可可", detail: "可可色的夜晚，落着奶白色月牙。", swatch: "#88614E"},
    {id: "butter-cloud", name: "黄油云朵", detail: "淡淡的黄油色，口袋是一朵云。", swatch: "#EDDC9F"},
    {id: "sage-check", name: "鼠尾草格纹", detail: "温柔的绿，和自然亚麻色的领口。", swatch: "#A4AC98"},
    {id: "rose-dot", name: "玫瑰奶点", detail: "低饱和的玫瑰色，洒一点奶白。", swatch: "#C49694"},
  ];
  const defaultOutfit = "mist-blue";
  const isOutfit = value => outfits.some(outfit => outfit.id === value);
  const outfitById = id => outfits.find(outfit => outfit.id === id);
  const wardrobeKey = (identity, version) => window.WearingStore.key(`wardrobe:v${version}:web:${identity}`);
  // 与 App 相同的读取迁移：无 v2 时只读 v1；启动不写回，用户显式选择才写 v2。
  // 简洁标记已随 App 移除：历史 symbol 存档按小熊显示并保留穿搭。
  function readSaved(identity) {
    try {
      const saved = JSON.parse(window.WearingStore.get(`wardrobe:v2:web:${identity}`) || "null");
      if (saved?.version === 2 && isOutfit(saved.outfit)) return {outfit: saved.outfit};
      const legacy = JSON.parse(window.WearingStore.get(`wardrobe:v1:web:${identity}`) || "null");
      if (legacy?.version === 1 && isOutfit(legacy.outfit)) return {outfit: legacy.outfit};
    } catch {}
    return null;
  }
  const wardrobe = (() => {
    let identity = null, state = {outfit: defaultOutfit, ready: false, saving: false, error: ""};
    const listeners = new Set();
    const publish = () => listeners.forEach(listener => listener());
    function identityChanged(next) {
      identity = next;
      const saved = readSaved(next);
      state = {outfit: saved?.outfit || defaultOutfit, ready: true, saving: false, error: ""};
      publish();
    }
    async function save(outfit) {
      if (!state.ready || state.saving || !isOutfit(outfit)) return false;
      if (outfit === state.outfit) return true;
      state = {...state, saving: true, error: ""};
      publish();
      try {
        window.WearingStore.set(`wardrobe:v2:web:${identity}`, JSON.stringify({version: 2, outfit, companion: "bear"}));
        state = {outfit, ready: true, saving: false, error: ""};
        publish();
        return true;
      } catch {
        state = {...state, saving: false, error: "形象设置还没保存好，点一下再试。"};
        publish();
        return false;
      }
    }
    return {
      get state() { return state; },
      identityChanged, save,
      subscribe: listener => { listeners.add(listener); return () => listeners.delete(listener); },
    };
  })();
  wardrobe.subscribe(() => paintChrome());
  theme.subscribe(() => paintChrome());

  /* ---------- 品牌标记与小熊 ---------- */
  const starPath = "M12 2C12.8 8.8 14.6 11.2 20 12C14.6 12.8 12.8 15.2 12 22C11.2 15.2 9.4 12.8 4 12C9.4 11.1 11.2 8.8 12 2Z";
  const starMarkup = (size = 22, label = "Pajio") =>
    `<svg class="pajio-star" viewBox="0 0 24 24" width="${size}" height="${size}" role="img" aria-label="${label}"><path fill="currentColor" d="${starPath}"/></svg>`;
  const wordmarkMarkup = (width = 76, label = "Pajio") =>
    `<svg class="pajio-wordmark" viewBox="12 20 574 240" width="${width}" height="${Math.round(width * 240 / 574)}" role="img" aria-label="${label}" fill="currentColor"><path fill-rule="evenodd" d="M36 32H94C132 32 156 54 156 90C156 125 134 148 96 148H56V196C56 203 51 206 41 206C31 206 26 203 26 196V43C26 36 30 32 36 32ZM56 59V121H94C115 121 128 109 128 90C128 70 115 59 94 59Z"/><path fill-rule="evenodd" d="M219 77C184 77 161 103 161 143C161 182 184 208 219 208C240 208 254 198 262 184V193C262 201 267 206 276 206C285 206 290 201 290 193V93C290 85 285 80 276 80C267 80 262 85 262 93V102C254 87 240 77 219 77ZM224 104C202 104 189 120 189 143C189 166 202 181 224 181C247 181 262 166 262 143C262 120 247 104 224 104Z"/><path fill-rule="evenodd" d="M322 93C322 85 327 81 336 81C345 81 350 85 350 93V202C350 234 331 252 300 252C286 252 277 247 277 237C277 230 282 225 289 225C294 225 296 226 300 226C314 226 322 217 322 202ZM351 47A15 15 0 1 1 321 47A15 15 0 1 1 351 47Z"/><path fill-rule="evenodd" d="M384 93C384 85 389 81 398 81C407 81 412 85 412 93V195C412 203 407 206 398 206C389 206 384 203 384 195ZM413 47A15 15 0 1 1 383 47A15 15 0 1 1 413 47Z"/><path fill-rule="evenodd" d="M508 77C548 77 572 103 572 143C572 183 548 209 508 209C468 209 444 183 444 143C444 103 468 77 508 77ZM508 104C486 104 472 120 472 143C472 167 486 182 508 182C530 182 544 167 544 143C544 120 530 104 508 104Z"/></svg>`;
  /* ---------- 小熊：实测 alpha 注册框（对齐 clients/mobile/src/bear-registration.ts） ---------- */
  // 1254px 源图的 alpha>100 包围盒；注册只是视图变换，不改原图。
  const bearBounds = {
    "mist-blue": [254, 62, 966, 1220], "cream-moon": [240, 38, 970, 1236],
    "peach-check": [251, 46, 957, 1219], "oat-knit": [246, 40, 956, 1207],
    "cocoa-moon": [223, 32, 983, 1217], "butter-cloud": [226, 38, 980, 1231],
    "sage-check": [232, 44, 955, 1218], "rose-dot": [236, 47, 978, 1216],
  };
  function bearFrame(outfit, size, portrait = false) {
    const [left, top, right, bottom] = bearBounds[outfit];
    const scale = size * .91 / (bottom - top);
    const width = 1254 * scale;
    const frame = {width, height: width, left: size / 2 - (left + right) / 2 * scale, top: size * .955 - bottom * scale};
    if (!portrait) return frame;
    // 头肩裁切填充小尺寸 UI 位置，而不是把整只熊缩小到看不清。
    const zoom = 1.92;
    return {width: width * zoom, height: width * zoom, left: size / 2 + (frame.left - size / 2) * zoom, top: frame.top * zoom - size * .05};
  }
  // CSP style-src 'self' 拦截标记里的 style 属性：所有尺寸/注册框只能经 CSSOM 赋值。
  // 标记只携带 data 参数，由 hydrateBear 在节点入文档后统一写入 .style.*。
  const bearMarkup = (outfit = wardrobe.state.outfit, size = 180, {portrait = false, label = ""} = {}) =>
    `<span class="pajio-bear${portrait ? " is-portrait" : ""}" data-bear-outfit="${outfit}" data-bear-size="${size}"${portrait ? ' data-bear-portrait="1"' : ""}${label ? ` role="img" aria-label="${label}"` : ' aria-hidden="true"'}><img src="/assets/bear/${outfit}.png" alt="" decoding="async" draggable="false"></span>`;
  function hydrateBear(scope = document) {
    for (const span of scope.querySelectorAll(".pajio-bear[data-bear-size]:not([data-bear-hydrated])")) {
      if (span.classList.contains("living")) {span.dataset.bearHydrated = "1"; continue;}
      const size = Number(span.dataset.bearSize);
      const frame = bearFrame(span.dataset.bearOutfit, size, span.dataset.bearPortrait === "1");
      span.style.width = size + "px";
      span.style.height = size + "px";
      const img = span.querySelector("img");
      if (img) {
        img.style.width = frame.width + "px";
        img.style.height = frame.height + "px";
        img.style.left = frame.left + "px";
        img.style.top = frame.top + "px";
      }
      span.dataset.bearHydrated = "1";
    }
  }
  // 任何视图注入的小熊（含 views.js 的衣橱/舞台/入口）在入文档后立即注水。
  const hydrateSoon = () => requestAnimationFrame(() => hydrateBear(document));
  new MutationObserver(hydrateSoon).observe(document.documentElement, {childList: true, subtree: true});
  // 八套图常驻解码：换装只在目标图 decode 成功后发生。
  const bearLoaded = new Set();
  for (const {id} of outfits) {
    const image = new Image();
    image.src = `/assets/bear/${id}.png`;
    const mark = () => bearLoaded.add(id);
    image.decode ? image.decode().then(mark, mark) : image.onload = mark;
    image.onerror = mark;
  }
  function bearReady(outfit) {
    return bearLoaded.has(outfit) ? Promise.resolve() : new Promise(resolve => {
      const started = Date.now();
      const check = () => bearLoaded.has(outfit) || Date.now() - started > 4000 ? resolve() : setTimeout(check, 60);
      check();
    });
  }

  /* ---------- 顶部进展入口的 Hypit 真实动作（仅雾蓝） ---------- */
  // 与 App LivingPajamaBear 同语义：静音、内联、无控件，播一次安静停留，每 23 秒一次；
  // 隐藏/离屏/减少动态效果时暂停并停在 poster，绝不连续不停动。其它睡衣保持各自静图。
  const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)");
  function mountLivingBear(chip) {
    const size = 52;
    // 视频/海报取景使用 App LivingPajamaBear 的视频构图（素材按此构图制作），
    // 不是静图 1254px 全身注册框——两者混用会把熊裁出可见圆。
    const frame = {width: size * 1.92, height: size * 1.92, left: -size * .46, top: -size * .04};
    chip.innerHTML = `<span class="pajio-bear is-portrait living" data-bear-outfit="mist-blue" data-bear-size="${size}" data-bear-portrait="1" aria-hidden="true">
      <video class="living-video" muted playsinline preload="auto" disablepictureinpicture src="/assets/motion/mist-blue-idle.mp4"></video>
      <img class="living-poster" src="/assets/motion/mist-blue-poster.jpg" alt="">
    </span>`;
    const span = chip.querySelector(".pajio-bear"), video = chip.querySelector("video"), poster = chip.querySelector(".living-poster");
    span.style.width = size + "px";
    span.style.height = size + "px";
    for (const node of [video, poster]) {
      node.style.width = frame.width + "px";
      node.style.height = frame.height + "px";
      node.style.left = frame.left + "px";
      node.style.top = frame.top + "px";
    }
    // poster 常驻底层：无焦点/自动播放被拒/暂停/离屏/首帧未就绪时，圆里永远是海报熊。
    // 视频仅在真实渲染出画面（requestVideoFrameCallback 双保险 playing+timeupdate）后淡入。
    let timer = 0, stopped = false;
    const visible = () => !document.hidden && chip.getBoundingClientRect().width > 0;
    const showPoster = () => video.classList.remove("is-live");
    const showVideo = () => {if (!stopped && !video.paused && !video.ended && !reducedMotion.matches) video.classList.add("is-live");};
    const onFrameReady = () => showVideo();
    if (video.requestVideoFrameCallback) video.requestVideoFrameCallback(() => onFrameReady());
    video.addEventListener("playing", onFrameReady);
    video.addEventListener("timeupdate", onFrameReady);
    video.addEventListener("pause", showPoster);
    video.addEventListener("ended", () => {showPoster(); scheduleGreet();});
    video.addEventListener("error", showPoster);
    function greet() {
      if (stopped) return;
      if (reducedMotion.matches || !visible() || video.error) {video.pause(); showPoster(); return;}
      video.currentTime = 0;
      video.play().catch(showPoster);
    }
    function scheduleGreet() {if (!stopped) {clearTimeout(timer); timer = setTimeout(greet, 23 * 1000);}}
    // 一次问候，然后安静停留： presence，不是任务进度模拟。
    greet();
    const observer = "IntersectionObserver" in window ? new IntersectionObserver(entries => {
      if (entries.some(entry => entry.isIntersecting) && !reducedMotion.matches && !document.hidden) return;
      video.pause(); showPoster();
    }) : null;
    observer?.observe(chip);
    document.addEventListener("visibilitychange", onVisibility);
    function onVisibility() {if (document.hidden) {video.pause(); showPoster();}}
    return () => {
      stopped = true;
      clearTimeout(timer);
      observer?.disconnect();
      document.removeEventListener("visibilitychange", onVisibility);
      video.pause();
    };
  }
  const livingChips = new Map();
  function paintChrome() {
    const {outfit} = wardrobe.state;
    for (const node of document.querySelectorAll("[data-pajio-chip]")) {
      if (node.dataset.pajioChip === "progress") {
        // 只有雾蓝顶部进展熊携带真实动作；其余睡衣与导航入口保持静图。
        if (node.dataset.outfit === outfit) continue;
        livingChips.get(node)?.();
        livingChips.delete(node);
        node.dataset.outfit = outfit;
        if (outfit === "mist-blue") livingChips.set(node, mountLivingBear(node));
        else node.innerHTML = bearMarkup(outfit, 52, {portrait: true});
      } else if (node.dataset.outfit !== outfit || !node.innerHTML) {
        node.dataset.outfit = outfit;
        node.innerHTML = bearMarkup(outfit, 26, {portrait: true});
      }
    }
    for (const node of document.querySelectorAll("[data-pajio-bear]")) {
      const size = Number(node.dataset.pajioBear) || 200;
      node.innerHTML = bearMarkup(outfit, size);
    }
  }

  window.WearingPajio = {
    theme, wardrobe, outfits, outfitById, defaultOutfit,
    starMarkup, wordmarkMarkup, bearMarkup, bearFrame, bearReady, paintChrome,
    identityChanged: id => wardrobe.identityChanged(id),
  };
  // 主题就绪后刷新一次界面上的形象触点；身份在 bootstrap 后由 views/life 接入。
  paintChrome();
})();
