const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { test } = require('node:test');
const ignore = require('ignore');
const repo = path.resolve(__dirname, '../..');
const rules = ignore().add(fs.readFileSync(path.join(repo, '.easignore'), 'utf8'));

test('EAS can traverse the mobile directory and include native iPhone sources', () => {
  // EAS shallow-copy checks directory names without a trailing slash.
  for (const file of ['mobile-v2', 'mobile-v2/package.json', 'mobile-v2/package-lock.json',
    'mobile-v2/app.json', 'mobile-v2/app.config.js', 'mobile-v2/src',
    'mobile-v2/plugins/withTrotterShareExtension.js', 'mobile-v2/native-ios',
    'mobile-v2/assets/world-window/app-icon.png']) {
    assert.equal(rules.ignores(file), false, file);
  }
});

test('EAS excludes private configuration and generated build output', () => {
  for (const file of ['backend', '.ios-remote', 'deploy', 'sites',
    'mobile-v2/.env', 'mobile-v2/credentials.json', 'mobile-v2/AuthKey_TEST.p8',
    'mobile-v2/signing.p12', 'mobile-v2/profile.mobileprovision',
    'mobile-v2/android/google-maps.properties', 'mobile-v2/android/signing.properties',
    'mobile-v2/android/app/trotter-upload.keystore', 'mobile-v2/ios/Info.plist',
    'mobile-v2/node_modules/expo/package.json', 'mobile-v2/.cache/generated/Info.plist']) {
    assert.equal(rules.ignores(file), true, file);
  }
});

test('release build numbering does not change the pinned source checkout', () => {
  const eas = JSON.parse(fs.readFileSync(path.join(repo, 'mobile-v2/eas.json'), 'utf8'));
  assert.equal(eas.cli.appVersionSource, 'remote');
  assert.equal(eas.build['iphone-testflight'].ios.autoIncrement, 'buildNumber');
});
