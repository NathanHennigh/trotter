// Real motion components with a bounded Animated/native mock. No timers, network,
// provider state or device are used outside this isolated process.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
const { test } = require('node:test');
const src = path.join(__dirname, '../src');
const flush = async () => { for (let i = 0; i < 8; i++) await Promise.resolve(); };
const flatten = value => Array.isArray(value) ? Object.assign({}, ...value.map(flatten)) : value || {};
function environment({ reduced = false, os = 'android', width = 410, height = 880, visualWidth = 410 } = {}) {
  let current, nextTimer = 1;
  const frames = new Map(), timers = new Map(), animations = [], reducedListeners = new Set();
  const same = (a, b) => a && b && a.length === b.length && a.every((v, i) => v === b[i]);
  const React = {
    createElement: (type, props, ...children) => ({ type, props: { ...props, children } }),
    useRef(value) { const c = current, i = c.cursor++; return c.slots[i] ?? (c.slots[i] = { current: value }); },
    useState(initial) { const c = current, i = c.cursor++; if (!(i in c.slots)) c.slots[i] = typeof initial === 'function' ? initial() : initial; return [c.slots[i], value => { c.slots[i] = typeof value === 'function' ? value(c.slots[i]) : value; }]; },
    useReducer(reducer, initial) { const [value, setValue] = React.useState(initial); return [value, action => setValue(previous => reducer(previous, action))]; },
    useEffect(fn, deps) { const c = current, i = c.cursor++; if (!c.slots[i] || !same(c.slots[i].deps, deps)) { c.slots[i]?.cleanup?.(); c.slots[i] = { deps }; c.effects.push(() => { c.slots[i].cleanup = fn(); }); } },
  };
  class Value {
    constructor(value) { this.value = value; this.active = undefined; }
    stopAnimation() { this.active?.stop(); }
    interpolate(config) { return { ...config, parent: this }; }
  }
  const native = {
    View: 'View', Text: 'Text', Pressable: 'Pressable', Platform: { OS: os },
    StyleSheet: { create: x => x, flatten, absoluteFill: { position: 'absolute', top: 0, left: 0, right: 0, bottom: 0 } },
    useWindowDimensions: () => ({ width, height }), Easing: { bezier: () => 'paperEase' },
    AccessibilityInfo: {
      isReduceMotionEnabled: async () => reduced,
      addEventListener: (_, callback) => { reducedListeners.add(callback); return { remove: () => reducedListeners.delete(callback) }; },
    },
    Animated: {
      View: 'AnimatedView', Value, createAnimatedComponent: type => `Animated(${type})`,
      timing(value, config) {
        const animation = { value, config, callback: undefined, completed: false, stopped: false,
          start(callback) { this.callback = callback; animations.push(this); value.active = this; },
          finish(finished = true) { if (this.completed) return; this.completed = true; if (finished) value.value = config.toValue; if (value.active === this) value.active = undefined; this.callback?.({ finished }); },
          stop() { this.stopped = true; this.finish(false); },
        }; return animation;
      },
      divide: (left, right) => ({ operator: 'divide', left, right }),
      sequence(children) {
        let active, cancelled = false, done = false, callback;
        const complete = finished => { if (!done) { done = true; callback?.({ finished }); } };
        const next = index => {
          if (cancelled) return;
          if (index === children.length) { complete(true); return; }
          active = children[index];
          active.start(({ finished }) => { if (finished && !cancelled) next(index + 1); else complete(false); });
        };
        return { start(fn) { callback = fn; next(0); }, stop() { cancelled = true; active?.stop(); complete(false); } };
      },
    },
  };
  const cache = new Map();
  function load(file) {
    if (cache.has(file)) return cache.get(file);
    const code = ts.transpileModule(fs.readFileSync(path.join(src, file), 'utf8'), { compilerOptions: { jsx: ts.JsxEmit.React, module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, esModuleInterop: true } }).outputText;
    const module = { exports: {} };
    const mocks = {
      react: React, 'react-native': native,
      'react-native-safe-area-context': { useSafeAreaInsets: () => ({ top: 24, bottom: 20 }) },
      '../../../theme/trotterTheme': { colors: { paperSoft: '#faf8f2', ink: '#193a49', paperBorder: '#d6dbd0' }, fonts: {} },
      '../../../utils/mobileLayout': { getMobileVisualWidth: () => visualWidth },
      './WalletCover': { WalletCover: 'WalletCover', walletColors: { blue: '#427494' } },
      '../WorldWindowUI': { WWIcon: 'WWIcon' },
    };
    new Function('module', 'exports', 'require', 'setTimeout', 'clearTimeout', 'requestAnimationFrame', 'cancelAnimationFrame', code)(module, module.exports, name => {
      if (name === '../motion') return load('components/world-window/motion.tsx');
      if (name === './walletPopupGeometry') return load('components/world-window/trips/walletPopupGeometry.ts');
      assert(name in mocks, `Unexpected dependency: ${name}`); return mocks[name];
    }, callback => { const id = nextTimer++; timers.set(id, callback); return id; }, id => timers.delete(id), callback => { const id = nextTimer++; frames.set(id, callback); return id; }, id => frames.delete(id));
    cache.set(file, module.exports); return module.exports;
  }
  function mount(Component, initialProps) {
    const c = { slots: [], cursor: 0, effects: [], props: initialProps };
    return {
      render(props = c.props) { c.props = props; c.cursor = 0; current = c; const tree = Component(props); const pending = c.effects; c.effects = []; pending.forEach(fn => fn()); current = undefined; return tree; },
      dispose() { c.slots.forEach(slot => slot?.cleanup?.()); },
    };
  }
  const motion = load('components/world-window/motion.tsx');
  return { motion, load, mount, animations, timers, frames,
    async ready() { const probe = mount(motion.useReducedMotion); probe.render(); await flush(); probe.render(); probe.dispose(); },
    advanceFrame() { const pending = [...frames.values()]; frames.clear(); pending.forEach(fn => fn()); },
    advanceTimers() { const pending = [...timers.values()]; timers.clear(); pending.forEach(fn => fn()); },
    reduce(value) { reduced = value; reducedListeners.forEach(fn => fn(value)); },
  };
}
const trip = { id: 'synthetic', segments: [] };
const props = overrides => ({ trip, origin: { x: 20, y: 300, width: 370, height: 280,
  wallet: { trip, scopeYear: '2026', totalFlightCount: 4 } }, closing: false, onClosed() {}, onRequestClose() {}, children: 'Real itinerary', ...overrides });
