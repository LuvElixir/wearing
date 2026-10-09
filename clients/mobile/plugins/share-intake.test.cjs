const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const plist = require('@expo/plist').default;
const plugin = require('./share-intake.cjs');

test('official target generation is overridden after template copy, with only intake app-group', async () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'pajio-share-plugin-'));
  try {
    const config = plugin({_internal: {projectRoot: path.resolve(__dirname, '..')}, name: 'Pajio', slug: 'pajio-test', scheme: ['pajio', 'wearing'], ios: {bundleIdentifier: 'test.pajio', entitlements: {'existing': true}}, android: {package: 'test.pajio'}});
    assert.deepEqual(config.scheme, ['pajio', 'wearing']);
    assert.equal(config.ios.entitlements.existing, true);
    assert.deepEqual(config.ios.entitlements['com.apple.security.application-groups'], [plugin.APP_GROUP]);
    const ext = config.extra.eas.build.experimental.ios.appExtensions;
    assert.equal(ext.length, 1); assert.equal(ext[0].bundleIdentifier, 'test.pajio.share');
    await config.mods.ios.dangerous({...config, modRequest: {platformProjectRoot: directory, projectRoot: path.resolve(__dirname, '..')}});
    const target = path.join(directory, 'expo-sharing-extension');
    assert.equal(fs.readFileSync(path.join(target, 'ShareIntoViewController.swift'), 'utf8'), fs.readFileSync(path.join(__dirname, '../extensions/share-intake/ShareIntoViewController.swift'), 'utf8'));
    const info = plist.parse(fs.readFileSync(path.join(target, 'Info.plist'), 'utf8'));
    assert.equal(info.CFBundleDisplayName, 'Pajio'); assert.equal(info.MainTargetUrlScheme, undefined);
    assert.equal(info.NSExtension.NSExtensionPointIdentifier, 'com.apple.share-services');
    assert.equal(info.NSExtension.NSExtensionAttributes.NSExtensionActivationRule.NSExtensionActivationSupportsImageWithMaxCount, 4);
    const entitlements = plist.parse(fs.readFileSync(path.join(target, 'expo-sharing-extension.entitlements'), 'utf8'));
    assert.deepEqual(Object.keys(entitlements), ['com.apple.security.application-groups']);
    assert.deepEqual(entitlements['com.apple.security.application-groups'], [plugin.APP_GROUP]);
  } finally {fs.rmSync(directory, {recursive: true, force: true});}
});

test('Android scheme remains a string and only supported SEND MIME types are declared', async () => {
  const config = plugin({_internal: {projectRoot: path.resolve(__dirname, '..')}, name: 'Pajio', slug: 'pajio-test', scheme: ['pajio', 'wearing'], ios: {bundleIdentifier: 'test.pajio'}, android: {package: 'test.pajio'}});
  const strings = await config.mods.android.strings({...config, modRequest: {}, modResults: {resources: {}}});
  assert.equal(strings.modResults.resources.string.find(s => s.$.name === 'share_into_scheme')._, 'pajio');
  const activity = {$: {'android:name': '.MainActivity'}, 'intent-filter': []};
  await config.mods.android.manifest({...config, modRequest: {}, modResults: {manifest: {application: [{activity: [activity]}]}}});
  assert.equal(activity['intent-filter'].length, 2);
  assert.deepEqual(activity['intent-filter'].map(f => f.action[0].$['android:name']), ['android.intent.action.SEND', 'android.intent.action.SEND_MULTIPLE']);
  const types = activity['intent-filter'].flatMap(f => f.data.map(d => d.$['android:mimeType']));
  assert(types.includes('application/pdf')); assert(types.includes('text/plain')); assert(!types.includes('*/*')); assert(!types.includes('text/html'));
});

test('Android text-stream hook covers cold/warm start, preserves existing callback and is idempotent', () => {
  const base = 'class MainActivity {\n override fun onCreate(savedInstanceState: Bundle?) { super.onCreate(null) }\n override fun getMainComponentName(): String = "main"\n}';
  const output = plugin.normalizeAndroidActivity(base);
  assert(output.indexOf('normalizePajioShareIntent(intent)') < output.indexOf('super.onCreate(null)'));
  assert(output.includes('super.onNewIntent(intent)'));
  assert(output.includes('intent.hasExtra(android.content.Intent.EXTRA_STREAM)'));
  assert.equal(plugin.normalizeAndroidActivity(output), output);
  const warm = base.replace('override fun getMainComponentName()', 'override fun onNewIntent(received: Intent) { super.onNewIntent(received) }\n override fun getMainComponentName()');
  const modified = plugin.normalizeAndroidActivity(warm);
  assert(modified.includes('normalizePajioShareIntent(received)')); assert(modified.includes('super.onNewIntent(received)'));
  assert.throws(() => plugin.normalizeAndroidActivity('unknown template'));
});
