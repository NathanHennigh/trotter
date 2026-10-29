const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { patchFrameBarrier } = require('../plugins/withTrotterGlFrameBarrier');
const native = fs.readFileSync(path.join(path.dirname(require.resolve('expo-gl/package.json')), 'ios/EXGLObjectManager.mm'), 'utf8');

test('the installed native GL manager gains exactly one repeatable frame barrier', () => {
  const patched = patchFrameBarrier(native);
  assert.equal(patchFrameBarrier(patched), patched);
  assert.equal(patched.split('EX_EXPORT_METHOD_AS(trotterWaitForFrameAsync,').length, 2);
  assert.match(patched, /\[context runAsync:\^\{ resolve\(@YES\); \}\]/);
});
test('an upstream context-manager change fails explicitly rather than patching the wrong code', () => {
  assert.throws(() => patchFrameBarrier('An incompatible upstream implementation'), /changed its native context manager/);
  assert.throws(() => patchFrameBarrier(patchFrameBarrier(native).replace('resolve(@YES)', 'resolve(@NO)')), /differs from its maintained implementation/);
});
