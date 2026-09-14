// Execute production screen/gesture logic with native services mocked. No API or GL.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { test } = require("node:test");
const ts = require("typescript");
const root = path.resolve(__dirname, "..");
process.env.TZ = "America/Chicago";

function environment(trips = []) {
  const slots = [],
    refs = [],
    modules = new Map(),
    announcements = [];
  let cursor = 0,
    effects = [],
    dirty = false,
    currentTrips = trips;
  const same = (a, b) =>
    a && b && a.length === b.length && a.every((v, i) => Object.is(v, b[i]));
  const React = {
    createElement: (type, props, ...children) => ({
      type,
      props: props ?? {},
      children,
    }),
    useState(value) {
      const i = cursor++;
      if (!slots[i])
        slots[i] = { value: typeof value === "function" ? value() : value };
      return [
        slots[i].value,
        (next) => {
          next = typeof next === "function" ? next(slots[i].value) : next;
          if (!Object.is(next, slots[i].value)) {
            slots[i].value = next;
            dirty = true;
          }
        },
      ];
    },
    useRef(value) {
      const i = cursor++;
      if (!slots[i]) {
        slots[i] = { current: value };
        refs.push(slots[i]);
      }
      return slots[i];
    },
    useMemo(fn, deps) {
      const i = cursor++;
      if (!slots[i] || !same(slots[i].deps, deps))
        slots[i] = { deps, value: fn() };
      return slots[i].value;
    },
    useCallback(fn, deps) {
      return React.useMemo(() => fn, deps);
    },
    useEffect(fn, deps) {
      const i = cursor++;
      if (!slots[i] || !same(slots[i].deps, deps))
        effects.push(() => {
          slots[i]?.cleanup?.();
          slots[i] = { deps, cleanup: fn() };
        });
    },
  };
  const RN = {
    Platform: { OS: "android" },
    useWindowDimensions: () => ({ width: 390, height: 844, fontScale: 1 }),
    StyleSheet: { create: (x) => x, absoluteFill: {} },
    PanResponder: { create: (panHandlers) => ({ panHandlers }) },
    AppState: {
      currentState: "active",
      addEventListener: () => ({ remove() {} }),
    },
    AccessibilityInfo: {
      isReduceMotionEnabled: async () => false,
      addEventListener: () => ({ remove() {} }),
      announceForAccessibility: (value) => announcements.push(value),
    },
  };
  for (const name of [
    "View",
    "Text",
    "Pressable",
    "ScrollView",
    "Modal",
    "ActivityIndicator",
  ])
    RN[name] = name;
  function load(file) {
    file = path.resolve(file);
    if (modules.has(file)) return modules.get(file);
    if (/\.(png|jpg|webp)$/.test(file)) return 1;
    if (file.endsWith(".json"))
      return JSON.parse(fs.readFileSync(file, "utf8"));
    const mod = { exports: {} };
    modules.set(file, mod.exports);
    const requireLocal = (name) => {
      if (name === "react") return React;
      if (name === "react-native") return RN;
      if (name === "three") return require("three");
      if (name === "expo-gl") return { GLView: "GLView" };
      if (name === "react-native-safe-area-context")
        return { useSafeAreaInsets: () => ({ top: 24, bottom: 20 }) };
      if (name.endsWith("expoThree")) return {};
      if (name.endsWith("/motion")) return { PressFeedback: "Pressable", PaperReveal: "View", PaperPresence: "View", useReducedMotion: () => false };
      if (name.endsWith("/experiencePreferences")) return {
        useExperiencePreferences: () => {
          const [texture, setTexture] = React.useState("classic");
          return { texture, setTexture, haptics: false, setHaptics() {} };
        },
        selectionHaptic() {},
      };
      if (name.endsWith("/travelTrips"))
        return {
          useTravelTrips: () => ({
            trips: currentTrips,
            status: "ready",
            syncFromGmail() {},
          }),
        };
      if (name.endsWith("/WorldWindowUI"))
        return { WWIcon: "WWIcon", WWEmblem: "WWEmblem", WWButton: "WWButton" };
      if (name.endsWith("/TrotterKit")) return { BottomNav: "BottomNav" };
      if (name.startsWith(".")) {
        const base = path.resolve(path.dirname(file), name);
        const found = ["", ".ts", ".tsx", ".json"]
          .map((ext) => base + ext)
          .find(
            (candidate) =>
              fs.existsSync(candidate) && fs.statSync(candidate).isFile(),
          );
        if (found) return load(found);
      }
      throw Error(`Unmocked dependency ${name} in ${file}`);
    };
    const source = ts.transpileModule(fs.readFileSync(file, "utf8"), {
      compilerOptions: {
        jsx: ts.JsxEmit.React,
        module: ts.ModuleKind.CommonJS,
        target: ts.ScriptTarget.ES2022,
        esModuleInterop: true,
      },
    }).outputText;
    new Function("module", "exports", "require", source)(
      mod,
      mod.exports,
      requireLocal,
    );
    modules.set(file, mod.exports);
    return mod.exports;
  }
  return {
    load,
    refs,
    announcements,
    setTrips(next) {
      currentTrips = next;
    },
    render(fn) {
      for (let i = 0; i < 10; i++) {
        cursor = 0;
        effects = [];
        dirty = false;
        const tree = fn();
        effects.forEach((fn) => fn());
        if (!dirty) return tree;
      }
      throw Error("Effects did not settle");
    },
  };
}
function nodes(tree) {
  return !tree || typeof tree !== "object"
    ? []
    : Array.isArray(tree)
      ? tree.flatMap(nodes)
      : [tree, ...tree.children.flatMap(nodes)];
}
function texts(tree) {
  return typeof tree === "string" || typeof tree === "number"
    ? [tree]
    : !tree || typeof tree !== "object"
      ? []
      : Array.isArray(tree)
        ? tree.flatMap(texts)
        : tree.children.flatMap(texts);
}
const point = (code, country, countryCode, lat, lon) => ({
  code,
  city: code,
  country,
  countryCode,
  lat,
  lon,
});
const DFW = point("DFW", "United States", "US", 32.9, -97),
  NRT = point("NRT", "Japan", "JP", 35.7, 140.3),
  SIN = point("SIN", "Singapore", "SG", 1.35, 104);
