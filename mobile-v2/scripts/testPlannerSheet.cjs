const assert = require('node:assert/strict');
const { test } = require('node:test');
const fs = require('node:fs'), path = require('node:path'), ts = require('typescript');
const React = require('react'), Renderer = require('react-test-renderer');
const { act } = React;
global.IS_REACT_ACT_ENVIRONMENT = true;
const file = path.resolve(__dirname, '../src/components/world-window/planner/PlannerKit.tsx');
const source = fs.readFileSync(file, 'utf8');
const ast = ts.createSourceFile(file, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const declaration = ast.statements.find(node => ts.isFunctionDeclaration(node) && node.name?.text === 'PlannerSheet');
const code = ts.transpileModule(declaration.getText(ast), {
  compilerOptions: { jsx: ts.JsxEmit.React, module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;

function harness({ reduced = false, keyboardVisible = false, createNodeMock } = {}) {
  const animations = [], reducedNow = { current: reduced };
  class Value {
    constructor(value) { this.value = value; }
    setValue(value) { this.value = value; }
    stopAnimation() { this.animation?.stop(); }
    interpolate(config) { return { value: this, ...config }; }
  }
  const Animated = { Value, View: 'AnimatedView', timing(value, config) {
    const animation = { config, stopped: false, start(callback) {
      value.animation = animation; animation.callback = callback;
      if (!config.duration) animation.finish();
    }, stop() { animation.stopped = true; animation.callback?.({ finished: false }); }, finish() {
      value.value = config.toValue; animation.callback?.({ finished: true });
    } };
    animations.push(animation); return animation;
  } };
  const input = { measureInWindow: fn => fn(0, 600, 100, 48) };
  const globals = {
    React, Animated,
    ...Object.fromEntries(['Modal', 'KeyboardAvoidingView', 'Pressable', 'View', 'Text', 'PressFeedback', 'WWIcon', 'ScrollView'].map(name => [name, name])),
    useSafeAreaInsets: () => ({ bottom: 24 }), useWindowDimensions: () => ({ height: 844 }),
    useReducedMotion: () => reducedNow.current, paperEase: value => value,
    Platform: { OS: 'android' }, StyleSheet: { absoluteFill: {} }, k: {},
    Keyboard: { isVisible: () => keyboardVisible }, TextInput: { State: { currentlyFocusedInput: () => input } },
  };
  const loaded = { exports: {} };
  new Function('module', 'exports', ...Object.keys(globals), code)(loaded, loaded.exports, ...Object.values(globals));
  let view, props = { title: 'Edit this stop', onClose() {}, children: React.createElement('Field', { value: 'Slow morning' }), visible: true };
  return {
    animations, reducedNow,
    async render(patch = {}) { props = { ...props, ...patch }; await act(async () => {
      if (view) view.update(React.createElement(loaded.exports.PlannerSheet, props));
      else view = Renderer.create(React.createElement(loaded.exports.PlannerSheet, props), { createNodeMock });
    }); },
    modal: () => view.root.findByType('Modal'),
    sheet: () => view.root.findAllByType('AnimatedView').find(node => node.props.accessibilityViewIsModal),
    scroll: () => view.root.findByType('ScrollView'),
    field: () => view.root.findByType('Field'),
    async present() { await act(async () => { this.modal().props.onShow(); this.sheet().props.onLayout({ nativeEvent: { layout: { height: 500 } } }); }); },
    async close() { await act(async () => { this.modal().props.onRequestClose(); }); },
    async finish(animation = animations.at(-1)) { await act(async () => animation.finish()); },
    async dispose() { await act(async () => view.unmount()); },
  };
}

test('sheet waits for its window and actual height, then enters with native slide and scrim motion', async () => {
  const h = harness(); await h.render();
  assert.equal(h.modal().props.animationType, 'none'); assert.equal(h.animations.length, 0);
  await h.present();
  assert.equal(h.animations.at(-1).config.duration, 240);
  assert.equal(h.animations.at(-1).config.useNativeDriver, true);
  const style = h.sheet().props.style.at(-1);
  assert.equal(style.paddingBottom, 24); assert.deepEqual(style.transform[0].translateY.outputRange, [500, 0]);
  await h.finish(); await h.dispose();
});

test('back and repeated dismiss gestures finish one exit before closing the parent', async () => {
  let closed = 0; const h = harness(); await h.render({ onClose: () => closed++ }); await h.present(); await h.finish();
  await h.close(); await h.close();
  assert.equal(closed, 0); assert.equal(h.sheet().props.pointerEvents, 'none');
  assert.equal(h.animations.at(-1).config.duration, 150); assert.equal(h.animations.at(-1).config.toValue, 0);
  await h.finish(); assert.equal(closed, 1);
  assert.equal(h.sheet().props.pointerEvents, 'auto'); await h.dispose();
});

test('a hidden retained screen dismisses immediately and cancels a stale close without losing form props', async () => {
  let closed = 0; const h = harness(); await h.render({ onClose: () => closed++ }); await h.present(); await h.finish(); await h.close();
  const stale = h.animations.at(-1); await h.render({ visible: false });
  assert.equal(h.modal().props.visible, false); assert.equal(h.field().props.value, 'Slow morning');
  await h.finish(stale); assert.equal(closed, 0);
  await h.render({ visible: true }); assert.equal(h.modal().props.visible, true);
  await h.present(); await h.finish(); assert.equal(h.sheet().props.pointerEvents, 'auto'); await h.dispose();
});

test('changing form identity during exit cannot close the newly opened form', async () => {
  let oldClosed = 0, newClosed = 0; const h = harness();
  await h.render({ transitionKey: 'stop-one', onClose: () => oldClosed++ }); await h.present(); await h.finish(); await h.close();
  const stale = h.animations.at(-1);
  await h.render({ transitionKey: 'stop-two', onClose: () => newClosed++ }); await h.finish(stale);
  assert.equal(oldClosed, 0); assert.equal(newClosed, 0); assert.equal(h.sheet().props.pointerEvents, 'auto');
  await h.finish(); await h.close(); await h.finish(); assert.equal(newClosed, 1); await h.dispose();
});

test('reduced motion removes translation and dismisses promptly; a live change completes an in-flight exit once', async () => {
  let closed = 0; const h = harness({ reduced: true }); await h.render({ onClose: () => closed++ }); await h.present();
  assert.deepEqual(h.sheet().props.style.at(-1).transform[0].translateY.outputRange, [0, 0]);
  assert.equal(h.animations.at(-1).config.duration, 0); await h.close(); assert.equal(closed, 1); await h.dispose();
  const moving = harness(); closed = 0; await moving.render({ onClose: () => closed++ }); await moving.present(); await moving.finish(); await moving.close();
  const stale = moving.animations.at(-1); moving.reducedNow.current = true; await moving.render();
  assert.equal(closed, 1); await moving.finish(stale); assert.equal(closed, 1); await moving.dispose();
});

test('focused fields are revealed after entering and whenever the keyboard resizes the form', async () => {
  const scrolls = [], scroll = { getNativeScrollRef: () => ({ measureInWindow: fn => fn(0, 100, 320, 400) }), scrollTo: target => scrolls.push(target) };
  const h = harness({ keyboardVisible: true, createNodeMock: element => element.type === 'ScrollView' ? scroll : null });
  await h.render(); await h.present();
  await act(async () => h.scroll().props.onLayout()); assert.equal(scrolls.length, 0);
  await h.finish(); assert.deepEqual(scrolls, [{ y: 172, animated: false }]);
  await act(async () => { h.scroll().props.onScroll({ nativeEvent: { contentOffset: { y: 20 } } }); h.scroll().props.onLayout(); });
  assert.deepEqual(scrolls.at(-1), { y: 192, animated: false }); await h.dispose();
});
