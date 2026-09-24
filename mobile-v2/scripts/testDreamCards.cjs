const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), ts = require('typescript');
const { test } = require('node:test');
const root = path.join(__dirname, '../src'), noop = () => {};
const item = { id: '1', country: 'Thailand', city: 'Krabi', placeName: 'Kuan Nom Saow Café', category: 'cafe',
  tags: [], summary: 'Coffee overlooking the mountains.', sourceUrl: 'https://www.instagram.com/reel/example/', status: 'parsed', needsReview: false };
function host(exportName, items = [item]) {
  const slots = [], cache = {}; let cursor = 0, effects = [], props;
  const same = (a, b) => a && b && a.length === b.length && a.every((v, i) => v === b[i]);
  const react = {
    createElement: (type, props, ...children) => ({ type, props: { ...props, children } }),
    useState(value) { const i = cursor++; if (!(i in slots)) slots[i] = typeof value === 'function' ? value() : value;
      return [slots[i], v => slots[i] = typeof v === 'function' ? v(slots[i]) : v]; },
    useRef(value) { return slots[cursor++] ??= { current: value }; },
    useMemo(fn, deps) { const i = cursor++; if (!slots[i] || !same(slots[i].deps, deps)) slots[i] = { value: fn(), deps }; return slots[i].value; },
    useCallback(fn, deps) { return react.useMemo(() => fn, deps); },
    useEffect(fn, deps) { const i = cursor++; if (!slots[i] || !same(slots[i].deps, deps)) { slots[i]?.cleanup?.(); slots[i] = { deps }; effects.push(() => slots[i].cleanup = fn()); } },
  };
  class Value { interpolate(value) { return value; } stopAnimation() {} setValue() {} }
  const native = { ...Object.fromEntries('View Text Pressable Modal TextInput ScrollView FlatList RefreshControl KeyboardAvoidingView'.split(' ').map(t => [t, t])),
    Platform: { OS: 'android' }, Keyboard: { dismiss: noop }, NativeModules: {}, BackHandler: { addEventListener: () => ({ remove: noop }) },
    StyleSheet: { create: value => value }, Linking: { openURL: async () => {} }, useWindowDimensions: () => ({ width: 390, fontScale: 1 }),
    Animated: { Value, View: 'AnimatedView', timing: () => ({ start: callback => callback?.({ finished: true }) }) } };
  const mocks = {
    react, 'react-native': native, 'react-native-safe-area-context': { useSafeAreaInsets: () => ({ top: 24, bottom: 20 }) },
    '../components/world-window/motion': { useReducedMotion: () => true, PressFeedback: 'Pressable', paperEase: noop },
    '../components/world-window/WorldWindowUI': Object.fromEntries(['WWButton', 'WWHeader', 'WWIcon', 'WWEmpty'].map(t => [t, t])),
    '../components/trotter/TrotterKit': { BottomNav: 'BottomNav' },
    '../components/world-window/dreams/DreamPlacesMap': { DreamPlacesMap: 'DreamPlacesMap' },
    '../components/world-window/dreams/DreamPhoto': { DreamPhoto: 'DreamPhoto' },
    '../components/world-window/dreams/CountryPostcard': { CountryPostcard: 'CountryPostcard' },
    '../components/world-window/dreams/DreamEditor': { DreamEditor: 'DreamEditor' },
    '../services/dreams': { useDreams: () => ({ items, processingItems: [], status: 'ready', refresh: noop, locateMissing: noop }) },
    '../theme/trotterTheme': { colors: {}, fonts: {}, layout: { bottomNavHeight: 73 } },
    '../components/world-window/displayTextFit': { fitDisplayFont: (_text, size) => size },
    '../utils/mobileLayout': { getMobileVisualWidth: width => width },
  };
  function load(filename) {
    if (cache[filename]) return cache[filename];
    const code = fs.readFileSync(filename, 'utf8') + (filename.endsWith('DreamsScreen.tsx') ? '\nexport { CountryPlaces, PlaceRow };' : '');
    const compiled = ts.transpileModule(code, { compilerOptions: { jsx: ts.JsxEmit.React, module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, esModuleInterop: true } }).outputText;
    const mod = { exports: {} };
    new Function('module', 'exports', 'require', compiled)(mod, mod.exports, request => {
      if (request in mocks) return mocks[request];
      const candidate = path.resolve(path.dirname(filename), request);
      if (candidate.endsWith('.json')) return JSON.parse(fs.readFileSync(candidate, 'utf8'));
      for (const extension of ['.ts', '.tsx']) if (fs.existsSync(candidate + extension)) return load(candidate + extension);
      throw Error('Unmocked ' + request);
    });
    return cache[filename] = mod.exports;
  }
  const component = load(path.join(root, 'screens/DreamsScreen.tsx'))[exportName];
  return { model: load(path.join(root, 'components/world-window/dreams/dreamCardPresentation.ts')),
    render(next = props) { props = next; cursor = 0; const tree = component(props); const pending = effects; effects = []; pending.forEach(fn => fn()); return tree; },
    dispose() { slots.forEach(slot => slot?.cleanup?.()); } };
}
function nodes(value, seen = new Set()) { if (!value || typeof value !== 'object' || seen.has(value)) return []; seen.add(value); return [value, ...Object.values(value).flatMap(child => nodes(child, seen))]; }
const find = (tree, type) => nodes(tree).find(node => node.type === type);
const action = (tree, label) => nodes(tree).find(node => node.props?.accessibilityLabel === label);
const text = tree => nodes(tree).filter(node => node.type === 'Text').map(node => node.props.children.flat(Infinity).join(''));
const countryProps = overrides => ({ title: 'Thailand', items: [item], topInset: 0, bottomInset: 20,
  loading: false, onBack: noop, onRefresh: noop, onSelect: noop, onLocateMissing: async () => {}, motion: false, ...overrides });

