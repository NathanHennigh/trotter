// Offline geography, encoded-texture, and solar checks. No GL context or network.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { test } = require("node:test");
const ts = require("typescript");
const sharp = require("sharp");
const THREE = require("three");
const root = path.resolve(__dirname, "..");
const directory = path.join(root, "src/components/world-window");
const compile = (source) =>
  ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      esModuleInterop: true,
      target: ts.ScriptTarget.ES2020,
      jsx: ts.JsxEmit.React,
    },
  }).outputText;
const geographyModule = { exports: {} };
new Function(
  "module",
  "exports",
  "require",
  compile(fs.readFileSync(path.join(directory, "globe-geography.ts"), "utf8")),
)(geographyModule, geographyModule.exports, (request) =>
  request.endsWith("worldCountries.json")
    ? require("../src/data/worldCountries.json")
    : require(request),
);
const geography = geographyModule.exports;
const source = fs.readFileSync(
  path.join(directory, "WorldWindowGlobe.tsx"),
  "utf8",
);
const ast = ts.createSourceFile(
  "WorldWindowGlobe.tsx",
  source,
  ts.ScriptTarget.Latest,
  true,
  ts.ScriptKind.TSX,
);
const globeModule = { exports: {} };
new Function(
  "module",
  "exports",
  "require",
  compile(source) +
    "\nmodule.exports.math = { vector, sunVector, globeTextureQuality, configureGlobeTexture, selectGlobeTiles, makeGlobeTileGeometry, createGlobeDetail };",
)(globeModule, globeModule.exports, (request) => {
  if (request === "three" || request === "react") return require(request);
  if (request === "react-native")
    return { StyleSheet: { create: (styles) => styles } };
  if (request === "expo-gl" || request.includes("expoThree")) return {};
  if (request.includes("trotterTheme")) return { colors: {}, fonts: {} };
  if (request === "./globe-geography") return geography;
  if (request === "./routeSelection") {
    const module = { exports: {} };
    new Function("module", "exports", compile(fs.readFileSync(path.join(directory, "routeSelection.ts"), "utf8")))(module, module.exports);
    return module.exports;
  }
  if (request.includes("globeDayDetailTiles"))
    return {
      globeDayDetailTiles: Array.from({ length: 6 }, (_, r) =>
        Array.from({ length: 12 }, (_, c) => r * 12 + c),
      ),
    };
  if (request.includes("globeCountryDetailTiles"))
    return {
      globeCountryDetailTiles: Array.from({ length: 6 }, (_, r) =>
        Array.from({ length: 12 }, (_, c) => 100 + r * 12 + c),
      ),
    };
  if (request.includes("globeNightDetailTiles"))
    return {
      globeNightDetailTiles: Array.from({ length: 6 }, (_, r) =>
        Array.from({ length: 12 }, (_, c) => 200 + r * 12 + c),
      ),
    };
  if (/\.(png|jpg)$/.test(request)) return request;
  throw new Error(`Unexpected globe dependency: ${request}`);
});
const { vector, sunVector } = globeModule.exports.math;
function findNode(predicate) {
  let found;
  function visit(node) {
    if (predicate(node)) found = node;
    if (!found) ts.forEachChild(node, visit);
  }
  visit(ast);
  assert(found, "Expected production source node");
  return found;
}
const shaderProperty = findNode(
  (node) =>
    ts.isPropertyAssignment(node) &&
    node.name.getText(ast) === "fragmentShader",
);
assert(
  ts.isNoSubstitutionTemplateLiteral(shaderProperty.initializer),
  "Shader UV test must read the actual fragment shader",
);
const shader = shaderProperty.initializer.text;
const uvBody = shader.match(/vec2\s+uv\s*=\s*vec2\((.*?)\);/s)[1];
let depth = 0,
  split = -1;
for (let i = 0; i < uvBody.length; i++) {
  if (uvBody[i] === "(") depth++;
  if (uvBody[i] === ")") depth--;
  if (uvBody[i] === "," && depth === 0) {
    split = i;
    break;
  }
}
assert(split > 0);
const evaluateUv = new Function(
  "n",
  "atan",
  "asin",
  "clamp",
  `return [${uvBody.slice(0, split)},${uvBody.slice(split + 1)}];`,
);
const uv = (normal) =>
  evaluateUv(normal, Math.atan2, Math.asin, (value, low, high) =>
    Math.max(low, Math.min(high, value)),
  );
