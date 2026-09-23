// Execute the production store against an asynchronous in-memory AsyncStorage adapter.
const assert = require('node:assert/strict');
const { test } = require('node:test');
const fs = require('node:fs'), path = require('node:path'), ts = require('typescript');
const source = fs.readFileSync(path.join(__dirname, '../src/services/dreamShareOutbox.ts'), 'utf8');
const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, esModuleInterop: true, target: ts.ScriptTarget.ES2022 } }).outputText;
const ownerA = { apiBaseUrl: 'https://api.trotter.test/api', ownerId: 11 };
const ownerB = { ...ownerA, ownerId: 22 };
const share = (id, sharedText) => ({ sourceUrl: `https://www.instagram.com/reel/${id}/?igsh=tracking`, sharedText });
const pause = () => new Promise(resolve => setImmediate(resolve));

function storage() {
  const values = new Map();
  return {
    values, failRead: false, failWrite: false, writes: 0,
    async getItem(key) { await pause(); if (this.failRead) throw Error('read unavailable'); return values.get(key) ?? null; },
    async setItem(key, value) { await pause(); if (this.failWrite) throw Error('storage full'); this.writes++; values.set(key, value); },
    async removeItem(key) { await pause(); if (this.failWrite) throw Error('storage full'); values.delete(key); },
  };
}
function load(adapter = storage()) {
  const module = { exports: {} };
  new Function('require', 'module', 'exports', code)(name => {
    assert.equal(name, '@react-native-async-storage/async-storage'); return adapter;
  }, module, module.exports);
  return { ...module.exports, adapter, store: module.exports.dreamShareOutbox };
}

test('canonical links deduplicate tracking variants without accepting unrelated URLs', () => {
  const { canonicalDreamShareUrl: canonical } = load();
  assert.equal(canonical('https://www.instagram.com/reel/Ab-c_d/?igsh=tracking#caption'), 'https://instagram.com/reel/Ab-c_d');
  assert.equal(canonical('Look here: https://instagram.com/p/AbCd/. Enjoy!'), 'https://instagram.com/p/AbCd');
  assert.equal(canonical('instagram.com/tv/AbCd/'), 'https://instagram.com/tv/AbCd');
  for (const invalid of ['https://instagram.com/', 'https://instagram.com/friend', 'https://instagram.com/p/', 'https://instagram.com/p/code/other',
    'https://instagram.com.evil.test/p/code', 'https://instagram.com@evil.test/p/code', 'https://evil.test/p/code', 'ftp://instagram.com/p/code',
    'https://instagram.com:8443/p/code', undefined, 'x'.repeat(32769)]) assert.equal(canonical(invalid), undefined, String(invalid));
});

test('concurrent enqueues from separate instances retain all URLs and deduplicate one post', async () => {
  const { store, createDreamShareOutbox, adapter } = load();
  const secondStore = createDreamShareOutbox(adapter);
  const receipts = await Promise.all([
    store.enqueue(ownerA, share('first', 'A cafe')),
    secondStore.enqueue(ownerA, share('second', 'A beach')),
    store.enqueue(ownerA, { sourceUrl: 'https://instagram.com/reel/first#same' }),
    secondStore.enqueue(ownerA, share('third')),
  ]);
  assert.equal(receipts[0].id, receipts[2].id);
  assert.equal(receipts[0].generation, receipts[2].generation);
  const pending = await store.list(ownerA);
  assert.deepEqual(pending.map(entry => entry.sourceUrl), ['first', 'second', 'third'].map(id => `https://instagram.com/reel/${id}`));
  assert.equal(pending[0].sharedText, 'A cafe');
  assert.equal(adapter.writes, 3, 'Duplicate receipt requires no new disk write');
});

