"use strict";
/* Pajio 账号隔离存储层（P0）：同一网关 origin 下不同账号的草稿/流水/回执互不可见。
   可信 storage_scope 来自 bootstrap（gateway/worker 构造，客户端不可伪造）。
   - cloud + 有效 scope：localStorage 键加 `pajio:{scope}:` 前缀。
   - cloud 无 scope：仅内存（绝不读写 localStorage，也不读旧的无 scope 缓存、不迁移旧云草稿）。
   - local：沿用既有键（本机私有开发兼容，不作为云降级）。
   所有个人持久存储（草稿/发送流水/语音回执/brief/decision/export/记忆草稿/穿搭）
   必须经 WearingStore.* 取键；模块加载早于 bootstrap 时，先用内存占位，
   bootstrap 完成后由 app.js 调 WearingStore.bind() 切换到真实后端。 */
(() => {
  const memory = new Map();
  const memoryAdapter = {
    getItem: key => memory.has(key) ? memory.get(key) : null,
    setItem: (key, value) => {memory.set(key, String(value));},
    removeItem: key => {memory.delete(key);},
  };
  const validScope = value => typeof value === "string" && /^[0-9a-f]{64}$/.test(value);
  const store = {
    mode: "pending",           // pending | local | scoped | cloud-memory
    scope: null,
    get backend() { return this.mode === "cloud-memory" || this.mode === "pending" ? memoryAdapter : localStorage; },
    key(name) {
      if (this.mode === "scoped") return `pajio:${this.scope}:${name}`;
      return name; // local 兼容沿用旧键；pending/cloud-memory 仅内存
    },
    get(name) { try { return this.backend.getItem(this.key(name)); } catch { return null; } },
    set(name, value) { try { this.backend.setItem(this.key(name), value); return true; } catch { return false; } },
    remove(name) { try { this.backend.removeItem(this.key(name)); return true; } catch { return false; } },
    // Storage 兼容接口：WearingDrafts 等既有模块直接调 getItem/setItem/removeItem，
    // 同样走 scope 前缀（local 无前缀），不再误报存储不可用。
    getItem(name) { return this.get(name); },
    setItem(name, value) { this.set(name, value); },
    removeItem(name) { this.remove(name); },
  };
  function bind(deployment, scope) {
    const previous = store.mode === "scoped" ? store.scope : null;
    if (deployment === "local") {
      // 唯一允许沿用旧本机键的模式：明确的本机私有开发部署。
      store.mode = "local"; store.scope = null;
    } else if (deployment === "cloud" && validScope(scope)) {
      store.mode = "scoped"; store.scope = scope;
    } else {
      // cloud 无/伪 scope、unknown/undefined/失败：一律仅内存，绝不回落 local。
      store.mode = "cloud-memory"; store.scope = null;
    }
    // 账号/租户变化：清空内存态（旧内存草稿不带入新账号），localStorage 因键前缀天然隔离。
    memory.clear();
    return {previous, current: store.scope, mode: store.mode};
  }
  window.WearingStore = store;
  window.WearingStoreBind = bind;
})();