const fixtures = [
  { code: "SG", name: "Singapore", lat: 1.366587, lon: 103.816925 },
  { code: "AE", name: "United Arab Emirates", lat: 23.466285, lon: 54.547256 },
  { code: "TN", name: "Tunisia", lat: 34, lon: 9 },
  { code: "X-SOMALILAND", name: "Somaliland", lat: 9.5624, lon: 44.077 },
  { code: "AU", name: "Australia", lat: -25, lon: 135 },
  { code: "US", name: "United States of America", lat: 40, lon: -100 },
  { code: "CL", name: "Chile", lat: -30, lon: -71 },
];
const angleDistance = (a, b) => Math.abs(((a - b + 540) % 360) - 180);

test("geography picking recognizes required countries and keeps Somaliland distinct from Somalia", () => {
  for (const place of fixtures)
    assert.equal(
      geography.countryAt(place.lon, place.lat)?.code,
      place.code,
      place.name,
    );
  assert.equal(
    geography.countryAt(45.3182, 2.0469)?.code,
    "SO",
    "Mogadishu remains Somalia",
  );
  assert.equal(
    geography.flightCountryKey("Somalia", "SO", "HGA"),
    "X-SOMALILAND",
  );
  assert.equal(
    geography.flightCountryKey("Somalia", "SO", "BBO"),
    "X-SOMALILAND",
  );
  assert.equal(geography.flightCountryKey("Somalia", "SO", "MGQ"), "SO");
  assert.equal(geography.flightCountryKey("Tunisia", "TN", "TUN"), "TN");
  assert.equal(geography.flightCountryKey("Unknown", "not-a-code"), undefined);
  assert.equal(
    geography.countryAt(0, -30),
    undefined,
    "Open Atlantic water must not pick a country",
  );
});

test("render vector, world rotation, picking inverse and actual GLSL UV agree", () => {
  const globe = new THREE.Group();
  globe.rotation.set(0.55, -1.7, 0.12);
  globe.updateMatrixWorld();
  for (const place of fixtures) {
    const normal = vector(place.lat, place.lon, 1);
    assert(Math.abs(normal.length() - 1) < 1e-12);
    const recovered = globe
      .worldToLocal(globe.localToWorld(normal.clone()))
      .normalize();
    const lat = (Math.asin(recovered.y) * 180) / Math.PI,
      lon = (Math.atan2(-recovered.z, recovered.x) * 180) / Math.PI;
    assert(Math.abs(lat - place.lat) < 1e-10);
    assert(angleDistance(lon, place.lon) < 1e-10);
    const [u, v] = uv(normal);
    assert(
      Math.abs(u - (place.lon + 180) / 360) < 1e-10,
      `${place.name}: east/west UV`,
    );
    assert(
      Math.abs(v - (90 - place.lat) / 180) < 1e-10,
      `${place.name}: north/south UV`,
    );
  }
});

test("PNG country IDs agree with geographic picks at the shader sampling coordinates", async () => {
  const { data, info } = await sharp(
    path.join(root, "assets/world-window/country-index.png"),
  )
    .ensureAlpha()
    .raw()
    .toBuffer({ resolveWithObject: true });
  const at = (lat, lon) => {
    const [u, v] = uv(vector(lat, lon, 1));
    const x = Math.min(info.width - 1, Math.max(0, Math.floor(u * info.width)));
    const y = Math.min(
      info.height - 1,
      Math.max(0, Math.floor(v * info.height)),
    );
    return data.subarray(
      (y * info.width + x) * 4,
      (y * info.width + x) * 4 + 4,
    );
  };
  for (const place of fixtures) {
    const encoded = at(place.lat, place.lon),
      country = geography.countryAt(place.lon, place.lat);
    assert.equal(
      encoded[0],
      country.index,
      `${place.name}: raster ID must match picker/lookup order`,
    );
    assert.equal(
      encoded[1],
      0,
      "The current shader uses an 8-bit country index",
    );
    assert.equal(encoded[2], 255, "Land bit must be set");
  }
  assert.deepEqual(
    [...at(-30, 0)].slice(0, 3),
    [0, 0, 0],
    "Ocean cannot inherit a country mask",
  );
  const validIds = new Set([
    0,
    ...geography.globeCountries.map((country) => country.index),
  ]);
  for (let i = 0; i < data.length; i += 4) {
    assert(
      validIds.has(data[i]),
      "Raster ID must name a current geography entry",
    );
    assert.equal(
      data[i + 1],
      0,
      "Raster country IDs cannot overflow the shader lookup",
    );
    assert.equal(
      data[i + 2],
      data[i] ? 255 : 0,
      "No anti-aliased/interpolated country labels",
    );
  }
});

