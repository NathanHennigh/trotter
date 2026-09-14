const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../app.config.js'), 'utf8');
const base = JSON.parse(fs.readFileSync(path.join(__dirname, '../app.json'), 'utf8')).expo;

function config(file, env = {}) {
  const sandbox = { module: { exports: {} }, __dirname: '/test/mobile', process: { env }, require(name) {
    if (name === 'node:path') return path;
    if (name === 'node:fs') return { existsSync: () => file !== null, readFileSync: () => file };
    throw new Error(`Unexpected import: ${name}`);
  } };
  vm.runInNewContext(source, sandbox);
  return sandbox.module.exports({ config: base });
}

const absent = config(null, { GOOGLE_PLACES_API_KEY: 'SERVER-ONLY' });
assert.equal(absent.extra.googleMapsAndroidConfigured, false);
assert.equal(absent.extra.googleMapsIosConfigured, false);
assert.equal(JSON.stringify(absent).includes('SERVER-ONLY'), false);
assert.equal(absent.android.package, base.android.package);
assert.equal(absent.extra.eas.projectId, base.extra.eas.projectId);

const local = config('# ignored\r\nandroidApiKey= android-restricted-key \r\niosApiKey=ios-restricted-key\r\n');
assert.equal(local.android.config.googleMaps.apiKey, 'android-restricted-key');
assert.equal(local.ios.config.googleMapsApiKey, 'ios-restricted-key');
assert.equal(local.extra.googleMapsAndroidConfigured, true);
assert.equal(local.extra.googleMapsIosConfigured, true);
assert.equal(JSON.stringify(local.extra).includes('restricted-key'), false);

const overridden = config('androidApiKey=file-key', { GOOGLE_MAPS_ANDROID_API_KEY: ' environment-key ' });
assert.equal(overridden.android.config.googleMaps.apiKey, 'environment-key');
assert.equal(config('androidApiKey=\niosApiKey=').extra.googleMapsAndroidConfigured, false);
console.log('Google Maps configuration: missing keys, restricted-key separation, file parsing and overrides passed.');
