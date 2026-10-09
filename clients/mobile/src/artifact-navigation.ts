import type {Connection} from './core';
export function artifactNavigationScript(identity: string) {
  return `(function(){if(window.__pajioArtifactNavigationV1)return;window.__pajioArtifactNavigationV1=true;document.addEventListener('click',function(event){const target=event.target instanceof Element?event.target.closest('[data-artifact]'):null;const id=target?.getAttribute('data-artifact');if(!/^art_[a-f0-9]{1,64}$/.test(id||''))return;event.preventDefault();event.stopImmediatePropagation();window.ReactNativeWebView?.postMessage(JSON.stringify({type:'pajio-open-artifact',identity:${JSON.stringify(identity)},id}));},true);})();true;`;
}
/** This bridge selects a read-only result view. All content is fetched again
 * through the authenticated API; it cannot grant any OS capability or run a tool. */
export function readArtifactNavigation(raw: string, source: string, connection: Connection): string | null {
  try {
    const url = new URL(source), expected = new URL(connection.endpoint);
    if (raw.length > 512 || url.origin !== expected.origin || url.pathname !== expected.pathname || url.username || url.password) return null;
    const value = JSON.parse(raw);
    if (value?.type !== 'pajio-open-artifact' || value.identity !== connection.identity || typeof value.id !== 'string' || !/^art_[a-f0-9]{1,64}$/.test(value.id) || Object.keys(value).some(key => !['type','identity','id'].includes(key))) return null;
    return value.id;
  } catch {return null;}
}