test('unidentified reels use recognizable source words without inventing a destination or exposing caption clutter', () => {
  const h = host('PlaceRow'), { dreamCardTitle, dreamCardMeta } = h.model;
  const unknown = { ...item, placeName: undefined, city: undefined, country: undefined, category: 'unknown', caption: 'Deluxe room with view #fyp https://example.com', summary: '' };
  assert.equal(dreamCardTitle(unknown), 'Deluxe room with view'); assert.equal(dreamCardMeta(unknown), 'Saved reel');
  assert.equal(dreamCardTitle({ ...unknown, caption: '🏜️' }), '🏜️');
  assert.equal(dreamCardTitle({ ...unknown, caption: '' }), 'Saved reel');
  assert.equal(dreamCardTitle({ ...unknown, caption: '#fyp #travel' }), 'Saved reel');
  assert.equal(dreamCardTitle({ ...item, caption: 'An unrelated line' }), item.placeName);
  assert.equal(dreamCardMeta(item), 'Café · Krabi');
  assert.equal(dreamCardMeta({ ...item, city: undefined, regionOrNeighborhood: 'South Thailand' }), 'Café · South Thailand');
  h.dispose();
});

test('cards have a single details action and a separate pin action only for a valid location', () => {
  let details = 0, pin = 0;
  const h = host('PlaceRow'); let tree = h.render({ item, onPress: () => details++, onShowMap: () => pin++ });
  assert.equal(nodes(tree).filter(node => node.type === 'Pressable').length, 1);
  action(tree, `Details for ${item.placeName}`).props.onPress(); assert.equal(details, 1);
  assert(!nodes(tree).some(node => ['plus', 'close'].includes(node.props?.name)));
  tree = h.render({ item: { ...item, latitude: 8.1, longitude: 98.9 }, onPress: () => details++, onShowMap: () => pin++ });
  action(tree, `Show ${item.placeName} on map`).props.onPress(); assert.equal(pin, 1); assert.equal(details, 1);
  tree = h.render({ item: { ...item, latitude: 8.1, longitude: 98.9, locationProvider: 'google_places', locationExpiresAt: '2020-01-01' }, onPress: noop, onShowMap: noop });
  assert(!action(tree, `Show ${item.placeName} on map`), 'Expired provider coordinates must never appear as a usable pin');
  h.dispose();
});

