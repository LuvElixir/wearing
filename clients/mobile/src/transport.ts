import {fetch as expoFetch} from 'expo/fetch';
import {File} from 'expo-file-system';

// SDK 57 derives Blob headers from File.type. Private originals use UUID filenames,
// whose inferred type may be null on Android. Bytes preserve the validated MIME
// header supplied by WearingApi. Expo fetch buffers File bodies internally too.
export const serviceFetch: typeof fetch = async (input, init) => {
  if (init?.body instanceof File) {
    return (expoFetch as typeof fetch)(input, {...init, body: await init.body.arrayBuffer()});
  }
  return (expoFetch as typeof fetch)(input, init);
};
