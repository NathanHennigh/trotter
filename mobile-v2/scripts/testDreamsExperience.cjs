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
    Linking: { openURL: async () => {} }, useWindowDimensions: () => ({ width: 320, height: 850, fontScale: 2 }),
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
    '../components/world-window/profile/ProfileAvatar': { ProfileAvatar: 'ProfileAvatar' },
    '../components/world-window/planner/DreamTripPicker': { DreamTripPicker: 'DreamTripPicker' },
    './DreamPlacesMap': { DreamPlacesMap: 'DreamPlacesMap' },
    '../components/world-window/dreams/DreamPlacesMap': { DreamPlacesMap: 'DreamPlacesMap' },
    './DreamPhoto': { DreamPhoto: 'DreamPhoto' },
    '../components/world-window/dreams/DreamPhoto': { DreamPhoto: 'DreamPhoto', PlaceSymbol: 'PlaceSymbol' },
    '../components/world-window/dreams/CountryPostcard': { CountryPostcard: 'CountryPostcard' },
    '../components/world-window/dreams/DreamEditor': { DreamEditor: 'DreamEditor' },
    './useLiveDreamLocation': { useLiveDreamLocation: (_item, enabled) => { options.liveEnabled = enabled; return live; } },
    '../services/dreams': { useDreams: () => ({ items: account, processingItems: [], status: 'ready', refresh: options.refresh || noop, locateMissing: noop }) },
    '../services/nativeDreamShare': options.nativeShare || { listNativeDreamShareReceipts: async () => [], acknowledgeNativeDreamShare: async () => {}, retryNativeDreamShare: async () => {} },
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
    const code = fs.readFileSync(filename, 'utf8') + (filename.endsWith('DreamsScreen.tsx') ? '\nexport { CountryPlaces, CapturePlace, PlaceRow };' : '');
    const compiled = ts.transpileModule(code, { compilerOptions: { jsx: ts.JsxEmit.React, module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, esModuleInterop: true } }).outputText;
    const mod = { exports: {} };
    new Function('module','exports','require','setTimeout','clearTimeout', compiled)(mod, mod.exports, request => {
      if (request in allMocks) return allMocks[request];
      const candidate = path.resolve(path.dirname(filename), request);
      if (candidate.endsWith('.json') && fs.existsSync(candidate)) return JSON.parse(fs.readFileSync(candidate, 'utf8'));
      for (const extension of ['.ts','.tsx']) if (fs.existsSync(candidate + extension)) return load(candidate + extension);
      throw new Error('Unmocked dependency ' + request);
    }, options.timers?.setTimeout || setTimeout, options.timers?.clearTimeout || clearTimeout);
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
const listWrapper = tree => nodes(tree).find(node => node.type === 'View' && node.props.children.flat(Infinity).some(child => child?.type === 'FlatList'));
const editor = 'components/world-window/dreams/DreamEditor.tsx', screen = 'screens/DreamsScreen.tsx';
const editorProps = overrides => ({ item, points: [], onSave: async () => {}, onDelete: async () => {}, onClose: noop, onRetry: noop, ...overrides });
const countryProps = overrides => ({ title: 'Portugal', items: [item], review: false, topInset: 0, bottomInset: 20,
  loading: false, onBack: noop, onRefresh: noop, onSelect: noop, onLocateMissing: async () => {}, motion: false,
  sourceCounts: new Map(), onShowSource: noop, ...overrides });

