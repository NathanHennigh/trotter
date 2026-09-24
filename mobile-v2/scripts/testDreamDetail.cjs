// Exercise the shipped place detail handlers, including its overflow and draft guards.
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), ts = require('typescript');
const { test } = require('node:test');
const noop = () => {}, flush = async () => { for (let n = 0; n < 20; n++) await Promise.resolve(); };
const item = { id: '8', placeName: 'Saved café', country: 'Portugal', city: 'Lisbon', category: 'cafe',
  tags: ['Coffee'], summary: 'A café from the saved reel.', sourceUrl: 'https://www.instagram.com/reel/example/',
  status: 'needs_review', needsReview: true, sortingState: 'sorted', latitude: 38.7, longitude: -9.1,
  googleMapsUrl: 'https://www.google.com/maps/search/?api=1&query=38.7,-9.1' };
function host(overrides = {}) {
  let slots = [], cursor = 0, effects = [], props;
  const urls = [], same = (a, b) => a && b && a.length === b.length && a.every((v, i) => v === b[i]);
  const react = {
    createElement: (type, props, ...children) => ({ type, props: { ...props, children } }),
    useState(value) { const i = cursor++; if (!(i in slots)) slots[i] = typeof value === 'function' ? value() : value;
      return [slots[i], next => slots[i] = typeof next === 'function' ? next(slots[i]) : next]; },
    useRef(value) { return slots[cursor++] ??= { current: value }; },
    useMemo(fn, deps) { const i = cursor++; if (!slots[i] || !same(slots[i].deps, deps)) slots[i] = { value: fn(), deps }; return slots[i].value; },
    useEffect(fn, deps) { const i = cursor++; if (!slots[i] || !same(slots[i].deps, deps)) {
      slots[i]?.cleanup?.(); slots[i] = { deps }; effects.push(() => slots[i].cleanup = fn()); } },
  };
  const mocks = {
    react,
    'react-native': { ...Object.fromEntries('View Text Modal TextInput ScrollView KeyboardAvoidingView'.split(' ').map(t => [t, t])),
      Platform: { OS: 'android' }, StyleSheet: { create: x => x, absoluteFill: {}, absoluteFillObject: {} },
      Linking: { openURL: async url => { urls.push(url); } }, useWindowDimensions: () => ({ width: 390, height: 844, fontScale: 1 }) },
    'react-native-safe-area-context': { useSafeAreaInsets: () => ({ top: 24, bottom: 20 }) },
    '../motion': { useReducedMotion: () => true, PressFeedback: 'Pressable' },
    '../WorldWindowUI': { WWButton: 'WWButton', WWIcon: 'WWIcon' },
    '../../../theme/trotterTheme': { colors: {}, fonts: {} },
    '../displayTextFit': { fitDisplayFont: (_name, size) => size },
    '../../../utils/mobileLayout': { getMobileVisualWidth: width => width },
    '../../../utils/experiencePreferences': { selectionHaptic: async () => {} },
    './DreamPhoto': { DreamPhoto: 'DreamPhoto' }, './DreamPlacesMap': { DreamPlacesMap: 'DreamPlacesMap' },
    './useLiveDreamLocation': { useLiveDreamLocation: () => ({ retry: noop, ...overrides.live }) },
  };
  const cache = {};
  function load(filename) {
    if (cache[filename]) return cache[filename];
    const output = ts.transpileModule(fs.readFileSync(filename, 'utf8'), { compilerOptions: {
      jsx: ts.JsxEmit.React, module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, esModuleInterop: true,
    } }).outputText;
    const mod = { exports: {} };
    new Function('module', 'exports', 'require', output)(mod, mod.exports, request => {
      if (request in mocks) return mocks[request];
      const candidate = path.resolve(path.dirname(filename), request);
      if (candidate.endsWith('.json') && fs.existsSync(candidate)) return JSON.parse(fs.readFileSync(candidate, 'utf8'));
      for (const ext of ['.ts', '.tsx']) if (fs.existsSync(candidate + ext)) return load(candidate + ext);
      throw new Error('Unmocked dependency ' + request);
    });
    return cache[filename] = mod.exports;
  }
  const { DreamEditor } = load(path.join(__dirname, '../src/components/world-window/dreams/DreamEditor.tsx'));
  return {
    urls,
    render(next = props) { props = next; cursor = 0; const tree = DreamEditor(props); const pending = effects; effects = []; pending.forEach(fn => fn()); return tree; },
    dispose() { slots.forEach(slot => slot?.cleanup?.()); },
  };
}
function nodes(value, seen = new Set()) {
  if (!value || typeof value !== 'object' || seen.has(value)) return [];
  seen.add(value); return [value, ...Object.values(value).flatMap(child => nodes(child, seen))];
}
const action = (tree, label) => nodes(tree).find(node => node.props?.label === label || node.props?.accessibilityLabel === label);
const byType = (tree, type) => nodes(tree).find(node => node.type === type);
const text = tree => nodes(tree).filter(node => node.type === 'Text').map(node => node.props.children.flat(Infinity).join(''));
const props = changes => ({ item, points: [], onClose: noop, onSave: async () => {}, onDelete: async () => {}, onRetry: noop, ...changes });

