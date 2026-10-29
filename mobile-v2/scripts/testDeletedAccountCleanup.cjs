const { test } = require('node:test'), assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), ts = require('typescript');
const KEY = 'trotter.account-erasure.pending.v1';
const owner = { apiBaseUrl: 'https://api.example.invalid', ownerId: 7 };
function harness(storage = new Map(), failure) {
  const calls = [], module = { exports: {} };
  const mocks = {
    '@react-native-async-storage/async-storage': { getItem: async key => storage.get(key) ?? null, setItem: async (key, value) => { storage.set(key, value); }, removeItem: async key => { storage.delete(key); } },
    './dreamShareOutbox': { dreamShareOutbox: { clear: async value => { calls.push(['outbox', value]); } } },
    './gmailRecovery': { clearGmailRecovery: async (...args) => { calls.push(['gmail', ...args]); } },
    '../utils/travelerIdentity': { clearTravelerIdentity: async value => { calls.push(['identity', value]); } },
    './nativeDreamShare': { forgetNativeDreamShareAccount: async (...args) => { calls.push(['native', ...args]); if (failure) throw new Error('locked'); } },
  };
  const source = ts.transpileModule(fs.readFileSync(path.join(__dirname, '../src/services/deletedAccountCleanup.ts'), 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, esModuleInterop: true } }).outputText;
  new Function('require', 'module', 'exports', source)(name => { assert(name in mocks, name); return mocks[name]; }, module, module.exports);
  return { api: module.exports, calls, storage };
}
test('confirmed deletion clears only the specified server and owner', async () => {
  const h = harness(); h.api.markDeletedAccountForCleanup(owner);
  assert.equal(await h.api.hasDeletedAccountCleanup(), true);
  await h.api.finishDeletedAccountCleanup();
  assert.deepEqual(h.calls, [['native', owner.apiBaseUrl, 7], ['outbox', owner], ['gmail', owner.apiBaseUrl, 7], ['identity', `${owner.apiBaseUrl}/7`]]);
  assert.equal(await h.api.hasDeletedAccountCleanup(), false);
});
test('partial native erasure failure persists a token-free marker for retry after restart', async () => {
  const h = harness(new Map(), true); h.api.markDeletedAccountForCleanup(owner);
  await assert.rejects(h.api.finishDeletedAccountCleanup(), /Retry sign out/);
  assert.deepEqual(JSON.parse(h.storage.get(KEY)), owner); assert.equal(h.calls.length, 4);
  const restart = harness(h.storage); assert.equal(await restart.api.hasDeletedAccountCleanup(), true);
  await restart.api.finishDeletedAccountCleanup(); assert.equal(h.storage.has(KEY), false);
});
test('normal sign-out has no account erasure side effects', async () => {
  const h = harness(); await h.api.finishDeletedAccountCleanup(); assert.deepEqual(h.calls, []);
});
test('malformed cleanup metadata cannot clear unrelated data', async () => {
  const h = harness(new Map([[KEY, JSON.stringify({ apiBaseUrl: 'file:///private', ownerId: 7 })]]));
  await assert.rejects(h.api.finishDeletedAccountCleanup()); assert.deepEqual(h.calls, []); assert(h.storage.has(KEY));
});
