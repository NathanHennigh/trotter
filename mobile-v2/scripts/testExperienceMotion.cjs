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
function environment({ reduced = false, os = 'android', width = 410, visualWidth = 410 } = {}) {
  let current, nextTimer = 1;
  const timers = new Map(), animations = [], reducedListeners = new Set();
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
    useWindowDimensions: () => ({ width, height: 880 }), Easing: { bezier: () => 'paperEase' },
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
      '../../../theme/trotterTheme': { colors: {}, fonts: {} },
      '../../../utils/mobileLayout': { getMobileVisualWidth: () => visualWidth },
      './WalletCover': { WalletCover: 'WalletCover' }, './tripPresentation': { flightDate: () => '1 Jan 2026' },
    };
    new Function('module', 'exports', 'require', 'setTimeout', 'clearTimeout', code)(module, module.exports, name => {
      if (name === '../motion') return load('components/world-window/motion.tsx');
      assert(name in mocks, `Unexpected dependency: ${name}`); return mocks[name];
    }, callback => { const id = nextTimer++; timers.set(id, callback); return id; }, id => timers.delete(id));
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
  return { motion, load, mount, animations, timers,
    async ready() { const probe = mount(motion.useReducedMotion); probe.render(); await flush(); probe.render(); probe.dispose(); },
    advanceTimers() { const pending = [...timers.values()]; timers.clear(); pending.forEach(fn => fn()); },
    reduce(value) { reduced = value; reducedListeners.forEach(fn => fn(value)); },
  };
}
const trip = { id: 'synthetic', segments: [] };
const props = overrides => ({ trip, origin: { x: 20, y: 300, width: 370, height: 280 }, target: { x: 0, y: 76, width: 410, height: 400 }, closing: false, onClosed() {}, children: 'Real itinerary', ...overrides });
const surface = env => env.load('components/world-window/trips/TripNavigationSurface.tsx').TripNavigationSurface;
const ghost = tree => tree.props.children.find(child => child?.props?.importantForAccessibility === 'no-hide-descendants');

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

test('a ready destination never starts a fallback timer or restarts entry', async () => {
  const env = environment(); await env.ready(); const h = env.mount(surface(env));
  h.render(props()); assert.equal(env.animations.length, 1); assert.equal(env.timers.size, 0);
  env.advanceTimers(); h.render(); assert.equal(env.animations.length, 1); h.dispose();
});

test('late layout cancels fallback; layout after fallback does not restart entry', async () => {
  for (const fallbackFirst of [false, true]) {
    const env = environment(); await env.ready(); const h = env.mount(surface(env));
    h.render(props({ target: undefined })); assert.equal(env.animations.length, 0); assert.equal(env.timers.size, 1);
    if (fallbackFirst) { env.advanceTimers(); h.render(); assert.equal(env.animations.length, 1); }
    h.render(props()); assert.equal(env.animations.length, 1); assert.equal(env.timers.size, 0);
    env.advanceTimers(); h.render(); assert.equal(env.animations.length, 1); h.dispose();
  }
});

test('Back interrupts entry, disables touches and closes exactly once using the current callback', async () => {
  const env = environment(); await env.ready(); let oldCloses = 0, closes = 0;
  const h = env.mount(surface(env)); h.render(props({ onClosed: () => oldCloses++ }));
  const entering = env.animations[0];
  let tree = h.render(props({ closing: true, onClosed: () => oldCloses++ }));
  assert.equal(entering.stopped, true); assert.equal(oldCloses, 0); assert.equal(tree.props.pointerEvents, 'none');
  const closing = env.animations.at(-1); assert.equal(closing.config.toValue, 0); assert.equal(closing.config.duration, 170);
  h.render(props({ closing: true, onClosed: () => closes++ }));
  assert.equal(env.animations.length, 2); closing.finish(); closing.finish();
  assert.equal(closes, 1); assert.equal(oldCloses, 0); h.dispose();
});

test('interrupting a close or unmounting cannot finish an abandoned navigation', async () => {
  const env = environment(); await env.ready(); let closes = 0;
  const h = env.mount(surface(env)), base = props({ onClosed: () => closes++ });
  h.render(base); h.render({ ...base, closing: true }); const oldClose = env.animations.at(-1);
  h.render(base); oldClose.finish(); assert.equal(closes, 0);
  h.render({ ...base, closing: true }); const abandoned = env.animations.at(-1); h.dispose(); abandoned.finish();
  assert.equal(closes, 0);
});