test("actual visited lookup masks only the requested country codes and clears an old account", () => {
  const countries = geography.globeCountries;
  assert(countries.length < 256);
  // A country can own multiple geographic features; indices, not codes, are unique.
  assert.notEqual(
    countries.find((country) => country.name === "Siachen Glacier").code,
    "AU",
    "Disputed Siachen cannot inherit the Australia visit mask",
  );
  assert.equal(
    new Set(countries.map((country) => country.index)).size,
    countries.length,
  );
  const node = findNode(
    (node) =>
      ts.isVariableDeclaration(node) &&
      node.name.getText(ast) === "updateVisited",
  );
  const callback = node.initializer.arguments[0].getText(ast);
  const context = {
    current: {
      lookup: { image: { data: new Uint8Array(256 * 4) }, needsUpdate: false },
    },
  };
  const live = {
    current: {
      visited: ["SG", "AE", "TN", "X-SOMALILAND", "invalid"],
      selectedCountryCode: "TN",
    },
  };
  const module = { exports: {} };
  new Function(
    "module",
    "context",
    "live",
    "globeCountries",
    compile(`module.exports = ${callback};`),
  )(module, context, live, countries);
  module.exports();
  for (const country of countries) {
    const offset = country.index * 4,
      data = context.current.lookup.image.data;
    assert.equal(
      data[offset],
      live.current.visited.includes(country.code) ? 255 : 0,
      country.code,
    );
    assert.equal(
      data[offset + 1],
      country.code === "TN" ? 255 : 0,
      country.code,
    );
    assert.equal(data[offset + 3], 255);
  }
  assert.equal(
    context.current.lookup.image.data[0],
    0,
    "Ocean index is never marked visited",
  );
  live.current = { visited: [], selectedCountryCode: undefined };
  module.exports();
  for (let i = 0; i < 256; i++) {
    assert.equal(
      context.current.lookup.image.data[i * 4],
      0,
      "Prior owner visited bits must be erased",
    );
    assert.equal(
      context.current.lookup.image.data[i * 4 + 1],
      0,
      "Prior selection must be erased",
    );
  }
});

test("sun longitude tracks UTC and declination tracks seasonal months", () => {
  const march = geography.sunPosition(new Date("2026-03-20T12:00:00Z"));
  const june = geography.sunPosition(new Date("2026-06-21T12:00:00Z"));
  const september = geography.sunPosition(new Date("2026-09-22T12:00:00Z"));
  const december = geography.sunPosition(new Date("2026-12-21T12:00:00Z"));
  assert(
    Math.abs(march.lat) < 0.5 && Math.abs(september.lat) < 0.5,
    "Equinox sun stays near the equator",
  );
  assert(
    june.lat > 23 && june.lat < 24,
    "June sun is over the northern tropic",
  );
  assert(
    december.lat < -23 && december.lat > -24,
    "December sun is over the southern tropic",
  );
  assert(
    angleDistance(march.lon, 0) < 3,
    "UTC noon stays near Greenwich allowing equation of time",
  );
  for (const hour of [0, 6, 12, 18]) {
    const p = geography.sunPosition(
      new Date(`2026-03-20T${String(hour).padStart(2, "0")}:00:00Z`),
    );
    assert(
      angleDistance(p.lon, 180 - 15 * hour) < 3,
      "Solar longitude moves west 15 degrees per UTC hour",
    );
    assert(Number.isFinite(p.lon) && p.lon >= -180 && p.lon < 180);
  }
});

