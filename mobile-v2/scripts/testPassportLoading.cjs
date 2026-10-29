// Exercise the production native component with delayed local assets and bridge
// messages. This checks handoff/interaction ordering; real WebView painting is
// covered by capturePassportMotionProof and the Android device pass.
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), ts = require('typescript');
require('node:child_process').execFileSync(process.execPath, [path.join(__dirname, 'buildPassportCover.cjs'), '--check']);
const root = path.resolve(__dirname, '..');
function hookHost() {
  const slots = []; let cursor = 0, effects = [], component, props;
  const same = (a, b) => a && b && a.length === b.length && a.every((v, i) => Object.is(v, b[i]));
  const React = {
    createElement: (type, props, ...children) => ({ type, props: { ...props, children } }),
    useState(value) { const i = cursor++; slots[i] ??= { value: typeof value === 'function' ? value() : value }; return [slots[i].value, next => { slots[i].value = typeof next === 'function' ? next(slots[i].value) : next; }]; },
    useRef(value) { const i = cursor++; return slots[i] ??= { current: value }; },
    useMemo(make, deps) { const i = cursor++; if (!slots[i] || !same(slots[i].deps, deps)) slots[i] = { deps, value: make() }; return slots[i].value; },
    useCallback(fn, deps) { return React.useMemo(() => fn, deps); },
    useEffect(fn, deps) { const i = cursor++; if (!slots[i] || !same(slots[i].deps, deps)) effects.push(() => { slots[i]?.cleanup?.(); slots[i] = { deps, cleanup: fn() }; }); },
  };
  return { React, setComponent: fn => component = fn, render(next = props) { props = next; cursor = 0; effects = []; const tree = component(props); effects.forEach(fn => fn()); return tree; }, unmount() { slots.forEach(slot => slot?.cleanup?.()); } };
}
const moduleCache = new Map();
function loadModule(file) {
  if (moduleCache.has(file)) return moduleCache.get(file).exports;
  const mod = { exports: {} }; moduleCache.set(file, mod);
  const output = ts.transpileModule(fs.readFileSync(file, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } }).outputText;
  new Function('module', 'exports', 'require', output)(mod, mod.exports, name => {
    if (!name.startsWith('.')) return require(name);
    const base = path.resolve(path.dirname(file), name);
    return loadModule([base, base + '.ts', base + '.js'].find(candidate => fs.existsSync(candidate) && fs.statSync(candidate).isFile()));
  });
  return mod.exports;
}
const geometry = loadModule(path.join(root, 'src/components/world-window/passport/passport-cover.ts'));
const artwork = loadModule(path.join(root, 'src/components/world-window/passport/passport-cover-face.ts'));
function load() {
  const host = hookHost(), pending = [], injected = [];
  const file = path.join(root, 'src/components/world-window/passport/PassportBook.tsx'), source = fs.readFileSync(file, 'utf8');
  const ast = ts.createSourceFile(file, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const declaration = ast.statements.find(n => ts.isFunctionDeclaration(n) && n.name?.text === 'PassportBook');
  const styles = ast.statements.find(n => ts.isVariableStatement(n) && n.declarationList.declarations.some(d => d.name.getText(ast) === 'styles'));
  const globals = { React: host.React, ...host.React, ...geometry, ...artwork, Platform: { OS: 'android' }, View: 'View', Text: 'Text', Pressable: 'Pressable', WebView: 'WebView', SvgXml: 'SvgXml', StyleSheet: { create: s => s }, colors: {}, fonts: {}, selectionHaptic() {},
    preparePassportPayload: () => new Promise((resolve, reject) => pending.push({ resolve, reject })), passportDocument: payload => JSON.stringify(payload), scriptJSON: JSON.stringify };
  const compiled = ts.transpileModule(declaration.getText(ast) + '\n' + styles.getText(ast), { compilerOptions: { jsx: ts.JsxEmit.React, module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
  const mod = { exports: {} }; new Function('module', 'exports', ...Object.keys(globals), compiled)(mod, mod.exports, ...Object.values(globals)); host.setComponent(mod.exports.PassportBook);
  return { ...host, pending, injected };
}
function nodes(tree) { return Array.isArray(tree) ? tree.flatMap(nodes) : tree && typeof tree === 'object' ? [tree, ...nodes(tree.props?.children)] : []; }
const find = (tree, type) => nodes(tree).find(n => n.type === type);
const cover = tree => nodes(tree).find(n => n.props?.testID === 'passport-loading-cover');
const style = node => Object.assign({}, ...[node.props.style].flat().filter(Boolean));
const flush = async () => { await Promise.resolve(); await Promise.resolve(); };
const message = (webview, type, values = {}) => webview.props.onMessage({ nativeEvent: { data: JSON.stringify({ source: 'trotter-passport', type, ...values }) } });
function runtimeVisibility() {
  const source = fs.readFileSync(path.join(root, 'src/components/world-window/passport/passport-runtime.ts'), 'utf8');
  const ast = ts.createSourceFile('passport-runtime.ts', source, ts.ScriptTarget.Latest, true);
  const declarations = ['setVisible', 'update'].map(name => ast.statements.find(node => ts.isFunctionDeclaration(node) && node.name?.text === name).getText(ast)).join('\n');
  const body = ts.transpileModule(declarations, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText;
  return new Function(`
    const calls = { wake: 0, cancel: 0, released: [], textures: 0, flushed: [], posts: [] };
    let payload = { visible: true, fonts: { Font: 'cached' }, stamps: ['same-stamp'] }, pendingUpdate = null;
    let presentationVisible = true, generation = 0, disposed = false, pointer = { id: 7 }, feedbackOrigin = 'original';
    let frame = 31, lastTime = 90, finishTextures;
    const model = { spread: 3, cancel() { calls.cancel++; } };
    const cover = { settled: 1, snap(value) { this.settled = value; } };
    const host = { hasPointerCapture: () => true, releasePointerCapture: id => calls.released.push(id) };
    const document = { fonts: { check: () => true } }, textures = ['same-texture'];
    const cancelAnimationFrame = () => {}, post = (...args) => calls.posts.push(args);
    const wake = () => calls.wake++, pagesFor = () => ['prepared-page'];
    const flushUpdate = () => { calls.flushed.push(pendingUpdate); pendingUpdate = null; };
    const makeTextures = () => { calls.textures++; return new Promise(resolve => finishTextures = resolve); };
    ${body}
    return { setVisible, update, calls, model, cover, finish() { finishTextures(['new-texture']); },
      get payload() { return payload; }, get frame() { return frame; } };
  `)();
}
(async () => {
  {
    const runtime = runtimeVisibility(), stamps = runtime.payload.stamps;
    runtime.setVisible(false);
    assert.equal(runtime.frame, 0);
    assert.deepEqual(runtime.calls.released, [7]);
    assert.equal(runtime.model.spread, 3);
    assert.equal(runtime.cover.settled, 1);
    runtime.setVisible(true);
    assert.equal(runtime.calls.wake, 1);
    assert.equal(runtime.calls.textures, 0, 'Visibility does not rebuild any canvas textures');
    assert.equal(runtime.payload.stamps, stamps);
    const updating = runtime.update({ visible: true, fonts: { Font: 'cached' }, stamps: ['fresh-stamp'] });
    runtime.setVisible(false); runtime.finish(); await updating;
    assert.equal(runtime.calls.flushed[0].payload.visible, false, 'An in-flight archive refresh cannot resume a hidden passport');
    assert.equal(runtime.calls.wake, 1, 'Background hydration keeps rendering paused');
  }
  for (const width of [320, 410, 600]) {
    const host = load(); const props = { width, archive: { arrivals: [] }, onCountry() {} };
    let tree = host.render(props); const initial = style(cover(tree)), initialHeight = style(tree).height;
    assert(cover(tree)); assert(!find(tree, 'WebView'));
    const face = find(cover(tree), 'SvgXml');
    assert(face, 'Native placeholder renders shared vector artwork');
    assert.equal(face.props.xml, artwork.passportCoverFace(width), 'Placeholder uses the exact WebView cover face');
    assert(!find(cover(tree), 'Text'), 'Cover title cannot fall back to a second native font/layout');
    assert.match(face.props.xml, /id="cover-lettering"[^>]+d="M/, 'Title is outlined before any font loads');
    assert.equal((face.props.xml.match(/<svg\b/g) || []).length, 1, 'Native face cannot contain another SVG viewport with unsupported x/y positioning');
    assert.doesNotMatch(face.props.xml, /\btransform=/, 'All artwork placement is baked into path coordinates for native rendering');
    host.pending.shift().resolve({ name: 'Traveler', fonts: {}, stamps: [] }); await flush();
    tree = host.render(); let webview = find(tree, 'WebView');
    assert(cover(tree), 'Preparing HTML must not remove the native cover');
    assert.deepEqual(style(cover(tree)), initial, 'Cover does not resize while WebView mounts');
    assert.equal(style(tree).height, initialHeight);
    assert.equal(style(webview).opacity, 0, 'Unpainted WebView cannot flash above the cover');
    webview.props.ref.current = { injectJavaScript: code => host.injected.push(code) };
    webview.props.onLoad(); tree = host.render(); webview = find(tree, 'WebView');
    assert(cover(tree), 'WebView document-loaded event is not first-paint readiness');
    message(webview, 'size', { height: 123 }); tree = host.render();
    assert.equal(style(tree).height, initialHeight, 'Early size bridge message cannot shift the placeholder');
    cover(tree).props.onPress(); assert.equal(host.injected.filter(code => code.includes('openPassport')).length, 0, 'Early tap is queued while page assets load');
    message(webview, 'ready'); tree = host.render(); webview = find(tree, 'WebView');
    assert(!cover(tree)); assert.equal(style(webview).opacity, 1); assert.equal(style(tree).height, 123);
    assert.equal(host.injected.filter(code => code.includes('openPassport')).length, 1, 'Early tap opens the real cover exactly once after first paint');
    message(webview, 'ready'); host.render();
    assert.equal(host.injected.filter(code => code.includes('openPassport')).length, 1);
    tree = host.render({ ...props, archive: { arrivals: [] } });
    assert(!cover(tree), 'Archive refresh keeps the existing book visible');
    host.pending.shift().resolve({ name: 'Updated traveler', fonts: {}, stamps: [] }); await flush();
    tree = host.render(); assert.equal(style(find(tree, 'WebView')).opacity, 1); assert(!cover(tree));
    message(find(tree, 'WebView'), 'error'); tree = host.render();
    const retry = nodes(tree).find(n => n.type === 'Pressable' && !n.props.testID);
    assert(retry, 'Runtime asset failures expose retry'); retry.props.onPress(); tree = host.render();
    assert(cover(tree), 'Retry restores the stable cover while replacing the failed WebView');
    host.pending.at(-1).resolve({ name: 'Retry traveler', fonts: {}, stamps: [] }); await flush();
    tree = host.render(); assert(cover(tree)); assert.equal(style(find(tree, 'WebView')).opacity, 0);
    host.unmount();
  }
  {
    const host = load(), props = { width: 410, archive: { arrivals: [] }, onCountry() {}, visible: true };
    host.render(props);
    // Switching away while assets are in flight must not restart preparation.
    host.render({ ...props, visible: false });
    assert.equal(host.pending.length, 1);
    host.pending.shift().resolve({ name: 'Traveler', fonts: { DMSans: 'large-font-data' }, stamps: [] }); await flush();
    let tree = host.render(), webview = find(tree, 'WebView');
    assert.equal(JSON.parse(webview.props.source.html).visible, false, 'Delayed payload uses the current tab visibility');
    const source = webview.props.source;
    webview.props.ref.current = { injectJavaScript: code => host.injected.push(code) };
    webview.props.onLoad(); message(webview, 'ready'); host.render();
    host.injected.length = 0;
    for (const visible of [true, false, true, false, true]) {
      tree = host.render({ ...props, visible });
      assert.equal(find(tree, 'WebView').props.source, source, 'Tab switches retain the same native WebView document');
    }
    assert.equal(host.pending.length, 0, 'Tab visibility never reloads assets or prepares a full payload');
    assert.equal(host.injected.length, 5);
    assert(host.injected.every(code => code.includes('setPassportVisible') && code.length < 100), 'Only a tiny lifecycle message crosses the WebView bridge');
    assert(!host.injected.some(code => code.includes('updatePassport') || code.includes('large-font-data')));
    host.unmount();
  }
  console.log('Passport loading passed at 320/410/600: continuous cover, delayed paint reveal, queued tap, stable refresh and retry.');
})().catch(error => { console.error(error); process.exitCode = 1; });
