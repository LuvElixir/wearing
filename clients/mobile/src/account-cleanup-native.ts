import * as Crypto from 'expo-crypto';
import * as SecureStore from 'expo-secure-store';
import {Directory, File, Paths} from 'expo-file-system';
import {connectionEndpoint, scopeOf, type Connection} from './core';
import {clearDiagnosticErrors} from './diagnostics-client';
import {accountFences, prepareAccountCleanup, updateCleanupJournal, upsertState, type CleanupJournal} from './account-cleanup-state';
import {withNativeState} from './storage';
import {stopDeletedAccountWork} from './account-work';
import {managedRecordingUri} from './account-media';

const options = {keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY};
const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/;
export type AccountCleanupReport = {rowsRemoved: number; filesRemoved: number; pendingFiles: number; unownedLegacy: number; legacyCredentialInventoryIncomplete: true};
export async function isDeletedAccountLocal(connection: Connection): Promise<boolean> {
  if (!connection.session) return false;
  const address = connectionEndpoint(connection, true);
  return withNativeState(async db => (await accountFences(db)).some(row => row.address === address && row.userId === connection.session!.userId));
}
/** Call only after the gateway confirms the account's deletion request was admitted. */
export async function clearDeletedAccountLocalData(connection: Connection, optionsForCleanup?: {recordingUris: string[]}): Promise<AccountCleanupReport> {
  await stopDeletedAccountWork(connection);
  return withNativeState(async db => {
    const extraUris = optionsForCleanup?.recordingUris.filter(uri => managedRecordingUri(uri, Paths.document.uri, Paths.cache.uri)) || [];
    if (extraUris.length) {
      const key = 'recording-sources:v1:' + scopeOf(connection), row = await db.getFirstAsync<{value: string}>('SELECT value FROM local_state WHERE key = ?', key);
      const prior = row ? JSON.parse(row.value) as string[] : [];
      await upsertState(db, key, [...new Set([...prior, ...extraUris])]);
    }
    const journal = await prepareAccountCleanup(db, connection), remaining: CleanupJournal = {...journal, originals: [], uris: [], shareIds: [], scopes: [], credentialIds: []};
    let filesRemoved = 0;
    for (const id of journal.originals) {
      if (!uuid.test(id)) {remaining.originals.push(id); continue;}
      try {const file = new File(Paths.document, 'originals', id); if (file.exists) {file.delete(); filesRemoved++;}} catch {remaining.originals.push(id);}
    }
    for (const id of journal.shareIds) {
      if (!uuid.test(id)) {remaining.shareIds.push(id); continue;}
      try {const folder = new Directory(Paths.document, 'share-intake', id); if (folder.exists) {folder.delete(); filesRemoved++;}} catch {remaining.shareIds.push(id);}
    }
    const originalsRoot = new Directory(Paths.document, 'originals').uri.replace(/\/$/, '') + '/';
    const shareRoot = new Directory(Paths.document, 'share-intake').uri.replace(/\/$/, '') + '/';
    for (const uri of journal.uris) {
      // Only exact owned paths in directories created by Pajio. Never delete a
      // photo-library URI, arbitrary document or external provider's original.
      const voice = managedRecordingUri(uri, Paths.document.uri, Paths.cache.uri);
      const original = uri.startsWith(originalsRoot) && uuid.test(uri.slice(originalsRoot.length)) && journal.originals.includes(uri.slice(originalsRoot.length));
      const shared = uri.startsWith(shareRoot) && journal.shareIds.some(id => uuid.test(id) && uri.startsWith(shareRoot + id + '/') && /^[0-3]\.[a-z]{2,5}$/.test(uri.slice((shareRoot + id + '/').length)));
      if (!voice && !original && !shared) {remaining.uris.push(uri); continue;}
      try {const file = new File(uri); if (file.exists) {file.delete(); filesRemoved++;}} catch {remaining.uris.push(uri);}
    }
    for (const credentialId of journal.credentialIds) {
      if (!/^[A-Za-z0-9_-]{32,64}$/.test(credentialId)) {remaining.credentialIds.push(credentialId); continue;}
      try {await SecureStore.deleteItemAsync('pajio.session.' + credentialId, options);} catch {remaining.credentialIds.push(credentialId);}
    }
    for (const scope of journal.scopes) {
      try {await SecureStore.deleteItemAsync('pajio.native.' + await Crypto.digestStringAsync(Crypto.CryptoDigestAlgorithm.SHA256, scope), options);} catch {remaining.scopes.push(scope);}
    }
    // Keep the limited deletion receipt in Keychain; it cannot resume business access.
    await updateCleanupJournal(db, connection, remaining);
    clearDiagnosticErrors(connection);
    return {rowsRemoved: journal.rowsRemoved, filesRemoved, pendingFiles: remaining.originals.length + remaining.shareIds.length + remaining.uris.length + remaining.credentialIds.length + remaining.scopes.length, unownedLegacy: journal.unownedLegacy, legacyCredentialInventoryIncomplete: true};
  });
}
