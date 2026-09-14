// Pure account-queue regression tests; no React renderer, listener, or network.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
const { test } = require('node:test');
const source = fs.readFileSync(path.join(__dirname, '../App.tsx'), 'utf8');
const ast = ts.createSourceFile('App.tsx', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const declaration = ast.statements.find(node => ts.isFunctionDeclaration(node) && node.name?.text === 'reduceIncomingShareQueue');
assert(declaration, 'Load the actual account-queue reducer');
const compiled = ts.transpileModule(declaration.getText(ast), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } }).outputText;
const loaded = { exports: {} }; new Function('module', 'exports', compiled)(loaded, loaded.exports);
const reduce = loaded.exports.reduceIncomingShareQueue;
const empty = () => ({ items: [], nextId: 1, recent: [] });
const owner = (state, ownerId) => reduce(state, { type: 'owner', ownerId });
const receive = (state, ownerId, name, now = 10000) => reduce(state, { type: 'receive', ownerId, now, share: { sourceUrl: `https://www.instagram.com/p/${name}/`, sharedText: name } });

test('a signed-out share waits, then binds to the first verified account', () => {
  let queue = receive(empty(), undefined, 'signed-out');
  assert.equal(queue.items[0].ownerId, undefined);
  queue = owner(queue, 11);
  assert.equal(queue.items[0].ownerId, 11);
  assert.equal(queue.items[0].sharedText, 'signed-out');
});

test('account A queue is erased on logout and cannot appear in account B', () => {
  const original = receive(empty(), 11, 'account-A');
  const signedOut = owner(original, undefined);
  assert.equal(signedOut.items.length, 0);
  assert.equal(owner(signedOut, 22).items.length, 0);
  assert.equal(original.items.length, 1, 'Reducer does not mutate the prior state');
  assert.equal(owner(original, 22).items.length, 0, 'Direct A to B transition also clears A receipts');
});

test('a new signed-out receipt after logout belongs only to the next account', () => {
  let queue = owner(receive(empty(), 11, 'old-A'), undefined);
  queue = receive(queue, undefined, 'new-signed-out');
  queue = owner(queue, 22);
  assert.equal(queue.items.length, 1);
  assert.equal(queue.items[0].sharedText, 'new-signed-out');
  assert.equal(queue.items[0].ownerId, 22);
});

test('consuming a share twice cannot drop the next queued share during effect replay', () => {
  let queue = receive(empty(), 11, 'first');
  queue = receive(queue, 11, 'second');
  const firstId = queue.items[0].queueId, secondId = queue.items[1].queueId;
  queue = reduce(queue, { type: 'consume', queueId: firstId });
  queue = reduce(queue, { type: 'consume', queueId: firstId });
  assert.equal(queue.items.length, 1);
  assert.equal(queue.items[0].queueId, secondId);
});

test('duplicate native and initial delivery is queued once, even just after consumption', () => {
  let queue = receive(empty(), 11, 'same', 10000);
  queue = receive(queue, 11, 'same', 10001);
  assert.equal(queue.items.length, 1);
  queue = reduce(queue, { type: 'consume', queueId: queue.items[0].queueId });
  queue = receive(queue, 11, 'same', 10002);
  assert.equal(queue.items.length, 0);
  queue = receive(queue, 11, 'same', 15000);
  assert.equal(queue.items.length, 1, 'A deliberate later share remains possible');
});

test('receive synchronizes owner before adding a receipt, regardless of effect order', () => {
  const queue = receive(receive(empty(), 11, 'old-A'), 22, 'new-B');
  assert.equal(queue.items.length, 1);
  assert.equal(queue.items[0].ownerId, 22);
  assert.equal(queue.items[0].sharedText, 'new-B');
});
