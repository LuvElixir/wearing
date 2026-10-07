/* App shell owns global navigation; this flag grants no native capabilities. */
(() => {
  if (new URLSearchParams(location.search).get('host') !== 'mobile') return;
  document.documentElement.classList.add('mobile-host');
  if(new URLSearchParams(location.search).get('input')==='voice')document.documentElement.classList.add('native-voice-host');
  if(new URLSearchParams(location.search).get('composer')==='native')document.documentElement.classList.add('native-composer-host');
  // Only the embedded App owns the viewport. Browser pages retain their normal zoom.
  const viewport = document.querySelector('meta[name="viewport"]');
  viewport?.setAttribute('content', 'width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no,viewport-fit=cover');
  const stopZoom = event => {if (event.cancelable) event.preventDefault();};
  document.addEventListener('gesturestart', stopZoom, {passive: false});
  document.addEventListener('gesturechange', stopZoom, {passive: false});
  document.addEventListener('touchmove', event => {if (event.touches?.length > 1) stopZoom(event);}, {passive: false});
  document.addEventListener('dblclick', stopZoom, {passive: false});
  window.WearingHost = {
    hidden: false,
    setActive(active) {
      const hidden = active !== true;
      if (this.hidden === hidden) return;
      this.hidden = hidden;
      if (hidden) {
        document.querySelectorAll('video').forEach(video => video.pause());
        document.activeElement?.blur?.();
      }
      document.dispatchEvent(new Event('wearing-host-visibility'));
    },
  };

  // Presentation uses structured receipts only. Assistant prose is never an event.
  function taskChip(message) {
    const turn = message?.turn;
    if (!turn || typeof turn.id !== 'string' || !/^[-a-zA-Z0-9_]{1,64}$/.test(turn.id)) return null;
    const label = {starting: '任务正在开始', running: '任务进行中', waiting_for_approval: '有一步需要你确认',
      stopping: '正在停止任务', connection_lost: '连接中断', ambiguous: '执行结果待确认'}[turn.status];
    if (label) return {label, taskId: turn.id, active: ['starting', 'running'].includes(turn.status)};
    if (turn.status === 'draft' && message.queued) return {label: '任务已排队', taskId: turn.id, active: false};
    if (['goal_step', 'schedule_run'].includes(message.kind) && ['completed_unverified', 'verified'].includes(turn.status)) {
      return {label: message.kind === 'schedule_run' ? '定时任务有新结果' : '任务有新进展', taskId: turn.id, active: false};
    }
    return null;
  }

  function setupConversation() {
    if (!document.documentElement.classList.contains('native-composer-host')) return;
    const messages = document.getElementById('messages');
    if (!messages) return;
    const seen = new Set();
    let initialized = false, searchPanel, searchInput, searchCount, searchPrevious, searchNext;
    let matches = [], selected = -1, searchOpen = false;
    const reduceMotion = () => window.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true;

    function clearMatches() {
      matches.forEach(node => node.classList.remove('host-search-match', 'host-search-current'));
      matches = []; selected = -1;
    }
    function navigateMatch(direction = 0) {
      if (!matches.length) return;
      matches[selected]?.classList.remove('host-search-current');
      selected = (selected + direction + matches.length) % matches.length;
      if (selected < 0) selected = 0;
      const match = matches[selected];
      match.classList.add('host-search-current');
      match.scrollIntoView({block: 'center', behavior: reduceMotion() ? 'auto' : 'smooth'});
      searchCount.textContent = `${selected + 1} / ${matches.length}`;
    }
    function findMatches(scroll = true) {
      clearMatches();
      const query = searchInput.value.trim().toLocaleLowerCase();
      if (query) {
        matches = [...messages.querySelectorAll('.user-bubble, .assistant-copy')]
          .filter(node => node.textContent.toLocaleLowerCase().includes(query));
        matches.forEach(node => node.classList.add('host-search-match'));
      }
      searchPrevious.disabled = searchNext.disabled = !matches.length;
      searchCount.textContent = query ? (matches.length ? `${matches.length} 处` : '没有找到') : '搜索当前对话';
      if (scroll && matches.length) {selected = 0; navigateMatch();}
    }
    function makeSearch() {
      searchPanel = document.createElement('section');
      searchPanel.className = 'host-search-panel';
      searchPanel.setAttribute('role', 'search');
      searchPanel.setAttribute('aria-label', '搜索当前对话');
      const field = document.createElement('div');
      field.className = 'host-search-field';
      searchInput = document.createElement('input');
      searchInput.type = 'search'; searchInput.placeholder = '搜索对话'; searchInput.maxLength = 200;
      searchInput.setAttribute('aria-label', '搜索对话内容');
      searchInput.autocomplete = 'off';
      const close = document.createElement('button');
      close.type = 'button'; close.textContent = '完成';
      close.addEventListener('click', () => window.WearingHost.closeSearch());
      field.append(searchInput, close);
      const navigation = document.createElement('div');
      navigation.className = 'host-search-navigation';
      searchCount = document.createElement('span');
      searchCount.setAttribute('role', 'status'); searchCount.setAttribute('aria-live', 'polite');
      searchCount.textContent = '搜索当前对话';
      const button = (label, direction) => {
        const node = document.createElement('button'); node.type = 'button';
        node.textContent = label; node.disabled = true;
        node.addEventListener('click', () => navigateMatch(direction)); return node;
      };
      searchPrevious = button('上一处', -1); searchNext = button('下一处', 1);
      navigation.append(searchCount, searchPrevious, searchNext);
      searchPanel.append(field, navigation);
      document.body.append(searchPanel);
      searchInput.addEventListener('input', () => findMatches());
      searchInput.addEventListener('keydown', event => {
        if (event.key === 'Escape') window.WearingHost.closeSearch();
        if (event.key === 'Enter') {event.preventDefault(); navigateMatch(event.shiftKey ? -1 : 1);}
      });
    }
    window.WearingHost.openSearch = () => {
      if (!searchPanel) makeSearch();
      searchPanel.hidden = false; searchOpen = true;
      document.documentElement.classList.add('host-search-open');
      findMatches(false); searchInput.focus();
    };
    window.WearingHost.closeSearch = () => {
      if (!searchPanel) return;
      searchOpen = false; searchInput.blur(); searchPanel.hidden = true;
      clearMatches(); document.documentElement.classList.remove('host-search-open');
    };
    document.addEventListener('wearing-host-visibility', () => {
      if (window.WearingHost.hidden) window.WearingHost.closeSearch();
    });
    document.addEventListener('wearing-composer-ready', () => {
      if (searchInput) searchInput.value = '';
      window.WearingHost.closeSearch();
    });

    function decorate() {
      let records;
      try {records = state.messages;} catch {return;}
      if (!Array.isArray(records)) return;
      for (const message of records) {
        const id = message?.turn?.id;
        const turn = document.getElementById(`${message.kind === 'goal_step' ? 'goal-turn' : 'task-turn'}-${id}`);
        if (!turn) continue;
        if (!seen.has(id)) {if (initialized) turn.classList.add('host-new-turn'); seen.add(id);}
        const descriptor = taskChip(message);
        if (!descriptor || turn.querySelector('.host-event-chip')) continue;
        const chip = document.createElement('button');
        chip.type = 'button'; chip.className = 'host-event-chip';
        chip.dataset.active = String(descriptor.active);
        chip.setAttribute('aria-label', `${descriptor.label}，查看详情`);
        const dot = document.createElement('span'); dot.className = 'host-event-dot'; dot.setAttribute('aria-hidden', 'true');
        const copy = document.createElement('span'); copy.textContent = descriptor.label;
        const arrow = document.createElement('span'); arrow.textContent = '›'; arrow.setAttribute('aria-hidden', 'true');
        chip.append(dot, copy, arrow);
        chip.addEventListener('click', () => window.WearingActivity?.openTask(descriptor.taskId)
          ?.catch(() => notice('暂时打不开这件事，请重新查看进展。', true)));
        turn.append(chip);
      }
      initialized = true;
      if (searchOpen) findMatches(false);
    }
    new MutationObserver(decorate).observe(messages, {childList: true});
    decorate();
  }
  document.addEventListener('DOMContentLoaded', setupConversation, {once: true});
})();
