const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { test } = require('node:test');
const ts = require('typescript');

function load(os, bridge) {
  const filename = path.join(__dirname, '../src/services/nativeDreamShare.ts');
  const code = ts.transpileModule(fs.readFileSync(filename, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;
  const module = { exports: {} };
  new Function('require', 'module', 'exports', code)(name => {
    assert.equal(name, 'react-native');
    return { Platform: { OS: os }, NativeModules: { TrotterDreamShare: bridge } };
  }, module, module.exports);
  return module.exports;
}

test('web and older native builds retain their existing share flow without requiring a native receipt module', async () => {
  for (const os of ['web', 'ios', 'android']) {
    const api = load(os, undefined);
    await api.invalidateNativeDreamShareSession(2);
    await api.syncNativeDreamShareSession({ apiBaseUrl: 'https://example.test', ownerId: 5, token: 'fixture' }, 2);
    assert.deepEqual(await api.listNativeDreamShareReceipts(), []);
    await api.flushNativeDreamShares();
    await api.acknowledgeNativeDreamShare('receipt');
  }
});

test('verified identity and exact revision are forwarded together to the secure native bridge', async () => {
  const calls = [];
  const api = load('android', { invalidateSession: async (...args) => calls.push(['clear', ...args]), configureSession: async (...args) => calls.push(['configure', ...args]) });
  await api.invalidateNativeDreamShareSession(7);
  await api.syncNativeDreamShareSession({ apiBaseUrl: 'https://example.test', ownerId: 41, token: 'synthetic-session' }, 7);
  assert.deepEqual(calls, [['clear', 7], ['configure', 'https://example.test', 41, 'synthetic-session', 7]]);
});

test('native credential clearing errors propagate so sign-out cannot claim success while background sharing remains enabled', async () => {
  const failure = new Error('secure storage unavailable');
  const api = load('android', { invalidateSession: async () => { throw failure; } });
  await assert.rejects(api.invalidateNativeDreamShareSession(8), error => error === failure);
});

test('receipt listing preserves queued, saved, and retained failure states for honest app-side recovery', async () => {
  const receipts = [
    { id: 'queued', status: 'queued', sourceUrl: 'https://www.instagram.com/reel/fixture/', createdAt: 1 },
    { id: 'saved', status: 'saved', sourceUrl: 'https://www.instagram.com/reel/fixture2/', itemId: 12, createdAt: 2 },
    { id: 'retry', status: 'failed', sourceUrl: 'https://www.instagram.com/reel/fixture3/', message: 'Kept on this phone.', createdAt: 3 },
  ];
  const api = load('android', { listReceipts: async () => receipts });
  assert.deepEqual(await api.listNativeDreamShareReceipts(), receipts);
});

test('acknowledgement and explicit retry target only their receipt and propagate storage failures', async () => {
  const calls = [];
  const api = load('android', { acknowledge: async id => calls.push(['ack', id]), retry: async id => calls.push(['retry', id]), flush: async () => calls.push(['flush']) });
  await api.acknowledgeNativeDreamShare('saved-id');
  await api.retryNativeDreamShare('failed-id');
  await api.flushNativeDreamShares();
  assert.deepEqual(calls, [['ack', 'saved-id'], ['retry', 'failed-id'], ['flush']]);
  const errorApi = load('android', { acknowledge: async () => { throw new Error('retained'); } });
  await assert.rejects(errorApi.acknowledgeNativeDreamShare('saved-id'), /retained/);
});

test('a non-Android target never forwards credentials to an accidentally present Android module', async () => {
  let calls = 0;
  const api = load('web', { configureSession: async () => { calls++; }, invalidateSession: async () => { calls++; } });
  await api.syncNativeDreamShareSession({ apiBaseUrl: 'https://example.test', ownerId: 1, token: 'fixture' }, 1);
  await api.invalidateNativeDreamShareSession(2);
  assert.equal(calls, 0);
});
