// Exercise the shipping postcard transition with controlled native motion and
// accessibility events. Images remain covered by testDreamCountryArtwork.cjs.
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), ts = require('typescript');
const { test } = require('node:test');
const file = path.join(__dirname, '../src/components/world-window/dreams/CountryPostcard.tsx');
const board = { key: 'thailand', title: 'Thailand', cities: ['Bangkok', 'Krabi'], items: Array.from({ length: 28 }, (_, i) => ({ id: String(i) })) };
const flush = async () => { for (let i = 0; i < 8; i++) await Promise.resolve(); };
function harness() {
  let slots = [], cursor = 0, effects = [], listener, settlePreference, active, opens = 0, returns = 0;
  const transitions = [], values = [];
  const same = (a, b) => a && b && a.length === b.length && a.every((v, i) => v === b[i]);
  const react = {
    useRef(value) { const i = cursor++; return slots[i] ??= { current: value }; },
    useId() { const i = cursor++; return slots[i] ??= ':postcard-fixture:'; },
    useState(initial) { const i = cursor++; if (!(i in slots)) slots[i] = initial; return [slots[i], value => slots[i] = value]; },
    useCallback(fn, deps) { const i = cursor++; if (!slots[i] || !same(slots[i].deps, deps)) slots[i] = { fn, deps }; return slots[i].fn; },
    useEffect(fn, deps) { const i = cursor++; if (!slots[i] || !same(slots[i].deps, deps)) { slots[i]?.cleanup?.(); slots[i] = { deps }; effects.push(() => slots[i].cleanup = fn()); } },
  };
  class Value {
    constructor(value) { this.value = value; values.push(this); }
    interpolate(config) { return { animated: this, config }; }
    setValue(value) { this.value = value; }
    stopAnimation() { if (active?.value === this) { const callback = active.callback; active = undefined; callback({ finished: false }); } }
  }
  const native = {
    View: 'View', Pressable: 'Pressable', Text: 'Text', StyleSheet: { create: x => x, absoluteFill: {} },
    useWindowDimensions: () => ({ width: 320, height: 880, fontScale: 2 }),
    Easing: { bezier: (...args) => args },
    Animated: { Value, View: 'AnimatedView', timing(value, options) { transitions.push(options); return { start(callback) { active = { value, callback }; } }; } },
    AccessibilityInfo: { isReduceMotionEnabled: () => new Promise(resolve => settlePreference = resolve), addEventListener(name, callback) { listener = callback; return { remove() { listener = undefined; } }; } },
  };
  const jsx = (type, props) => ({ type, props });
  const mocks = {
    react, 'react/jsx-runtime': { jsx, jsxs: jsx }, 'react-native': native,
    'react-native-svg': { default: 'Svg', Defs: 'Defs', LinearGradient: 'LinearGradient', Rect: 'Rect', Stop: 'Stop' },
    '../displayTextFit': { fitDisplayFont: (_text, size) => size },
    '../../../utils/mobileLayout': { getMobileVisualWidth: width => width },
    '../../../theme/trotterTheme': { colors: {}, fonts: {} },
    '../WorldWindowUI': { WWIcon: 'Icon' }, './DreamPhoto': { DreamPhoto: 'DreamPhoto' },
    './dreamImageSource': { postcardReelCover: items => items[0] }, '../../../services/travelTrips': { getApiBaseUrl: () => '' },
  };
  const module = { exports: {} };
  const output = ts.transpileModule(fs.readFileSync(file, 'utf8'), { fileName: file, compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } }).outputText;
  new Function('module', 'exports', 'require', output)(module, module.exports, name => { assert(name in mocks, name); return mocks[name]; });
  return {
    transitions,
    get opens() { return opens; },
    get returns() { return returns; },
    render(nextBoard = board, props = {}) { cursor = 0; const tree = module.exports.CountryPostcard({ board: nextBoard, onPress: () => opens++, onReturned: () => returns++, ...props }); const pending = effects; effects = []; pending.forEach(fn => fn()); return tree; },
    preference(enabled) { settlePreference(enabled); },
    changePreference(enabled) { listener?.(enabled); },
    complete(finished = true) { assert(active, 'An animation must be running'); const callback = active.callback; active = undefined; callback({ finished }); },
    dispose() { slots.forEach(slot => slot?.cleanup?.()); },
  };
}

