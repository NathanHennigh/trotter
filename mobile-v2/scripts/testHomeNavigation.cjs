// Execute the current screen functions with an offline hook host: no native
// renderer, device, API, or duplicated navigation reducer is involved.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const ts = require("typescript");
const { test } = require("node:test");

const modules = new Map();
function pure(file) {
  const absolute = path.resolve(__dirname, "..", file);
  if (modules.has(absolute)) return modules.get(absolute);
  // Carrier branding is outside navigation; all catalog/progress/filter logic remains production code.
  if (absolute.endsWith(path.join("world-window", "AirlineLogo.tsx"))) return { airlineName: code => code };
  if (absolute.endsWith(".json")) return JSON.parse(fs.readFileSync(absolute, "utf8"));
  const source = fs.readFileSync(absolute, "utf8");
  const code = ts.transpileModule(source, {compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,esModuleInterop:true}}).outputText;
  const mod = { exports: {} }; modules.set(absolute, mod.exports);
  const resolve = ref => {
    const base=path.resolve(path.dirname(absolute), ref);
    const found=[base,base+".ts",base+".tsx",base+".json"].find(p=>fs.existsSync(p)&&fs.statSync(p).isFile());
    if (!found) throw Error("Missing pure module: "+ref);
    return pure(path.relative(path.resolve(__dirname,".."),found));
  };
  new Function("require","module","exports",code)(resolve,mod,mod.exports);
  modules.set(absolute,mod.exports); return mod.exports;
}

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
  id: "trip-one", backendId: 1, title: "Singapore", country: "Singapore", startDate:"2026-01-02", endDate:"2026-01-03", airportCode:"SIN", stamp:{icon:"singapore_marina_bay_sands",date:"2026-01-03"},
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
  const styles = ast.statements.find(n => ts.isVariableStatement(n) && n.declarationList.declarations.some(d => ["styles", "s"].includes(d.name.getText(ast))));
  const blurCapability = ast.statements.find(n => ts.isVariableStatement(n) && n.declarationList.declarations.some(d => d.name.getText(ast) === "supportsBackgroundBlur"));
  const text = declaration.getText(ast);
  const compiled = ts.transpileModule(`${blurCapability?.getText(ast) ?? ""}\n${text.startsWith("export") ? text : "export " + text}\n${styles?.getText(ast) ?? ""}`, {
    compilerOptions: { jsx: ts.JsxEmit.React, module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const tags = "View Text Pressable FlatList BoardingPass TripAtlas WalletHeading WWEmpty ScrollView Modal RefreshControl ActivityIndicator BottomNav WWHeader WWButton WWEmblem WWIcon WorldWindowGlobe PassportBook ActivityChart CollectionButtons CollectionScope CollectionList TransportCollectionIndex AirportLuggageLabel CountryArrivalDetail CountryIndex CollectionHeading CollectionTitle CollectionBack CroppedPassportStamp TripRows AirlineLogo AirportRouteFan HomeGlobeScreen PassportStatsScreen CountryStampCollectionScreen TripDetailScreen TripsListScreen DreamsScreen ProfileScreen PaperReveal PaperPresence TripNavigationSurface".split(" ");
  const globals = {
    ...Object.fromEntries(tags.map(tag => [tag, tag])),
    React: host.React, useState: host.React.useState, useMemo: host.React.useMemo, useEffect: host.React.useEffect, useRef: host.React.useRef,
    StyleSheet: { create: x => x, absoluteFillObject: {}, absoluteFill: {} },
    PressFeedback: "Pressable", useReducedMotion: () => false, selectionHaptic: noOp,
    useExperiencePreferences: () => { const [texture, setTexture] = host.React.useState("classic"); return { texture, setTexture, haptics: true, setHaptics: noOp }; },
    ...pure("src/utils/travelScope.ts"), ...pure("src/components/world-window/routeSelection.ts"),
    ...pure("src/components/world-window/displayTextFit.ts"),
    ...pure("src/data/collections/catalogs.ts"), ...pure("src/components/world-window/collections/catalogProgress.ts"),
    ...pure("src/components/world-window/collections/transportCollectionModel.ts"),
    scopedPassportArchive: () => archive,
    passportScope: () => ({ arrivals: archive.arrivals, lifetimeArrivals: archive.arrivals, trips: [trip], scopedTrips: [trip] }),
    ...pure("src/components/world-window/trips/tripPresentation.ts"), walletColors: {}, Platform: { OS: "android", Version: 35 }, colors: {}, fonts: {}, layout: { bottomNavHeight: 62 },
    useSafeAreaInsets: () => ({ top: 24, bottom: 20 }), useWindowDimensions: () => ({ width: 390, height: 844 }), getMobileVisualWidth: x => x,
    useTravelTrips: () => ({ trips: [trip], profile: {}, status: "ready", refresh: noOp, syncFromGmail: noOp }),
    useDreams: () => ({ shareInstagramLink: noOp }), getInitialTab: () => "globe",
    buildGlobeHistory: pure("src/components/world-window/globe-history.ts").buildGlobeHistory, flightDate: pure("src/components/world-window/trips/tripPresentation.ts").flightDate, tripsForCountry: () => [trip], buildPassportArchive: () => archive, buildPassportArrivals: () => [arrival], flightCountryKey: (_country, code) => code,
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
  return [tree, ...nodes(tree.props?.children), ...nodes(tree.props?.header), ...nodes(tree.props?.ListHeaderComponent), ...nodes(tree.props?.ListEmptyComponent)];
}
const find = (tree, type) => nodes(tree).find(n => n.type === type);
const button = (tree, label) => nodes(tree).find(n => n.type === "Pressable" && n.props.accessibilityLabel === label);
const appHost = overrides => load("App.tsx", "AppShell", overrides);
const passportHost = () => load("src/screens/PassportStatsScreen.tsx", "PassportStatsScreen");
const countriesHost = () => load("src/screens/CountryStampCollectionScreen.tsx", "CountryStampCollectionScreen");
const listHost = () => load("src/components/world-window/passport/PassportCollections.tsx", "CollectionList");
const finishTripTransition = host => { let tree = host.render(); const surface = find(tree, "TripNavigationSurface"); assert(surface?.props.closing); surface.props.onClosed(); return host.render(); };

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

test("Home year reaches Flights and clearing it does not silently change the globe year", () => {
  const host = appHost(); let tree = host.render({ consumeShare: noOp });
  find(tree, "HomeGlobeScreen").props.onFilterYear("2026"); tree = host.render();
  find(tree, "HomeGlobeScreen").props.onOpenFlights("2026"); tree = host.render();
  assert.equal(find(tree, "TripsListScreen").props.initialYear, "2026");
  const epoch = find(tree, "TripsListScreen").props.scopeEpoch;
  find(tree, "TripsListScreen").props.onClearYear(); tree = host.render();
  assert.equal(find(tree, "TripsListScreen").props.initialYear, undefined);
  assert(find(tree, "TripsListScreen").props.scopeEpoch > epoch);
  assert.equal(find(tree, "HomeGlobeScreen").props.filterYear, "2026");
});

test("Profile airport goes directly to its airport history and Back returns Profile", () => {
  const host = appHost(); let tree = host.render({ consumeShare: noOp });
  find(tree, "HomeGlobeScreen").props.onChange("profile"); tree = host.render();
  find(tree, "ProfileScreen").props.onOpenAirport("DFW"); tree = host.render();
  const collection = find(tree, "PassportStatsScreen");
  assert.equal(collection.props.initialCollection, "airports"); assert.equal(collection.props.initialAirport, "DFW");
  assert.equal(collection.props.collectionBackLabel, "Profile");
  collection.props.onCloseCollection(); tree = host.render(); assert.equal(find(tree, "ProfileScreen").props.active, "profile");
});

test("Direct airport from Globe delegates Back to Globe and retains the chosen year", () => {
  const app = appHost(); let tree = app.render({ consumeShare: noOp });
  find(tree, "HomeGlobeScreen").props.onFilterYear("2026"); tree = app.render();
  find(tree, "HomeGlobeScreen").props.onOpenCollection("airports", "2026", "SIN"); tree = app.render();
  const passport = passportHost(), list = listHost();
  const book = passport.render(find(tree, "PassportStatsScreen").props);
  const detail = list.render(find(book, "CollectionList").props);
  assert(find(detail, "AirportRouteFan"));
  assert.equal(find(detail, "CollectionTitle").props.backLabel, "Globe");
  assert.equal(find(detail, "TransportCollectionIndex").props.year, "2026");
  find(detail, "CollectionTitle").props.onBack(); tree = app.render();
  assert.equal(find(tree, "HomeGlobeScreen").props.active, "globe");
  assert.equal(find(tree, "HomeGlobeScreen").props.filterYear, "2026");
  list.unmount(); passport.unmount(); app.unmount();
});

test("a delayed wallet measurement cannot reopen Trips after changing tabs", () => {
  const host = appHost(); let tree = host.render({ consumeShare: noOp });
  find(tree, 'HomeGlobeScreen').props.onChange('trips'); tree = host.render();
  const delayedOpen = find(tree, 'TripsListScreen').props.onOpenTrip;
  find(tree, 'TripsListScreen').props.onChange('profile'); tree = host.render();
  delayedOpen(trip, undefined, { x: 20, y: 180, width: 350, height: 260 }); tree = host.render();
  assert.equal(find(tree, 'TripDetailScreen'), undefined); assert.equal(find(tree, 'ProfileScreen').props.active, 'profile');
});

for (const kind of ["countries", "airports"]) {
  test(`Home ${kind} opens that collection; close returns Home and preserves year`, () => {
    const host = appHost();
    let tree = host.render({ consumeShare: noOp });
    find(tree, "HomeGlobeScreen").props.onFilterYear("2026");
    tree = host.render();
    find(tree, "HomeGlobeScreen").props.onOpenCollection(kind, "2026");
    tree = host.render();
    const passport = find(tree, "PassportStatsScreen");
    const collection = kind === "countries" ? find(tree, "CountryStampCollectionScreen") : passport;
    assert.equal(passport.props.initialCollection, kind === "countries" ? undefined : kind);
    assert.equal(collection.props.initialYear, "2026");
    assert.equal(kind === "countries" ? collection.props.backLabel : collection.props.collectionBackLabel, "Globe");
    assert.equal(collection.props.visible, true);
    assert.equal(find(tree, "HomeGlobeScreen").props.active, "passport");
    (kind === "countries" ? collection.props.onBack : collection.props.onCloseCollection)();
    tree = host.render();
    assert.equal(find(tree, "HomeGlobeScreen").props.active, "globe");
    assert.equal(find(tree, "HomeGlobeScreen").props.filterYear, "2026");
    assert.equal(find(tree, "PassportStatsScreen").props.visible, false);
    assert.equal(find(tree, "CountryStampCollectionScreen"), undefined);
  });
}

test("Home Countries and Passport Countries share the new catalog, retaining scoped and lifetime arrivals", () => {
  const host = appHost(); let tree = host.render({ consumeShare: noOp });
  find(tree, "HomeGlobeScreen").props.onFilterYear("2026"); tree = host.render();
  find(tree, "HomeGlobeScreen").props.onOpenCollection("countries", "2026"); tree = host.render();
  const collection = countriesHost();
  let countryTree = collection.render(find(tree, "CountryStampCollectionScreen").props);
  const homeIndex = find(countryTree, "CountryIndex");
  assert(homeIndex, "Home reaches the same country catalog component as Passport");
  assert.equal(homeIndex.props.year, "2026");
  assert.deepEqual(homeIndex.props.arrivals, [arrival]);
  assert.deepEqual(homeIndex.props.lifetimeArrivals, [arrival]);
  assert.equal(find(tree, "PassportStatsScreen").props.visible, false, "Legacy passport collection stays hidden");
  homeIndex.props.onClearYear(); tree = host.render();
  countryTree = collection.render(find(tree, "CountryStampCollectionScreen").props);
  assert.equal(find(countryTree, "CountryIndex").props.year, undefined);
  assert.equal(find(tree, "HomeGlobeScreen").props.filterYear, "2026", "Catalog scope changes do not change the globe");
  find(countryTree, "CountryIndex").props.onBack(); tree = host.render();
  find(tree, "HomeGlobeScreen").props.onChange("passport"); tree = host.render();
  find(tree, "PassportStatsScreen").props.onOpenCountries(); tree = host.render();
  assert.equal(find(tree, "CountryStampCollectionScreen").props.backLabel, "Passport");
  assert.equal(find(tree, "CountryStampCollectionScreen").props.initialYear, undefined);
  collection.unmount(); host.unmount();
});

test("Explicit tab navigation clears a collection; a trip detail preserves its return route", () => {
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
  tree = finishTripTransition(host);
  assert.equal(find(tree, "PassportStatsScreen").props.visible, true);
  assert.equal(find(tree, "PassportStatsScreen").props.initialCollection, "airports");
});

test("Airport hardware Back steps detail → airport list → Home", () => {
  let exits = 0, back;
  const passport = passportHost();
  let tree = passport.render({ active: "passport", onChange: noOp, initialCollection: "airports", collectionBackLabel: "Globe", onCloseCollection: () => exits++, onBackHandlerChange: handler => back = handler });
  const list = listHost();
  let listTree = list.render(find(tree, "CollectionList").props);
  const index = load("src/components/world-window/collections/TransportCollectionIndex.tsx", "TransportCollectionIndex");
  const indexTree = index.render(find(listTree, "TransportCollectionIndex").props);
  const airportList = find(indexTree, "FlatList");
  const selected = airportList.props.data.find(entry => entry.key === "SIN");
  assert(selected?.record, "Visited index receives the recorded airport");
  find(airportList.props.renderItem({ item: selected }), "Pressable").props.onPress();
  listTree = list.render();
  assert(find(listTree, "AirportRouteFan"));
  back();
  listTree = list.render();
  assert.equal(find(listTree, "AirportRouteFan"), undefined);
  assert.equal(exits, 0);
  assert.equal(find(listTree, "CollectionHeading").props.backLabel, "Globe");
  back();
  tree = passport.render();
  assert.equal(find(tree, "CollectionList"), undefined);
  assert.equal(exits, 1);
  index.unmount(); list.unmount();
});

test("Country journeys are inline; hardware Back steps country → country list → Home", () => {
  let back;
  const app = appHost({BackHandler:{addEventListener:(_event,fn)=>{back=fn;return {remove:noOp}}}});
  let appTree = app.render({ consumeShare: noOp });
  find(appTree, "HomeGlobeScreen").props.onFilterYear("2026"); appTree = app.render();
  find(appTree, "HomeGlobeScreen").props.onOpenCollection("countries", "2026"); appTree = app.render();
  const countries = countriesHost();
  let tree = countries.render(find(appTree, "CountryStampCollectionScreen").props);
  find(tree, "CountryIndex").props.setQuery("Singapore");
  find(tree, "CountryIndex").props.onSelect(arrival);
  tree = countries.render();
  const detail = load("src/components/world-window/passport/PassportCollections.tsx", "CountryArrivalDetail");
  let detailTree = detail.render(find(tree, "CountryArrivalDetail").props);
  assert(find(detailTree, "TripRows"));
  assert.equal(find(detailTree, "WWButton"), undefined, "No redundant View trips navigation step");
  assert.equal(back(), true);
  detail.unmount();
  tree = countries.render();
  assert.equal(find(tree, "CountryArrivalDetail"), undefined);
  assert.equal(find(tree, "CountryIndex").props.query, "Singapore");
  assert.equal(find(tree, "CountryIndex").props.year, "2026");
  assert.equal(back(), true); appTree = app.render();
  assert.equal(find(appTree, "CountryStampCollectionScreen"), undefined);
  assert.equal(find(appTree, "HomeGlobeScreen").props.active, "globe");
  assert.equal(find(appTree, "HomeGlobeScreen").props.filterYear, "2026");
  countries.unmount(); app.unmount();
});

test("Normal Passport collection closes to Passport and unregisters detail handlers", () => {
  let back;
  const passport = passportHost();
  let tree = passport.render({ active: "passport", onChange: noOp, onBackHandlerChange: handler => back = handler });
  find(tree, "CollectionButtons").props.onOpen("airports");
  tree = passport.render();
  const list = listHost();
  list.render(find(tree, "CollectionList").props);
  list.unmount();
  back();
  tree = passport.render();
  assert.equal(find(tree, "CollectionList"), undefined);
  assert(find(tree, "PassportBook"));
});


test("Hidden tab layers cannot receive touches or appear in either accessibility tree", () => {
  const host=appHost(); let tree=host.render({consumeShare:noOp});
  find(tree,"HomeGlobeScreen").props.onChange("trips"); tree=host.render();
  const list=find(tree,"TripsListScreen"); list.props.onOpenTrip(trip); tree=host.render();
  assert(find(tree,"TripsListScreen"),"Trip list stays mounted beneath detail");
  const layers=tree.props.children.flat(Infinity).filter(n=>n&&n.type==="View");
  assert.equal(layers.filter(n=>n.props.pointerEvents==="auto").length,0, "Only the separate itinerary surface accepts input");
  assert(find(tree, "TripNavigationSurface"));
  for(const layer of layers.filter(n=>n.props.pointerEvents==="none")){
    assert.equal(layer.props.accessibilityElementsHidden,true);
    assert.equal(layer.props.importantForAccessibility,"no-hide-descendants");
    assert.equal(layer.props["aria-hidden"],true);
  }
  find(tree,"TripDetailScreen").props.onBack(); tree=finishTripTransition(host);
  assert.equal(find(tree,"TripsListScreen").props.active,"trips");
});

test("App hardware Back returns to the collection before delegating its nested Back", () => {
  let back, childCalls=0;
  const host=appHost({BackHandler:{addEventListener:(_event,fn)=>{back=fn;return {remove:noOp}}}});
  let tree=host.render({consumeShare:noOp});
  find(tree,"HomeGlobeScreen").props.onOpenCollection("countries"); tree=host.render();
  find(tree,"CountryStampCollectionScreen").props.onBackHandlerChange(()=>{childCalls++;return true});
  find(tree,"CountryStampCollectionScreen").props.onOpenTrip(trip); tree=host.render();
  assert.equal(back(),true); tree=host.render(); assert.equal(childCalls,0);
  tree=finishTripTransition(host);
  assert.equal(find(tree,"CountryStampCollectionScreen").props.visible,true);
  assert.equal(back(),true); assert.equal(childCalls,1);
});


test("Detail follows fresh provider flights while an older detail response is still held", async () => {
  let finish;
  const oldTrip={...trip,startDate:'2026-01-02',endDate:'2026-01-03'};
  let current=oldTrip;
  const response=new Promise(resolve=>finish=resolve);
  const detail=load("src/screens/TripDetailScreen.tsx","TripDetailScreen",{useTravelTrips:()=>({trips:[current],loadTripDetail:()=>response})});
  let tree=detail.render({trip:oldTrip,active:'trips',onBack:noOp,onChange:noOp});
  finish(oldTrip); await response; await Promise.resolve(); tree=detail.render();
  current={...oldTrip,segments:[...oldTrip.segments,{...oldTrip.segments[0],id:'return',depAirport:'SIN',arrAirport:'LHR',depTime:'2026-01-09T10:00:00'}]};
  tree=detail.render();
  assert.deepEqual(find(tree,'FlatList').props.data.map(f=>f.id),['flight-one','return']);
  detail.unmount();
});

test("Removing a selected trip in a newer archive returns to its origin without a stale detail", () => {
  let records=[trip];
  const host=appHost({useTravelTrips:()=>({trips:records})}); let tree=host.render({consumeShare:noOp});
  find(tree,'HomeGlobeScreen').props.onOpenTrip(trip); tree=host.render(); assert(find(tree,'TripDetailScreen'));
  records=[]; tree=host.render(); assert.equal(find(tree,'TripDetailScreen'),undefined);
  assert.equal(find(tree,'HomeGlobeScreen').props.active,'globe');
});


test("Explicit navigation from a trip clears its retained passport overlay; ordinary Back preserves it", () => {
  const host=appHost(); let tree=host.render({consumeShare:noOp});
  find(tree,'HomeGlobeScreen').props.onChange('passport'); tree=host.render();
  const passport=passportHost(); let book=passport.render(find(tree,'PassportStatsScreen').props);
  find(book,'CollectionButtons').props.onOpen('airports'); book=passport.render();
  find(book,'CollectionList').props.onOpenTrip(trip); tree=host.render();
  book=passport.render(find(tree,'PassportStatsScreen').props); assert(find(book,'CollectionList'));
  find(tree,'TripDetailScreen').props.onBack(); tree=finishTripTransition(host);
  book=passport.render(find(tree,'PassportStatsScreen').props); assert(find(book,'CollectionList'));
  find(book,'CollectionList').props.onOpenTrip(trip); tree=host.render();
  find(tree,'TripDetailScreen').props.onChange('profile'); tree=host.render();
  book=passport.render(find(tree,'PassportStatsScreen').props); assert.equal(find(book,'CollectionList'),undefined);
});

const flattenStyle = value => Array.isArray(value) ? Object.assign({}, ...value.map(flattenStyle)) : value || {};
const screenLayers = tree => nodes(tree).filter(n => /^screen-layer-/.test(n.props?.testID ?? ""));

test("Native screen boundaries stay stable through tab hiding, blur entry and close", () => {
  const host = appHost(); let tree = host.render({ consumeShare: noOp });
  const boundaries = new Map();
  const checkBoundaries = () => {
    for (const layer of screenLayers(tree)) {
      assert.equal(layer.props.collapsable, false, "Fabric must retain the same native stacking boundary before opacity/pointerEvents/filter change");
      const signature = { type: layer.type, key: layer.props.key, childType: layer.props.children[0]?.type };
      if (boundaries.has(layer.props.testID)) assert.deepEqual(signature, boundaries.get(layer.props.testID), "A retained screen cannot move into a replacement native wrapper");
      else boundaries.set(layer.props.testID, signature);
    }
    assert(screenLayers(tree).some(layer => layer.props.testID === "screen-layer-globe"), "Globe boundary remains mounted on every tab");
  };
  checkBoundaries();
  for (const tab of ["trips", "passport", "dreams", "profile", "globe"]) {
    find(tree, "HomeGlobeScreen").props.onChange(tab); tree = host.render(); checkBoundaries();
    const globe = screenLayers(tree).find(layer => layer.props.testID === "screen-layer-globe");
    assert.equal(globe.props.pointerEvents, tab === "globe" ? "auto" : "none");
    assert.equal(flattenStyle(globe.props.style).opacity, tab === "globe" ? undefined : 0);
  }
  find(tree, "HomeGlobeScreen").props.onOpenTrip(trip); tree = host.render(); checkBoundaries();
  assert.equal(flattenStyle(screenLayers(tree).find(layer => layer.props.testID === "screen-layer-globe").props.style).filter, "blur(4px)");
  find(tree, "TripNavigationSurface").props.onEntered(); tree = host.render(); checkBoundaries();
  find(tree, "TripNavigationSurface").props.onRequestClose(); tree = host.render(); checkBoundaries();
  tree = finishTripTransition(host); checkBoundaries();
  const globe = screenLayers(tree).find(layer => layer.props.testID === "screen-layer-globe");
  assert.equal(globe.props.pointerEvents, "auto"); assert.equal(flattenStyle(globe.props.style).filter, undefined);
  host.unmount();
});

for (const platform of [{ OS: "android", Version: 31 }, { OS: "android", Version: 35 }, { OS: "android", Version: 30 }, { OS: "ios", Version: "18.0" }, { OS: "web" }]) {
  test(`Background blur capability and crisp modal separation: ${platform.OS} ${platform.Version ?? ""}`, () => {
    const host = appHost({ Platform: platform });
    let tree = host.render({ consumeShare: noOp });
    assert(screenLayers(tree).every(layer => !flattenStyle(layer.props.style).filter), "No blur without a modal");
    find(tree, "HomeGlobeScreen").props.onChange("profile"); tree = host.render();
    find(tree, "ProfileScreen").props.onChange("globe"); tree = host.render();
    find(tree, "HomeGlobeScreen").props.onOpenTrip(trip, "flight-one"); tree = host.render();
    const layers = screenLayers(tree), filtered = layers.filter(layer => flattenStyle(layer.props.style).filter);
    assert(layers.every(layer => layer.props.collapsable === false), "Platform fallback must not change native screen boundaries");
    const supported = platform.OS === "web" || platform.OS === "android" && platform.Version >= 31;
    assert.deepEqual(filtered.map(layer => layer.props.testID), supported ? ["screen-layer-globe"] : []);
    if (supported) assert.equal(flattenStyle(filtered[0].props.style).filter, "blur(4px)");
    assert(layers.every(layer => !find(layer, "TripNavigationSurface")), "The wallet is not a descendant of a filtered source layer");
    assert(tree.props.children.flat(Infinity).includes(find(tree, "TripNavigationSurface")), "Modal remains a direct sibling of source screens");
    assert.equal(flattenStyle(tree.props.style).filter, undefined, "Shell never blurs the entire app");
    assert.equal(find(tree, "TripDetailScreen").props.selectedFlightId, "flight-one", "Route focus survives opening");
    assert(layers.every(layer => layer.props.pointerEvents === "none"), "Blurred and retained backgrounds cannot intercept input");
    assert.equal(find(tree, "HomeGlobeScreen").props.visible, false, "Covered globe is explicitly suspended");
    host.unmount();
  });
}

for (const origin of ["globe", "trips", "countries", "airports"]) {
  test(`Blur persists throughout close and restores ${origin} origin and scope`, () => {
    const host = appHost(); let tree = host.render({ consumeShare: noOp });
    find(tree, "HomeGlobeScreen").props.onFilterYear("2026"); tree = host.render();
    if (origin === "trips") {
      find(tree, "HomeGlobeScreen").props.onOpenFlights("2026"); tree = host.render();
      find(tree, "TripsListScreen").props.onOpenTrip(trip);
    } else if (origin === "countries" || origin === "airports") {
      find(tree, "HomeGlobeScreen").props.onOpenCollection(origin, "2026"); tree = host.render();
      find(tree, origin === "countries" ? "CountryStampCollectionScreen" : "PassportStatsScreen").props.onOpenTrip(trip);
    } else find(tree, "HomeGlobeScreen").props.onOpenTrip(trip);
    tree = host.render();
    const source = origin === "airports" ? "passport" : origin;
    const blurredKeys = () => screenLayers(tree).filter(layer => flattenStyle(layer.props.style).filter).map(layer => layer.props.testID);
    assert.deepEqual(blurredKeys(), [`screen-layer-${source}`]);
    assert.equal(find(tree, "TripDetailScreen").props.deferUpdates, true, "Hydration waits while opening");
    find(tree, "TripNavigationSurface").props.onEntered(); tree = host.render();
    assert.equal(find(tree, "TripDetailScreen").props.deferUpdates, false, "Hydration resumes only after entry completes");
    find(tree, "TripNavigationSurface").props.onRequestClose(); tree = host.render();
    assert.equal(find(tree, "TripNavigationSurface").props.closing, true);
    assert.equal(find(tree, "TripDetailScreen").props.deferUpdates, true, "Closing freezes detail presentation again");
    assert.deepEqual(blurredKeys(), [`screen-layer-${source}`], "Close request does not snap the background sharp");
    assert.equal(find(tree, "HomeGlobeScreen").props.visible, false);
    tree = finishTripTransition(host);
    assert.equal(find(tree, "TripNavigationSurface"), undefined);
    assert.deepEqual(blurredKeys(), [], "Blur clears when the wallet has actually left");
    assert.equal(find(tree, "HomeGlobeScreen").props.filterYear, "2026");
    if (origin === "countries") assert.equal(find(tree, "CountryStampCollectionScreen").props.initialYear, "2026");
    if (origin === "airports") assert.equal(find(tree, "PassportStatsScreen").props.initialCollection, "airports");
    if (origin === "trips") assert.equal(find(tree, "TripsListScreen").props.initialYear, "2026");
    assert.equal(find(tree, "HomeGlobeScreen").props.visible, origin === "globe");
    host.unmount();
  });
}

test("Closing during entry never releases deferred updates; a later open gets a fresh entry gate", () => {
  const host = appHost(); let tree = host.render({ consumeShare: noOp });
  find(tree, "HomeGlobeScreen").props.onOpenTrip(trip); tree = host.render();
  find(tree, "TripDetailScreen").props.onBack(); tree = host.render();
  assert.equal(find(tree, "TripDetailScreen").props.deferUpdates, true);
  // Even an already queued completion cannot unlock presentation while closing.
  find(tree, "TripNavigationSurface").props.onEntered(); tree = host.render();
  assert.equal(find(tree, "TripDetailScreen").props.deferUpdates, true);
  tree = finishTripTransition(host);
  find(tree, "HomeGlobeScreen").props.onOpenTrip(trip); tree = host.render();
  assert.equal(find(tree, "TripDetailScreen").props.deferUpdates, true, "Previous trip's settled state is reset");
  find(tree, "TripNavigationSurface").props.onEntered(); tree = host.render();
  assert.equal(find(tree, "TripDetailScreen").props.deferUpdates, false);
  host.unmount();
});

test("Home globe rendering respects explicit overlay visibility without forgetting the texture or year", () => {
  const host = load("src/screens/HomeGlobeScreen.tsx", "HomeGlobeScreen");
  const props = { active: "globe", visible: true, filterYear: "2026", onChange: noOp };
  let tree = host.render(props);
  assert.equal(find(tree, "WorldWindowGlobe").props.active, true);
  button(tree, "Switch to NASA imagery").props.onPress(); tree = host.render();
  tree = host.render({ ...props, visible: false });
  assert.equal(find(tree, "WorldWindowGlobe").props.active, false);
  assert.equal(find(tree, "WorldWindowGlobe").props.mapStyle, "nasa");
  tree = host.render(props);
  assert.equal(find(tree, "WorldWindowGlobe").props.active, true);
  assert.equal(find(tree, "WorldWindowGlobe").props.mapStyle, "nasa");
  tree = host.render({ ...props, active: "trips", visible: true });
  assert.equal(find(tree, "WorldWindowGlobe").props.active, false, "Visibility cannot activate an inactive tab");
  host.unmount();
});
