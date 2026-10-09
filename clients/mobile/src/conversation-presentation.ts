/** A network interface and an available Pajio service are separate facts.
 * Unknown connectivity is not proof that the device is offline; a LAN pairing
 * can remain usable without public internet access.
 */
export function isDeviceOffline(state: {type?: string; isConnected?: boolean}) {
  return state.type === 'NONE' || (state.type !== 'UNKNOWN' && state.isConnected === false);
}

export function canSubmitConversation({text, offline, sending, ready}: {text: string; offline: boolean; sending: boolean; ready: boolean}) {
  return ready && !offline && !sending && !!text.trim();
}

export function conversationFontScale(value: number) {
  return Number.isFinite(value) ? Math.min(3, Math.max(.85, value)) : 1;
}

/** Only text sizing crosses this bridge. Never reload the page, zoom its layout,
 * or alter the page/context/sequence receipt that owns the user's draft.
 */
export function conversationTextScaleScript(value: number) {
  const scale = conversationFontScale(value);
  return `if(document.documentElement){document.documentElement.style.setProperty('--app-font-scale','${scale}');} true;`;
}
