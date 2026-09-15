// Exercise shipping Dreams event handlers with synthetic saves and controlled motion.
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), ts = require('typescript');
const { test } = require('node:test');
const root = path.join(__dirname, '../src');
const noop = () => {}, flush = async () => { for (let n = 0; n < 20; n++) await Promise.resolve(); };
const item = { id: '1', country: 'Portugal', city: 'Lisbon', placeName: 'Saved café', category: 'cafe',
  tags: ['Coffee'], summary: 'Original notes', sourceUrl: 'https://www.instagram.com/reel/example', status: 'confirmed', needsReview: false };
function host(file, exportName, options = {}) {
  let slots = [], cursor = 0, effects = [], props, live = options.live || {}, account = options.items || [item];
  const animations = [], keyboard = { dismiss: noop }, same = (a, b) => a && b && a.length === b.length && a.every((v, i) => v === b[i]);
  const react = {
    createElement: (type, props, ...children) => ({ type, props: { ...props, children } }),
    useState(value) { const i = cursor++; if (!(i in slots)) slots[i] = typeof value === 'function' ? value() : value;
      return [slots[i], value => slots[i] = typeof value === 'function' ? value(slots[i]) : value]; },
    useRef(value) { return slots[cursor++] ??= { current: value }; },
    useMemo(fn, deps) { const i = cursor++; if (!slots[i] || !same(slots[i].deps, deps)) slots[i] = { value: fn(), deps }; return slots[i].value; },
    useCallback(fn, deps) { return react.useMemo(() => fn, deps); },
    useEffect(fn, deps) { const i = cursor++; if (!slots[i] || !same(slots[i].deps, deps)) { slots[i]?.cleanup?.(); slots[i] = { deps }; effects.push(() => slots[i].cleanup = fn()); } },
  };
  class Value {
    constructor(value) { this.value = value; }
    interpolate(config) { return { value: this, config }; }
    setValue(value) { this.value = value; }
    stopAnimation() { for (const a of animations) if (a.value === this && a.callback) { const fn = a.callback; a.callback = undefined; fn({ finished: false }); } }
  }
  const tags = 'View Text Pressable Modal TextInput ScrollView FlatList RefreshControl KeyboardAvoidingView'.split(' ');
  const native = { ...Object.fromEntries(tags.map(t => [t, t])), Platform: { OS: 'android' }, Keyboard: keyboard,
    BackHandler: { addEventListener: () => ({ remove: noop }) }, StyleSheet: { create: x => x, absoluteFill: {} },
    Linking: { openURL: async () => {} }, useWindowDimensions: () => ({ width: 320, fontScale: 2 }),
    Animated: { Value, View: 'AnimatedView', timing(value, config) { const a = { value, config }; animations.push(a); return { start(callback) { a.callback = callback; if (!config.duration) { value.value = config.toValue; callback?.({ finished: true }); a.callback = undefined; } } }; } },
  };
  const allMocks = {
    react, 'react-native': native, 'react-native-safe-area-context': { useSafeAreaInsets: () => ({ top: 24, bottom: 20 }) },
    '../motion': { useReducedMotion: () => options.reduced !== false, PressFeedback: 'Pressable' },
    '../components/world-window/motion': { useReducedMotion: () => options.reduced !== false, PressFeedback: 'Pressable', paperEase: noop },
    '../../../utils/experiencePreferences': { selectionHaptic: async () => {} },
    '../WorldWindowUI': { WWButton: 'WWButton', WWHeader: 'WWHeader', WWIcon: 'WWIcon' },
    '../components/world-window/WorldWindowUI': { WWButton: 'WWButton', WWHeader: 'WWHeader', WWIcon: 'WWIcon', WWEmpty: 'WWEmpty' },
    '../components/trotter/TrotterKit': { BottomNav: 'BottomNav' },
    './DreamPlacesMap': { DreamPlacesMap: 'DreamPlacesMap' },
    '../components/world-window/dreams/DreamPlacesMap': { DreamPlacesMap: 'DreamPlacesMap' },
    './DreamPhoto': { DreamPhoto: 'DreamPhoto' },
    '../components/world-window/dreams/DreamPhoto': { DreamPhoto: 'DreamPhoto', PlaceSymbol: 'PlaceSymbol' },
    '../components/world-window/dreams/CountryPostcard': { CountryPostcard: 'CountryPostcard' },
    '../components/world-window/dreams/DreamEditor': { DreamEditor: 'DreamEditor' },
    './useLiveDreamLocation': { useLiveDreamLocation: (_item, enabled) => { options.liveEnabled = enabled; return live; } },
    '../services/dreams': { useDreams: () => ({ items: account, processingItems: [], status: 'ready', refresh: noop, locateMissing: noop }) },
    '../theme/trotterTheme': { colors: {}, fonts: {}, layout: { bottomNavHeight: 73 } },
    '../../../theme/trotterTheme': { colors: {}, fonts: {} },
    '../displayTextFit': { fitDisplayFont: (_text, size) => size },
    '../components/world-window/displayTextFit': { fitDisplayFont: (_text, size) => size },
    '../../../utils/mobileLayout': { getMobileVisualWidth: width => width },
    '../utils/mobileLayout': { getMobileVisualWidth: width => width },
  };
  const cache = {};
  function load(filename) {
    if (cache[filename]) return cache[filename];
    const code = fs.readFileSync(filename, 'utf8') + (filename.endsWith('DreamsScreen.tsx') ? '\nexport { CountryPlaces, CapturePlace };' : '');
    const compiled = ts.transpileModule(code, { compilerOptions: { jsx: ts.JsxEmit.React, module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, esModuleInterop: true } }).outputText;
    const mod = { exports: {} };
    new Function('module','exports','require', compiled)(mod, mod.exports, request => {
      if (request in allMocks) return allMocks[request];
      const candidate = path.resolve(path.dirname(filename), request);
      if (candidate.endsWith('.json') && fs.existsSync(candidate)) return JSON.parse(fs.readFileSync(candidate, 'utf8'));
      for (const extension of ['.ts','.tsx']) if (fs.existsSync(candidate + extension)) return load(candidate + extension);
      throw new Error('Unmocked dependency ' + request);
    });
    cache[filename] = mod.exports; return mod.exports;
  }
  const component = load(path.join(root, file))[exportName];
  return {
    render(next = props) { props = next; cursor = 0; const tree = component(props); const pending = effects; effects = []; pending.forEach(fn => fn()); return tree; },
    live(next) { live = next; }, account(next) { account = next; }, animations,
    complete() { for (const a of animations) if (a.callback) { const fn = a.callback; a.callback = undefined; a.value.value = a.config.toValue; fn({ finished: true }); } },
    dispose() { slots.forEach(slot => slot?.cleanup?.()); },
  };
}
function nodes(value, seen = new Set()) {
  if (!value || typeof value !== 'object' || seen.has(value)) return [];
  seen.add(value); return [value, ...Object.values(value).flatMap(child => nodes(child, seen))];
}
const byType = (tree, type) => nodes(tree).find(node => node.type === type);
const action = (tree, label) => nodes(tree).find(node => node.props?.label === label || node.props?.accessibilityLabel === label);
const text = tree => nodes(tree).filter(node => node.type === 'Text').map(node => node.props.children.flat(Infinity).join(''));
const editor = 'components/world-window/dreams/DreamEditor.tsx', screen = 'screens/DreamsScreen.tsx';
const editorProps = overrides => ({ item, points: [], onSave: async () => {}, onDelete: async () => {}, onClose: noop, onRetry: noop, ...overrides });
const countryProps = overrides => ({ title: 'Portugal', items: [item], review: false, topInset: 0, bottomInset: 20,
  loading: false, onBack: noop, onRefresh: noop, onSelect: noop, onLocateMissing: async () => {}, motion: false, ...overrides });