test("sun vector produces antipodal midnight, a right-angle terminator and polar seasons", () => {
  for (const month of [1, 3, 6, 9, 12]) {
    const date = new Date(
        `2026-${String(month).padStart(2, "0")}-21T12:00:00Z`,
      ),
      p = geography.sunPosition(date),
      sun = sunVector(date);
    assert(Math.abs(sun.length() - 1) < 1e-12);
    assert(vector(p.lat, p.lon, 1).dot(sun) > 0.999999);
    assert(vector(-p.lat, p.lon + 180, 1).dot(sun) < -0.999999);
    assert(
      Math.abs(vector(0, p.lon + 90, 1).dot(sun)) < 1e-10,
      "Equatorial terminator is 90 degrees from the subsolar meridian",
    );
  }
  const june = sunVector(new Date("2026-06-21T12:00:00Z")),
    winter = sunVector(new Date("2026-12-21T12:00:00Z"));
  for (const lon of [0, 90, 180, -90]) {
    assert(
      vector(80, lon, 1).dot(june) > 0,
      "High Arctic has continuous summer daylight",
    );
    assert(
      vector(80, lon, 1).dot(winter) < 0,
      "High Arctic has continuous winter darkness",
    );
  }
});

test("high-detail country tiles and base retain exact geography IDs with wrapped gutters", async () => {
  for (const place of fixtures) {
    const [u, v] = uv(vector(place.lat, place.lon, 1)),
      col = Math.min(11, Math.floor(u * 12)),
      row = Math.min(5, Math.floor(v * 6));
    for (const [file, x, y] of [
      ["country-index-4096.png", Math.floor(u * 4096), Math.floor(v * 2048)],
      [
        `country-detail/country-r${row}-c${col}.png`,
        Math.floor((u * 12 - col) * 1024 + 1),
        Math.floor((v * 6 - row) * 1024 + 1),
      ],
    ]) {
      const pixel = await sharp(path.join(root, "assets/world-window", file))
        .extract({ left: x, top: y, width: 1, height: 1 })
        .ensureAlpha()
        .raw()
        .toBuffer();
      assert.equal(
        pixel[0],
        geography.countryAt(place.lon, place.lat).index,
        `${place.name} ${file}`,
      );
      assert.equal(pixel[1], 0);
      assert.equal(pixel[2], 255);
    }
  }
  const west = await sharp(
    path.join(root, "assets/world-window/country-detail/country-r3-c0.png"),
  )
    .extract({ left: 0, top: 0, width: 1, height: 1026 })
    .raw()
    .toBuffer();
  const east = await sharp(
    path.join(root, "assets/world-window/country-detail/country-r3-c11.png"),
  )
    .extract({ left: 1024, top: 0, width: 1, height: 1026 })
    .raw()
    .toBuffer();
  assert.deepEqual(
    west,
    east,
    "Date-line gutter equals its neighbor instead of becoming an ocean seam",
  );
});

test("detail patch faces point outward and neighboring geometry meets exactly", () => {
  const make = globeModule.exports.math.makeGlobeTileGeometry;
  for (const [row, col] of [
    [0, 0],
    [2, 5],
    [3, 11],
    [5, 8],
  ]) {
    const mesh = make(row, col),
      p = mesh.getAttribute("position"),
      n = mesh.getAttribute("normal"),
      index = mesh.index;
    for (let i = 0; i < p.count; i++) {
      assert(
        Math.abs(new THREE.Vector3().fromBufferAttribute(n, i).length() - 1) <
          1e-6,
      );
      assert(
        Math.abs(
          new THREE.Vector3().fromBufferAttribute(p, i).length() - 2.0808,
        ) < 1e-6,
      );
    }
    for (let i = 0; i < index.count; i += 3) {
      const a = new THREE.Vector3().fromBufferAttribute(p, index.getX(i)),
        b = new THREE.Vector3().fromBufferAttribute(p, index.getX(i + 1)),
        c = new THREE.Vector3().fromBufferAttribute(p, index.getX(i + 2));
      const normal = b.clone().sub(a).cross(c.clone().sub(a));
      if (normal.length() > 1e-9)
        assert(
          normal.dot(a) > 0,
          "Native front-face culling must preserve the detail patch",
        );
    }
    mesh.dispose();
  }
  const a = make(2, 11),
    b = make(2, 0);
  for (let y = 0; y <= 48; y++)
    assert(
      new THREE.Vector3()
        .fromBufferAttribute(a.getAttribute("position"), y * 49 + 48)
        .distanceTo(
          new THREE.Vector3().fromBufferAttribute(
            b.getAttribute("position"),
            y * 49,
          ),
        ) < 1e-6,
      "Date line mesh vertices match",
    );
  a.dispose();
  b.dispose();
});