const surface = env => env.load('components/world-window/trips/TripNavigationSurface.tsx').TripNavigationSurface;
function nodes(tree) {
  if (!tree || typeof tree !== 'object') return [];
  if (Array.isArray(tree)) return tree.flatMap(nodes);
  return [tree, ...nodes(tree.props?.children)];
}
const byId = (tree, id) => nodes(tree).find(node => node.props?.testID === id);
const ghost = tree => byId(tree, 'wallet-source-cover');
function sampled(value, progress) {
  if (typeof value === 'number') return value;
  if (value.operator === 'divide') return sampled(value.left, progress) / sampled(value.right, progress);
  if (value.inputRange) {
    const amount = sampled(value.parent, progress), input = value.inputRange, output = value.outputRange;
    let index = 0;
    while (index < input.length - 2 && amount > input[index + 1]) index++;
    const fraction = (amount - input[index]) / (input[index + 1] - input[index]);
    return output[index] + (output[index + 1] - output[index]) * fraction;
  }
  assert.equal(typeof value.value, 'number'); return progress ?? value.value;
}
const transform = (tree, id, key) => flatten(byId(tree, id).props.style).transform.find(entry => key in entry)?.[key];

test('disabled opacity and base transforms survive concrete Animated Pressable styles', async () => {
  const env = environment(); await env.ready();
  const h = env.mount(env.motion.PressFeedback);
  const tree = h.render({ disabled: true, style: [{ opacity: .45 }, { transform: [{ rotate: '-2deg' }] }] });
  assert.equal(tree.props.disabled, true); assert(Array.isArray(tree.props.style));
  const style = flatten(tree.props.style);
  assert.deepEqual(style.opacity.outputRange, [.45, .45 * .72]);
  assert.deepEqual(style.transform, [{ rotate: '-2deg' }]); h.dispose();
});