test('direct Edit starts in the form; Close guards changed fields, Keep editing retains them, Discard alone closes', () => {
  let closes = 0;
  const h = host(editor, 'DreamEditor'); let tree = h.render(editorProps({ initialMode: 'edit', onClose: () => closes++ }));
  assert(action(tree, 'Place name')); assert(!action(tree, 'Edit details'));
  action(tree, 'Notes').props.onChange('Unsaved personal notes'); tree = h.render();
  action(tree, 'Close place').props.onPress(); tree = h.render();
  assert.equal(closes, 0); assert(action(tree, 'Keep editing')); assert(!action(tree, 'Save changes'));
  action(tree, 'Keep editing').props.onPress(); tree = h.render();
  assert.equal(action(tree, 'Notes').props.value, 'Unsaved personal notes');
  byType(tree, 'Modal').props.onRequestClose(); tree = h.render();
  action(tree, 'Discard changes').props.onPress(); assert.equal(closes, 1); h.dispose();
});

test('hardware Back and hidden-tab return preserve a dirty editor; hidden views do not fetch live Google details', () => {
  let handler, closes = 0; const options = {};
  const h = host(editor, 'DreamEditor', options);
  const props = editorProps({ initialMode: 'edit', onClose: () => closes++, onCloseRequestChange: value => handler = value });
  let tree = h.render(props); action(tree, 'City').props.onChange('Porto'); tree = h.render();
  handler(); tree = h.render(); assert(action(tree, 'Keep editing')); assert.equal(closes, 0);
  byType(tree, 'Modal').props.onRequestClose(); tree = h.render(); assert.equal(action(tree, 'City').props.value, 'Porto');
  tree = h.render({ ...props, visible: false, item: { ...item, city: 'Later parsed city' } });
  assert.equal(byType(tree, 'Modal').props.visible, false); assert.equal(options.liveEnabled, false); assert.equal(handler, null);
  tree = h.render({ ...props, visible: true }); assert.equal(action(tree, 'City').props.value, 'Porto'); h.dispose();
});

