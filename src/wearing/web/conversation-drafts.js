"use strict";
// Unsent text stays on this device/origin. Reading a draft never sends a message.
(() => {
  const prefix = "wearing-chat-draft:v1:";
  const text = (value, max) => typeof value === "string" && value.length <= max;
  function context(value) {
    if (!value || !text(value.identity, 64) || !value.identity) return null;
    const result = {identity: value.identity, goal: null, life: null};
    if (value.goal) {
      const g = value.goal;
      if (!text(g.id, 64) || !g.id || !text(g.objective, 2000) || !["discuss", "note"].includes(g.mode) || !Number.isInteger(g.revision) || g.revision < 1) return null;
      result.goal = {id: g.id, objective: g.objective, mode: g.mode, revision: g.revision};
    } else if (value.life) {
      const r = value.life;
      if (!text(r.id, 64) || !r.id || !text(r.title, 2000) || !["note", "event", "task"].includes(r.kind) || !Number.isInteger(r.revision) || r.revision < 1) return null;
      result.life = {id: r.id, title: r.title, kind: r.kind, revision: r.revision};
    }
    return result;
  }
  function key(value) {
    const c = context(value);
    if (!c) throw new Error("Draft context is incomplete");
    return prefix + [c.identity, c.goal ? "goal" : c.life ? "life" : "chat", c.goal?.id || c.life?.id || "", c.goal?.mode || ""].map(encodeURIComponent).join(":");
  }
  function create(storage, onError = () => {}) {
    const memory = new Map();
    function get(k) {if (memory.has(k)) return memory.get(k); try {return storage().getItem(k);} catch {onError(); return null;}}
    function put(k, value) {
      memory.set(k, value);
      try {value === null ? storage().removeItem(k) : storage().setItem(k, value); return true;} catch {onError(); return false;}
    }
    function read(c) {
      try {
        const value = JSON.parse(get(key(c)) || "null");
        if (!value || !context(value.context) || key(value.context) !== key(c) || !text(value.text, 12000)) return null;
        return {context: context(value.context), text: value.text};
      } catch {return null;}
    }
    function last(identity) {
      try {const c = context(JSON.parse(get(prefix + "focus:" + encodeURIComponent(identity)) || "null")); return c?.identity === identity ? c : null;} catch {return null;}
    }
    function save(c, value) {
      const normalized = context(c);
      if (!normalized || !text(value, 12000)) return false;
      const saved = put(key(normalized), value ? JSON.stringify({context: normalized, text: value}) : null);
      return put(prefix + "focus:" + encodeURIComponent(normalized.identity), JSON.stringify(normalized)) && saved;
    }
    // Clear only the acknowledged snapshot; a newer edit must survive.
    function acknowledge(c, sent) {
      const current = read(c);
      if (current && current.text !== sent) return false;
      return put(key(c), null);
    }
    return {read, save, last, acknowledge, key};
  }
  window.WearingDrafts = {create};
})();
