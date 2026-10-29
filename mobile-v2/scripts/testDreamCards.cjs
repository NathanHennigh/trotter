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
    '../components/world-window/profile/ProfileAvatar': { ProfileAvatar: 'ProfileAvatar' },
    '../components/world-window/planner/DreamTripPicker': { DreamTripPicker: 'DreamTripPicker' },
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
const action = (tree, label) => nodes(tree).find(node => node.props?.accessibilityLabel === label || node.props?.label === label);
const text = tree => nodes(tree).filter(node => node.type === 'Text').map(node => node.props.children.flat(Infinity).join(''));
const countryProps = overrides => ({ title: 'Thailand', items: [item], topInset: 0, bottomInset: 20,
  loading: false, onBack: noop, onRefresh: noop, onSelect: noop, onLocateMissing: async () => {}, motion: false, ...overrides });

test('unidentified reels use recognizable source words without inventing a destination or exposing caption clutter', () => {
  const h = host('PlaceRow'), { dreamCardTitle, dreamCardMeta } = h.model;
  const unknown = { ...item, placeName: undefined, city: undefined, country: undefined, category: 'unknown', caption: 'Deluxe room with view #fyp https://example.com', summary: '' };
  assert.equal(dreamCardTitle(unknown), 'Deluxe room with view'); assert.equal(dreamCardMeta(unknown), 'Saved reel');
  assert.equal(dreamCardTitle({ ...unknown, caption: '🏜️' }), 'Saved reel');
  assert.equal(dreamCardTitle({ ...unknown, caption: '' }), 'Saved reel');
  assert.equal(dreamCardTitle({ ...unknown, caption: '#fyp #travel' }), 'Saved reel');
  assert.equal(dreamCardTitle({ ...item, caption: 'An unrelated line' }), item.placeName);
  assert.equal(dreamCardMeta(item), 'Café · Krabi');
  assert.equal(dreamCardMeta({ ...item, city: undefined, regionOrNeighborhood: 'South Thailand' }), 'Café · South Thailand');
  h.dispose();
});

test('social follow and bio promotions are secondary source copy, while real route instructions remain titles',()=>{
 const h=host('PlaceRow'),{dreamCardTitle}=h.model;
 const source={...item,placeName:undefined,city:undefined,country:'Morocco',category:'unknown',locationState:'source_details',summary:''};
 for(const caption of [
  'Follow @isabella.aroundtheworld for more daily travel inspiration and epic roadtrips! 🚗🏜️',
  'Follow for more places worth saving.',
  'Get the full travel guide — link in bio.',
  'Find our itinerary through the link in our bio.',
 ]){
  assert.equal(dreamCardTitle({...source,caption}),'Inspiration in Morocco');
  assert.equal(dreamCardTitle({...source,placeName:caption,caption}),'Inspiration in Morocco');
 }
 assert.equal(dreamCardTitle({...source,caption:'A quiet road through the Atlas Mountains. Follow @roadtrip.guide for more.'}),'A quiet road through the Atlas Mountains.');
 assert.equal(dreamCardTitle({...source,caption:'Follow the coast to the hidden cove.'}),'Follow the coast to the hidden cove.');
 assert.equal(dreamCardTitle({...source,placeName:'Follow the Sun Café',caption:'Follow @travel for more.'}),'Follow the Sun Café');
 h.dispose();
});

