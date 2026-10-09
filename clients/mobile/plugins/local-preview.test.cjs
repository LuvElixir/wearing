const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const {parseStringPromise} = require('xml2js');
const plugin = require('./local-preview.cjs');

test('generated Android network policy only grants exact loopback HTTP and keeps backups disabled', async () => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'pajio-network-policy-'));
  try {
    const config = plugin({_internal: {projectRoot: path.resolve(__dirname, '..')}, name: 'Pajio', slug: 'pajio-test', android: {package: 'test.pajio'}});
    const app = {$: {'android:name': '.MainApplication'}};
    await config.mods.android.manifest({...config, modRequest: {}, modResults: {manifest: {application: [app]}}});
    assert.equal(app.$['android:allowBackup'], 'false');
    assert.equal(app.$['android:usesCleartextTraffic'], 'false');
    assert.equal(app.$['android:networkSecurityConfig'], '@xml/wearing_network_security');

    await config.mods.android.dangerous({...config, modRequest: {projectRoot: path.resolve(__dirname, '..'), platformProjectRoot: directory}});
    const xml = await fs.readFile(path.join(directory, 'app/src/main/res/xml/wearing_network_security.xml'), 'utf8');
    const policy = (await parseStringPromise(xml))['network-security-config'];
    assert.deepEqual(policy['base-config'], [{$: {cleartextTrafficPermitted: 'false'}}]);
    assert.equal(policy['domain-config'].length, 1);
    const exception = policy['domain-config'][0];
    assert.equal(exception.$.cleartextTrafficPermitted, 'true');
    assert.deepEqual(exception.domain.map(item => item._).sort(), ['127.0.0.1', '::1', 'localhost']);
    assert(exception.domain.every(item => item.$.includeSubdomains === 'false'));
    assert.deepEqual(Object.keys(policy).sort(), ['base-config', 'domain-config']);
    assert.deepEqual(Object.keys(exception).sort(), ['$', 'domain']);
  } finally {
    await fs.rm(directory, {recursive: true, force: true});
  }
});
