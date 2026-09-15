// Production search hooks with native input focus/blur boundaries simulated.
const assert = require('node:assert/strict'), fs = require('node:fs'), path = require('node:path'), ts = require('typescript');
const mobile = path.resolve(__dirname, '..');
const hostSource = fs.readFileSync(path.join(__dirname, 'testPassportNavigation.cjs'), 'utf8');
const ast = ts.createSourceFile('host.cjs', hostSource, ts.ScriptTarget.Latest, true);
const hookHost = new Function('return (' + ast.statements.find(node => ts.isFunctionDeclaration(node) && node.name.text === 'hookHost').getText(ast) + ')')();
function nodes(tree) { if (Array.isArray(tree)) return tree.flatMap(nodes); return tree && typeof tree === 'object' ? [tree, ...nodes(tree.props?.children)] : []; }
const button = (tree, label) => nodes(tree).find(node => node.type === 'PressFeedback' && node.props.accessibilityLabel === label);
const field = tree => nodes(tree).find(node => node.type === 'TextInput');
for (const title of ['Countries', 'Airports', 'Airlines']) {
  const host = hookHost(); let focused = 0, blurred = 0, dismissed = 0, query = '', registered, exited = 0;
  const nativeInput = { focus() { focused++; }, blur() { blurred++; } };
  const element = host.React.createElement;
  host.React.createElement = (type, props, ...children) => {
    if (type === 'TextInput' && props.ref) props.ref.current = nativeInput;
    return element(type, props, ...children);
  };
  const imports = {
    react: host.React,
    'react-native': { Keyboard: { dismiss() { dismissed++; } }, StyleSheet: { create: value => value }, Text: 'Text', TextInput: 'TextInput', View: 'View', useWindowDimensions: () => ({ width: 320, fontScale: 2 }) },
    '../../../theme/trotterTheme': { colors: {}, fonts: {} }, '../../../utils/mobileLayout': { getMobileVisualWidth: value => value },
    '../motion': { PressFeedback: 'PressFeedback' }, '../WorldWindowUI': { WWIcon: 'WWIcon' },
  };
  const file = path.join(mobile, 'src/components/world-window/collections/CollectionIndexHeader.tsx');
  const compiled = ts.transpileModule(fs.readFileSync(file, 'utf8'), { compilerOptions: { jsx: ts.JsxEmit.React, module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, esModuleInterop: true } }).outputText;
  const module = { exports: {} }; new Function('require', 'module', 'exports', compiled)(name => imports[name] ?? assert.fail(name), module, module.exports);
  host.setComponent(module.exports.CollectionIndexHeader);
  const props = { title, query, setQuery: value => query = value, placeholder: 'Search the catalogue', onBack: () => exited++, backLabel: 'Globe', onBackHandlerChange: value => registered = value };
  let tree = host.render(props); assert(!field(tree)); assert.equal(registered(), false);
  button(tree, `Search ${title.toLowerCase()}`).props.onPress(); tree = host.render({ ...props, query });
  assert(field(tree)); assert.equal(focused, 1, 'Opening search focuses its native input once');
  field(tree).props.onChangeText('SIN'); tree = host.render({ ...props, query }); assert.equal(focused, 1); assert.equal(field(tree).props.value, 'SIN');
  tree = host.render({ ...props, query, active: false }); assert.equal(registered, null); assert(blurred > 0);
  tree = host.render({ ...props, query, active: true }); assert.equal(focused, 1, 'Returning from a detail does not pull the keyboard back up'); assert.equal(field(tree).props.value, 'SIN');
  field(tree).props.onKeyPress({ nativeEvent: { key: 'Escape' } }); tree = host.render({ ...props, query });
  assert.equal(query, ''); assert(!field(tree)); assert.equal(exited, 0); assert.equal(dismissed, 1);
  button(tree, `Search ${title.toLowerCase()}`).props.onPress(); tree = host.render({ ...props, query });
  field(tree).props.onChangeText('DFW'); tree = host.render({ ...props, query }); button(tree, 'Close search').props.onPress(); tree = host.render({ ...props, query });
  assert.equal(query, ''); assert(!field(tree)); assert.equal(dismissed, 2);
  button(tree, `Search ${title.toLowerCase()}`).props.onPress(); tree = host.render({ ...props, query });
  assert.equal(registered(), true, 'Back closes even an empty search before leaving the collection'); tree = host.render({ ...props, query });
  assert.equal(registered(), false); button(tree, 'Back to Globe').props.onPress(); assert.equal(exited, 1);
  host.unmount(); assert.equal(registered, null);
}
console.log('Collection search passed for Countries/Airports/Airlines: focus, close/clear, Escape, Back interception, hidden-layer blur and detail-return keyboard restraint.');