test('reverting a draft to its baseline allows ordinary close without a confirmation', () => {
  let closes = 0; const h = host(editor, 'DreamEditor'); let tree = h.render(editorProps({ initialMode: 'edit', onClose: () => closes++ }));
  action(tree, 'Notes').props.onChange('Temporary'); tree = h.render(); action(tree, 'Notes').props.onChange(item.summary); tree = h.render();
  action(tree, 'Close place').props.onPress(); assert.equal(closes, 1); h.dispose();
});

test('saving details keeps the place open with explicit success, without changing an untouched provider pin', async () => {
  let saved, closes = 0; const h = host(editor, 'DreamEditor');
  let tree = h.render(editorProps({ initialMode: 'edit', item: { ...item, googleMapsUrl: 'https://www.google.com/maps/search/?api=1&query=38.7,-9.1', locationProvider: 'google_places' },
    onClose: () => closes++, onSave: async (_id, patch) => saved = patch }));
  action(tree, 'Notes').props.onChange('Better notes'); tree = h.render(); action(tree, 'Save changes').props.onPress(); await flush(); tree = h.render();
  assert.equal(saved.summary, 'Better notes'); assert(!Object.hasOwn(saved, 'googleMapsUrl'));
  assert.equal(closes, 0); assert(text(tree).includes('Changes saved.')); assert(action(tree, 'Edit details')); h.dispose();
});