test('long source titles truncate without splitting a non-BMP character into a replacement glyph',()=>{
 const h=host('PlaceRow'),{dreamCardTitle}=h.model;
 const prefix='A'.repeat(88),caption=prefix+'🚗'+'B'.repeat(12);
 const saved={...item,placeName:undefined,caption,summary:''};
 const title=dreamCardTitle(saved);
 assert.equal(title,prefix+'🚗…');
 assert(!/[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/u.test(title));
 assert.equal(dreamCardTitle({...saved,caption:'A'+ '🚗'.repeat(90)}),'A'+ '🚗'.repeat(90),'The limit counts Unicode characters, not UTF-16 halves');
 assert.equal(saved.caption,caption,'Presentation never changes the saved source');h.dispose();
});

test('same-title saves from different posts retain their identity and expose their own stored descriptions',()=>{
 const h=host('PlaceRow'),{repeatedDreamTitleIds,dreamCardExcerpt}=h.model;
 const first={...item,id:'80',placeName:'Taghazout',city:undefined,country:'Morocco',sourceUrl:'https://instagram.com/reel/post-one',
  locationState:'source_details',locationReason:'creator_link_required',summary:'A beautiful hideaway located above the ocean with stunning sunset views.'};
 const second={...first,id:'85',sourceUrl:'https://instagram.com/reel/post-two',locationReason:'identity_not_shared',summary:'Boutique stays and Airbnb rentals with ocean views.'};
 const sameSource={...first,id:'81',sourceUrl:'https://instagram.com/reel/post-one/?tracking=ignored'};
 assert.deepEqual([...repeatedDreamTitleIds([first,second])],['80','85']);
 assert.equal(repeatedDreamTitleIds([first,sameSource]).size,0,'Several entries from one post use their source group, not a false separate-source distinction');
 assert.equal(dreamCardExcerpt(first),first.summary);assert.equal(dreamCardExcerpt(second),second.summary);
 assert.equal(dreamCardExcerpt({...first,summary:'Saved from Instagram',caption:'Ocean views at sunset. Follow @creator for more.'}),'Ocean views at sunset.');
 assert.equal(dreamCardExcerpt({...first,summary:'Taghazout',caption:'Comment LINK for the address.'}),'');
 assert.equal(first.placeName,'Taghazout');assert.equal(second.placeName,'Taghazout');h.dispose();
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

test('Needs attention separates actionable saves from automatic organizing above country postcards', () => {
  const saves = [item, { ...item, id: '2', country: undefined, placeName: undefined, status: 'processing', sortingState: 'running' },
    { ...item, id: '3', country: undefined, status: 'needs_review', sortingState: 'needs_details' },
    { ...item, id: '4', country: undefined, status: 'needs_review', sortingState: 'unavailable' }];
  const h = host('DreamsScreen', saves); let tree = h.render({ active: 'dreams', onChange: noop });
  assert.deepEqual(find(tree, 'FlatList').props.data.map(board => board.title), ['Thailand']);
  const inbox = action(tree, 'Needs attention, 2 saves'); assert(inbox);
  assert(!text(tree).some(value => /^Review \d/.test(value))); inbox.props.onPress(); tree = h.render();
  const collection = nodes(tree).find(node => typeof node.type === 'function' && node.type.name === 'CountryPlaces');
  assert.equal(collection.props.title, 'Needs attention'); assert.equal(collection.props.items.length, 2);
  collection.props.onBack(); tree = h.render(); assert.equal(find(tree, 'FlatList').props.data.length, 1); h.dispose();
});

test('country card opens details directly while its pin selects the country map and scrolls to it', () => {
  const selected = [], scrolls = [], saved = { ...item, latitude: 8.1, longitude: 98.9 };
  const h = host('CountryPlaces'); let tree = h.render(countryProps({ items: [saved], onSelect: (...value) => selected.push(value) }));
  const list = find(tree, 'FlatList'); list.props.ref.current = { scrollToOffset: value => scrolls.push(value) };
  const row = nodes(list.props.renderItem({ item: saved, index: 0 })).find(node => typeof node.type === 'function' && node.type.name === 'PlaceRow');
  row.props.onPress(); assert.deepEqual(selected, [['1', 'view']]);
  row.props.onShowMap(); tree = h.render(); assert.equal(find(tree, 'DreamPlacesMap').props.selectedId, '1');
  assert.deepEqual(scrolls, [], 'Switching to Map preserves the list scroll offset'); assert.equal(selected.length, 1); h.dispose();
});

test('the detail sheet owns multi-place reel navigation and returning preserves its country', () => {
  const h = host('DreamsScreen', [item, { ...item, id: '2', placeName: 'Second café' }]);
  let tree = h.render({ active: 'dreams', onChange: noop }); const list = find(tree, 'FlatList');
  list.props.renderItem({ item: list.props.data[0] }).props.onPress(); tree = h.render();
  let collection = nodes(tree).find(node => typeof node.type === 'function' && node.type.name === 'CountryPlaces');
  collection.props.onSelect('1', 'view'); tree = h.render(); const detail = find(tree, 'DreamEditor');
  assert.equal(detail.props.sourceCount, 2); detail.props.onShowSource(); tree = h.render();
  assert(!find(tree, 'DreamEditor'));
  const retained=nodes(tree).find(node=>typeof node.type==='function'&&node.type.name==='CountryPlaces'&&!node.props.sourceUrl);
  assert.equal(retained.props.active,false);
  collection = nodes(tree).find(node => typeof node.type === 'function' && node.type.name === 'CountryPlaces' && node.props.sourceUrl);
  assert.equal(collection.props.title, 'Places from this post'); assert.equal(collection.props.items.length, 2);
  collection.props.onBack(); tree = h.render(); collection = nodes(tree).find(node => typeof node.type === 'function' && node.type.name === 'CountryPlaces');
  assert.equal(collection.props.title, 'Thailand'); h.dispose();
});

test('source-limited saves keep their country, photo and recognizable title without a broken-pin or review warning', () => {
  const saved = { ...item, placeName: undefined, category: 'hotel', country: 'Greece', city: 'Serifos',
    caption: 'A little house by the sea', needsReview: true, sortingState: 'needs_details',
    locationState: 'source_details', locationReason: 'creator_link_required', locationStatus: 'not_found' };
  const h = host('PlaceRow'); const tree = h.render({ item: saved, onPress: noop, onShowMap: noop });
  assert(text(tree).includes('A little house by the sea')); assert(text(tree).includes('Inspiration · Serifos'));
  assert(text(tree).includes('Location not shared')); assert.equal(find(tree, 'DreamPhoto').props.item, saved);
  assert(!text(tree).some(value => /error|needs details|finding location|retry/i.test(value)));
  assert.equal(nodes(tree).filter(node => node.type === 'Pressable').length, 1); h.dispose();
  const home = host('DreamsScreen', [saved]); const homeTree = home.render({ active: 'dreams', onChange: noop });
  assert.deepEqual(find(homeTree, 'FlatList').props.data.map(board => board.title), ['Greece']);
  assert(!nodes(homeTree).some(node => node.props?.accessibilityLabel?.startsWith('Unsorted,'))); home.dispose();
});

test('a mixed collection retries only identifiable places and describes inspiration without demanding a pin', async () => {
  const inspiration = { ...item, id: '2', placeName: undefined, locationState: 'source_details', locationReason: 'identity_not_shared', locationStatus: 'not_found' };
  const unresolved = { ...item, id: '3', locationState: 'unresolved', locationReason: 'named_unresolved', locationStatus: 'not_found' };
  const deferred = { ...unresolved, id: '4', locationState: 'unavailable', locationRetryAt: '2099-01-01' };
  const calls = [], h = host('CountryPlaces'); let tree = h.render(countryProps({ items: [inspiration, unresolved, deferred], onLocateMissing: async ids => calls.push(ids) }));
  action(tree,'Show map').props.onPress(); tree=h.render();
  assert(nodes(tree).some(node=>node.props?.title==='Places first. Pins later.'));
  action(tree,'Add locations').props.onPress(); tree=h.render();
  assert(!text(tree).some(value => /needs? a pin/.test(value)));
  await action(tree, 'Retry available locations').props.onPress(); assert.deepEqual(calls, [['3']]);
  tree = h.render(countryProps({ items: [inspiration, deferred] })); assert(!action(tree, 'Retry available locations')); h.dispose();
});