test('paper feedback composes the caller style and interrupts a press with its release', async () => {
  const env = environment(); await env.ready(); let downs = 0, ups = 0;
  const h = env.mount(env.motion.PressFeedback);
  const input = { paper: true, style: ({ pressed }) => [{ backgroundColor: pressed ? 'pressed' : 'rest', opacity: .8, transform: [{ rotate: '3deg' }] }], onPressIn: () => downs++, onPressOut: () => ups++ };
  let tree = h.render(input); assert.equal(flatten(tree.props.style).backgroundColor, 'rest');
  tree.props.onPressIn({}); tree = h.render();
  assert.equal(flatten(tree.props.style).backgroundColor, 'pressed'); assert.equal(downs, 1);
  assert.deepEqual(flatten(tree.props.style).transform[0], { rotate: '3deg' });
  assert.equal(flatten(tree.props.style).transform[1].translateY.outputRange[1], 1);
  tree.props.onPressOut({}); tree = h.render();
  assert.equal(ups, 1); assert.equal(flatten(tree.props.style).backgroundColor, 'rest');
  assert.equal(env.animations[0].stopped, true);
  assert.deepEqual(env.animations.map(a => [a.config.toValue, a.config.duration, a.config.useNativeDriver]), [[1, 65, true], [0, 150, true]]);
  h.dispose(); assert.equal(env.animations.at(-1).stopped, true);
});


const movingSurface = tree => byId(tree, 'wallet-popup-panel');
const paintEntry = (h, env, tree = h.render()) => {
  movingSurface(tree).props.onLayout(); h.render(); env.advanceFrame(); env.advanceFrame(); return h.render();
};

test('wallet entry waits for native layout and two painted frames, then lifts before opening', async () => {
  const env = environment(); await env.ready(); const h = env.mount(surface(env));
  const tree = h.render(props());
  assert.equal(env.animations.length, 0); assert.equal(env.frames.size, 0);
  movingSurface(tree).props.onLayout(); h.render();
  assert.equal(env.animations.length, 0); assert.equal(env.frames.size, 1);
  env.advanceFrame(); assert.equal(env.animations.length, 0);
  env.advanceFrame();
  assert.equal(env.animations.length, 1); assert.equal(env.timers.size, 0);
  const lift = env.animations[0]; assert.equal(lift.config.toValue, .22); assert.equal(lift.config.duration, 85);
  assert.equal(lift.config.useNativeDriver, true);
  const panel = movingSurface(tree), style = flatten(panel.props.style);
  assert.equal(style.backgroundColor, '#427494'); assert.equal(style.transformOrigin, 'top left');
  assert.deepEqual(byId(tree, 'wallet-popup-content').props.children, ['Real itinerary']);
  assert.equal(flatten(tree.props.style).overflow, 'hidden');
  assert.equal(ghost(tree).props.pointerEvents, 'none');
  assert.equal(ghost(tree).props.importantForAccessibility, 'no-hide-descendants');
  assert.equal(sampled(flatten(ghost(tree).props.style).opacity, .22), 1);
  assert.equal(sampled(flatten(byId(tree, 'wallet-popup-content').props.style).opacity, .22), 0);
  lift.finish(); assert.equal(env.animations.length, 2);
  const opening = env.animations[1]; assert.equal(opening.config.toValue, 1); assert.equal(opening.config.duration, 245);
  assert.equal(opening.config.useNativeDriver, true); assert.equal(opening.value.value, .22);
  opening.finish(); assert.equal(sampled(flatten(ghost(tree).props.style).opacity), 0);
  assert.equal(sampled(flatten(byId(tree, 'wallet-popup-content').props.style).opacity), 1);
  h.dispose();
});

test('hydration and late source measurements cannot retarget, replace the captured wallet, or restart entry', async () => {
  const env = environment(); await env.ready(); const h = env.mount(surface(env));
  const base = props(), initial = h.render(base); paintEntry(h, env, initial);
  const lift = env.animations[0]; lift.finish(); env.animations[1].value.value = .4;
  const changed = h.render(props({ trip: { ...trip, title: 'Hydrated trip' }, origin: { x: 200, y: -30, width: 20, height: 5,
    wallet: { trip: { ...trip, title: 'Other wallet' }, scopeYear: '2025' } } }));
  assert.equal(env.animations.length, 2); assert.equal(env.animations[1].stopped, false);
  for (const key of ['translateX', 'translateY', 'scaleX', 'scaleY']) {
    const before = transform(initial, 'wallet-popup-panel', key), after = transform(changed, 'wallet-popup-panel', key);
    assert.strictEqual(before.parent, after.parent); assert.deepEqual(before.outputRange, after.outputRange);
    assert.equal(after.parent.value, .4);
  }
  assert.strictEqual(ghost(changed).props.children[0].props.trip, base.origin.wallet.trip);
  assert.equal(ghost(changed).props.children[0].props.scopeYear, '2026'); h.dispose();
});

