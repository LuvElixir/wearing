/** Expo SDK 57 recorder paths. Only exact App-created recording files are eligible. */
export function managedRecordingUri(uri: string, documents: string, cache: string): boolean {
  const roots = [documents, cache].map(root => root.replace(/\/$/, '') + '/');
  for (const root of roots) {
    if (!uri.startsWith(root)) continue;
    const relative = uri.slice(root.length);
    if (/^(?:ExpoAudio|Audio)\/recording-[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}\.(?:m4a|wav|webm)$/i.test(relative)) return true;
    if (root === roots[0] && /^voice-takes\/voice-[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}\.wav$/i.test(relative)) return true;
  }
  return false;
}
