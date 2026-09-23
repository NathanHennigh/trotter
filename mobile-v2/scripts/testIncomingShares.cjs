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

function gateHost(initialAccount) {
  const slots = []; let cursor = 0, effects = [], dirty = false, account = initialAccount, receive;
  let resolveInitial;
  const initial = new Promise(resolve => { resolveInitial = resolve; });
  const same = (a, b) => a && b && a.length === b.length && a.every((value, index) => Object.is(value, b[index]));
  const react = {
    createElement: (type, props, ...children) => ({ type, props: { ...props, children } }),
    useState(initial) {
      const index = cursor++;
      if (!(index in slots)) slots[index] = { value: typeof initial === 'function' ? initial() : initial };
      return [slots[index].value, next => {
        const value = typeof next === 'function' ? next(slots[index].value) : next;
        if (!Object.is(value, slots[index].value)) { slots[index].value = value; dirty = true; }
      }];
    },
    useReducer(reducer, initial) { const [value, setValue] = react.useState(initial); return [value, action => setValue(previous => reducer(previous, action))]; },
    useRef(value) { const index = cursor++; return slots[index] ??= { current: value }; },
    useCallback(fn, deps) { const index = cursor++; if (!slots[index] || !same(slots[index].deps, deps)) slots[index] = { deps, fn }; return slots[index].fn; },
    useEffect(fn, deps) {
      const index = cursor++;
      if (!slots[index] || !same(slots[index].deps, deps)) effects.push(() => { slots[index]?.cleanup?.(); slots[index] = { deps, cleanup: fn() }; });
    },
  };
  const gate = ast.statements.find(node => ts.isFunctionDeclaration(node) && node.name?.text === 'AccountGate');
  const output = ts.transpileModule(`export ${gate.getText(ast)}`, { compilerOptions: { jsx: ts.JsxEmit.React, module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } }).outputText;
  const module = { exports: {} };
  const globals = { React: react, useTravelTrips: () => account, reduceIncomingShareQueue: reduce,
    Linking: { addEventListener: (_name, callback) => { receive = callback; return { remove() {} }; }, getInitialURL: () => initial },
    parseIncomingDreamShare: sourceUrl => ({ sourceUrl }), AuthScreen: 'AuthScreen', SessionRestoringScreen: 'SessionRestoringScreen', DreamsProvider: 'DreamsProvider', AppShell: 'AppShell' };
  new Function('module', 'exports', ...Object.keys(globals), output)(module, module.exports, ...Object.values(globals));
  return {
    render(nextAccount = account) {
      account = nextAccount;
      for (let attempts = 0; attempts < 10; attempts++) {
        cursor = 0; effects = []; dirty = false;
        const tree = module.exports.AccountGate(); effects.forEach(fn => fn());
        if (!dirty) return tree;
      }
      throw new Error('Account gate did not settle');
    },
    resolveInitial, receive: url => receive({ url }),
    dispose: () => slots.forEach(slot => slot?.cleanup?.()),
  };
}
const flushGate = async () => { for (let n = 0; n < 15; n++) await Promise.resolve(); };

test('a verified cold launch waits for its initial share instead of mounting the default tab first', async () => {
  const host = gateHost({ authStatus: 'loading' });
  assert.equal(host.render().type, 'SessionRestoringScreen');
  assert.equal(host.render({ authStatus: 'signed-in', accountId: 11 }).type, 'SessionRestoringScreen');
  host.resolveInitial('https://www.instagram.com/p/cold/'); await flushGate();
  const tree = host.render();
  assert.equal(tree.type, 'DreamsProvider');
  const incoming = tree.props.children[0].props.incomingShare;
  assert.equal(incoming.sourceUrl, 'https://www.instagram.com/p/cold/');
  assert.equal(incoming.ownerId, 11);
  host.dispose();
});

test('a signed-out share stays queued through sign-in and cannot cross an account switch', async () => {
  const host = gateHost({ authStatus: 'signed-out' });
  host.render(); host.resolveInitial('https://www.instagram.com/p/waiting/'); await flushGate();
  assert.equal(host.render().type, 'AuthScreen');
  let tree = host.render({ authStatus: 'loading' });
  assert.equal(tree.type, 'SessionRestoringScreen');
  assert.equal(tree.props.sourceUrl, 'https://www.instagram.com/p/waiting/');
  tree = host.render({ authStatus: 'signed-in', accountId: 11 });
  assert.equal(tree.props.children[0].props.incomingShare.ownerId, 11);
  assert.equal(host.render({ authStatus: 'signed-out' }).type, 'AuthScreen');
  tree = host.render({ authStatus: 'signed-in', accountId: 22 });
  assert.equal(tree.props.children[0].props.incomingShare, undefined);
  host.dispose();
});

test('a new verified session remounts Dreams even if same-account loading renders are batched away', async () => {
  const host = gateHost({ authStatus: 'signed-in', accountId: 11, accountRevision: 3 });
  host.render(); host.resolveInitial(null); await flushGate();
  const first = host.render();
  assert.equal(first.type, 'DreamsProvider');
  assert.equal(first.props.key, '11:3');
  const renewed = host.render({ authStatus: 'signed-in', accountId: 11, accountRevision: 4 });
  assert.equal(renewed.type, 'DreamsProvider');
  assert.equal(renewed.props.key, '11:4');
  host.dispose();
});