const leg = (id, from, to, depTime, arrTime) => ({
  id,
  mode: "flight",
  depAirport: from.code,
  arrAirport: to.code,
  depPoint: from,
  arrPoint: to,
  depTime,
  arrTime,
});
const crossYear = {
  id: "synthetic",
  country: "Singapore",
  countryCode: "SG",
  airportCode: "SIN",
  title: "Singapore",
  startDate: "2025-12-30",
  endDate: "2026-01-09",
  firstCountryEntryAirport: "SIN",
  firstCountryEntryDate: "2026-01-02",
  stamp: { country: "Singapore", airportCode: "SIN", date: "2026-01-02" },
  segments: [
    leg("first", DFW, NRT, "2025-12-30T10:00:00Z", "2025-12-31T14:00:00Z"),
    leg("second", NRT, SIN, "2026-01-02T08:00:00Z", "2026-01-02T15:00:00Z"),
  ],
};

test("year filtering cannot import another year primary destination; connections remain counted", () => {
  const env = environment(),
    { buildGlobeHistory } = env.load(
      path.join(root, "src/components/world-window/globe-history.ts"),
    );
  const first = buildGlobeHistory([crossYear], "2025"),
    second = buildGlobeHistory([crossYear], "2026");
  assert.deepEqual(first.visited, ["JP"]);
  assert.deepEqual(
    first.routes.map((r) => r.id),
    ["first"],
  );
  assert.deepEqual(second.visited, ["SG"]);
  assert.equal(second.flightCount, 1);
  assert.deepEqual(
    new Set(buildGlobeHistory([crossYear], "All years").visited),
    new Set(["JP", "SG"]),
  );
});

