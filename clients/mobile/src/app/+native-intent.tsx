import {completeNativeSignIn} from '../native-session';

export async function redirectSystemPath({path}: {path: string; initial: boolean}) {
  try {
    const url = new URL(path, 'pajio://app');
    if (url.protocol === 'pajio:' && url.hostname === 'expo-sharing') return '/?view=share-intake';
    if (url.protocol === 'pajio:' && url.hostname === 'auth') {
      const connection = await completeNativeSignIn(path);
      return '/?view=conversation&authDone=' + connection.session!.credentialId;
    }
    return path;
  } catch {return '/?view=connection&authError=1';}
}