test('a resolved Google result populates the map and address without a location approval action', () => {
  const h = host(editor, 'DreamEditor', { live: { loading: true } });
  const props = editorProps({ item: { ...item, locationProvider: 'google_places', locationStatus: 'resolved', locationPlaceId: 'google-place-id' } });
  let tree = h.render(props); assert(text(tree).includes('Loading location details…')); assert(!text(tree).some(value => value.includes('Add a city')));
  assert(!action(tree, 'Confirm pin'));
  h.live({ details: { locationProvider: 'google_places', locationStatus: 'resolved', locationPlaceId: 'google-place-id',
    locationExpiresAt: '2099-01-01', locationAddress: 'Lisbon, Portugal',
    locationCandidates: [{ id: 'google-place-id', name: 'One café', address: 'Lisbon, Portugal', latitude: 38.71, longitude: -9.14,
      googleMapsUrl: 'https://maps.google.com/?q=38.71,-9.14' }], locationAttributions: [] } });
  tree = h.render(); assert(!action(tree, 'Confirm pin')); assert(!action(tree, 'Save place details'));
  const point = byType(tree, 'DreamPlacesMap').props.points[0];
  assert.equal(point.id, item.id); assert.equal(point.lat, 38.71); assert.equal(point.lon, -9.14);
  assert(text(tree).includes('Lisbon, Portugal')); assert(action(tree, 'Maps')); assert(action(tree, 'Edit details')); h.dispose();
});

test('unresolved or mismatched Google candidates are not plotted or presented as an approval queue', () => {
  const h = host(editor, 'DreamEditor', { live: { details: { locationProvider: 'google_places', locationStatus: 'needs_review',
    locationCandidates: [{ id: 'unselected', name: 'Wrong café', latitude: 38.71, longitude: -9.14 }], locationAttributions: [] } } });
  let tree = h.render(editorProps({ item: { ...item, locationProvider: 'google_places', locationStatus: 'needs_review' } }));
  assert(!byType(tree, 'DreamPlacesMap')); assert(!action(tree, 'Confirm pin')); assert(!text(tree).includes('Wrong café'));
  h.live({ details: { locationProvider: 'google_places', locationStatus: 'resolved', locationPlaceId: 'selected', locationExpiresAt: '2099-01-01',
    locationCandidates: [{ id: 'unselected', latitude: 38.71, longitude: -9.14 }], locationAttributions: [] } });
  tree = h.render(); assert(!byType(tree, 'DreamPlacesMap')); h.dispose();
});

test('location lookup alone does not put a saved place into the Dreams review queue', () => {
  const h = host(screen, 'DreamsScreen', { items: [{ ...item, locationStatus: 'needs_review' }] });
  const tree = h.render({ active: 'dreams', onChange: noop });
  assert(!text(tree).some(value => /^Review \d/.test(value))); h.dispose();
});

test('fresh Google identity and coordinates replace the list pin together without reviving old coordinates', () => {
  const h = host(editor, 'DreamEditor', { live: { details: { locationProvider: 'google_places', locationStatus: 'resolved',
    locationPlaceId: 'new-match', locationExpiresAt: '2099-01-01', locationAddress: 'New address',
    locationCandidates: [{ id: 'new-match', latitude: 41.15, longitude: -8.61 }], locationAttributions: [] } } });
  let tree = h.render(editorProps({ item: { ...item, locationProvider: 'google_places', locationStatus: 'resolved',
    locationPlaceId: 'old-match', locationExpiresAt: '2099-01-01', latitude: 38.7, longitude: -9.1 } }));
  assert.equal(byType(tree, 'DreamPlacesMap').props.points[0].lat, 41.15);
  h.live({ details: { locationProvider: 'google_places', locationStatus: 'not_found', locationCandidates: [], locationAttributions: [] } });
  tree=h.render(); assert(!byType(tree, 'DreamPlacesMap')); h.dispose();
});

test('country Search focuses above the map; first resolution keeps map height and pin Details opens directly', () => {
  const located = { ...item, latitude: 38.71, longitude: -9.14, coordinatePrecision: 'place' };
  let selected; const h = host(screen, 'CountryPlaces'); const props = countryProps({ onSelect: (...value) => selected = value });
  let tree = h.render(props); assert.equal(byType(tree, 'DreamPlacesMap').props.height, 248);
  action(tree, 'Search saved places').props.onPress(); tree = h.render();
  const input = byType(tree, 'TextInput'); assert.equal(input.props.autoFocus, true);
  const ordered = nodes(tree); assert(ordered.indexOf(input) < ordered.indexOf(byType(tree, 'FlatList')));
  tree = h.render({ ...props, items: [located] }); const map = byType(tree, 'DreamPlacesMap'); assert.equal(map.props.height, 248);
  map.props.onSelect('1'); tree = h.render(); action(tree, 'Details for Saved café').props.onPress(); assert.deepEqual(selected, ['1','view']);
  const row = byType(tree, 'FlatList').props.renderItem({ item: located, index: 0 });
  const place = nodes(row).find(node => typeof node.type === 'function' && node.props?.onEdit); place.props.onEdit(); assert.deepEqual(selected, ['1','edit']); h.dispose();
});