test("quality selects supported textures and bounds active detail memory", () => {
  const { globeTextureQuality, configureGlobeTexture, selectGlobeTiles } =
    globeModule.exports.math;
  assert.deepEqual(globeTextureQuality(2048), {
    baseWidth: 2048,
    detailTiles: 2,
  });
  assert.deepEqual(globeTextureQuality(4096), {
    baseWidth: 4096,
    detailTiles: 4,
  });
  assert.deepEqual(
    globeTextureQuality(16384),
    { baseWidth: 4096, detailTiles: 4 },
    "Large GPU limits do not upload a whole 21600px image",
  );
  const textureBytes =
    4096 * 2048 * 4 * 3 + 4 * (1800 * 1800 + 1026 * 1026 + 1127 * 1127) * 4;
  assert(
    textureBytes < 192 * 1024 * 1024,
    "Base + all four day/night/mask detail triples stay under 192MiB, without mip chains",
  );
  const t = new THREE.Texture();
  configureGlobeTexture(t, false, {
    capabilities: { getMaxAnisotropy: () => 16 },
  });
  assert.equal(t.generateMipmaps, false);
  assert.equal(t.magFilter, THREE.LinearFilter);
  assert.equal(t.anisotropy, 4);
  configureGlobeTexture(t, true, {
    capabilities: { getMaxAnisotropy: () => 16 },
  });
  assert.equal(t.magFilter, THREE.NearestFilter);
  assert.equal(t.anisotropy, 1);
  t.dispose();
  for (const lon of [-180, -90, 0, 90, 179]) {
    const q = new THREE.Quaternion().setFromEuler(
      new THREE.Euler(0, -Math.PI / 2 - (lon * Math.PI) / 180, 0),
    );
    const keys = selectGlobeTiles(q, 4);
    assert.equal(keys.length, 4);
    assert.equal(new Set(keys).size, 4);
    assert(keys.every((key) => key >= 0 && key < 72));
  }
});

function detailHarness(limit = 4) {
  const pending = [],
    all = [];
  const group = new THREE.Group();
  const base = new THREE.ShaderMaterial({
    uniforms: {
      sun: { value: new THREE.Vector3(0, 0, 1) },
      textureMix: { value: 0 },
      visitedMap: { value: new THREE.DataTexture() },
      nightMap: { value: new THREE.Texture() },
      nightBounds: { value: new THREE.Vector4(0, 0, 1, 1) },
    },
    vertexShader: "void main(){}",
    fragmentShader: "void main(){}",
  });
  const load = (asset, labels) =>
    new Promise((resolve, reject) =>
      pending.push({
        asset,
        labels,
        resolve: () => {
          const texture = new THREE.Texture();
          texture.userData.disposals = 0;
          texture.addEventListener(
            "dispose",
            () => texture.userData.disposals++,
          );
          all.push(texture);
          resolve(texture);
          return texture;
        },
        reject,
      }),
    );
  const controller = globeModule.exports.math.createGlobeDetail(
    group,
    base,
    {},
    limit,
    load,
  );
  const flush = async () => {
    for (let i = 0; i < 6; i++) await Promise.resolve();
  };
  const settle = async () => {
    let guard = 0;
    while (pending.length) {
      assert(++guard < 50);
      pending.shift().resolve();
      await flush();
      assert(controller.stats().resident <= limit);
    }
  };
  return { pending, all, group, base, controller, flush, settle };
}

test("rapid spin evicts obsolete tiles and never grows the GPU texture cache", async () => {
  const h = detailHarness();
  h.controller.update(4.8, 300, 16);
  assert.equal(h.pending.length, 1, "Only one detail decode starts at once");
  const old = h.pending.shift();
  h.group.rotation.y = Math.PI;
  h.controller.update(4.8, 600, 16);
  const obsolete = old.resolve();
  await h.flush();
  assert.equal(
    obsolete.userData.disposals,
    1,
    "Old view decode cannot install into new view",
  );
  await h.settle();
  assert.equal(h.controller.stats().resident, 4);
  for (let i = 1; i <= 8; i++) {
    h.group.rotation.y = i * 0.8;
    h.controller.update(4.8, 600 + i * 300, 16);
    await h.settle();
    assert.equal(h.controller.stats().resident, 4);
    assert(
      h.all.filter((t) => !t.userData.disposals).length <= 12,
      "At most four day/night/mask triples remain alive",
    );
  }
  h.controller.dispose();
  assert(h.all.every((t) => t.userData.disposals === 1));
  assert.equal(h.group.children.length, 0);
  h.base.dispose();
});