test("flight and airport totals include missing map coordinates and remain scoped to the year", () => {
  const env = environment(),
    { buildGlobeHistory } = env.load(
      path.join(root, "src/components/world-window/globe-history.ts"),
    );
  const unlocated = {
    ...crossYear,
    segments: [
      crossYear.segments[0],
      {
        ...crossYear.segments[1],
        depPoint: undefined,
        arrPoint: undefined,
        arrCountry: "Singapore",
        arrCountryCode: "SG",
      },
    ],
  };
  const all = buildGlobeHistory([unlocated], "All years");
  assert.equal(all.flightCount, 2);
  assert.equal(all.airportCount, 3);
  assert.equal(all.routes.length, 1);
  const year = buildGlobeHistory([unlocated], "2026");
  assert.equal(year.flightCount, 1);
  assert.equal(year.airportCount, 2);
  assert.equal(year.routes.length, 0);
  assert.deepEqual(year.visited, ["SG"]);
});

test("Home ticket preserves departure calendar date and reconciles year/data changes", () => {
  const trip = {
    ...crossYear,
    segments: [
      { ...crossYear.segments[0], depTime: "2026-02-21T00:20:00+09:00" },
    ],
  };
  const env = environment([trip]),
    { HomeGlobeScreen } = env.load(
      path.join(root, "src/screens/HomeGlobeScreen.tsx"),
    );
  const { WorldWindowGlobe } = env.load(
    path.join(root, "src/components/world-window/WorldWindowGlobe.tsx"),
  );
  let props = { active: "globe", filterYear: "All years", onChange() {} };
  const render = () => env.render(() => HomeGlobeScreen(props));
  let tree = render(),
    globe = nodes(tree).find((n) => n.type === WorldWindowGlobe);
  globe.props.onRoute(globe.props.routes[0]);
  tree = render();
  assert(texts(tree).includes("21 Feb 2026"));
  props = { ...props, filterYear: "2025" };
  tree = render();
  assert.equal(
    nodes(tree).find((n) => n.type === WorldWindowGlobe).props.selectedRouteId,
    undefined,
  );
  assert(!texts(tree).includes("View trip"));
  props = { ...props, filterYear: "All years" };
  tree = render();
  globe = nodes(tree).find((n) => n.type === WorldWindowGlobe);
  globe.props.onRoute(globe.props.routes[0]);
  render();
  env.setTrips([]);
  tree = render();
  assert.equal(
    nodes(tree).find((n) => n.type === WorldWindowGlobe).props.selectedRouteId,
    undefined,
  );
  assert(!texts(tree).includes("View trip"));
});

test("a retained Home cannot leave its native year modal over another tab", () => {
  const env = environment();
  const { HomeGlobeScreen } = env.load(
    path.join(root, "src/screens/HomeGlobeScreen.tsx"),
  );
  let props = { active: "globe", onChange() {} };
  const render = () => env.render(() => HomeGlobeScreen(props));
  nodes(render())
    .find((node) => node.props.accessibilityLabel === "Filter flights by year")
    .props.onPress();
  assert.equal(
    nodes(render()).find((node) => node.type === "Modal").props.visible,
    true,
  );
  props = { ...props, active: "dreams" };
  assert.equal(
    nodes(render()).find((node) => node.type === "Modal").props.visible,
    false,
  );
  props = { ...props, active: "globe" };
  assert.equal(
    nodes(render()).find((node) => node.type === "Modal").props.visible,
    false,
    "returning to Home must not reopen the dismissed year sheet",
  );
});

