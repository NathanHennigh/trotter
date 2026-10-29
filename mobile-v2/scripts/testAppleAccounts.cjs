const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), ts = require('typescript');
const pending = () => { let resolve; const promise = new Promise(r => { resolve = r; }); return { promise, resolve }; };
const flush = async () => { for (let i = 0; i < 30; i++) await Promise.resolve(); };
function harness(options = {}) {
  const calls = [], native = [], cache = new Map(); let current = true;
  const apple = {
    isAvailableAsync: async () => true, AppleAuthenticationScope: { FULL_NAME: 0, EMAIL: 1 },
    formatFullName: name => name.givenName,
    signInAsync: async args => { native.push(args); return options.credential ? options.credential(args) : { state: args.state, identityToken: 'identity', authorizationCode: 'code', fullName: { givenName: 'Alex' } }; },
  };
  function load(name) {
    if (cache.has(name)) return cache.get(name).exports;
    const module = { exports: {} }; cache.set(name, module);
    const source = ts.transpileModule(fs.readFileSync(path.join(__dirname, '../src/services', `${name}.ts`), 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
    const request = async (url, init) => {
      const call = { path: new URL(url).pathname, method: init.method, token: init.headers.Authorization, body: init.body ? JSON.parse(init.body) : undefined };
      calls.push(call);
      const result = options.fetcher ? await options.fetcher(call) : undefined;
      const data = result ?? (call.path.endsWith('/challenge') ? { challenge_id: 'challenge-one', nonce: 'server-nonce' }
        : call.path === '/auth/apple' ? { access_token: 'fresh-token', user_id: 7, email: 'relay@example.invalid' }
        : call.path === '/auth/me' ? { user_id: 7 } : undefined);
      const status = data?.httpStatus ?? (call.method === 'DELETE' ? 204 : 200);
      return { status, ok: status >= 200 && status < 300, text: async () => data === undefined ? '' : JSON.stringify(data) };
    };
    new Function('require', 'module', 'exports', 'fetch', source)(ref => {
      if (ref === 'react-native') return { Platform: { OS: options.os ?? 'ios' } };
      if (ref === 'expo-apple-authentication') return apple;
      if (ref === './googleAuth') return { GoogleSignInCanceled: class extends Error {}, requestGoogleReauthentication: async prepare => { await prepare('trotterv2://oauthredirect?attempt=one'); return 'google-fresh'; } };
      if (ref.startsWith('./')) return load(ref.slice(2));
      throw new Error(ref);
    }, module, module.exports, request);
    return module.exports;
  }
  return { load, calls, native, scope: { base: 'https://api.example.invalid', token: 'existing-session', ownerId: 7, isCurrent: () => current }, cancel: () => { current = false; } };
}

test('Apple binds state and server nonce and exchanges code before accepting a token', async () => {
  const h = harness();
  const result = await h.load('appleAuth').requestAppleAuth(h.scope.base);
  assert.equal(result.user_id, 7); assert.equal(h.native[0].nonce, 'server-nonce'); assert.equal(h.native[0].state, 'challenge-one');
  assert.deepEqual(h.calls[1].body, { challenge_id: 'challenge-one', identity_token: 'identity', authorization_code: 'code', name: 'Alex' });
  assert.equal(h.calls[0].token, undefined);
});
test('Apple will not exchange a mismatched native callback', async () => {
  const h = harness({ credential: () => ({ state: 'another-attempt', identityToken: 'identity', authorizationCode: 'code' }) });
  await assert.rejects(h.load('appleAuth').requestAppleAuth(h.scope.base), /verified/);
  assert.equal(h.calls.length, 1);
});
test('Apple cancellation never sends a credential to the backend', async () => {
  const h = harness({ credential: () => { throw { code: 'ERR_REQUEST_CANCELED' }; } });
  await assert.rejects(h.load('appleAuth').requestAppleAuth(h.scope.base), h.load('appleAuth').AppleSignInCanceled);
  assert.equal(h.calls.length, 1);
});
test('sign-out while Apple is open discards its late result', async () => {
  const credential = pending(), h = harness({ credential: () => credential.promise });
  const p = h.load('appleAuth').requestAppleAuth(h.scope.base, { isCurrent: h.scope.isCurrent }); await flush();
  h.cancel(); credential.resolve({ state: 'challenge-one', identityToken: 'identity', authorizationCode: 'code' });
  await assert.rejects(p, h.load('appleAuth').AppleSignInCanceled); assert.equal(h.calls.length, 1);
});
test('a second Apple request cannot overlap the first native dialog', async () => {
  const credential = pending(), h = harness({ credential: () => credential.promise });
  const p = h.load('appleAuth').requestAppleAuth(h.scope.base); await flush();
  await assert.rejects(h.load('appleAuth').requestAppleAuth(h.scope.base), /already open/);
  h.load('appleAuth').cancelAppleAuthSession(); credential.resolve({}); await assert.rejects(p);
});
test('Apple is never invoked on Android', async () => {
  const h = harness({ os: 'android' }); await assert.rejects(h.load('appleAuth').requestAppleAuth(h.scope.base), /iPhone/); assert.equal(h.calls.length, 0);
});
test('deletion reauthenticates the bound account and uses only the verified token', async () => {
  const h = harness(); await h.load('accountLifecycle').deleteVerifiedAccount(h.scope, 'apple');
  assert.equal(h.calls[0].body.purpose, 'reauth'); assert.equal(h.calls[0].token, 'Bearer existing-session');
  assert.equal(h.calls.at(-2).path, '/auth/me');
  assert.deepEqual(h.calls.at(-1), { path: '/auth/account', method: 'DELETE', token: 'Bearer fresh-token', body: { confirmation: 'DELETE' } });
});
test('a different verified account cannot be deleted', async () => {
  const h = harness({ fetcher: call => call.path === '/auth/me' ? { user_id: 99 } : undefined });
  await assert.rejects(h.load('accountLifecycle').deleteVerifiedAccount(h.scope, 'apple'), /current Trotter account/);
  assert(!h.calls.some(call => call.method === 'DELETE'));
});
test('an account change during verification prevents deletion', async () => {
  const me = pending(), h = harness({ fetcher: call => call.path === '/auth/me' ? me.promise : undefined });
  const operation = h.load('accountLifecycle').deleteVerifiedAccount(h.scope, 'apple'); await flush(); h.cancel(); me.resolve({ user_id: 7 });
  await assert.rejects(operation); assert(!h.calls.some(call => call.method === 'DELETE'));
});
test('Apple linking retains the same account and credentials', async () => {
  const h = harness(); await h.load('accountLifecycle').linkAppleAccount(h.scope);
  assert.equal(h.calls[0].body.purpose, 'link'); assert.equal(h.calls[1].token, 'Bearer existing-session');
  assert(!h.calls.some(call => call.method === 'DELETE'));
});
test('an expired link verification goes through bound Google reauth then Apple', async () => {
  let challenge = 0;
  const h = harness({ fetcher: call => call.path.endsWith('/challenge') && ++challenge === 1 ? { httpStatus: 403, detail: 'reauthentication_required' }
    : call.path === '/auth/google/reauth/start' ? { url: 'https://accounts.google.com/o/oauth2/v2/auth?state=one' } : undefined });
  await h.load('accountLifecycle').linkAppleAccount(h.scope);
  const links = h.calls.filter(call => call.path === '/auth/apple/challenge');
  assert.equal(links[1].token, 'Bearer google-fresh'); assert.equal(h.native.length, 1);
});
test('unsafe Google verification URLs never open or delete accounts', async () => {
  const h = harness({ fetcher: call => call.path === '/auth/google/reauth/start' ? { url: 'https://example.invalid/steal' } : undefined });
  await assert.rejects(h.load('accountLifecycle').deleteVerifiedAccount(h.scope, 'google'), /could not be started/);
  assert(!h.calls.some(call => call.method === 'DELETE'));
});
test('invalid deletion counts cannot enable destructive confirmation', async () => {
  const h = harness({ fetcher: () => ({ owned_trips: 1, shared_owned_trips: 3 }) });
  await assert.rejects(h.load('accountLifecycle').getDeletionPreview(h.scope), /could not be checked/);
});