test('browsing presents the reel and map actions without an approval step or editing clutter', async () => {
  const h = host(); const tree = h.render(props());
  assert.equal(byType(tree, 'Modal').props.transparent, true);
  assert(action(tree, 'View reel')); assert(action(tree, 'Open in Maps'));
  assert(!action(tree, 'Save place details')); assert(!action(tree, 'Edit details')); assert(!action(tree, 'Remove saved place'));
  assert(text(tree).includes('Café · Lisbon · Portugal'));
  action(tree, 'View reel').props.onPress(); action(tree, 'Open in Maps').props.onPress(); await flush();
  assert.deepEqual(h.urls, [item.sourceUrl, item.googleMapsUrl]); h.dispose();
});

test('overflow contains edit and retry, and the first hardware Back closes only that menu', () => {
  let closes = 0; const h = host(); let tree = h.render(props({ onClose: () => closes++ }));
  action(tree, 'More place options').props.onPress(); tree = h.render();
  assert(action(tree, 'Edit details')); assert(action(tree, 'Retry reading post')); assert(action(tree, 'Remove saved place'));
  byType(tree, 'Modal').props.onRequestClose(); tree = h.render();
  assert(!action(tree, 'Edit details')); assert.equal(closes, 0);
  byType(tree, 'Modal').props.onRequestClose(); assert.equal(closes, 1); h.dispose();
});

test('editing from overflow retains unsaved notes behind the existing discard guard', () => {
  let closes = 0; const h = host(); let tree = h.render(props({ onClose: () => closes++ }));
  action(tree, 'More place options').props.onPress(); tree = h.render(); action(tree, 'Edit details').props.onPress(); tree = h.render();
  action(tree, 'Notes').props.onChange('My personal notes'); tree = h.render();
  action(tree, 'Close place').props.onPress(); tree = h.render();
  assert(action(tree, 'Keep editing')); assert.equal(closes, 0);
  action(tree, 'Keep editing').props.onPress(); tree = h.render(); assert.equal(action(tree, 'Notes').props.value, 'My personal notes'); h.dispose();
});

test('remove is a deliberate second action and only deletes the selected saved place', async () => {
  let removed, closes = 0; const h = host(); let tree = h.render(props({ onClose: () => closes++, onDelete: async id => { removed = id; } }));
  action(tree, 'More place options').props.onPress(); tree = h.render(); action(tree, 'Remove saved place').props.onPress(); tree = h.render();
  assert.equal(removed, undefined); assert(action(tree, 'Keep place')); assert(!byType(tree, 'DreamPhoto'));
  action(tree, 'Remove').props.onPress(); await flush(); assert.equal(removed, item.id); assert.equal(closes, 1); h.dispose();
});

test('a multi-place reel dismisses its detail before source navigation and ignores duplicate taps', () => {
  const events = []; const h = host(); const tree = h.render(props({ sourceCount: 5, onClose: () => events.push('close'), onShowSource: () => events.push('source') }));
  const press = action(tree, 'View 5 places from this reel').props.onPress; press(); press();
  assert.deepEqual(events, ['close', 'source']); h.dispose();
});

