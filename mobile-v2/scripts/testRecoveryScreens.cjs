// Isolated renders of the real screens, with synthetic account/item state.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
const { test } = require('node:test');
const root = path.join(__dirname, '../src');
const noop = () => {};
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
const flush = async () => { for (let n = 0; n < 30; n++) await Promise.resolve(); };
function screen(file, exportName, overrides = {}) {
  const slots = []; let cursor = 0, effects = [], props;
  const same = (a, b) => a && b && a.length === b.length && a.every((v, i) => v === b[i]);
  const react = {
    createElement: (type, props, ...children) => ({ type, props: { ...props, children } }),
    useState(initial) { const i = cursor++; if (!(i in slots)) slots[i] = typeof initial === 'function' ? initial() : initial; return [slots[i], value => { slots[i] = typeof value === 'function' ? value(slots[i]) : value; }]; },
    useRef(value) { const i = cursor++; if (!(i in slots)) slots[i] = { current: value }; return slots[i]; },
    useMemo(fn, deps) { const i = cursor++; if (!slots[i] || !same(slots[i].deps, deps)) slots[i] = { value: fn(), deps }; return slots[i].value; },
    useEffect(fn, deps) { const i = cursor++; if (!slots[i] || !same(slots[i].deps, deps)) { slots[i]?.cleanup?.(); slots[i] = { deps }; effects.push(() => { slots[i].cleanup = fn(); }); } },
  };
  const tags = 'ActivityIndicator Pressable ScrollView Text View KeyboardAvoidingView Modal TextInput'.split(' ');
  const native = { ...Object.fromEntries(tags.map(tag => [tag, tag])), StyleSheet: { create: x => x }, Platform: { OS: 'android' }, useWindowDimensions: () => ({ width: 390, height: 840 }), Linking: { openURL: async () => {} } };
  const mocks = {
    react, 'react-native': native, 'react-native-svg': { default: 'Svg', Path: 'Path' },
    'react-native-safe-area-context': { useSafeAreaInsets: () => ({ top: 24, bottom: 20 }) },
    '../services/travelTrips': { useTravelTrips: () => overrides.account },
    '../components/world-window/WorldWindowUI': { WWEmblem: 'WWEmblem' },
    '../theme/trotterTheme': { colors: {}, fonts: {} },
    '../../../theme/trotterTheme': { colors: {}, fonts: {} },
    '../WorldWindowUI': { WWButton: 'WWButton', WWHeader: 'WWHeader', WWIcon: 'WWIcon' },
    './DreamPlacesMap': { DreamPlacesMap: 'DreamPlacesMap' }, './DreamPhoto': { DreamPhoto: 'DreamPhoto' },
    './useLiveDreamLocation': { useLiveDreamLocation: () => ({}) },
    './countryRegion': { countryRegion: () => undefined },
    './dreamPresentation': { categoryLabel: x => x, exactMapPoint: () => undefined, safeWebUrl: x => x },
    './locationPresentation': { isFindingLocation: item => ['queued','running'].includes(item.locationStatus), locationExplanation: item => item.locationStatus === 'needs_review' ? 'Which location is the one you saved?' : 'Looking for the address.' },
    '../displayTextFit': { fitDisplayFont: (_text, size) => size },
    '../../../utils/mobileLayout': { getMobileVisualWidth: width => width },
  };
  const compiled = ts.transpileModule(fs.readFileSync(path.join(root, file), 'utf8'), { compilerOptions: { jsx: ts.JsxEmit.React, module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, esModuleInterop: true } }).outputText;
  const module = { exports: {} };
  new Function('module', 'exports', 'require', compiled)(module, module.exports, name => {
    assert(name in mocks, name); return mocks[name];
  });
  return {
    render(next = props) { props = next; cursor = 0; const tree = module.exports[exportName](props); const pending = effects; effects = []; pending.forEach(fn => fn()); return tree; },
    dispose() { slots.forEach(slot => slot?.cleanup?.()); },
  };
}
function nodes(value, seen = new Set()) {
  if (!value || typeof value !== 'object' || seen.has(value)) return [];
  seen.add(value); return [value, ...Object.values(value).flatMap(child => nodes(child, seen))];
}
const find = (tree, type) => nodes(tree).find(node => node.type === type);
const button = (tree, label) => nodes(tree).find(node => node.props?.label === label || node.props?.accessibilityLabel === label);
const text = tree => nodes(tree).filter(node => node.type === 'Text').map(node => node.props.children.flat().join(''));
const item = { id: '1', tags: [], category: 'cafe', placeName: 'Synthetic cafe', summary: 'Notes', country: 'Portugal', needsReview: true, status: 'needs_review', sourceUrl: 'https://www.instagram.com/reel/synthetic' };

test('failed logout offers cleanup retry and never a Google sign-in or archive retry', async () => {
  const wait = deferred(); let retries = 0;
  const host = screen('screens/AuthScreen.tsx', 'AuthScreen', { account: { authStatus: 'signed-out', status: 'error', signOutPending: true, error: 'Retry sign out', signOut: () => { retries++; return wait.promise; }, signIn: noop, refresh: noop } });
  let tree = host.render();
  assert(!text(tree).includes('Continue with Google')); assert(!text(tree).includes('Try connection again'));
  const retry = nodes(tree).find(node => node.type === 'Pressable' && text(node).includes('Retry sign out'));
  assert(retry); retry.props.onPress(); tree = host.render();
  assert(text(tree).includes('Finishing sign out…'));
  assert(nodes(tree).some(node => node.type === 'Pressable' && node.props.disabled === true));
  wait.resolve(); await flush(); assert.equal(retries, 1); host.dispose();
});

