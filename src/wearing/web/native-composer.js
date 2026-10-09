"use strict";
// This bridge mirrors one composer. It cannot request native capabilities or send on its own.
(() => {
  const query = new URLSearchParams(location.search);
  if (query.get("host") !== "mobile" || query.get("composer") !== "native" ||
      typeof window.ReactNativeWebView?.postMessage !== "function") return;
  const input = document.getElementById("message-input"), form = document.getElementById("conversation-form");
  if (!input || !form) return;
  const pageId = window.crypto?.randomUUID?.() || "composer-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2);
  const voicePattern = /^voice-[a-f0-9-]{36}$/;
  const storageError = "草稿暂时无法保存在这台设备上，请保留输入后再试。";
  let ackSeq = 0, lastSeq = 0, ackVoiceId, ackVoiceIdentity, error = "", changing = false;

  function snapshot() {
    // app.js may still be bootstrapping; never export a previous identity's text as ready.
    try {
      const context = composerContext(), identity = state.identityId, contextKey = JSON.stringify(context);
      const ready = Boolean(composerReady && context.identity === identity && input.value.length <= 12000);
      const label = context.goal ? (context.goal.mode === "note" ? "补充新情况 · " : "聊聊这件事 · ") + context.goal.objective :
        context.life ? ({note: "笔记", event: "日程", task: "任务"}[context.life.kind] || "记录") + " · " + context.life.title : "";
      return {type: "wearing-composer-state", identity, pageId, contextKey, text: ready ? input.value : "",
        sending: Boolean(state.sending), ready, ackSeq, contextLabel: label.slice(0, 1000),
        ...(ackVoiceId && ackVoiceIdentity === identity ? {ackVoiceId} : {})};
    } catch {return null;}
  }
  function publish() {
    if (changing) return;
    const current = snapshot();
    if (!current) return;
    const feedback = document.getElementById("notice");
    const message = error || (!feedback?.hidden && feedback?.classList.contains("error") ? feedback.textContent : "");
    if (message) current.error = String(message).slice(0, 2000);
    try {window.ReactNativeWebView.postMessage(JSON.stringify(current));} catch { /* The host may have detached. */ }
  }
  function reject(message) {error = message; publish(); return false;}
  function remember() {
    try {return rememberComposer() === true;} catch {return false;}
  }
  function write(value) {
    input.value = value;
    input.dispatchEvent(new Event("input", {bubbles: true}));
    return remember();
  }
  function receiveVoice(command, current) {
    const key = "wearing-native-voice:v1:" + encodeURIComponent(current.identity) + ":" + command.voiceId;
    let receipt;
    try {receipt = JSON.parse(localStorage.getItem(key) || "null");} catch {return storageError;}
    if (receipt?.status === "received") {
      // A confirmed receipt survives sending, subsequent edits, context changes and page reloads.
      ackVoiceId = command.voiceId; ackVoiceIdentity = current.identity; return "";
    }
    if (receipt) {
      if (receipt.status !== "pending" || receipt.contextKey !== current.contextKey ||
          typeof receipt.before !== "string" || typeof receipt.after !== "string" || receipt.after.length > 12000 ||
          (input.value !== receipt.before && input.value !== receipt.after)) {
        return "这段语音的草稿已经变化，请先核对当前输入，语音原文仍保留。";
      }
    } else {
      const after = [input.value, command.text].filter(Boolean).join("\n");
      if (after.length > 12000) return "合并后的输入太长，请先发送或缩短当前草稿。";
      receipt = {status: "pending", contextKey: current.contextKey, before: input.value, after};
      // Journal before changing the draft: a reload between the two writes must not append twice.
      try {localStorage.setItem(key, JSON.stringify(receipt));} catch {return storageError;}
    }
    if (!write(receipt.after)) return storageError;
    try {localStorage.setItem(key, JSON.stringify({status: "received"}));} catch {return storageError;}
    ackVoiceId = command.voiceId; ackVoiceIdentity = current.identity;
    return "";
  }
  function command(payload) {
    const current = snapshot();
    if (!current || !payload || typeof payload !== "object" ||
        payload.identity !== current.identity || payload.pageId !== pageId || payload.contextKey !== current.contextKey) {
      return reject("输入位置已经变化，请在当前对话继续。");
    }
    if (!Number.isSafeInteger(payload.seq) || payload.seq < 0 || !["sync", "change", "send", "append"].includes(payload.kind)) {
      return reject("这次输入未被接收，请重新操作。");
    }
    if (payload.kind === "sync") {publish(); return true;}
    if (!current.ready) return reject("正在恢复这段对话的草稿，请稍候。");
    if (payload.seq <= lastSeq) {publish(); return false;}
    if (typeof payload.text !== "string" || payload.text.length > 12000 ||
        (payload.kind === "append" && (!voicePattern.test(payload.voiceId) || !payload.text.trim()))) {
      return reject("输入内容无效或超过 12000 字，请修改后重试。");
    }
    if (payload.kind === "send" && (current.sending || !payload.text.trim())) {
      return reject(current.sending ? "这条消息正在送出，请稍候。" : "先写一点内容再发送。");
    }
    // Consume before mutation, including failed persistence, so a late older edit cannot win.
    lastSeq = payload.seq; error = ""; changing = true;
    try {
      if (payload.kind === "append") error = receiveVoice(payload, current);
      else if (!write(payload.text)) error = storageError;
      if (!error && payload.kind === "send" && !form.checkValidity()) {
        error = input.validationMessage || "输入尚未符合当前内容要求，请修改后发送。";
      }
      if (!error) {
        ackSeq = payload.seq;
        if (payload.kind === "send") form.requestSubmit();
      }
    } catch {error = "输入暂时未完成，请保留原文后重试。";}
    finally {changing = false; publish();}
    return !error;
  }
  window.WearingHost = window.WearingHost || {};
  window.WearingHost.composerCommand = command;
  input.addEventListener("input", () => {if (!changing) error = ""; publish();});
  document.addEventListener("wearing-composer-ready", () => {error = ""; publish();});
  document.addEventListener("wearing-composer-state", publish);
  publish();
})();