test('attention and organizing queues keep every save reachable without mixing automatic work into the action inbox', () => {
  const saves = Array.from({ length: 28 }, (_, index) => ({ ...item, id: index < 3 ? `pending-${index}` : String(index + 1),
    country: undefined, city: undefined, placeName: undefined, category: 'unknown', tags: [], summary: '',
    sourceUrl: `https://www.instagram.com/reel/pending-${index}`, status: ['created', 'processing', 'failed'][index % 3],
    uploadStatus: index < 3 ? 'queued' : undefined, needsReview: index % 3 === 2 }));
  const home = host(screen, 'DreamsScreen', { items: saves });
  let tree = home.render({ active: 'dreams', onChange: noop });
  const boards = byType(tree, 'FlatList'); assert.equal(boards.props.data.length, 0);
  const expected = saves.filter(saved => saved.status === 'failed' && !saved.uploadStatus);
  const inbox = action(tree, `Needs attention, ${expected.length} saves`);
  assert(action(tree, `Organizing ${saves.length - expected.length} saves`));
  assert(inbox, 'Actionable saves remain reachable above the country postcards');
  inbox.props.onPress(); tree = home.render();
  const collection = nodes(tree).find(node => typeof node.type === 'function' && node.type.name === 'CountryPlaces');
  assert(collection); const country = host(screen, 'CountryPlaces'); const opened = country.render(collection.props);
  assert(!byType(opened, 'DreamPlacesMap'), 'A collection without country or pins must not mount an irrelevant native world map');
  const list = byType(opened, 'FlatList'); assert.equal(list.props.data.length, expected.length);
  for (let index = 0; index < expected.length; index++) {
    const row = list.props.renderItem({ item: list.props.data[index], index });
    const content = nodes(row).find(node => typeof node.type === 'function' && node.type.name === 'PlaceRow');
    const rowHost = host(screen, 'PlaceRow'); assert(text(rowHost.render(content.props)).includes('Saved reel')); rowHost.dispose();
  }
  action(opened, 'Back to Dreams').props.onPress(); tree = home.render();
  assert.equal(byType(tree, 'FlatList').props.data.length, 0);
  assert(action(tree, `Needs attention, ${expected.length} saves`));
  action(tree, `Organizing ${saves.length - expected.length} saves`).props.onPress(); tree = home.render();
  const organizing = nodes(tree).find(node => typeof node.type === 'function' && node.type.name === 'CountryPlaces');
  assert.equal(organizing.props.items.length + expected.length, saves.length);
  country.dispose(); home.dispose();
});

test('compact attention row announces singular and plural counts and disappears when resolved',()=>{
 const failed={...item,sortingState:'failed'};const h=host(screen,'DreamsScreen',{items:[failed]});
 let tree=h.render({active:'dreams',onChange:noop});
 assert(action(tree,'Needs attention, 1 save'));assert(text(tree).includes('· 1'));
 h.account([failed,{...failed,id:'2'}]);tree=h.render();
 assert(action(tree,'Needs attention, 2 saves'));assert(text(tree).includes('· 2'));
 assert(!action(tree,'Needs attention, 1 save'));
 h.account([item]);tree=h.render();assert(!action(tree,'Needs attention, 1 save'));assert(!action(tree,'Needs attention, 2 saves'));h.dispose();
});

test('attention rows distinguish live sorting, missing details and unreadable reels without an endless progress claim', () => {
  const base = { ...item, country: undefined, city: undefined, placeName: undefined, category: 'unknown', status: 'needs_review', needsReview: true };
  const cases = [
    { ...base, id: 'queued', sortingState: 'queued', status: 'processing' },
    { ...base, id: 'running', sortingState: 'running', status: 'processing' },
    { ...base, id: 'emoji', sortingState: 'needs_details', caption: '🏜️' },
    { ...base, id: 'room', sortingState: 'needs_details', caption: 'Deluxe room with view #fyp' },
    { ...base, id: 'named', sortingState: 'needs_details', placeName: 'Seaweed Studio' },
    { ...base, id: 'failed', sortingState: 'unavailable', processingMessage: 'Instagram could not provide a readable caption.' },
  ];
  const collection = host(screen, 'CountryPlaces'); let tree = collection.render(countryProps({ title: 'Needs attention', inbox: true, items: cases }));
  assert(text(tree).includes('Needs attention'));
  assert(!text(tree).some(value => /2 sorting.*3 need/.test(value)));
  assert(!byType(tree, 'DreamPlacesMap'));
  const expected = ['Sorting reel…', 'Sorting reel…', 'Needs details', 'Needs details', 'Location missing', 'Couldn’t read reel'];
  cases.forEach((saved, index) => {
    const h = host(screen, 'PlaceRow'); const row = h.render({ item: saved, onPress: noop, onShowMap: noop });
    assert(text(row).includes(expected[index]));
    if (index >= 2) assert(!text(row).some(value => /Sorting|Reading post|Finding.*background/.test(value)));
    if (saved.sortingState === 'unavailable') assert(nodes(row).some(node => node.props?.accessibilityHint === saved.processingMessage));
    h.dispose();
  });
  const located = { ...cases[4], latitude: 40, longitude: 25, status: 'parsed', needsReview: false };
  tree = collection.render(countryProps({ title: 'Needs attention', inbox: true, items: [located] }));
  assert(!byType(tree, 'DreamPlacesMap'), 'The inbox stays focused on recovery, even when an item has coordinates');
  collection.dispose();
});