test('reduced motion opens and closes immediately without a moving ghost or paper displacement', async () => {
  const env = environment({ reduced: true }); await env.ready(); let closes = 0;
  const h = env.mount(surface(env)), base = props({ target: undefined, onClosed: () => closes++ });
  let tree = h.render(base); assert.equal(ghost(tree), undefined); assert.equal(env.animations[0].config.duration, 0);
  assert.deepEqual(flatten(tree.props.children[1].props.style).transform, []);
  tree = h.render({ ...base, closing: true }); assert.equal(env.animations.at(-1).config.duration, 0);
  env.animations.at(-1).finish(); assert.equal(closes, 1); h.dispose();
  const paper = env.mount(env.motion.PaperReveal); const rendered = paper.render({ children: 'Paper' });
  assert.deepEqual(flatten(rendered.props.style).transform[0].translateY.outputRange, [0, 0]); paper.dispose();
});

test('enabling reduced motion during Back interrupts the old exit and completes only the immediate one', async () => {
  const env = environment(); await env.ready(); let closes = 0;
  const h = env.mount(surface(env)), base = props({ onClosed: () => closes++ });
  h.render(base); h.render({ ...base, closing: true }); const movingExit = env.animations.at(-1);
  env.reduce(true); const tree = h.render();
  assert.equal(movingExit.stopped, true); assert.equal(closes, 0); assert.equal(ghost(tree), undefined);
  const immediateExit = env.animations.at(-1); assert.equal(immediateExit.config.duration, 0);
  movingExit.finish(); immediateExit.finish(); assert.equal(closes, 1); h.dispose();
});

test('a stale PaperPresence exit never removes newly opened paper', async () => {
  const env = environment(); await env.ready(); const h = env.mount(env.motion.PaperPresence);
  h.render({ children: 'First paper' }); const exiting = h.render({ children: null });
  const reopened = h.render({ children: 'Second paper' }); assert.equal(reopened.props.visible, true);
  exiting.props.onHidden(); assert.deepEqual(h.render().props.children, ['Second paper']); h.dispose();
});

test('wallet ghost is marginless and measured screen bounds are translated into a centered web host', async () => {
  const env = environment({ os: 'web', width: 1000, visualWidth: 410 }); await env.ready(); const h = env.mount(surface(env));
  const origin = { x: 315, y: 300, width: 370, height: 280 }, target = { x: 295, y: 76, width: 410, height: 400 };
  const tree = h.render(props({ origin, target })), paper = ghost(tree), style = paper.props.style;
  assert.equal(paper.props.children[0].props.embedded, true); assert.equal(style.left, 20);
  const scale = style.transform[2].scale.outputRange[1], dx = style.transform[0].translateX.outputRange[1], dy = style.transform[1].translateY.outputRange[1];
  assert.equal(style.left + dx - origin.width * (scale - 1) / 2, 0);
  assert(Math.abs(style.top + dy - origin.height * (scale - 1) / 2 - target.y) < 1e-8);
  h.dispose();
});

test('year-scoped wallet ghost retains the exact source preview while the real detail receives the original trip', async () => {
  const env = environment(); await env.ready(); const h = env.mount(surface(env));
  const fullTrip = { ...trip, flightCount: 2, segments: [{ id: '2025-leg' }, { id: '2026-leg' }] };
  const preview = { ...fullTrip, flightCount: 1, segments: [fullTrip.segments[1]] };
  const source = { x: 20, y: 200, width: 370, height: 280, wallet: { trip: preview, scopeYear: '2026', totalFlightCount: 2 } };
  const tree = h.render(props({ trip: fullTrip, origin: source })), paper = ghost(tree).props.children[0];
  assert.strictEqual(paper.props.trip, preview); assert.equal(paper.props.scopeYear, '2026'); assert.equal(paper.props.totalFlightCount, 2);
  assert.deepEqual(fullTrip.segments.map(s => s.id), ['2025-leg', '2026-leg']); h.dispose();
});

test('paper handoff never renders both moving and itinerary text at positive opacity', async () => {
  const env = environment(); await env.ready(); const h = env.mount(surface(env));
  const tree = h.render(props()), moving = ghost(tree).props.style.opacity;
  const detail = flatten(tree.props.children[1].props.style).opacity;
  const at = (interpolation, progress) => {
    const { inputRange, outputRange } = interpolation;
    const last = inputRange.length - 1;
    if (progress <= inputRange[0]) return outputRange[0];
    if (progress >= inputRange[last]) return outputRange[last];
    const i = inputRange.findIndex((value, index) => index < last && progress >= value && progress <= inputRange[index + 1]);
    return outputRange[i] + (outputRange[i + 1] - outputRange[i]) * (progress - inputRange[i]) / (inputRange[i + 1] - inputRange[i]);
  };
  for (let step = 0; step <= 1000; step++) {
    const progress = step / 1000;
    assert(!(at(moving, progress) > 1e-9 && at(detail, progress) > 1e-9), `Double text at progress ${progress}`);
  }
  assert.equal(at(moving, 0), 1); assert.equal(at(detail, 1), 1); h.dispose();
});