test('failed local receipts expose Retry save while active sorting does not expose mutating actions', () => {
  const h = host(); let tree = h.render(props({ item: { ...item, id: 'pending-8', uploadStatus: 'failed' } }));
  action(tree, 'More place options').props.onPress(); tree = h.render(); assert(action(tree, 'Retry save')); h.dispose();
  const active = host(); tree = active.render(props({ item: { ...item, sortingState: 'running', status: 'processing' } }));
  assert(!action(tree, 'More place options')); assert(action(tree, 'View reel')); active.dispose();
});

test('live Google addresses retain attribution and only the selected verified candidate is plotted', () => {
  const h = host({ live: { details: { locationProvider: 'google_places', locationStatus: 'resolved', locationPlaceId: 'verified',
    locationExpiresAt: '2099-01-01', locationAddress: 'A current Google address', locationCandidates: [{ id: 'verified', latitude: 38.8, longitude: -9.2 }],
    locationAttributions: [{ displayName: 'Photo contributor', uri: 'https://example.com/contributor' }] } } });
  const tree = h.render(props({ item: { ...item, locationProvider: 'google_places', locationExpiresAt: '2099-01-01' } }));
  assert.equal(byType(tree, 'DreamPlacesMap').props.points[0].lat, 38.8);
  assert(text(tree).includes('A current Google address'));
  const attribution = nodes(tree).find(node => typeof node.type === 'function' && node.type.name === 'GoogleAttribution');
  const renderedAttribution = attribution.type(attribution.props);
  assert(text(renderedAttribution).includes('Google Maps')); assert(text(renderedAttribution).includes('Photo contributor'));
  assert(!action(tree, 'Save place details')); h.dispose();
});

test('closing an in-flight edit does not offer to discard an already submitted request or close twice later', async () => {
  let finish, closes = 0, received;
  const h = host(); let tree = h.render(props({ initialMode: 'edit', onClose: () => closes++,
    onSave: async (_id, patch) => { received = patch; await new Promise(resolve => { finish = resolve; }); } }));
  action(tree, 'Notes').props.onChange('An intentional edit'); tree = h.render();
  action(tree, 'Save changes').props.onPress(); tree = h.render();
  assert.equal(received.summary, 'An intentional edit');
  byType(tree, 'Modal').props.onRequestClose(); tree = h.render();
  assert.equal(closes, 1); assert(!action(tree, 'Discard changes'));
  h.dispose(); finish(); await flush(); assert.equal(closes, 1);
});

test('unidentified reels use the same recognizable source title as their card without repeating a short caption', () => {
  const h = host(); const tree = h.render(props({ item: { ...item, placeName: undefined, city: undefined,
    country: undefined, category: 'unknown', caption: 'Deluxe room with view #fyp', summary: '' } }));
  const title = nodes(tree).find(node => node.type === 'Text' && node.props.accessibilityRole === 'header');
  assert.equal(text(title)[0], 'Deluxe room with view'); assert.equal(title.props.numberOfLines, 3);
  assert(!text(tree).includes('Saved inspiration')); assert(!text(tree).includes('Deluxe room with view #fyp')); h.dispose();
});

test('an unparsed long caption remains readable below a constrained source title when no summary exists', () => {
  const caption = 'A quiet room overlooking the water. ' + 'These are the original words from the saved reel. '.repeat(7);
  const h = host(); let tree = h.render(props({ item: { ...item, placeName: undefined, caption, summary: '' } }));
  const title = nodes(tree).find(node => node.type === 'Text' && node.props.accessibilityRole === 'header');
  assert(text(title)[0].length <= 92); assert.equal(title.props.numberOfLines, 3);
  assert(action(tree, 'Read more') || text(tree).includes('Read more'));
  nodes(tree).find(node => node.type === 'Pressable' && text(node).includes('Read more')).props.onPress(); tree = h.render();
  assert(text(tree).includes(caption.trim())); h.dispose();
});
