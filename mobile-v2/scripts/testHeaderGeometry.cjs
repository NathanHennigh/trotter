const assert = require('node:assert/strict');
const { test } = require('node:test');
const fs = require('node:fs'), path = require('node:path'), ts = require('typescript');
const React = require('react'), Renderer = require('react-test-renderer');
global.IS_REACT_ACT_ENVIRONMENT = true;
const root = path.resolve(__dirname, '../src'), cache = new Map();
let fontScale = 1;
const native = { View: 'View', Text: 'Text', Pressable: 'Pressable', Platform: { OS: 'android' }, StyleSheet: { create: styles => styles }, useWindowDimensions: () => ({ width: 420, fontScale }) };
function load(file) {
  if (cache.has(file)) return cache.get(file).exports;
  if (file.endsWith('.json')) return JSON.parse(fs.readFileSync(file, 'utf8'));
  const module = { exports: {} }; cache.set(file, module);
  const compiled = ts.transpileModule(fs.readFileSync(file, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.React, esModuleInterop: true, target: ts.ScriptTarget.ES2022 } }).outputText;
  new Function('require', 'module', 'exports', compiled)(name => {
    if (name === 'react') return React;
    if (name === 'react-native') return native;
    if (name === 'react-native-svg') return { __esModule: true, default: 'Svg', Path: 'Path', Circle: 'Circle', Ellipse: 'Ellipse', Rect: 'Rect' };
    if (name.endsWith('/motion')) return { PressFeedback: 'Pressable' };
    if (name.endsWith('/travelTrips')) return { useTravelTrips: () => ({ profile: { name: 'Test traveller' } }) };
    const base = path.resolve(path.dirname(file), name), resolved = ['', '.ts', '.tsx', '.json'].map(ext => base + ext).find(value => fs.existsSync(value));
    assert(resolved, `Unexpected dependency ${name}`); return load(resolved);
  }, module, module.exports);
  return module.exports;
}
const geometry = load(path.join(root, 'components/world-window/headerGeometry.ts'));
const { WWHeader, WWIcon } = load(path.join(root, 'components/world-window/WorldWindowUI.tsx'));
const { ProfileAvatar } = load(path.join(root, 'components/world-window/profile/ProfileAvatar.tsx'));
const theme = load(path.join(root, 'theme/trotterTheme.ts'));

// Render Planner's actual header JSX and styles in isolation, without starting its network effects.
const plannerFile = path.join(root, 'screens/PlannerScreen.tsx'), plannerSource = fs.readFileSync(plannerFile, 'utf8');
const plannerAst = ts.createSourceFile(plannerFile, plannerSource, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const styles = plannerAst.statements.find(node => ts.isVariableStatement(node) && node.declarationList.declarations.some(declaration => declaration.name.getText(plannerAst) === 's'));
let header;
function visit(node) { if (ts.isJsxElement(node) && node.openingElement.tagName.getText(plannerAst) === 'View' && node.openingElement.attributes.getText(plannerAst) === 'style={s.header}') header = node; ts.forEachChild(node, visit); }
visit(plannerAst); assert(header, 'Planner must expose its actual header row');
const compiledPlanner = ts.transpileModule(`${styles.getText(plannerAst)}\nfunction PlannerHeader(){return ${header.getText(plannerAst)}}\nreturn PlannerHeader;`, { compilerOptions: { jsx: ts.JsxEmit.React, target: ts.ScriptTarget.ES2022 } }).outputText;
const globals = { React, ...native, ...theme, ...geometry, ProfileAvatar, WWIcon, PressFeedback: 'Pressable', tripId: undefined, inviteToken: undefined, joined: false, back() {}, onOpenProfile() {} };
const PlannerHeader = new Function(...Object.keys(globals), compiledPlanner)(...Object.values(globals));

test('Planner and the shared tab header declare the same safe-area avatar anchor at normal and large text sizes', async () => {
  for (fontScale of [1, 1.35, 2]) {
    const variants = [React.createElement(PlannerHeader), ...['Trips', 'Passport', 'Dreams'].map(title => React.createElement(WWHeader, { title, action: React.createElement(ProfileAvatar, { onPress() {} }) }))];
    for (const element of variants) {
      let view; await React.act(async () => { view = Renderer.create(element); });
      const row = view.root.findAllByType('View')[0], avatar = view.root.findByProps({ accessibilityLabel: 'Open your profile and settings' });
      const frame = avatar.props.style, outer = row.props.style;
      assert.equal(outer.alignItems, 'flex-start', 'title height must not center the trailing action vertically');
      assert.equal(frame.alignSelf, 'flex-start');
      assert.deepEqual([frame.width, frame.height], [44, 44], 'the small circle retains its full touch target');
      const bounds = [420 - outer.paddingHorizontal - frame.width, 54 + outer.paddingTop, 420 - outer.paddingHorizontal, 54 + outer.paddingTop + frame.height].map(dp => dp * 3);
      assert.deepEqual(bounds, [1056, 204, 1188, 336]);
      await React.act(async () => view.unmount());
    }
  }
});

test('an additional Dreams action leaves the profile slot at the trailing edge', async () => {
  let view; await React.act(async () => { view = Renderer.create(React.createElement(WWHeader, { title: 'Dreams', action: React.createElement('View', { style: { flexDirection: 'row' } }, React.createElement('Pressable', { style: { width: 44, height: 44 }, accessibilityLabel: 'Save from Instagram' }), React.createElement(ProfileAvatar, { onPress() {} })) })); });
  const slot = view.root.findAllByType('View').find(node => node.props.style === geometry.headerActionStyle);
  assert(slot); assert.equal(slot.props.style.alignSelf, 'flex-start'); assert.equal(slot.props.style.flexShrink, 0);
  const actions = slot.findAllByType('Pressable'); assert.equal(actions.at(-1).props.accessibilityLabel, 'Open your profile and settings');
  await React.act(async () => view.unmount());
});
