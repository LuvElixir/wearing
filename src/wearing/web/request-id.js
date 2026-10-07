"use strict";
// Web Crypto randomUUID requires a secure context; getRandomValues also works
// in the authenticated LAN development WebView. Never weaken request IDs to
// timestamps or Math.random: they protect idempotent submissions and retries.
(() => {
  function uuid() {
    const source = globalThis.crypto;
    if (typeof source?.randomUUID === "function") return source.randomUUID();
    if (typeof source?.getRandomValues !== "function") throw Error("暂时无法生成提交编号，请重新打开应用。输入仍然保留。");
    const bytes = source.getRandomValues(new Uint8Array(16));
    bytes[6] = (bytes[6] & 15) | 64;
    bytes[8] = (bytes[8] & 63) | 128;
    const hex = Array.from(bytes, byte => byte.toString(16).padStart(2, "0")).join("");
    return [hex.slice(0, 8), hex.slice(8, 12), hex.slice(12, 16), hex.slice(16, 20), hex.slice(20)].join("-");
  }
  window.WearingIds = {uuid};
})();