test("zoom-out and unmount discard late mask decodes without restoring disposed detail", async () => {
  for (const unmount of [false, true]) {
    const h = detailHarness();
    h.controller.update(4.8, 300, 16);
    const day = h.pending.shift().resolve();
    await h.flush();
    assert.equal(h.pending[0].labels, true);
    if (unmount) h.controller.dispose();
    else h.controller.update(1, 600, 16);
    const mask = h.pending.shift().resolve();
    await h.flush();
    assert.equal(day.userData.disposals, 1);
    assert.equal(mask.userData.disposals, 1);
    assert.equal(h.controller.stats().resident, 0);
    assert.equal(h.pending.length, 0);
    assert.equal(h.group.children.length, 0);
    h.controller.dispose();
    h.base.dispose();
  }
});

test("failed detail decoding preserves base material and releases partial textures", async () => {
  const h = detailHarness(2),
    baseUniforms = h.base.uniforms;
  h.controller.update(4.8, 300, 16);
  const day = h.pending.shift().resolve();
  await h.flush();
  h.pending.shift().reject(new Error("synthetic missing tile"));
  await h.flush();
  assert.equal(day.userData.disposals, 1);
  assert.equal(h.controller.stats().failed, 1);
  assert.equal(h.base.uniforms, baseUniforms);
  await h.settle();
  assert.equal(h.controller.stats().resident, 1);
  h.controller.update(4.8, 600, 16);
  assert.equal(
    h.pending.length,
    0,
    "Missing asset is not decoded repeatedly every frame",
  );
  h.controller.dispose();
  assert(h.all.every((t) => t.userData.disposals === 1));
  h.base.dispose();
});

test("unavailable night detail retains day detail and the base night sampler", async () => {
  const h = detailHarness(1);
  h.controller.update(4.8, 300, 16);
  h.pending.shift().resolve();
  await h.flush();
  h.pending.shift().resolve();
  await h.flush();
  assert(h.pending[0].asset >= 200, "The third decode is a night tile");
  h.pending.shift().reject(new Error("synthetic unavailable night detail"));
  await h.flush();
  assert.equal(h.controller.stats().resident, 1);
  assert.equal(h.controller.stats().failed, 0);
  const tile = h.group.children[0];
  assert.equal(tile.material.uniforms.nightMap, h.base.uniforms.nightMap);
  assert.equal(tile.material.uniforms.nightBounds, h.base.uniforms.nightBounds);
  assert(h.all.every((t) => t.userData.disposals === 0));
  h.controller.dispose();
  assert(h.all.every((t) => t.userData.disposals === 1));
});

test("late night decode disposes all three textures after zoom out or unmount", async () => {
  for (const unmount of [false, true]) {
    const h = detailHarness(1);
    h.controller.update(4.8, 300, 16);
    h.pending.shift().resolve();
    await h.flush();
    h.pending.shift().resolve();
    await h.flush();
    if (unmount) h.controller.dispose();
    else h.controller.update(1, 600, 16);
    h.pending.shift().resolve();
    await h.flush();
    assert.equal(h.controller.stats().resident, 0);
    assert.equal(h.all.length, 3);
    assert(h.all.every((t) => t.userData.disposals === 1));
    h.controller.dispose();
  }
});

test("suspending a hidden globe evicts detail and resumes without replacing the base", async () => {
  const h = detailHarness(),
    baseUniforms = h.base.uniforms;
  h.controller.update(4.8, 300, 16);
  await h.settle();
  assert.equal(h.controller.stats().resident, 4);
  h.controller.suspend();
  assert.equal(h.controller.stats().resident, 0);
  assert.equal(h.group.children.length, 0);
  assert(h.all.every((texture) => texture.userData.disposals === 1));
  assert.equal(h.base.uniforms, baseUniforms);
  h.controller.update(4.8, 316, 16);
  await h.settle();
  assert.equal(
    h.controller.stats().resident,
    4,
    "resume can restore detail immediately without the old 250 ms selection delay",
  );
  assert.equal(h.base.uniforms, baseUniforms);
  h.controller.dispose();
  assert(h.all.every((texture) => texture.userData.disposals === 1));
});