test('completed and failed server job status overrides a stale processing item in place details', () => {
  const h = host(editor, 'DreamEditor');
  let tree = h.render(editorProps({ item: { ...item, status: 'processing', sortingState: 'needs_details', needsReview: true, placeName: undefined, country: undefined } }));
  assert(text(tree).includes('Your reel is saved. Its caption didn’t identify a place.'));
  assert(!text(tree).some(value => value.includes('Sorting this post')));
  tree = h.render(editorProps({ item: { ...item, status: 'needs_review', needsReview: true, sortingState: 'unavailable', processingMessage: 'Instagram could not provide a readable caption.' } }));
  assert(text(tree).includes('Instagram could not provide a readable caption.'));
  action(tree, 'More place options').props.onPress(); tree = h.render(); assert(action(tree, 'Retry reading post'));
  h.dispose();
});

test('sorted destination suppresses obsolete review warnings while a failed parse remains retryable', () => {
  const h = host(screen, 'PlaceRow');
  let tree = h.render({ item: { ...item, placeName: 'Echoes Luxury Suites', country: 'Greece', city: 'Santorini', needsReview: true, sortingState: 'sorted' }, expanded: true, onPress: noop, onEdit: noop, onShowMap: noop, sourceCount: 1 });
  assert(!text(tree).some(value => /Location missing|Needs details|Sorting reel/.test(value)));
  tree = h.render({ item: { ...item, country: undefined, sortingState: 'failed', processingMessage: 'Saved. We could not finish sorting this post. Try again.' }, expanded: true, onPress: noop, onEdit: noop, onShowMap: noop, sourceCount: 1 });
  assert(text(tree).includes('Couldn’t sort reel'));
  assert(!text(tree).includes('Couldn’t read reel'));
  h.dispose();
});

test('direct Edit starts in the form; Close guards changed fields, Keep editing retains them, Discard alone closes', () => {
  let closes = 0;
  const h = host(editor, 'DreamEditor'); let tree = h.render(editorProps({ initialMode: 'edit', onClose: () => closes++ }));
  assert(action(tree, 'Place name')); assert(!action(tree, 'Edit details'));
  action(tree, 'Your note').props.onChange('Unsaved personal notes'); tree = h.render();
  action(tree, 'Close place').props.onPress(); tree = h.render();
  assert.equal(closes, 0); assert(action(tree, 'Keep editing')); assert(!action(tree, 'Save changes'));
  action(tree, 'Keep editing').props.onPress(); tree = h.render();
  assert.equal(action(tree, 'Your note').props.value, 'Unsaved personal notes');
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
  action(tree, 'Your note').props.onChange('Temporary'); tree = h.render(); action(tree, 'Your note').props.onChange(item.personalNote || ''); tree = h.render();
  action(tree, 'Close place').props.onPress(); assert.equal(closes, 1); h.dispose();
});

