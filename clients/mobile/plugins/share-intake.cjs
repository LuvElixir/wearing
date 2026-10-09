const fs = require('node:fs');
const path = require('node:path');
const plist = require('@expo/plist').default;
const {withDangerousMod, withMainActivity} = require('@expo/config-plugins');
const withSharing = require('expo-sharing/app.plugin').default;

const APP_GROUP = 'group.io.luckyloading.wearing.mobile.share';
const MIME_TYPES = ['text/plain', 'image/jpeg', 'image/png', 'image/gif', 'image/heic', 'image/webp', 'application/pdf', 'text/markdown', 'application/zip', 'application/x-zip-compressed'];

module.exports = function withPajioShareIntake(config) {
  // The SDK 57 plugin expects one string although Expo permits multiple schemes.
  const schemes = config.scheme;
  // Mod callbacks execute in reverse registration order: register the override
  // first so the official plugin writes its template before we replace it.
  config = withDangerousMod(config, ['ios', async mod => {
    // Runs after expo-sharing creates its target. Keep its supported target and
    // entitlement plumbing, replace the experimental auto-open controller.
    const target = path.join(mod.modRequest.platformProjectRoot, 'expo-sharing-extension');
    fs.copyFileSync(path.join(__dirname, '../extensions/share-intake/ShareIntoViewController.swift'), path.join(target, 'ShareIntoViewController.swift'));
    const infoPath = path.join(target, 'Info.plist');
    const info = plist.parse(fs.readFileSync(infoPath, 'utf8'));
    info.CFBundleDisplayName = 'Pajio';
    delete info.MainTargetUrlScheme;
    fs.writeFileSync(infoPath, plist.build(info));
    return mod;
  }]);
  config = withSharing({...config, scheme: 'pajio'}, {
    ios: {enabled: true, appGroupId: APP_GROUP,
      extensionBundleIdentifier: `${config.ios.bundleIdentifier}.share`,
      activationRule: {supportsText: true, supportsWebUrlWithMaxCount: 1, supportsImageWithMaxCount: 4, supportsFileWithMaxCount: 4, supportsAttachmentsWithMaxCount: 4}},
    android: {enabled: true, singleShareMimeTypes: MIME_TYPES, multipleShareMimeTypes: MIME_TYPES.filter(type => type !== 'text/plain')},
  });
  config.scheme = schemes;
  return withMainActivity(config, mod => {
    if (mod.modResults.language !== 'kt') throw new Error('Pajio share intake expects Expo SDK 57 Kotlin MainActivity.');
    mod.modResults.contents = normalizeAndroidActivity(mod.modResults.contents);
    return mod;
  });
};
module.exports.APP_GROUP = APP_GROUP;

function normalizeAndroidActivity(source) {
  if (source.includes('// pajio-share-text-stream-v1')) return source;
  // SDK 57's text/plain parser otherwise drops EXTRA_STREAM-only text files.
  // The provider still supplies the actual MIME, and URI grant flags are intact.
  if (!/super\.onCreate\((null|savedInstanceState)\)/.test(source)) throw new Error('Cannot locate Android share cold-start hook.');
  source = source.replace(/super\.onCreate\((null|savedInstanceState)\)/, 'normalizePajioShareIntent(intent)\n    $&');
  if (/override fun onNewIntent\(/.test(source)) {
    const hook = /override fun onNewIntent\((\w+):\s*(?:android\.content\.)?Intent\??\)\s*\{/;
    if (!hook.test(source)) throw new Error('Cannot safely locate Android warm share hook.');
    source = source.replace(hook, '$&\n    normalizePajioShareIntent($1)');
  } else {
    const anchor = /override fun getMainComponentName\(\)/;
    if (!anchor.test(source)) throw new Error('Cannot locate Expo Android activity methods.');
    source = source.replace(anchor, 'override fun onNewIntent(intent: android.content.Intent) {\n    normalizePajioShareIntent(intent)\n    super.onNewIntent(intent)\n  }\n\n  $&');
  }
  return source + `
// pajio-share-text-stream-v1
private fun normalizePajioShareIntent(intent: android.content.Intent?) {
  if (intent?.action == android.content.Intent.ACTION_SEND &&
      intent.type == "text/plain" && intent.hasExtra(android.content.Intent.EXTRA_STREAM)) {
    intent.type = "application/octet-stream"
  }
}
`;
}
module.exports.normalizeAndroidActivity = normalizeAndroidActivity;