test('receipt is acknowledged locally only after storage commits; failures keep earlier entries and allow retry', async () => {
  const { store, adapter } = load();
  await store.enqueue(ownerA, share('first'));
  adapter.failWrite = true;
  await assert.rejects(store.enqueue(ownerA, share('second')), /storage full/);
  assert.deepEqual((await store.list(ownerA)).map(entry => entry.sourceUrl), ['https://instagram.com/reel/first']);
  adapter.failWrite = false;
  await store.enqueue(ownerA, share('second'));
  adapter.failRead = true;
  await assert.rejects(store.enqueue(ownerA, share('third')), /read unavailable/);
  adapter.failRead = false;
  assert.equal((await store.list(ownerA)).length, 2, 'Read failure cannot replace the existing queue with an empty queue');
  await store.enqueue(ownerA, share('third'));
  assert.equal((await store.list(ownerA)).length, 3, 'A rejected operation does not poison the serialized queue');
});

test('cold restoration retains pending uploads and shared text after an interrupted network attempt', async () => {
  const { store, adapter } = load();
  const queued = await store.enqueue(ownerA, share('first', 'Visit this place'));
  const started = await store.beginAttempt(ownerA, queued);
  assert.equal(started.attemptCount, 1);
  assert.ok(started.lastAttemptAt >= started.queuedAt);
  const cold = load(adapter).store;
  assert.deepEqual(await cold.list(ownerA), [started]);
  const resumed = await cold.beginAttempt(ownerA, started);
  assert.equal(resumed.attemptCount, 2);
  assert.equal(resumed.sharedText, 'Visit this place');
  assert.equal(await cold.acknowledge(ownerA, resumed), true);
  assert.deepEqual(await cold.list(ownerA), []);
});

test('a stale success or failure cannot erase or replace a newer attempt', async () => {
  const { store } = load();
  const queued = await store.enqueue(ownerA, share('first'));
  const first = await store.beginAttempt(ownerA, queued);
  assert.equal(await store.beginAttempt(ownerA, queued), undefined, 'One receipt starts only one concurrent attempt');
  const second = await store.beginAttempt(ownerA, first);
  assert.equal(await store.acknowledge(ownerA, first), false);
  assert.equal(await store.markFailed(ownerA, first), false);
  assert.deepEqual(await store.list(ownerA), [second]);
  assert.equal(await store.acknowledge(ownerA, second), true);
  const reshared = await store.enqueue(ownerA, share('first'));
  assert.notEqual(reshared.id, second.id);
  assert.equal(await store.acknowledge(ownerA, second), false, 'A later deliberate reshare has its own ID');
  assert.deepEqual(await store.list(ownerA), [reshared]);
});

test('offline or timed-out attempts retain the original link, and retry changes generation', async () => {
  const { store } = load();
  const queued = await store.enqueue(ownerA, share('offline', 'Keep the caption'));
  const attempt = await store.beginAttempt(ownerA, queued);
  assert.equal(await store.markFailed(ownerA, attempt), true);
  const [failed] = await store.list(ownerA);
  assert.equal(failed.status, 'failed');
  assert.equal(failed.attemptCount, 1);
  assert.ok(failed.failedAt >= attempt.lastAttemptAt);
  assert.equal(failed.sourceUrl, queued.sourceUrl);
  assert.equal(failed.sharedText, queued.sharedText);
  const retry = await store.enqueue(ownerA, share('offline'));
  assert.equal(retry.status, 'queued');
  assert.equal(retry.failedAt, undefined);
  assert.equal(retry.attemptCount, 1);
  assert.ok(retry.generation > attempt.generation);
  assert.equal(await store.acknowledge(ownerA, attempt), false);
  assert.equal((await store.beginAttempt(ownerA, retry)).attemptCount, 2);
});

test('caption arriving after the URL is durable and cannot be lost by an earlier response', async () => {
  const { store } = load();
  const queued = await store.enqueue(ownerA, share('first'));
  const attempt = await store.beginAttempt(ownerA, queued);
  const withCaption = await store.enqueue(ownerA, share('first', 'An important place name'));
  assert.equal(withCaption.id, queued.id);
  assert.ok(withCaption.generation > attempt.generation);
  assert.equal(await store.acknowledge(ownerA, attempt), false);
  assert.equal((await store.list(ownerA))[0].sharedText, 'An important place name');
});

