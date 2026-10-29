const assert = require('node:assert/strict'), { test } = require('node:test');
const fs = require('node:fs'), path = require('node:path'), ts = require('typescript');
const React = require('react'), Renderer = require('react-test-renderer');
global.IS_REACT_ACT_ENVIRONMENT = true;
const pending = () => { let resolve; const promise = new Promise(r => { resolve = r; }); return { promise, resolve }; };
const text = node => typeof node === 'string' ? node : (node.children || []).map(text).join('');
const allText = root => root.findAllByType('Text').map(text).join('\n');
const button = (root, label) => root.findAllByType('Pressable').find(node => text(node) === label) || assert.fail(`Missing ${label}`);
const click = async (root, label) => React.act(async () => { const target = button(root, label); assert(!target.props.disabled); target.props.onPress(); });

function harness(options = {}) {
  const events = []; let revision = 1;
  const account = { accountId: 7, accountEmail: 'relay@example.invalid', authProviders: options.providers || ['apple'],
    signOut: async () => { events.push('signout'); }, finishAccountDeletion: async () => { events.push('signout'); }, refresh: async () => {} };
  const module = { exports: {} };
  const native = { View: 'View', Text: 'Text', ActivityIndicator: 'ActivityIndicator', Platform: { OS: options.os || 'ios' }, StyleSheet: { create: v => v } };
  const mocks = { react: React, 'react-native': native,
    '../../../services/travelTrips': { useTravelTrips: () => account, getApiBaseUrl: () => 'https://api.example.invalid', getAuthRevision: () => revision, getStoredToken: () => 'session' },
    '../../../services/appleAuth': { AppleSignInCanceled: class extends Error {} }, '../../../services/googleAuth': { GoogleSignInCanceled: class extends Error {} },
    '../../../services/appleSignInAvailability': { isAppleSignInEnabled: () => options.appleEnabled === true && (options.os || 'ios') === 'ios' },
    '../../../services/accountLifecycle': {
      getDeletionPreview: async owner => { events.push('preview'); return options.preview ? options.preview(owner) : { owned_trips: 2, shared_owned_trips: 1 }; },
      deleteVerifiedAccount: async (owner, provider) => { events.push(`delete:${provider}`); await options.remove?.(owner); },
      linkAppleAccount: async () => { events.push('link'); },
    }, '../../../theme/trotterTheme': { colors: {}, fonts: {} }, '../motion': { PressFeedback: 'Pressable' },
    '../planner/PlannerKit': { PlannerSheet: ({ children, error, ...props }) => React.createElement('Sheet', props, error ? React.createElement('Text', null, error) : null, children) },
    './AppleSignInButton': { AppleSignInButton: props => React.createElement('AppleButton', props) },
  };
  const source = ts.transpileModule(fs.readFileSync(path.resolve(__dirname, '../src/components/world-window/profile/AccountControls.tsx'), 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.React, esModuleInterop: true, target: ts.ScriptTarget.ES2022 } }).outputText;
  new Function('require', 'module', 'exports', source)(name => { assert(name in mocks, name); return mocks[name]; }, module, module.exports);
  return { Component: module.exports.AccountControls, events, changeAccount: () => revision++ };
}
async function render(h) { let view; await React.act(async () => { view = Renderer.create(React.createElement(h.Component)); }); return view; }
async function close(view) { await React.act(async () => view.unmount()); }

test('account controls show the actual account and providers without assuming Google', async () => {
  const h = harness(), view = await render(h);
  assert.match(allText(view.root), /relay@example.invalid/); assert.match(allText(view.root), /Sign in with Apple/);
  assert.doesNotMatch(allText(view.root), /Link Apple/); await close(view);
});
test('deletion requires preview, explicit confirmation, and provider verification', async () => {
  const h = harness(), view = await render(h);
  await click(view.root, 'Delete account');
  assert.deepEqual(h.events, ['preview']); assert.equal(view.root.findAllByType('AppleButton').length, 0);
  assert.match(allText(view.root), /Other members will lose access/); assert.match(allText(view.root), /2 trips you organise · 1 shared/);
  const inside = view.root.findByType('Sheet'); await click(inside, 'Delete account');
  assert.deepEqual(h.events, ['preview']);
  await React.act(async () => { view.root.findByType('AppleButton').props.onPress(); });
  assert.deepEqual(h.events, ['preview', 'delete:apple', 'signout']); await close(view);
});
test('failed deletion preview leaves retry and keep-account actions only', async () => {
  const h = harness({ preview: async () => { throw new Error('Offline'); } }), view = await render(h);
  await click(view.root, 'Delete account'); const sheet = view.root.findByType('Sheet');
  assert.match(allText(sheet), /Offline/); assert(button(sheet, 'Try again')); assert(button(sheet, 'Keep my account'));
  assert.equal(sheet.findAllByType('AppleButton').length, 0);
  assert(!sheet.findAllByType('Pressable').some(node => text(node) === 'Delete account'));
  await close(view);
});
test('late deletion completion cannot sign out a different account', async () => {
  const done = pending(), h = harness({ remove: () => done.promise }), view = await render(h);
  await click(view.root, 'Delete account'); await click(view.root.findByType('Sheet'), 'Delete account');
  await React.act(async () => { view.root.findByType('AppleButton').props.onPress(); });
  h.changeAccount(); await React.act(async () => done.resolve());
  assert(!h.events.includes('signout')); await close(view);
});
test('a pending deletion cannot be submitted twice or dismissed mid-request', async () => {
  const done = pending(), h = harness({ remove: () => done.promise }), view = await render(h);
  await click(view.root, 'Delete account'); await click(view.root.findByType('Sheet'), 'Delete account');
  const action = view.root.findByType('AppleButton').props.onPress;
  await React.act(async () => { action(); action(); view.root.findByType('Sheet').props.onClose(); });
  assert.equal(h.events.filter(e => e === 'delete:apple').length, 1); assert(view.root.findByType('Sheet'));
  await React.act(async () => done.resolve()); await close(view);
});
test('existing Google account has a separate Apple-link action on iPhone', async () => {
  const h = harness({ providers: ['google'], appleEnabled: true }), view = await render(h);
  await click(view.root, 'Link Apple sign-in'); assert.deepEqual(h.events, ['link']); await close(view);
});

test('unconfigured Apple login has no profile link action', async () => {
  const h = harness({ providers: ['google'] }), view = await render(h);
  assert.doesNotMatch(allText(view.root), /Link Apple/); await close(view);
});
