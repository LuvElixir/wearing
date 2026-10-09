const {withAndroidManifest, withDangerousMod, AndroidConfig} = require('expo/config-plugins');
const fs = require('node:fs/promises');
const path = require('node:path');
module.exports = function localPreview(config) {
  config = AndroidConfig.Permissions.withPermissions(config, ['android.permission.CAMERA', 'android.permission.RECORD_AUDIO']);
  config = withAndroidManifest(config, config => {
    const app = config.modResults.manifest.application[0];
    app.$['android:allowBackup'] = 'false';
    app.$['android:usesCleartextTraffic'] = 'false';
    app.$['android:networkSecurityConfig'] = '@xml/wearing_network_security';
    return config;
  });
  return withDangerousMod(config, ['android', async config => {
    const dir = path.join(config.modRequest.platformProjectRoot, 'app/src/main/res/xml');
    await fs.mkdir(dir, {recursive: true});
    await fs.writeFile(path.join(dir, 'wearing_network_security.xml'), '<?xml version="1.0" encoding="utf-8"?>\n<network-security-config><base-config cleartextTrafficPermitted="false"/><domain-config cleartextTrafficPermitted="true"><domain includeSubdomains="false">localhost</domain><domain includeSubdomains="false">127.0.0.1</domain><domain includeSubdomains="false">::1</domain></domain-config></network-security-config>\n');
    return config;
  }]);
};