for (const closeVia of ['hardware', 'button']) test(`Dream editor ${closeVia} Close works during save and late success cannot close the next screen`, async () => {
  const wait = deferred(); let closes = 0, saves = 0;
  const host = screen('components/world-window/dreams/DreamEditor.tsx', 'DreamEditor');
  let tree = host.render({ item, points: [], onClose: () => closes++, onSave: () => { saves++; return wait.promise; }, onDelete: noop, onRetry: noop });
  const confirm = button(tree, 'Confirm place'); confirm.props.onPress(); confirm.props.onPress();
  assert.equal(saves, 1, 'Double press cannot launch two mutations before React rerenders');
  tree = host.render();
  const close = button(tree, 'Close place'); assert.notEqual(close.props.disabled, true);
  if (closeVia === 'hardware') find(tree, 'Modal').props.onRequestClose(); else close.props.onPress();
  assert.equal(closes, 1); host.dispose();
  wait.resolve(); await flush(); assert.equal(closes, 1);
});

test('failed Dreams save keeps the editor and its draft, then allows a deliberate retry', async () => {
  let calls = 0, closes = 0;
  const host = screen('components/world-window/dreams/DreamEditor.tsx', 'DreamEditor');
  let tree = host.render({ item, points: [], onClose: () => closes++, onSave: async () => { if (++calls === 1) throw new Error('The request timed out. Refresh before retrying.'); }, onDelete: noop, onRetry: noop });
  button(tree, 'Edit details').props.onPress(); tree = host.render();
  const nameField = nodes(tree).find(node => typeof node.type === 'function' && node.props?.label === 'Place name');
  nameField.props.onChange('My retained draft'); tree = host.render();
  button(tree, 'Save changes').props.onPress(); await flush(); tree = host.render();
  assert.equal(closes, 0); assert(text(tree).some(value => value.includes('request timed out')));
  assert.equal(nodes(tree).find(node => node.props?.label === 'Place name').props.value, 'My retained draft');
  assert.equal(button(tree, 'Save changes').props.disabled, false);
  button(tree, 'Save changes').props.onPress(); await flush(); assert.equal(closes, 1); host.dispose();
});

test('editing notes does not silently turn an automatically found location into a manual pin', async () => {
  let patch;
  const host=screen('components/world-window/dreams/DreamEditor.tsx','DreamEditor');
  let tree=host.render({item:{...item,needsReview:false,locationStatus:'resolved',googleMapsUrl:'https://www.google.com/maps/search/?api=1&query=38.7,-9.1'},points:[],onClose:noop,onSave:async(id,value)=>{patch=value;},onDelete:noop,onRetry:noop});
  button(tree,'Edit details').props.onPress(); tree=host.render();
  button(tree,'Save changes').props.onPress(); await flush();
  assert(patch); assert(!Object.hasOwn(patch,'googleMapsUrl'),'An unchanged provider-derived Maps URL stays provider-derived'); host.dispose();
});

test('location lookup remains open and candidate confirmation sends only the chosen candidate',async()=>{
  let closes=0,lookups=0,confirmed;
  const host=screen('components/world-window/dreams/DreamEditor.tsx','DreamEditor');
  const props={item:{...item,needsReview:false},points:[],onClose:()=>closes++,onSave:noop,onDelete:noop,onRetry:noop,onLocate:async()=>lookups++,onConfirmLocation:async(id,candidate)=>{confirmed=[id,candidate];}};
  let tree=host.render(props); button(tree,'Find location').props.onPress(); await flush(); assert.equal(lookups,1); assert.equal(closes,0);
  tree=host.render({...props,item:{...props.item,locationStatus:'needs_review',locationCandidates:[{id:'candidate-2',name:'Cafe One',address:'1 Synthetic Road',latitude:38.7,longitude:-9.1}]}});
  assert.equal(button(tree,'Find location'),undefined); button(tree,'Use this location').props.onPress(); await flush();
  assert.deepEqual(confirmed,['1','candidate-2']); assert.equal(closes,1); host.dispose();
});

test('entering Edit uses the latest parsed place, then polling preserves an active draft',()=>{
  const host=screen('components/world-window/dreams/DreamEditor.tsx','DreamEditor');
  const props={item:{...item,status:'processing',placeName:undefined,city:undefined},points:[],onClose:noop,onSave:noop,onDelete:noop,onRetry:noop};
  host.render(props);
  const ready={...props,item:{...item,placeName:'Completed Cafe',city:'Lisbon',summary:'Parsed notes'}};
  let tree=host.render(ready); button(tree,'Edit details').props.onPress(); tree=host.render();
  const field=(tree,label)=>nodes(tree).find(node=>node.props?.label===label);
  assert.equal(field(tree,'Place name').props.value,'Completed Cafe');
  field(tree,'Place name').props.onChange('My corrected name');
  tree=host.render({...ready,item:{...ready.item,placeName:'Later server value',locationStatus:'resolved'}});
  assert.equal(field(tree,'Place name').props.value,'My corrected name'); host.dispose();
});