test("one globe arc exposes both directions and every date; Back dismisses before leaving Home", () => {
  const returnTrip = { ...crossYear, id: 'return-trip', segments: [leg('return', NRT, DFW, '2026-02-02T08:00:00Z', '2026-02-02T16:00:00Z')] };
  const env = environment([crossYear, returnTrip]), calls = [];
  const { HomeGlobeScreen } = env.load(path.join(root, 'src/screens/HomeGlobeScreen.tsx'));
  const { WorldWindowGlobe } = env.load(path.join(root, 'src/components/world-window/WorldWindowGlobe.tsx'));
  let back;
  const props = { active: 'globe', onChange() {}, onBackHandlerChange: value => { back = value; }, onOpenTrip: (...args) => calls.push(args) };
  const render = () => env.render(() => HomeGlobeScreen(props));
  let tree = render(), globe = nodes(tree).find(node => node.type === WorldWindowGlobe);
  globe.props.onRoute(globe.props.routes.find(route => route.id === 'first')); tree = render();
  assert(texts(tree).join('').includes('2 flights on this route'));
  assert(texts(tree).join('').includes('NRT → DFW')); assert(texts(tree).join('').includes('DFW → NRT'));
  const reverse = nodes(tree).find(node => node.props.accessibilityLabel?.startsWith('Select NRT to DFW'));
  reverse.props.onPress(); tree = render();
  assert.equal(nodes(tree).find(node => node.type === WorldWindowGlobe).props.selectedRouteId, 'return');
  assert.equal(back(), true); tree = render();
  assert.equal(nodes(tree).find(node => node.type === WorldWindowGlobe).props.selectedRouteId, undefined);
  assert.equal(back(), false);
  globe = nodes(tree).find(node => node.type === WorldWindowGlobe);
  globe.props.onRoute(globe.props.routes.find(route => route.id === 'return')); tree = render();
  assert.equal(back(), true); tree = render();
  assert.equal(nodes(tree).find(node => node.type === WorldWindowGlobe).props.selectedRouteId, 'return', 'First Back collapses date choices');
  const open = nodes(tree).find(node => node.props.accessibilityLabel?.startsWith('View trip for'));
  assert(open); open.props.onPress(); render();
  assert.equal(calls[0][0].id, 'return-trip'); assert.equal(calls[0][1], 'return');
});

test("Home totals wait for paper exit and a new selection cancels their delayed return", async () => {
  const env = environment([crossYear]);
  const { HomeGlobeScreen } = env.load(path.join(root, 'src/screens/HomeGlobeScreen.tsx'));
  const { WorldWindowGlobe } = env.load(path.join(root, 'src/components/world-window/WorldWindowGlobe.tsx'));
  const render = () => env.render(() => HomeGlobeScreen({ active: 'globe', onChange() {} }));
  const stats = tree => nodes(tree).find(node => node.props['aria-hidden'] !== undefined);
  let tree = render(), globe = nodes(tree).find(node => node.type === WorldWindowGlobe);
  globe.props.onRoute(globe.props.routes[0]); tree = render(); assert.equal(stats(tree).props.pointerEvents, 'none');
  const dismiss = nodes(tree).find(node => node.props.accessibilityLabel === 'Dismiss flight');
  dismiss.props.onPress(); tree = render(); assert.equal(stats(tree).props.pointerEvents, 'none');
  globe = nodes(tree).find(node => node.type === WorldWindowGlobe); globe.props.onRoute(globe.props.routes[0]); render();
  await new Promise(resolve => setTimeout(resolve, 180)); tree = render(); assert.equal(stats(tree).props.pointerEvents, 'none');
  nodes(tree).find(node => node.props.accessibilityLabel === 'Dismiss flight').props.onPress(); render();
  await new Promise(resolve => setTimeout(resolve, 180)); tree = render(); assert.equal(stats(tree).props.pointerEvents, 'auto');
});

