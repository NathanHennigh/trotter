// Exercise the shipped postcard entry and coordinated country-page transition.
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), ts = require('typescript');
const { test } = require('node:test');
const directory = path.join(__dirname, '../src/components/world-window/dreams');
const board = { key: 'thailand', title: 'Thailand', cities: ['Bangkok', 'Krabi'], items: Array.from({ length: 28 }, (_, i) => ({ id: String(i) })) };
const library = { type: 'Library', props: { scrollOffset: 430 } }, detail = { type: 'Country', props: {} };
function harness(componentName = 'DreamCountryTransition') {
  let slots = [], cursor = 0, effects = [], props, opens = 0, closes = 0, tree, frameId = 0;
  const frames = new Map();
  const animations = [];
  const same = (a, b) => a && b && a.length === b.length && a.every((v, i) => v === b[i]);
  const react = {
    useState(initial) { const i = cursor++; if (!(i in slots)) slots[i] = typeof initial === 'function' ? initial() : initial;
      return [slots[i], value => { slots[i] = typeof value === 'function' ? value(slots[i]) : value; }]; },
    useRef(value) { return slots[cursor++] ??= { current: value }; },
    useEffect(fn, deps) { const i = cursor++; if (!slots[i] || !same(slots[i].deps, deps)) {
      slots[i]?.cleanup?.(); slots[i] = { deps }; effects.push(() => slots[i].cleanup = fn());
    } },
  };
  const stop = animation => {
    if (!animation.active) return;
    animation.active = false; animation.callback?.({ finished: false });
  };
  class Value {
    constructor(value) { this.value = value; }
    interpolate(config) { return { animated: this, config }; }
    setValue(value) { this.value = value; }
    stopAnimation() { animations.filter(a => a.value === this).forEach(stop); }
  }
  const native = {
    View: 'View', Text: 'Text', StyleSheet: { create: x => x, absoluteFill: {}, absoluteFillObject: {} },
    useWindowDimensions: () => ({ width: 320, height: 880, fontScale: 2 }),
    Easing: { bezier: (...args) => args },
    Animated: { Value, View: 'AnimatedView', timing(value, config) {
      const animation = { value, config, active: false }; animations.push(animation);
      return { start(callback) { animation.callback = callback; animation.active = true; }, stop() { stop(animation); } };
    } },
  };
  const jsx = (type, props) => ({ type, props });
  const mocks = {
    react, 'react/jsx-runtime': { jsx, jsxs: jsx }, 'react-native': native,
    '../motion': { PressFeedback: 'PressFeedback' },
    '../displayTextFit': { fitDisplayFont: (_text, size) => size },
    '../../../utils/mobileLayout': { getMobileVisualWidth: width => width },
    '../../../theme/trotterTheme': { colors: {}, fonts: {} },
    '../WorldWindowUI': { WWIcon: 'Icon' }, './DreamPhoto': { DreamPhoto: 'DreamPhoto' },
    './dreamImageSource': { postcardReelCover: items => items[0] }, '../../../services/travelTrips': { getApiBaseUrl: () => '' },
    './dreamProcessing': { dreamProcessingSummary: () => '' },
  };
  const file = path.join(directory, componentName + '.tsx'), module = { exports: {} };
  const output = ts.transpileModule(fs.readFileSync(file, 'utf8'), { fileName: file, compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true,
  } }).outputText;
  new Function('module', 'exports', 'require', 'requestAnimationFrame', 'cancelAnimationFrame', output)(module, module.exports,
    name => { assert(name in mocks, name); return mocks[name]; },
    callback => { const id = ++frameId; frames.set(id, callback); return id; }, id => frames.delete(id));
  const h = {
    animations,
    get opens() { return opens; }, get closes() { return closes; },
    render(next = props) {
      props = next || {}; cursor = 0;
      const defaults = componentName === 'CountryPostcard'
        ? { board, onPress: () => opens++ }
        : { library, detail, open: true, reducedMotion: false, onClosed: () => closes++ };
      tree = module.exports[componentName]({ ...defaults, ...props });
      const pending = effects; effects = []; pending.forEach(fn => fn()); return tree;
    },
    layout() { animatedViews(tree)[1]?.props.onLayout(); return h.render(); },
    frame() { const pending = [...frames.values()]; frames.clear(); pending.forEach(callback => callback()); },
    advance(progress) { h.frame(); const active = animations.findLast(a => a.active); assert(active); active.value.value = progress; },
    complete() { h.frame(); const active = animations.findLast(a => a.active); assert(active, 'An animation must be running');
      active.active = false; active.value.value = active.config.toValue; active.callback?.({ finished: true }); },
    dispose() { slots.forEach(slot => slot?.cleanup?.()); },
  };
  return h;
}
function nodes(value, seen = new Set()) {
  if (!value || typeof value !== 'object' || seen.has(value)) return [];
  seen.add(value); return [value, ...Object.values(value).flatMap(child => nodes(child, seen))];
}
const animatedViews = tree => nodes(tree).filter(node => node.type === 'AnimatedView');

test('a postcard opens immediately using press feedback, without waiting for a detached flip', () => {
  const h = harness('CountryPostcard'), card = h.render();
  assert.equal(card.type, 'PressFeedback'); card.props.onPress();
  assert.equal(h.opens, 1); assert.equal(h.animations.length, 0); h.dispose();
});