test("backgrounding during a night decode releases all pending detail textures", async () => {
  const h = detailHarness(1);
  h.controller.update(4.8, 300, 16);
  h.pending.shift().resolve();
  await h.flush();
  h.pending.shift().resolve();
  await h.flush();
  h.controller.suspend();
  h.pending.shift().resolve();
  await h.flush();
  assert.equal(h.controller.stats().resident, 0);
  assert.equal(h.pending.length, 0);
  assert(h.all.every((texture) => texture.userData.disposals === 1));
  h.controller.update(4.8, 320, 16);
  await h.settle();
  assert.equal(h.controller.stats().resident, 1);
  h.controller.dispose();
  assert(h.all.every((texture) => texture.userData.disposals === 1));
});

test("night detail uses real NASA resolution and matches the unfiltered source pixels", async () => {
  const master = path.join(root, "assets/globe/black-marble-2016-13500.jpg");
  const metadata = await sharp(master).metadata();
  assert.deepEqual([metadata.width, metadata.height], [13500, 6750]);
  for (const width of [2048, 4096]) {
    const info = await sharp(
      path.join(root, `assets/world-window/nasa-night-${width}.jpg`),
    ).metadata();
    assert.deepEqual([info.width, info.height], [width, width / 2]);
    assert.equal(info.chromaSubsampling, "4:4:4");
  }
  for (let r = 0; r < 6; r++)
    for (let c = 0; c < 12; c++) {
      const info = await sharp(
        path.join(
          root,
          `assets/world-window/night-detail/night-r${r}-c${c}.jpg`,
        ),
      ).metadata();
      assert.deepEqual([info.width, info.height], [1127, 1127]);
      assert.equal(info.chromaSubsampling, "4:4:4");
    }
  // Interior patches from North America, Europe and Asia: encoding may differ,
  // but no saturation, brightness, synthetic sharpening or UV shift is added.
  for (const [row, col] of [
    [1, 3],
    [1, 6],
    [2, 9],
  ]) {
    const original = await sharp(master)
      .extract({
        left: col * 1125 + 300,
        top: row * 1125 + 300,
        width: 64,
        height: 64,
      })
      .raw()
      .toBuffer();
    const tile = await sharp(
      path.join(
        root,
        `assets/world-window/night-detail/night-r${row}-c${col}.jpg`,
      ),
    )
      .extract({ left: 301, top: 301, width: 64, height: 64 })
      .raw()
      .toBuffer();
    const meanError =
      original.reduce((sum, value, i) => sum + Math.abs(value - tile[i]), 0) /
      original.length;
    assert(
      meanError < 3,
      `Night tile source alignment/color changed (${meanError})`,
    );
  }
  assert(source.includes("texture2D(nightMap,regionUV(uv,nightBounds))"));
});

test("NASA detail and fallback use the same source generation and tile orientation", async () => {
  const nasa = path.join(root, "assets/globe/blue-marble-day-21600.jpg");
  const sample = async (image) =>
    image.resize(120, 60, { fit: "fill" }).removeAlpha().raw().toBuffer();
  const difference = (a, b) =>
    Math.sqrt(a.reduce((sum, v, i) => sum + (v - b[i]) ** 2, 0) / a.length);
  const master = await sample(sharp(nasa));
  for (const size of [2048, 4096]) {
    const base = await sample(
      sharp(path.join(root, `assets/world-window/nasa-day-base-${size}.jpg`)),
    );
    assert(
      difference(master, base) < 3,
      "Fallback cannot switch between green and winter imagery",
    );
  }
  const crop = await sample(
    sharp(nasa).extract({
      left: 3 * 1800,
      top: 1 * 1800,
      width: 1800,
      height: 1800,
    }),
  );
  const tile = await sample(
    sharp(
      path.join(root, "assets/globe/blue-marble-day-tiles-21600/day-r1-c3.jpg"),
    ),
  );
  assert(
    difference(crop, tile) < 3,
    "North America detail uses the matching unflipped master crop",
  );
});
