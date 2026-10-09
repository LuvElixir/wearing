import * as Crypto from 'expo-crypto';
import {ArtifactApi, ArtifactMetadata} from './artifact-client';
import {shareOriginalBytes} from './workspace-share';

export async function digestArtifact(bytes: Uint8Array): Promise<string> {
  // The native Expo Crypto bridge expects a TypedArray. Copy only this view's
  // bytes so a subarray cannot accidentally include its backing buffer's tail.
  const result = await Crypto.digest(Crypto.CryptoDigestAlgorithm.SHA256, new Uint8Array(bytes));
  return Array.from(new Uint8Array(result), value => value.toString(16).padStart(2, '0')).join('');
}
/** The system sheet can save to Files or hand the verified original to another app. */
export async function shareArtifact(api: ArtifactApi, metadata: ArtifactMetadata, stillActive: () => boolean): Promise<void> {
  await shareOriginalBytes(() => api.original(metadata), `Pajio-${metadata.id}-v${metadata.revision}.html`, 'text/html', stillActive);
}
