// Execute the current screen functions with an offline hook host: no native
// renderer, device, API, or duplicated navigation reducer is involved.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const ts = require("typescript");
const { test } = require("node:test");

function hookHost() {
  const slots = [];
  let cursor = 0, pending = [], dirty = false, component, props, tree;
  const same = (a, b) => a && b && a.length === b.length && a.every((v, i) => Object.is(v, b[i]));
  const React = {
    Fragment: "Fragment",
    createElement: (type, props, ...children) => ({ type, props: { ...props, children } }),
    useState(initial) {
      const i = cursor++;
      if (!slots[i]) slots[i] = { value: typeof initial === "function" ? initial() : initial };
      return [slots[i].value, value => {
        const next = typeof value === "function" ? value(slots[i].value) : value;
        if (!Object.is(next, slots[i].value)) { slots[i].value = next; dirty = true; }
      }];
    },
    useRef(value) {
      const i = cursor++;
      return (slots[i] ??= { current: value });
    },
    useMemo(make, deps) {
      const i = cursor++;
      if (!slots[i] || !same(slots[i].deps, deps)) slots[i] = { deps, value: make() };
      return slots[i].value;
    },
    useCallback(fn, deps) { return React.useMemo(() => fn, deps); },
    useEffect(fn, deps) {
      const i = cursor++;
      if (!slots[i] || !same(slots[i].deps, deps)) {
        pending.push(() => { slots[i]?.cleanup?.(); slots[i] = { deps, cleanup: fn() }; });
      }
    },
  };
  return {
    React,
    setComponent(fn) { component = fn; },
    render(nextProps = props) {
      props = nextProps;
      for (let i = 0; i < 10; i++) {
        cursor = 0; pending = []; dirty = false;
        tree = component(props);
        pending.forEach(fn => fn());
        if (!dirty) return tree;
      }
      throw Error("Component did not settle after effects");
    },
    unmount() { slots.forEach(slot => slot?.cleanup?.()); },
  };
}

const trip = {
  id: "trip-one", backendId: 1, title: "Singapore", country: "Singapore",
  segments: [{ id: "flight-one", depAirport: "LHR", arrAirport: "SIN", depTime: "2026-01-02T12:00:00Z", arrTime: "2026-01-03T01:00:00Z",
    depPoint: { code: "LHR", city: "London", country: "United Kingdom", lat: 51.47, lon: -.454 },
    arrPoint: { code: "SIN", city: "Singapore", country: "Singapore", lat: 1.36, lon: 103.99 } }],
};
const arrival = { country: "Singapore", travelCountryKey: "SG", airportCode: "SIN", firstVisitDate: "2026-01-03" };
const archive = { arrivals: [arrival], airports: [{ code: "SIN", city: "Singapore", country: "Singapore", flights: 1, trips: [trip] }], airlines: [], years: [], records: [] };
const noOp = () => {};