test("pinch hands off continuously to one finger without a jump or accidental route tap", () => {
  const env = environment(),
    { WorldWindowGlobe } = env.load(
      path.join(root, "src/components/world-window/WorldWindowGlobe.tsx"),
    );
  let cleared = 0;
  const tree = env.render(() =>
    WorldWindowGlobe({
      routes: [],
      visited: [],
      active: true,
      mapStyle: "classic",
      cycle: false,
      onRoute() {},
      onCountry() {},
      onClear() {
        cleared++;
      },
    }),
  );
  const rotation = env.refs.find(
    (r) =>
      r.current &&
      typeof r.current.x === "number" &&
      Object.keys(r.current).length === 2,
  );
  const event = (touches) => ({
    nativeEvent: { touches, locationX: 0, locationY: 0 },
  });
  const g = { x0: 0, y0: 0, dx: 0, dy: 0, vx: 0, vy: 0 };
  tree.props.onPanResponderGrant(
    event([
      { pageX: 0, pageY: 0 },
      { pageX: 100, pageY: 0 },
    ]),
    g,
  );
  tree.props.onPanResponderMove(
    event([
      { pageX: 0, pageY: 0 },
      { pageX: 180, pageY: 0 },
    ]),
    g,
  );
  const start = rotation.current.y;
  tree.props.onPanResponderMove(event([{ pageX: 10, pageY: 0 }]), {
    ...g,
    dx: 10,
  });
  assert.equal(
    rotation.current.y,
    start,
    "handoff rebases without moving the globe",
  );
  tree.props.onPanResponderMove(event([{ pageX: 100, pageY: 0 }]), {
    ...g,
    dx: 100,
  });
  assert(
    Math.abs(rotation.current.y - start - 0.54) < 1e-9,
    "remaining finger rotates by its own new displacement",
  );
  tree.props.onPanResponderRelease(event([]), g);
  assert.equal(cleared, 0, "a pinch never becomes a synthetic tap at release");
});

test("accessibility actions zoom, rotate, browse every repeated flight, pick country and clear", () => {
  const env = environment(),
    { WorldWindowGlobe } = env.load(
      path.join(root, "src/components/world-window/WorldWindowGlobe.tsx"),
    );
  const routes = Array.from({ length: 3 }, (_, i) => ({
    id: String(i),
    from: DFW,
    to: NRT,
    depTime: `2026-02-${21 + i}T00:20:00+09:00`,
  }));
  let props = {
    routes,
    visited: ["JP"],
    active: true,
    mapStyle: "classic",
    cycle: false,
    onRoute(route) {
      props = { ...props, selectedRouteId: route.id };
    },
    onCountry(country) {
      props = { ...props, selectedCountryCode: country.code };
    },
    onClear() {
      props = {
        ...props,
        selectedRouteId: undefined,
        selectedCountryCode: undefined,
      };
    },
  };
  const render = () => env.render(() => WorldWindowGlobe(props));
  let tree = render();
  const action = (name) => {
    tree.props.onAccessibilityAction({ nativeEvent: { actionName: name } });
    tree = render();
  };
  assert.equal(tree.props.accessibilityRole, "adjustable");
  for (let i = 0; i < 20; i++) action("increment");
  assert.equal(tree.props.accessibilityValue.now, 4.8);
  for (let i = 0; i < 20; i++) action("decrement");
  assert.equal(tree.props.accessibilityValue.now, 1);
  const rotation = env.refs.find(
      (r) =>
        r.current &&
        typeof r.current.x === "number" &&
        Object.keys(r.current).length === 2,
    ),
    start = rotation.current.y;
  action("rotateEast");
  assert.equal(rotation.current.y, start + 0.22);
  for (const id of ["0", "1", "2", "0"]) {
    action("nextFlight");
    assert.equal(props.selectedRouteId, id);
  }
  action("previousFlight");
  assert.equal(props.selectedRouteId, "2");
  action("nextCountry");
  assert.equal(props.selectedCountryCode, "JP");
  action("clearSelection");
  assert.equal(props.selectedRouteId, undefined);
  assert.equal(props.selectedCountryCode, undefined);
  assert(env.announcements.some((text) => text.includes("Flight 3 of 3")));
});