test('accounts and API origins are isolated; clearing one owner cannot discard another owner', async () => {
  const { store } = load();
  const otherServer = { ...ownerA, apiBaseUrl: 'https://staging.trotter.test/api' };
  const [a, b, staging] = await Promise.all([
    store.enqueue(ownerA, share('first')), store.enqueue(ownerB, share('first')), store.enqueue(otherServer, share('first')),
  ]);
  assert.equal(await store.acknowledge(ownerB, a), false);
  await store.clear(ownerA);
  assert.deepEqual(await store.list(ownerA), []);
  assert.deepEqual(await store.list(ownerB), [b]);
  assert.deepEqual(await store.list(otherServer), [staging]);
  assert.deepEqual(await store.list({ ...otherServer, apiBaseUrl: 'https://staging.trotter.test/' }), [staging], 'Storage is scoped to the normalized API origin');
});

test('queued operations capture their owner and receipt before mutable caller objects change', async () => {
  const { store } = load();
  const mutableOwner = { ...ownerA };
  const pending = store.enqueue(mutableOwner, share('first'));
  mutableOwner.ownerId = ownerB.ownerId;
  const entry = await pending;
  assert.deepEqual(await store.list(ownerB), []);
  const receipt = { id: entry.id, generation: entry.generation };
  const acknowledgement = store.acknowledge(ownerA, receipt);
  receipt.generation += 1;
  assert.equal(await acknowledgement, true);
  assert.deepEqual(await store.list(ownerA), []);
});

test('acknowledgement storage failures preserve the receipt for safe replay', async () => {
  const { store, adapter } = load();
  const entry = await store.enqueue(ownerA, share('first'));
  const attempt = await store.beginAttempt(ownerA, entry);
  adapter.failWrite = true;
  await assert.rejects(store.acknowledge(ownerA, attempt), /storage full/);
  assert.deepEqual(await store.list(ownerA), [attempt]);
  adapter.failWrite = false;
  assert.equal(await store.acknowledge(ownerA, attempt), true);
});

test('malformed, oversized, wrong-owner and unsupported storage is bounded and ignored', async () => {
  const { store, adapter } = load();
  await store.enqueue(ownerA, share('first'));
  const key = [...adapter.values.keys()][0];
  const valid = JSON.parse(adapter.values.get(key));
  for (const raw of ['{bad', 'null', '[]', 'x'.repeat(1200001), JSON.stringify({ ...valid, ownerId: 999 }), JSON.stringify({ ...valid, version: 99 })]) {
    adapter.values.set(key, raw);
    assert.deepEqual(await store.list(ownerA), []);
  }
  adapter.values.set(key, JSON.stringify({ ...valid, entries: [null, { ...valid.entries[0], id: 'bad', sourceUrl: 'https://evil.test/p/a' },
    { ...valid.entries[0], id: 'bad-generation', generation: -1 }, valid.entries[0], valid.entries[0]] }));
  assert.equal((await store.list(ownerA)).length, 1);
  await assert.rejects(store.enqueue({ ...ownerA, ownerId: 0 }, share('other')), /verified account/);
  await assert.rejects(store.enqueue({ ...ownerA, apiBaseUrl: 'file:///api' }, share('other')), /Invalid API origin/);
  await assert.rejects(store.enqueue(ownerA, share('')), /valid Instagram/);
});

test('the bounded queue never evicts an older unsent share to accept a new one', async () => {
  const { store, adapter } = load();
  const first = await store.enqueue(ownerA, share('post0'));
  const key = [...adapter.values.keys()][0], envelope = JSON.parse(adapter.values.get(key));
  envelope.entries = Array.from({ length: 100 }, (_, index) => ({ ...first, id: `saved-${index}`, sourceUrl: `https://instagram.com/p/post${index}` }));
  adapter.values.set(key, JSON.stringify(envelope));
  await assert.rejects(store.enqueue(ownerA, share('overflow')), /queue is full/);
  assert.equal((await store.list(ownerA)).length, 100);
  assert.equal((await store.list(ownerA))[0].id, 'saved-0');
});