function load(file, name, overrides = {}) {
  const host = hookHost();
  const source = fs.readFileSync(path.join(__dirname, "..", file), "utf8");
  const ast = ts.createSourceFile(file, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const declaration = ast.statements.find(n => ts.isFunctionDeclaration(n) && n.name?.text === name);
  assert(declaration, `Load actual ${name}`);
  const styles = ast.statements.find(n => ts.isVariableStatement(n) && n.declarationList.declarations.some(d => d.name.getText(ast) === "styles"));
  const text = declaration.getText(ast);
  const compiled = ts.transpileModule(`${text.startsWith("export") ? text : "export " + text}\n${styles?.getText(ast) ?? ""}`, {
    compilerOptions: { jsx: ts.JsxEmit.React, module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const tags = "View Text Pressable ScrollView Modal RefreshControl ActivityIndicator BottomNav WWHeader WWButton WWEmblem WWIcon WorldWindowGlobe PassportBook ActivityChart CollectionButtons CollectionList CountryArrivalDetail CountryIndex CollectionHeading CollectionBack CroppedPassportStamp TripRows AirlineLogo AirportRouteFan HomeGlobeScreen PassportStatsScreen CountryStampCollectionScreen TripDetailScreen TripsListScreen DreamsScreen ProfileScreen".split(" ");
  const globals = {
    ...Object.fromEntries(tags.map(tag => [tag, tag])),
    React: host.React, useState: host.React.useState, useMemo: host.React.useMemo,
    StyleSheet: { create: x => x, absoluteFillObject: {}, absoluteFill: {} },
    Platform: { OS: "android" }, colors: {}, fonts: {}, layout: { bottomNavHeight: 62 },
    useSafeAreaInsets: () => ({ top: 24, bottom: 20 }), useWindowDimensions: () => ({ width: 390, height: 844 }), getMobileVisualWidth: x => x,
    useTravelTrips: () => ({ trips: [trip], profile: {}, status: "ready", refresh: noOp, syncFromGmail: noOp }),
    useDreams: () => ({ shareInstagramLink: noOp }), getInitialTab: () => "globe",
    buildPassportArchive: () => archive, buildPassportArrivals: () => [arrival], flightCountryKey: (_country, code) => code,
    readableDate: x => x, airlineName: x => x, BackHandler: { addEventListener: () => ({ remove: noOp }) },
    ...overrides,
  };
  const mod = { exports: {} };
  new Function("module", "exports", ...Object.keys(globals), compiled)(mod, mod.exports, ...Object.values(globals));
  host.setComponent(mod.exports[name]);
  return host;
}
function nodes(tree) {
  if (Array.isArray(tree)) return tree.flatMap(nodes);
  if (!tree || typeof tree !== "object") return [];
  return [tree, ...nodes(tree.props?.children)];
}
const find = (tree, type) => nodes(tree).find(n => n.type === type);
const button = (tree, label) => nodes(tree).find(n => n.type === "Pressable" && n.props.accessibilityLabel === label);
const appHost = overrides => load("App.tsx", "AppShell", overrides);
const passportHost = () => load("src/screens/PassportStatsScreen.tsx", "PassportStatsScreen");
const listHost = () => load("src/components/world-window/passport/PassportCollections.tsx", "CollectionList");

test("Home controls share one balanced row and preserve touch targets and texture toggle", () => {
  const host = load("src/screens/HomeGlobeScreen.tsx", "HomeGlobeScreen");
  let tree = host.render({ active: "globe", onChange: noOp });
  const year = button(tree, "Filter flights by year"), texture = button(tree, "Switch to NASA imagery");
  const row = nodes(tree).find(n => n.type === "View" && n.props.children.includes(year) && n.props.children.includes(texture));
  assert(row && find(row, "WWEmblem"), "Emblem and both controls have the same row parent");
  assert.equal(row.props.style.flexDirection, "row");
  assert.equal(row.props.style.alignItems, "center");
  assert(year.props.style({ pressed: false })[0].minHeight >= 44);
  assert(texture.props.style({ pressed: false })[0].height >= 44);
  texture.props.onPress();
  tree = host.render();
  assert.equal(find(tree, "WorldWindowGlobe").props.mapStyle, "nasa");
  assert(button(tree, "Switch to classic globe"));
});

test("Home statistic actions target flights, countries and airports separately", () => {
  const calls = [];
  const host = load("src/screens/HomeGlobeScreen.tsx", "HomeGlobeScreen");
  const tree = host.render({ active: "globe", onChange: tab => calls.push(tab), onOpenCollection: kind => calls.push(kind) });
  button(tree, "1 flights").props.onPress();
  button(tree, "1 countries").props.onPress();
  button(tree, "2 airports").props.onPress();
  assert.deepEqual(calls, ["trips", "countries", "airports"]);
});

for (const kind of ["countries", "airports"]) {
  test(`Home ${kind} opens that collection; close returns Home and preserves year`, () => {
    const host = appHost();
    let tree = host.render({ consumeShare: noOp });
    find(tree, "HomeGlobeScreen").props.onFilterYear("2026");
    tree = host.render();
    find(tree, "HomeGlobeScreen").props.onOpenCollection(kind);
    tree = host.render();
    const passport = find(tree, "PassportStatsScreen");
    assert.equal(passport.props.initialCollection, kind);
    assert.equal(passport.props.collectionBackLabel, "Globe");
    assert.equal(find(tree, "HomeGlobeScreen").props.active, "passport");
    passport.props.onCloseCollection();
    tree = host.render();
    assert.equal(find(tree, "HomeGlobeScreen").props.active, "globe");
    assert.equal(find(tree, "HomeGlobeScreen").props.filterYear, "2026");
    assert.equal(find(tree, "PassportStatsScreen"), undefined);
  });
}

test("Leaving a Home collection by tab or trip clears its pending return route", () => {
  const host = appHost();
  let tree = host.render({ consumeShare: noOp });
  find(tree, "HomeGlobeScreen").props.onOpenCollection("airports");
  tree = host.render();
  find(tree, "PassportStatsScreen").props.onChange("passport");
  tree = host.render();
  assert.equal(find(tree, "PassportStatsScreen").props.initialCollection, undefined);
  assert.equal(find(tree, "PassportStatsScreen").props.onCloseCollection, undefined);
  find(tree, "HomeGlobeScreen").props.onChange("globe");
  tree = host.render();
  find(tree, "HomeGlobeScreen").props.onOpenCollection("airports");
  tree = host.render();
  find(tree, "PassportStatsScreen").props.onOpenTrip(trip);
  tree = host.render();
  assert.equal(find(tree, "TripDetailScreen").props.trip.id, trip.id);
  find(tree, "TripDetailScreen").props.onBack();
  tree = host.render();
  assert(find(tree, "TripsListScreen"));
});

test("Airport hardware Back steps detail → airport list → Home", () => {
  let exits = 0;
  const passport = passportHost();
  let tree = passport.render({ active: "passport", onChange: noOp, initialCollection: "airports", collectionBackLabel: "Globe", onCloseCollection: () => exits++ });
  const list = listHost();
  let listTree = list.render(find(tree, "CollectionList").props);
  const airportRow = nodes(listTree).find(n => n.type === "Pressable" && n.props.onPress);
  airportRow.props.onPress();
  listTree = list.render();
  assert(find(listTree, "AirportRouteFan"));
  find(tree, "Modal").props.onRequestClose();
  listTree = list.render();
  assert.equal(find(listTree, "AirportRouteFan"), undefined);
  assert.equal(exits, 0);
  assert.equal(find(listTree, "CollectionHeading").props.backLabel, "Globe");
  find(tree, "Modal").props.onRequestClose();
  tree = passport.render();
  assert.equal(find(tree, "Modal").props.visible, false);
  assert.equal(exits, 1);
  list.unmount();
});

test("Country hardware Back steps trips → country → country list → Home", () => {
  let exits = 0;
  const passport = passportHost();
  let tree = passport.render({ active: "passport", onChange: noOp, initialCollection: "countries", onCloseCollection: () => exits++ });
  find(tree, "CollectionList").props.onSelectCountry(arrival);
  tree = passport.render();
  const detail = load("src/components/world-window/passport/PassportCollections.tsx", "CountryArrivalDetail");
  let detailTree = detail.render(find(tree, "CountryArrivalDetail").props);
  find(detailTree, "WWButton").props.onPress();
  detailTree = detail.render();
  assert(find(detailTree, "TripRows"));
  find(tree, "Modal").props.onRequestClose();
  detailTree = detail.render();
  assert.equal(find(detailTree, "TripRows"), undefined);
  assert.equal(exits, 0);
  find(tree, "Modal").props.onRequestClose();
  detail.unmount();
  tree = passport.render();
  assert.equal(find(tree, "CollectionList").props.kind, "countries");
  find(tree, "Modal").props.onRequestClose();
  assert.equal(exits, 1);
});

test("Normal Passport collection closes to Passport and unregisters detail handlers", () => {
  const passport = passportHost();
  let tree = passport.render({ active: "passport", onChange: noOp });
  find(tree, "CollectionButtons").props.onOpen("airports");
  tree = passport.render();
  const list = listHost();
  list.render(find(tree, "CollectionList").props);
  list.unmount();
  find(tree, "Modal").props.onRequestClose();
  tree = passport.render();
  assert.equal(find(tree, "Modal").props.visible, false);
  assert(find(tree, "PassportBook"));
});