test('hidden postcards cannot trigger navigation and restore their action when visible', () => {
  const h = harness('CountryPostcard'); let card = h.render({ visible: false });
  assert.equal(card.props.disabled, true); card.props.onPress(); assert.equal(h.opens, 0);
  card = h.render({ visible: true }); assert.equal(card.props.disabled, false); card.props.onPress();
  assert.equal(h.opens, 1); h.dispose();
});

test('screen reader names retain the country, count and direct opening purpose', () => {
  const h = harness('CountryPostcard'); assert.equal(h.render().props.accessibilityLabel, 'Thailand, view 28 saved places');
  assert.equal(h.render({ board: { ...board, items: board.items.slice(0, 1) } }).props.accessibilityLabel, 'Thailand, view 1 saved place'); h.dispose();
});

test('country entry keeps the original library mounted behind one short native page animation', () => {
  const h = harness(); h.render({ detail: undefined, open: false });
  assert.equal(h.animations.length, 0);
  const tree = h.render({ open: true }); const views = animatedViews(tree);
  assert.equal(views[0].props.children, library); assert.equal(views[1].props.children, detail);
  assert.equal(views[0].props.pointerEvents, 'none'); assert.equal(views[0].props.importantForAccessibility, 'no-hide-descendants');
  assert.equal(views[1].props.pointerEvents, 'auto');
  assert.equal(h.animations.length, 0, 'List mounting must not consume the page entrance');
  assert.equal(views[1].props.style[1].transform[0].translateX.config.outputRange[0], 320, 'Paper enters from the viewport edge, not an imperceptible nudge');
  h.layout(); assert.equal(h.animations.length, 1); assert.equal(h.animations[0].active, false);
  h.frame(); assert.equal(h.animations[0].active, true); assert.equal(h.animations[0].config.toValue, 1);
  assert.equal(h.animations[0].config.useNativeDriver, true); assert(h.animations[0].config.duration <= 300);
  h.complete(); assert.equal(h.closes, 0); h.dispose();
});

test('Back reverses the same native progress and returns to the retained library once', () => {
  const h = harness(); h.render(); h.layout(); h.complete();
  const tree = h.render({ open: false }); const views = animatedViews(tree);
  assert.equal(views[1].props.pointerEvents, 'none'); assert.equal(h.closes, 0);
  assert.equal(h.animations[1].value, h.animations[0].value); assert.equal(h.animations[1].config.toValue, 0);
  assert.equal(h.animations[1].config.useNativeDriver, true); h.complete(); assert.equal(h.closes, 1);
  const restored = animatedViews(h.render({ open: false, detail: undefined }));
  assert.equal(restored.length, 1); assert.equal(restored[0].props.children, library);
  assert.equal(restored[0].props.pointerEvents, 'auto'); assert.equal(restored[0].props.accessibilityElementsHidden, false); h.dispose();
});

test('closing during entry reverses from the current progress instead of jumping or completing stale navigation', () => {
  const h = harness(); h.render(); h.layout(); h.advance(.45); h.render({ open: false });
  assert.equal(h.animations[0].active, false); assert.equal(h.animations[1].value.value, .45);
  assert.equal(h.closes, 0); h.complete(); assert.equal(h.closes, 1); h.dispose();
});

test('reopening during return cancels its close callback and remains on the country page', () => {
  const h = harness(); h.render(); h.layout(); h.complete(); h.render({ open: false }); h.advance(.6); h.render({ open: true });
  assert.equal(h.animations[1].active, false); assert.equal(h.animations[2].value.value, .6);
  h.complete(); assert.equal(h.closes, 0); h.dispose();
});

test('reduced motion presents and dismisses the page immediately without scheduling motion', () => {
  const h = harness(); let tree = h.render({ reducedMotion: true });
  assert.equal(h.animations.length, 0); assert.equal(animatedViews(tree)[1].props.style[1].opacity.value, 1);
  h.render({ reducedMotion: true, open: false }); assert.equal(h.closes, 1);
  h.render({ reducedMotion: true, open: false }); assert.equal(h.closes, 1); h.dispose();
});

test('enabling reduced motion during return cancels motion and closes only once', () => {
  const h = harness(); h.render(); h.layout(); h.complete(); h.render({ open: false });
  h.render({ open: false, reducedMotion: true }); assert.equal(h.animations[1].active, false); assert.equal(h.closes, 1);
  h.render({ open: false, reducedMotion: true }); assert.equal(h.closes, 1); h.dispose();
});

test('unmount cancels a pending return without invoking navigation after disposal', () => {
  const h = harness(); h.render(); h.layout(); h.complete(); h.render({ open: false }); h.dispose(); h.frame();
  assert(h.animations.every(animation => !animation.active)); assert.equal(h.closes, 0);
});

test('return before native layout cancels the pending opening without an invisible animation', () => {
  const h = harness(); h.render(); h.render({ open: false }); h.frame();
  assert.equal(h.animations.length, 0); assert.equal(h.closes, 1); h.dispose();
});

test('disposing after layout cancels the queued entrance frame', () => {
  const h = harness(); h.render(); h.layout(); h.dispose(); h.frame();
  assert(h.animations.every(animation => !animation.active)); assert.equal(h.closes, 0);
});