test('Back reverses the current position, blocks fall-through touches, and closes once with the latest callback', async () => {
  const env = environment(); await env.ready(); let oldCloses = 0, closes = 0;
  const h = env.mount(surface(env)); h.render(props({ onClosed: () => oldCloses++ })); paintEntry(h, env);
  env.animations[0].finish(); const entering = env.animations[1]; entering.value.value = .42;
  let tree = h.render(props({ closing: true, onClosed: () => oldCloses++ }));
  assert.equal(entering.stopped, true); assert.equal(oldCloses, 0);
  assert.notEqual(tree.props.pointerEvents, 'none', 'The closing overlay must intercept source-list taps');
  assert.equal(movingSurface(tree).props.pointerEvents, 'none');
  assert.equal(byId(tree, 'wallet-backdrop').props.onPress, undefined);
  assert.equal(byId(tree, 'wallet-popup-dismiss').props.children[0].props.disabled, true);
  const closing = env.animations.at(-1); assert.equal(closing.config.toValue, 0);
  assert(closing.config.duration > 0 && closing.config.duration <= 300);
  assert.equal(closing.value.value, .42, 'Reversal retains its current position');
  h.render(props({ closing: true, onClosed: () => closes++ }));
  assert.equal(env.animations.length, 3); closing.finish(); closing.finish();
  assert.equal(closes, 1); assert.equal(oldCloses, 0); h.dispose();
});

test('Back during lift cancels the pending second stage without opening the itinerary later', async () => {
  const env = environment(); await env.ready(); let closes = 0;
  const h = env.mount(surface(env)), base = props({ onClosed: () => closes++ });
  h.render(base); paintEntry(h, env); const lift = env.animations[0]; lift.value.value = .11;
  h.render({ ...base, closing: true });
  assert.equal(lift.stopped, true); assert.equal(env.animations.length, 2);
  const exit = env.animations[1]; assert.equal(exit.config.toValue, 0); assert.equal(exit.value.value, .11);
  lift.finish(); assert.equal(env.animations.length, 2); assert.equal(closes, 0);
  exit.finish(); assert.equal(closes, 1); h.dispose();
});

test('interrupting a close or unmounting cannot finish an abandoned navigation', async () => {
  const env = environment(); await env.ready(); let closes = 0;
  const h = env.mount(surface(env)), base = props({ onClosed: () => closes++ });
  h.render(base); paintEntry(h, env); h.render({ ...base, closing: true }); const oldClose = env.animations.at(-1);
  h.render(base); oldClose.finish(); assert.equal(closes, 0);
  assert.equal(env.animations.at(-1).config.toValue, 1, 'Reopening resumes directly instead of replaying lift');
  h.render({ ...base, closing: true }); const abandoned = env.animations.at(-1); h.dispose(); abandoned.finish();
  assert.equal(closes, 0);
});

test('backdrop, accessible escape and labelled close all request dismissal without duplicating completion', async () => {
  const env = environment(); await env.ready(); let requests = 0, completions = 0;
  const h = env.mount(surface(env)), tree = h.render(props({ onRequestClose: () => requests++, onClosed: () => completions++, closeLabel: 'Back to Trips' }));
  assert.equal(tree.props.accessibilityViewIsModal, true);
  assert.equal(byId(tree, 'wallet-backdrop-tint').props.pointerEvents, 'none');
  byId(tree, 'wallet-backdrop').props.onPress(); tree.props.onAccessibilityEscape();
  const close = byId(tree, 'wallet-popup-dismiss').props.children[0];
  assert.equal(close.props.accessibilityRole, 'button'); assert.equal(close.props.accessibilityLabel, 'Back to Trips');
  assert(flatten(close.props.style).width >= 44 && flatten(close.props.style).height >= 44);
  close.props.onPress(); assert.equal(requests, 3); assert.equal(completions, 0); h.dispose();
});

