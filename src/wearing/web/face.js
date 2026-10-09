/* A dedicated static portrait keeps the speaker recognizable in every reply. */
(() => {
  const portrait = "/assets/chat-portrait.png?v=1";
  window.wearingFaceMarkup = () => `<span class="wearing-face" role="img" aria-label="Pajio"><span class="wearing-face-picture"><img src="${portrait}" width="256" height="256" alt="" decoding="async"></span></span>`;
})();