test('Unsorted is a compact inbox above real country postcards without a redundant review destination', () => {
  const saves = [item, { ...item, id: '2', country: undefined, placeName: undefined, status: 'processing', sortingState: 'running' },
    { ...item, id: '3', country: undefined, status: 'needs_review', sortingState: 'needs_details' },
    { ...item, id: '4', country: undefined, status: 'needs_review', sortingState: 'unavailable' }];
  const h = host('DreamsScreen', saves); let tree = h.render({ active: 'dreams', onChange: noop });
  assert.deepEqual(find(tree, 'FlatList').props.data.map(board => board.title), ['Thailand']);
  const inbox = action(tree, 'Unsorted, 3 saves. 1 sorting · 1 needs details · 1 couldn’t be read'); assert(inbox);
  assert(!text(tree).some(value => /^Review \d/.test(value))); inbox.props.onPress(); tree = h.render();
  const collection = nodes(tree).find(node => typeof node.type === 'function' && node.type.name === 'CountryPlaces');
  assert.equal(collection.props.title, 'Unsorted'); assert.equal(collection.props.items.length, 3);
  collection.props.onBack(); tree = h.render(); assert.equal(find(tree, 'FlatList').props.data.length, 1); h.dispose();
});

test('country card opens details directly while its pin selects the country map and scrolls to it', () => {
  const selected = [], scrolls = [], saved = { ...item, latitude: 8.1, longitude: 98.9 };
  const h = host('CountryPlaces'); let tree = h.render(countryProps({ items: [saved], onSelect: (...value) => selected.push(value) }));
  const list = find(tree, 'FlatList'); list.props.ref.current = { scrollToOffset: value => scrolls.push(value) };
  const row = nodes(list.props.renderItem({ item: saved, index: 0 })).find(node => typeof node.type === 'function' && node.type.name === 'PlaceRow');
  row.props.onPress(); assert.deepEqual(selected, [['1', 'view']]);
  row.props.onShowMap(); tree = h.render(); assert.equal(find(tree, 'DreamPlacesMap').props.selectedId, '1');
  assert.deepEqual(scrolls, [{ offset: 0, animated: false }]); assert.equal(selected.length, 1); h.dispose();
});

test('the detail sheet owns multi-place reel navigation and returning preserves its country', () => {
  const h = host('DreamsScreen', [item, { ...item, id: '2', placeName: 'Second café' }]);
  let tree = h.render({ active: 'dreams', onChange: noop }); const list = find(tree, 'FlatList');
  list.props.renderItem({ item: list.props.data[0] }).props.onPress(); tree = h.render();
  let collection = nodes(tree).find(node => typeof node.type === 'function' && node.type.name === 'CountryPlaces');
  collection.props.onSelect('1', 'view'); tree = h.render(); const detail = find(tree, 'DreamEditor');
  assert.equal(detail.props.sourceCount, 2); detail.props.onShowSource(); tree = h.render();
  assert(!find(tree, 'DreamEditor')); collection = nodes(tree).find(node => typeof node.type === 'function' && node.type.name === 'CountryPlaces');
  assert.equal(collection.props.title, 'From this reel'); assert.equal(collection.props.items.length, 2);
  collection.props.onBack(); tree = h.render(); collection = nodes(tree).find(node => typeof node.type === 'function' && node.type.name === 'CountryPlaces');
  assert.equal(collection.props.title, 'Thailand'); h.dispose();
});