test('reduced motion opens the country immediately, exactly once, without a separate flip step', async () => {
  const h = harness(), card = h.render(); h.preference(true); await flush();
  card.props.onPress(); card.props.onPress();
  assert.equal(h.opens, 1); assert.equal(h.transitions.length, 0); h.dispose();
});

test('normal motion remains a quick tap-to-open and rejects duplicate taps before React rerenders', async () => {
  const h = harness(), card = h.render(); h.preference(false); await flush();
  card.props.onPress(); card.props.onPress();
  assert.equal(h.opens, 0); assert.equal(h.transitions.length, 1); assert(h.transitions[0].duration <= 200);
  assert.equal(h.render().props.disabled, true);
  h.complete(); assert.equal(h.opens, 1); card.props.onPress(); assert.equal(h.opens, 1); h.dispose();
});

test('an interrupted transition returns to an actionable country front', async () => {
  const h = harness(), card = h.render(); h.preference(false); await flush(); card.props.onPress();
  h.complete(false); const restored = h.render(); assert.equal(restored.props.disabled, false); assert.equal(h.opens, 0);
  restored.props.onPress(); h.complete(); assert.equal(h.opens, 1); h.dispose();
});

test('enabling reduced motion during a turn completes navigation once and cancels the animation', async () => {
  const h = harness(), card = h.render(); h.preference(false); await flush(); card.props.onPress();
  h.changePreference(true); h.changePreference(true); assert.equal(h.opens, 1); assert.equal(h.render().props.disabled, true); h.dispose();
});

test('unmount cancels the transition and a late accessibility response cannot navigate', async () => {
  const h = harness(), card = h.render(); h.preference(false); await flush(); card.props.onPress(); h.dispose();
  h.changePreference(true); assert.equal(h.opens, 0);
  const pending = harness(); pending.render(); pending.dispose(); pending.preference(true); await flush(); assert.equal(pending.opens, 0);
});

test('screen reader names retain the country, count, and direct country-opening purpose', () => {
  const h = harness(); assert.equal(h.render().props.accessibilityLabel, 'Thailand, view 28 saved places');
  assert.equal(h.render({ ...board, items: board.items.slice(0, 1) }).props.accessibilityLabel, 'Thailand, view 1 saved place'); h.dispose();
});

test('Back reverses into the same postcard once, then leaves an actionable front', async () => {
  const h=harness(); let card=h.render(board,{returning:true}); h.preference(false); await flush();
  card.props.onPress(); assert.equal(h.opens,0); assert.equal(h.transitions.length,1); assert.equal(h.transitions[0].toValue,0);
  h.complete(); assert.equal(h.returns,1); card=h.render(); assert.equal(card.props.disabled,false);
  card.props.onPress(); h.complete(); assert.equal(h.opens,1); h.dispose();
});

test('reduced motion Back restores the postcard immediately without another entry action', async () => {
  const h=harness(); h.render(board,{returning:true}); h.preference(true); await flush();
  assert.equal(h.transitions.length,0); assert.equal(h.returns,1); assert.equal(h.opens,0); h.dispose();
});

test('switching away during an opening turn cancels navigation and restores the front for return', async () => {
  const h=harness(); let card=h.render(); h.preference(false); await flush(); card.props.onPress();
  h.render(board,{visible:false}); assert.equal(h.opens,0);
  card=h.render(board,{visible:true}); assert.equal(card.props.disabled,false); card.props.onPress(); h.complete(); assert.equal(h.opens,1); h.dispose();
});

test('reduced motion enabled mid-return ends at the front with one return callback', async () => {
  const h=harness();h.render(board,{returning:true});h.preference(false);await flush();h.changePreference(true);
  assert.equal(h.returns,1);assert.equal(h.render().props.disabled,false);assert.equal(h.opens,0);h.dispose();
});