test('reduced motion exposes real paper immediately and closes without lift or scaling', async () => {
  const env = environment({ reduced: true }); await env.ready(); let closes = 0;
  const h = env.mount(surface(env)), base = props({ onClosed: () => closes++ });
  let tree = h.render(base); assert.equal(ghost(tree), undefined); assert.equal(env.animations[0].config.duration, 0);
  assert.deepEqual(flatten(movingSurface(tree).props.style).transform, []);
  const content = flatten(byId(tree, 'wallet-popup-content').props.style);
  assert.deepEqual(content.transform, []); assert.equal(content.opacity, 1); assert.equal(env.frames.size, 0);
  tree = h.render({ ...base, closing: true }); assert.equal(env.animations.at(-1).config.duration, 0);
  env.animations.at(-1).finish(); assert.equal(closes, 1); h.dispose();
  const paper = env.mount(env.motion.PaperReveal); const rendered = paper.render({ children: 'Paper' });
  assert.deepEqual(flatten(rendered.props.style).transform[0].translateY.outputRange, [0, 0]); paper.dispose();
});

test('enabling reduced motion during Back cancels the previous completion callback', async () => {
  const env = environment(); await env.ready(); let closes = 0;
  const h = env.mount(surface(env)), base = props({ onClosed: () => closes++ });
  h.render(base); paintEntry(h, env); h.render({ ...base, closing: true }); const movingExit = env.animations.at(-1);
  env.reduce(true); const tree = h.render();
  assert.equal(movingExit.stopped, true); assert.equal(closes, 0);
  assert.deepEqual(flatten(movingSurface(tree).props.style).transform, []); assert.equal(ghost(tree), undefined);
  const immediateExit = env.animations.at(-1); assert.equal(immediateExit.config.duration, 0);
  movingExit.finish(); immediateExit.finish(); assert.equal(closes, 1); h.dispose();
});

test('a stale PaperPresence exit never removes newly opened paper', async () => {
  const env = environment(); await env.ready(); const h = env.mount(env.motion.PaperPresence);
  h.render({ children: 'First paper' }); const exiting = h.render({ children: null });
  const reopened = h.render({ children: 'Second paper' }); assert.equal(reopened.props.visible, true);
  exiting.props.onHidden(); assert.deepEqual(h.render().props.children, ['Second paper']); h.dispose();
});

for (const dimensions of [
  { os: 'android', width: 320, height: 640, visualWidth: 320, expectedWidth: 320 },
  { os: 'android', width: 410, height: 880, visualWidth: 410, expectedWidth: 410 },
  { os: 'android', width: 800, height: 1024, visualWidth: 430, expectedWidth: 800 },
  { os: 'web', width: 1000, height: 880, visualWidth: 430, expectedWidth: 430 },
]) test(`popup stays inset and its growing clip never vertically distorts content: ${dimensions.os} ${dimensions.width}`, async () => {
  const env = environment(dimensions); await env.ready(); const h = env.mount(surface(env));
  const origin = { x: 20, y: 160, width: Math.min(dimensions.expectedWidth - 40, 540), height: 220, wallet: { trip } };
  const geometry = env.load('components/world-window/trips/walletPopupGeometry.ts').walletPopupGeometry;
  const layout = geometry(dimensions.expectedWidth, dimensions.height, 24, 20, origin);
  assert.equal(layout.anchored, true); assert.deepEqual(layout.source, { x: origin.x, y: origin.y, width: origin.width, height: origin.height });
  const tree = h.render(props({ origin })), panelStyle = flatten(movingSurface(tree).props.style);
  const { target } = layout;
  assert.equal(panelStyle.left, target.x); assert.equal(panelStyle.top, target.y);
  assert(target.x >= 20 && target.x + target.width <= dimensions.expectedWidth - 20);
  assert(target.y >= 24 + 44 && target.y + target.height <= dimensions.height - 20);
  assert(target.width <= 560);
  const scaleY = transform(tree, 'wallet-popup-panel', 'scaleY');
  const inverseY = transform(tree, 'wallet-popup-content', 'scaleY');
  for (let step = 0; step <= 1000; step++) {
    const progress = step / 1000;
    for (const key of ['translateX', 'translateY', 'scaleX', 'scaleY']) assert(Number.isFinite(sampled(transform(tree, 'wallet-popup-panel', key), progress)));
    const sy = sampled(scaleY, progress); assert(sy > 0);
    assert(Math.abs(sy * sampled(inverseY, progress) - 1) < 1e-12, 'Native type/map height must remain unscaled');
    const contentAlpha = sampled(flatten(byId(tree, 'wallet-popup-content').props.style).opacity, progress);
    const coverAlpha = sampled(flatten(ghost(tree).props.style).opacity, progress);
    const summaryAlpha = sampled(ghost(tree).props.children[0].props.bodyOpacity, progress) * coverAlpha;
    assert.equal(summaryAlpha * contentAlpha, 0, 'Coupon text and route-map text never overlap during the handoff');
    assert(contentAlpha >= 0 && contentAlpha <= 1 && coverAlpha >= 0 && coverAlpha <= 1);
    assert(contentAlpha + coverAlpha > .99, 'There must always be visible paper through the reveal');
  }
  assert.equal(sampled(transform(tree, 'wallet-popup-panel', 'translateY'), .22), origin.y - target.y - 22);
  assert.equal(sampled(scaleY, 0) * target.height, origin.height);
  assert.equal(sampled(scaleY, 1), 1);
  assert.equal(sampled(transform(tree, 'wallet-popup-panel', 'translateX'), 1), 0);
  assert.equal(sampled(transform(tree, 'wallet-popup-panel', 'translateY'), 1), 0);
  h.dispose();
});