test('saving details keeps the place open with explicit success, without changing an untouched provider pin', async () => {
  let saved, closes = 0; const h = host(editor, 'DreamEditor');
  let tree = h.render(editorProps({ initialMode: 'edit', item: { ...item, googleMapsUrl: 'https://www.google.com/maps/search/?api=1&query=38.7,-9.1', locationProvider: 'google_places' },
    onClose: () => closes++, onSave: async (_id, patch) => saved = patch }));
  action(tree, 'Your note').props.onChange('Better notes'); tree = h.render(); action(tree, 'Save changes').props.onPress(); await flush(); tree = h.render();
  assert.deepEqual(saved, {personalNote:'Better notes'}); assert(!Object.hasOwn(saved, 'googleMapsUrl'));
  assert.equal(closes, 0); assert(text(tree).includes('Changes saved.'));
  action(tree, 'More place options').props.onPress(); tree = h.render(); assert(action(tree, 'Edit details')); h.dispose();
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
  assert(text(tree).includes('Lisbon, Portugal')); assert(action(tree, 'Open in Maps'));
  action(tree, 'More place options').props.onPress(); tree = h.render(); assert(action(tree, 'Edit details')); h.dispose();
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

test('area detail keeps the broad marker, labels its precision and does not display a representative centre as a venue address', () => {
  const h = host(editor, 'DreamEditor', { live: { details: { coordinatePrecision: 'area', locationProvider: 'google_places',
    locationStatus: 'resolved', locationPlaceId: 'area-id', locationExpiresAt: '2099-01-01', locationAddress: 'Representative map centre',
    locationCandidates: [{ id: 'area-id', latitude: 14.7, longitude: -91.2 }], locationAttributions: [] } } });
  const tree = h.render(editorProps({ item: { ...item, placeName: 'Lake Atitlán', category: 'unknown',
    locationProvider: 'google_places', coordinatePrecision: 'area', locationPlaceId: 'area-id', locationExpiresAt: '2099-01-01' } }));
  assert.equal(byType(tree, 'DreamPlacesMap').props.points[0].area, true);
  assert(text(tree).includes('Area · Lisbon · Portugal')); assert(text(tree).includes('Area on map'));
  assert(text(tree).includes('The marker shows the general area.'));
  assert(!text(tree).includes('Representative map centre'));
  h.dispose();
});

test('Map hides the native list and its RefreshControl together while preserving its scroll reference', () => {
  const located = { ...item, latitude: 38.71, longitude: -9.14, coordinatePrecision: 'place' };
  let selected; const h = host(screen, 'CountryPlaces');
  let tree = h.render(countryProps({items:[located],onSelect:(...value)=>selected=value}));
  assert(!byType(tree,'DreamPlacesMap')); assert(!action(tree,'Search country places'), 'One-save countries stay simple');
  const listRef=byType(tree,'FlatList').props.ref;
  action(tree,'Show map').props.onPress(); tree=h.render();
  const map=byType(tree,'DreamPlacesMap'); assert.equal(map.props.points[0].id,'1');
  assert.equal(map.props.selectedId,undefined,'The fallback preview card must not recenter the overview on its first place');
  map.props.onSelect('1');tree=h.render();assert.equal(byType(tree,'DreamPlacesMap').props.selectedId,'1','An explicitly selected pin can focus');
  byType(tree,'DreamPlacesMap').props.onSelect(undefined);tree=h.render();assert.equal(byType(tree,'DreamPlacesMap').props.selectedId,undefined,'Fit and blank-map taps clear camera focus while retaining the preview');
  assert.equal(byType(tree,'FlatList').props.ref,listRef);
  const hidden=listWrapper(tree);
  assert.equal(hidden.props.style.display,'none');
  assert.equal(hidden.props.importantForAccessibility,'no-hide-descendants');
  assert.equal(hidden.props.accessibilityElementsHidden,true);
  assert(nodes(hidden).includes(byType(tree,'FlatList').props.refreshControl), 'The outer wrapper must hide Android’s refresh container as well as list content');
  assert.equal(byType(tree,'FlatList').props.style.display,undefined);
  action(tree,'Details for Saved café').props.onPress(); assert.equal(selected[0],'1');
  action(tree,'Show saved places').props.onPress(); tree=h.render();
  assert.equal(listWrapper(tree).props.style.display,'flex'); assert(!byType(tree,'DreamPlacesMap')); h.dispose();
});

test('city and broad type filters apply to both views and remain selected after opening details', () => {
  const items=Array.from({length:28},(_,i)=>({...item,id:String(i+1),city:i<14?'Lisbon':'Porto',category:i<7?'cafe':i<23?'restaurant':'hotel',latitude:38.7,longitude:-9.1}));
  const h=host(screen,'CountryPlaces'); let tree=h.render(countryProps({items}));
  action(tree,'Filter places').props.onPress(); tree=h.render();
  assert.equal(byType(tree,'Modal').props.visible,true);
  action(tree,'Porto').props.onPress(); tree=h.render();
  assert.equal(byType(tree,'FlatList').props.data.length,14); assert.equal(action(tree,'Porto').props.accessibilityState.checked,true);
  action(tree,'Stay').props.onPress(); tree=h.render(); assert.equal(byType(tree,'FlatList').props.data.length,5);
  action(tree,'Show 5 places').props.onPress(); tree=h.render(); assert.equal(byType(tree,'Modal').props.visible,false);
  action(tree,'Show map').props.onPress(); tree=h.render(); assert.equal(byType(tree,'DreamPlacesMap').props.points.length,5);
  action(tree,'Details for Saved café').props.onPress(); tree=h.render();
  action(tree,'Show saved places').props.onPress(); tree=h.render();
  assert.equal(byType(tree,'FlatList').props.data.length,5); h.dispose();
});

test('Back closes the filter panel, then the map, then the country; a hidden country unregisters Back', () => {
  let backs=0,handler; const h=host(screen,'CountryPlaces');
  const props=countryProps({items:[item,{...item,id:'2'},{...item,id:'3'}],onBack:()=>backs++,onBackRequestChange:value=>handler=value});
  let tree=h.render(props); action(tree,'Filter places').props.onPress(); tree=h.render(); handler(); tree=h.render();
  assert.equal(byType(tree,'Modal').props.visible,false); assert.equal(backs,0);
  action(tree,'Show map').props.onPress(); tree=h.render(); handler(); tree=h.render();
  assert.equal(action(tree,'Show saved places').props.accessibilityState.selected,true); assert.equal(backs,0);
  handler(); assert.equal(backs,1); h.render({...props,active:false}); assert.equal(handler,null); h.dispose();
});

test('visible Back to Dreams exits the country from Map while hardware Back returns to Places',()=>{
 let backs=0,handler;const h=host(screen,'CountryPlaces');
 let tree=h.render(countryProps({items:[{...item,latitude:38.7,longitude:-9.1}],onBack:()=>backs++,onBackRequestChange:value=>handler=value}));
 action(tree,'Show map').props.onPress();tree=h.render();handler();tree=h.render();
 assert.equal(backs,0);assert.equal(action(tree,'Show saved places').props.accessibilityState.selected,true);
 action(tree,'Show map').props.onPress();tree=h.render();action(tree,'Back to Dreams').props.onPress();
 assert.equal(backs,1,'The labeled navigation action must reach the destination it promises');h.dispose();
});

test('country-less inspiration remains reachable without an attention warning or an organizing promise',()=>{
 const inspiration={...item,id:'2',country:undefined,city:undefined,placeName:undefined,category:'unknown',
  locationState:'source_details',locationReason:'creator_link_required',sortingState:'needs_details',caption:'Comment LINK for the full guide'};
 const h=host(screen,'DreamsScreen',{items:[inspiration]});let tree=h.render({active:'dreams',onChange:noop});
 assert(!nodes(tree).some(node=>/^Needs attention|^Organizing /.test(node.props?.accessibilityLabel||'')));
 action(tree,'Saved inspiration, 1 posts').props.onPress();tree=h.render();
 const collection=nodes(tree).find(node=>typeof node.type==='function'&&node.type.name==='CountryPlaces');
 assert.equal(collection.props.title,'Saved inspiration');assert.deepEqual(collection.props.items.map(saved=>saved.id),['2']);
 const row=host(screen,'PlaceRow');const rendered=row.render({item:inspiration,inbox:true,onPress:noop,onEdit:noop,onRetry:noop});
 assert(!action(rendered,'Try again'));assert(!text(rendered).includes('Add location'));assert(text(rendered).includes('Saved inspiration'));
 collection.props.onBack();tree=h.render();assert(action(tree,'Saved inspiration, 1 posts'));row.dispose();h.dispose();
});

test('islands appear in destination filters and select the same saves shown under their row labels',()=>{
 const island={...item,id:'2',country:'Greece',city:undefined,regionOrNeighborhood:'Milos'};
 let selection;const h=host(screen,'CountryPlaces');let tree=h.render(countryProps({title:'Greece',onSelect:(...value)=>selection=value,items:[island,{...item,id:'3',country:'Greece',city:'Athens'},{...item,id:'4',country:'Greece',city:'Athens'}]}));
 action(tree,'Filter places').props.onPress();tree=h.render();
 assert(action(tree,'All destinations'));action(tree,'Milos').props.onPress();tree=h.render();
 assert.deepEqual(byType(tree,'FlatList').props.data.map(saved=>saved.id),['2']);assert(action(tree,'Milos').props.accessibilityState.checked);
 action(tree,'Show 1 place').props.onPress();tree=h.render();
 const list=byType(tree,'FlatList'),rendered=list.props.renderItem({item:list.props.data[0],index:0});
 const row=nodes(rendered).find(node=>typeof node.type==='function'&&node.type.name==='PlaceRow');assert.equal(row.props.item.regionOrNeighborhood,'Milos');
 row.props.onEdit();assert.deepEqual(selection,['2','location'],'Add location must open the focused location tools');h.dispose();
});

test('places from one post share a source link while continuation rows replace repeated covers with category symbols',()=>{
 const samePost=[{...item,id:'1',placeName:'First café',sourceUrl:'https://www.instagram.com/reel/example?tracking=one'},
  {...item,id:'2',placeName:'Second café',sourceUrl:'https://www.instagram.com/reel/example/'}];
 const opened=[];const h=host(screen,'CountryPlaces');const tree=h.render(countryProps({items:samePost,onShowSource:url=>opened.push(url)}));
 const list=byType(tree,'FlatList');const first=list.props.renderItem({item:list.props.data[0],index:0});
 const next=list.props.renderItem({item:list.props.data[1],index:1});
 action(first,'View places from this post').props.onPress();assert.deepEqual(opened,[list.props.data[0].sourceUrl]);
 assert(text(first).includes('Places from this post'));assert(!action(next,'View places from this post'));
 const firstRow=nodes(first).find(node=>typeof node.type==='function'&&node.type.name==='PlaceRow');
 const nextRow=nodes(next).find(node=>typeof node.type==='function'&&node.type.name==='PlaceRow');
 assert.equal(firstRow.props.sharedPhoto,false);assert.equal(nextRow.props.sharedPhoto,true);
 const row=host(screen,'PlaceRow');assert(byType(row.render(firstRow.props),'DreamPhoto'));
 const continuation=row.render(nextRow.props);assert(!byType(continuation,'DreamPhoto'));assert.equal(byType(continuation,'PlaceSymbol').props.category,'cafe');
 assert(action(continuation,'Details for First café'));row.dispose();h.dispose();
});

test('same-title inspiration from separate posts stays separate and opens the ID described by its accessible excerpt',()=>{
 const first={...item,id:'80',placeName:'Taghazout',city:undefined,country:'Morocco',locationState:'source_details',
  locationReason:'creator_link_required',sourceUrl:'https://instagram.com/reel/first-stay',summary:'A hideaway above the ocean with sunset views.'};
 const second={...first,id:'85',locationReason:'identity_not_shared',sourceUrl:'https://instagram.com/reel/second-stay',summary:'Boutique stays and Airbnb rentals with ocean views.'};
 const unique={...item,id:'78',placeName:'Serenya',country:'Morocco',city:'Marrakech',sourceUrl:'https://instagram.com/reel/named-riad',summary:'Seven suites in a restored riad.'};
 const saves=Object.freeze([Object.freeze(first),Object.freeze(second),Object.freeze(unique)]),selections=[];
 const country=host(screen,'CountryPlaces');const tree=country.render(countryProps({title:'Morocco',items:saves,onSelect:(...value)=>selections.push(value)}));
 const list=byType(tree,'FlatList');assert.equal(list.props.data.length,3);
 assert.deepEqual(new Set(list.props.data.map(saved=>saved.id)),new Set(['78','80','85']),'No source is merged or removed');
 list.props.data.forEach((saved,index)=>{
  const wrapper=list.props.renderItem({item:saved,index});
  const row=nodes(wrapper).find(node=>typeof node.type==='function'&&node.type.name==='PlaceRow');
  const rendered=host(screen,'PlaceRow');const rowTree=rendered.render(row.props);
  if(saved.id==='78'){
   assert.equal(row.props.excerpt,undefined);assert(!text(rowTree).includes(saved.summary));
   action(rowTree,'Details for Serenya').props.onPress();
  }else{
   assert.equal(row.props.excerpt,saved.summary);assert(text(rowTree).includes(saved.summary));
   assert.equal(row.props.sharedPhoto,false,'Separate posts retain their own cover');
   action(rowTree,`Details for Taghazout, ${saved.summary}`).props.onPress();
  }
  assert.deepEqual(selections.at(-1),[saved.id,'view']);rendered.dispose();
 });
 assert.equal(new Set(selections.map(([id])=>id)).size,3);country.dispose();
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

test('capture waits for durable receipt, prevents duplicate taps, and preserves the draft on write failure', async () => {
  let finish, calls=0, closes=0;
  const h=host(screen,'CapturePlace'); const props={visible:true,onClose:()=>closes++,onSave:()=>{
    calls++; return new Promise((resolve,reject)=>finish={resolve,reject});
  }};
  let tree=h.render(props); action(tree,'Instagram link').props.onChangeText('https://instagram.com/reel/kept');
  tree=h.render(); const submit=action(tree,'Save to Dreams').props.onPress;
  const pending=submit(); void submit(); tree=h.render();
  assert.equal(calls,1); assert.equal(closes,0); assert(action(tree,'Keeping post…').props.disabled);
  finish.reject(new Error('Device storage is unavailable.')); await pending; tree=h.render();
  assert.equal(closes,0); assert.equal(action(tree,'Instagram link').props.value,'https://instagram.com/reel/kept');
  assert(text(tree).includes('Device storage is unavailable.'));
  const retry=action(tree,'Save to Dreams').props.onPress(); finish.resolve(true); await retry;
  assert.equal(closes,1); h.dispose();
});

test('opening a native saved receipt recovers when its first Dreams refresh fails quietly', async () => {
  let refreshes = 0, acknowledged = [], timerId = 0;
  const timers = new Map();
  const receipt = { id: 'native-receipt', status: 'saved', itemId: 1, sourceUrl: item.sourceUrl };
  const h = host(screen, 'DreamsScreen', {
    items: [],
    // Quiet refresh catches transport errors, so failure resolves without adding items.
    refresh: async () => { refreshes++; if (refreshes === 2) h.account([item]); },
    nativeShare: {
      listNativeDreamShareReceipts: async () => [receipt],
      acknowledgeNativeDreamShare: async id => acknowledged.push(id),
    },
    timers: { setTimeout(fn) { timers.set(++timerId, fn); return timerId; }, clearTimeout(id) { timers.delete(id); } },
  });
  const tick = async () => { const pending = [...timers.values()]; timers.clear(); pending.forEach(fn => fn()); await flush(); h.render(); };
  try {
    h.render({ active: 'dreams', onChange: noop, openSource: { url: item.sourceUrl, requestId: 1, receiptId: receipt.id } });
    h.render(); await flush(); h.render();
    assert.equal(refreshes, 1); assert.deepEqual(acknowledged, []);
    await tick();
    assert.equal(refreshes, 2, 'An accepted share must retry loading its item after a transient fetch failure');
    await tick();
    assert.deepEqual(acknowledged, ['native-receipt']);
    assert.equal(timers.size, 0, 'Stop polling once the actual saved item is visible');
    assert.equal(refreshes, 2, 'Do not fetch again after the item arrives');
  } finally { h.dispose(); }
});

test('processing copy distinguishes an unsent local post from a save being sorted on the server', () => {
  const h=host(editor,'DreamEditor');
  let tree=h.render(editorProps({item:{...item,id:'dream-item-local',status:'created',uploadStatus:'queued',needsReview:false}}));
  assert(text(tree).some(value=>value.includes('Reel saved on this device.')));
  tree=h.render(editorProps({item:{...item,status:'processing',needsReview:false}}));
  assert(text(tree).some(value=>value.includes('Sorting this post in the background')));
  tree=h.render(editorProps({item:{...item,status:'needs_review',needsReview:true,placeName:undefined}}));
  action(tree,'More place options').props.onPress(); tree=h.render();
  assert(action(tree,'Retry reading post')); assert(!text(tree).some(value=>value.includes('Reading this post')));
  h.dispose();
});

test('editing only a note cannot overwrite location fields resolved while the editor was open', async () => {
  let patch; const h=host(editor,'DreamEditor'); const p=editorProps({initialMode:'edit',item:{...item,city:undefined,country:undefined},onSave:async(_id,value)=>patch=value});
  let tree=h.render(p); action(tree,'Your note').props.onChange('Go early');
  tree=h.render({...p,item:{...item,city:'Kyoto',country:'Japan'}});
  action(tree,'Save changes').props.onPress(); await flush();
  assert.deepEqual(patch,{personalNote:'Go early'}); h.dispose();
});

test('inbox retries are deliberate, duplicate-safe, and retain recovery when a retry fails',async()=>{
 let reject,calls=0;const h=host(screen,'PlaceRow');const props={item:{...item,sortingState:'unavailable',needsReview:true},inbox:true,onPress:noop,onEdit:noop,onRetry:()=>{calls++;return new Promise((_,r)=>reject=r)}};
 let tree=h.render(props);const retry=action(tree,'Try again').props.onPress;
 const pending=retry();void retry();tree=h.render();assert.equal(calls,1);assert.equal(action(tree,'Retrying…').props.disabled,true);
 reject(new Error('Unavailable'));await pending;tree=h.render();assert(action(tree,'Try again'));assert(text(tree).includes('Couldn’t retry yet. Your link is still saved.'));h.dispose();
});
