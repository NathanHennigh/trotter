const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { checkIosReadiness } = require('./checkIosReadiness.cjs');
const root = path.resolve(__dirname, '..');
const base = JSON.parse(fs.readFileSync(path.join(root, 'app.json'), 'utf8')).expo;
// Exercise missing/explicit account configuration independently of the linked app.
delete base.extra?.eas?.projectId;
delete base.ios?.appleTeamId;
const source = fs.readFileSync(path.join(root, 'app.config.js'), 'utf8');
const projectId = '87ab4236-1257-41a3-bb98-acd601337a41';
const complete = { EAS_PROJECT_ID: projectId, APPLE_TEAM_ID: 'ABCDEFGHIJ',
  EXPO_PUBLIC_TROTTER_API_URL: 'https://api.example.test', GOOGLE_MAPS_IOS_API_KEY: 'ios-test-key' };
function config(env = {}) {
  const module = { exports: {} };
  vm.runInNewContext(source, { module, __dirname: root, URL, process: { env }, require(name) {
    if (name === 'node:path') return path;
    if (name === 'node:fs') return { existsSync: () => false };
    throw new Error(name);
  } });
  return module.exports({ config: base });
}

test('iPhone config uses real external identifiers, safe API domain and iOS Maps key', () => {
  const value = config(complete);
  assert.equal(value.extra.eas.projectId, projectId);
  assert.equal(value.ios.appleTeamId, 'ABCDEFGHIJ');
  assert.deepEqual(Array.from(value.ios.associatedDomains), ['applinks:api.example.test']);
  assert.equal(value.ios.config.googleMapsApiKey, 'ios-test-key');
  assert.equal(value.ios.supportsTablet, false);
  assert.equal(value.ios.usesAppleSignIn, true);
  assert.equal(JSON.stringify(value.extra).includes('ios-test-key'), false);
  assert.deepEqual(checkIosReadiness(value, complete).errors, []);
});

test('missing credentials stay missing and cannot pass as a configured release', () => {
  const value = config();
  assert.equal(value.extra.eas?.projectId, undefined);
  assert.equal(value.ios.appleTeamId, undefined);
  assert.equal(value.ios.associatedDomains.length, 0);
  assert.equal(checkIosReadiness(value, {}).errors.length, 4);
  assert.throws(() => config({ EAS_PROJECT_ID: 'local-v2-placeholder' }), /actual linked Expo project/);
  assert.throws(() => config({ APPLE_TEAM_ID: 'wrong' }), /10-character/);
});

test('unsafe API configuration never becomes an associated domain', () => {
  for (const url of ['http://api.example.test', 'https://user:pass@api.example.test', 'https://api.example.test?token=bad', 'https://api.example.test/#token=bad', 'https://api.example.test:8443']) {
    const env = { ...complete, EXPO_PUBLIC_TROTTER_API_URL: url };
    const value = config(env);
    assert.equal(value.ios.associatedDomains.length, 0, url);
    assert.ok(checkIosReadiness(value, env).errors.some(error => error.includes('HTTPS API URL')), url);
  }
});

test('local simulator preparation does not need signing or an Expo account', () => {
  const env = { EXPO_PUBLIC_TROTTER_API_URL: complete.EXPO_PUBLIC_TROTTER_API_URL, GOOGLE_MAPS_IOS_API_KEY: complete.GOOGLE_MAPS_IOS_API_KEY };
  assert.deepEqual(checkIosReadiness(config(env), env, { local: true, simulator: true }).errors, []);
});

test('Apple login stays hidden until Trotter explicitly enables it with its own team configured', () => {
  assert.equal(config().extra.appleSignInEnabled, false);
  assert.equal(config(complete).extra.appleSignInEnabled, false);
  assert.equal(config({ EXPO_PUBLIC_APPLE_SIGN_IN_ENABLED: 'true' }).extra.appleSignInEnabled, false);
  assert.equal(config({ ...complete, EXPO_PUBLIC_APPLE_SIGN_IN_ENABLED: 'false' }).extra.appleSignInEnabled, false);
  assert.equal(config({ ...complete, EXPO_PUBLIC_APPLE_SIGN_IN_ENABLED: 'true' }).extra.appleSignInEnabled, true);
});