test('absent, invalid or fully offscreen sources use finite nearby reveal geometry without a wallet snapshot', async () => {
  const base = props().origin;
  for (const origin of [undefined, { ...base, wallet: undefined }, { ...base, x: NaN }, { ...base, height: Infinity },
    { ...base, width: 0 }, { ...base, height: -5 }, { ...base, y: -500 }, { ...base, y: 900 }, { ...base, x: 500 }]) {
    const env = environment(); await env.ready(); const h = env.mount(surface(env));
    const geometry = env.load('components/world-window/trips/walletPopupGeometry.ts').walletPopupGeometry;
    const layout = geometry(410, 880, 24, 20, origin);
    assert.equal(layout.anchored, false);
    assert(Object.values(layout.source).every(Number.isFinite)); assert(Object.values(layout.target).every(Number.isFinite));
    const tree = h.render(props({ origin })); assert.equal(ghost(tree), undefined);
    assert.equal(sampled(transform(tree, 'wallet-popup-panel', 'translateY'), 0), 34);
    assert.equal(sampled(flatten(byId(tree, 'wallet-popup-content').props.style).opacity, 0), 1);
    paintEntry(h, env, tree); assert.equal(env.animations.length, 1); assert.equal(env.animations[0].config.toValue, 1);
    h.dispose();
  }
});

test('Back during initial layout/paint cancels pending entry and closes without flashing the itinerary', async () => {
  for (const framesPainted of [0, 1]) {
    const env = environment(); await env.ready(); let closes = 0;
    const h = env.mount(surface(env)), base = props({ onClosed: () => closes++ });
    const tree = h.render(base); movingSurface(tree).props.onLayout(); h.render();
    if (framesPainted) env.advanceFrame();
    h.render({ ...base, closing: true });
    assert.equal(env.frames.size, 0); assert.equal(env.animations.length, 1);
    assert.equal(env.animations[0].config.duration, 0); assert.equal(env.animations[0].config.toValue, 0);
    env.advanceFrame(); env.advanceFrame(); assert.equal(env.animations.length, 1);
    env.animations[0].finish(); assert.equal(closes, 1); h.dispose();
  }
});

test('unmount before first paint or during lift cancels pending stages without opening or navigating', async () => {
  for (const startLift of [false, true]) {
    const env = environment(); await env.ready(); let closes = 0;
    const h = env.mount(surface(env)), tree = h.render(props({ onClosed: () => closes++ }));
    movingSurface(tree).props.onLayout(); h.render(); env.advanceFrame();
    if (startLift) env.advanceFrame();
    const count = env.animations.length; h.dispose(); env.animations.at(-1)?.finish();
    assert.equal(env.frames.size, 0); env.advanceFrame(); assert.equal(env.animations.length, count); assert.equal(closes, 0);
  }
});

test('cold preference resolution cannot collapse an already exposed itinerary back into its wallet', async () => {
  const env = environment(); const h = env.mount(surface(env));
  const tree = h.render(props()); assert.deepEqual(flatten(movingSurface(tree).props.style).transform, []);
  assert.equal(env.animations[0].value.value, 1);
  await flush(); const normal = h.render();
  assert.equal(sampled(transform(normal, 'wallet-popup-panel', 'scaleY')), 1);
  assert.equal(sampled(transform(normal, 'wallet-popup-panel', 'translateY')), 0);
  assert.equal(sampled(flatten(ghost(normal).props.style).opacity), 0);
  assert.equal(env.animations.at(-1).config.toValue, 1); h.dispose();
});