test('city/category filters preserve every matching save, expose selection, and clear a hidden pin preview', () => {
  const items = Array.from({ length: 28 }, (_, i) => ({ ...item, id: String(i+1), city: i<14?'Lisbon':'Porto', category: i<7?'cafe':i<23?'restaurant':'hotel', latitude: 38.7, longitude: -9.1 }));
  const h = host(screen, 'CountryPlaces'); let tree = h.render(countryProps({ items }));
  byType(tree,'DreamPlacesMap').props.onSelect('1'); tree=h.render(); assert(action(tree,'Details for Saved café'));
  action(tree,'City: Porto').props.onPress(); tree=h.render(); tree=h.render(); assert.equal(byType(tree,'FlatList').props.data.length,14);
  assert.equal(action(tree,'City: Porto').props.accessibilityState.selected,true); assert(!action(tree,'Details for Saved café'));
  action(tree,'Hotels, 5 places').props.onPress(); tree=h.render(); assert.equal(byType(tree,'FlatList').props.data.length,5); h.dispose();
});

test('country Back reverses once and hiding a country during a transition prevents a delayed navigation', () => {
  let backs=0; const h=host(screen,'CountryPlaces'); const props=countryProps({motion:true,onBack:()=>backs++});
  let tree=h.render(props); h.complete(); action(tree,'Back to Dreams').props.onPress(); action(tree,'Back to Dreams').props.onPress();
  assert.equal(backs,0); h.complete(); assert.equal(backs,1); h.dispose();
  const hidden=host(screen,'CountryPlaces'); tree=hidden.render(props); hidden.complete(); action(tree,'Back to Dreams').props.onPress();
  hidden.render({...props,active:false}); hidden.complete(); assert.equal(backs,1); hidden.dispose();
});

test('retained Dreams keeps selected editor mounted but hidden across tab changes', () => {
  const h=host(screen,'DreamsScreen'); const props={active:'dreams',onChange:noop}; let tree=h.render(props);
  byType(tree,'FlatList').props.renderItem({item:{key:'portugal',title:'Portugal',items:[item],cities:['Lisbon']}}).props.onPress(); tree=h.render();
  const country=nodes(tree).find(node=>typeof node.type==='function'&&node.props?.onLocateMissing); country.props.onSelect('1','edit'); tree=h.render();
  assert.equal(byType(tree,'DreamEditor').props.initialMode,'edit'); tree=h.render({...props,visible:false});
  assert.equal(byType(tree,'DreamEditor').props.visible,false); h.account([]); tree=h.render({...props,visible:true}); assert(!byType(tree,'DreamEditor')); h.dispose();
});

test('capture draft also survives a hidden tab and requires deliberate discard',()=>{
  let closes=0; const h=host(screen,'CapturePlace');const props={visible:true,onClose:()=>closes++,onSave:()=>true};let tree=h.render(props);
  action(tree,'Instagram link').props.onChangeText('https://www.instagram.com/reel/draft');tree=h.render({...props,visible:false});
  assert.equal(byType(tree,'Modal').props.visible,false);tree=h.render(props);byType(tree,'Modal').props.onRequestClose();tree=h.render();
  assert.equal(closes,0);action(tree,'Keep editing').props.onPress();tree=h.render();assert(action(tree,'Instagram link').props.value.includes('/draft'));
  action(tree,'Close').props.onPress();tree=h.render();action(tree,'Discard').props.onPress();assert.equal(closes,1);h.dispose();
});
