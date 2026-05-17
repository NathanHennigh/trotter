const MAPBOX_TOKEN = 'pk.eyJ1IjoibmF0aGFuaGVubmlnaCIsImEiOiJjbW9zeDFhODAwMDl2MnFvaTI4cjd0aG44In0.FSRGT0W3r42TWIk9jIbS2A';
const TILE_SIZE = 512;
// satellite-streets-v12 shows borders; we cap zoom at 4 so roads never render
const MAP_STYLE = 'satellite-streets-v12';
const MAX_ZOOM_STREETS = 4.5; // roads render around zoom 5+ on satellite-streets
const MAP_STYLE_PURE = 'satellite-v9';

const AIRPORT_COORDS: Record<string, [number, number]> = {
  IAH: [-95.3368, 29.9902], DFW: [-97.0403, 32.8998], HOU: [-95.2789, 29.6454], DAL: [-96.8517, 32.8471],
  ATL: [-84.4277, 33.6367], LAX: [-118.4081, 33.9425], ORD: [-87.9073, 41.9742], JFK: [-73.7789, 40.6398],
  EWR: [-74.1745, 40.6895], MIA: [-80.2906, 25.7959], SEA: [-122.3088, 47.4502], SFO: [-122.3789, 37.6213],
  BOS: [-71.0052, 42.3643], DEN: [-104.6737, 39.8561], LAS: [-115.1523, 36.0840], PHX: [-112.0078, 33.4373],
  CLT: [-80.9431, 35.2140], MCO: [-81.3090, 28.4312], BWI: [-76.6682, 39.1754], DCA: [-77.0377, 38.8521],
  IAD: [-77.4565, 38.9531], BNA: [-86.6774, 36.1263], SAN: [-117.1896, 32.7338], TPA: [-82.5332, 27.9755],
  PDX: [-122.5973, 45.5887], STL: [-90.3700, 38.7487], AUS: [-97.6699, 30.1975], SLC: [-111.9779, 40.7884],
  MSP: [-93.2218, 44.8848], RDU: [-78.7875, 35.8776], MSY: [-90.2580, 29.9934], OKC: [-97.6007, 35.3931],
  SAT: [-98.4698, 29.5337], ELP: [-106.3776, 31.8072], ABQ: [-106.6093, 35.0402], TUL: [-95.8881, 36.1984],
  CUN: [-86.8770, 21.0365], MEX: [-99.0721, 19.4361], PUJ: [-68.3634, 18.5674], SDQ: [-69.6689, 18.4297],
  TQO: [-87.4562, 20.2270], SJD: [-109.7210, 23.1518], SJU: [-66.0018, 18.4394], HAV: [-82.4091, 22.9892],
  MBJ: [-77.9134, 18.5037], NAS: [-77.4662, 25.0390], GCM: [-81.3576, 19.2928],
  MGA: [-86.1681, 12.1415], PTY: [-79.3835, 9.0714], SJO: [-84.2088, 9.9939], BOG: [-74.1469, 4.7016],
  GRU: [-46.4731, -23.4356], SCL: [-70.7858, -33.3930], LIM: [-77.1143, -12.0219], EZE: [-58.5358, -34.8222],
  LHR: [-0.4543, 51.4700], CDG: [2.5479, 49.0097], AMS: [4.7683, 52.3086], FRA: [8.5622, 50.0379],
  BCN: [2.0785, 41.2971], MAD: [-3.5673, 40.4936], FCO: [12.2389, 41.8003], ZRH: [8.5491, 47.4647],
  VIE: [16.5697, 48.1103], CPH: [12.6561, 55.6180], ARN: [17.9186, 59.6519], HEL: [24.9633, 60.3172],
  DUB: [-6.2700, 53.4213], LIS: [-9.1354, 38.7813], ATH: [23.9445, 37.9364], IST: [28.7498, 41.2753],
  WAW: [14.1621, 52.1657], PRG: [14.2632, 50.1008], BUD: [19.2611, 47.4298], KEF: [-22.6056, 63.9850],
  RAK: [-8.0363, 31.6069], CAI: [31.4056, 30.1219], ADD: [38.7993, 8.9779], NBO: [36.9275, -1.3192],
  JNB: [28.2460, -26.1367], CMN: [-7.5899, 33.3675], LOS: [3.3213, 6.5774],
  DXB: [55.3647, 25.2532], AUH: [54.6511, 24.4330], DOH: [51.5681, 25.2732], TLV: [34.8854, 32.0114],
  BOM: [72.8679, 19.0896], DEL: [77.1025, 28.5562], BKK: [100.7501, 13.6811], HAN: [105.8067, 21.2187],
  KUL: [101.7098, 2.7456], SIN: [103.9915, 1.3644], MNL: [121.0197, 14.5086], CGK: [106.6558, -6.1256],
  DPS: [115.1670, -8.7482], REP: [103.8127, 13.4107],
  PVG: [121.8050, 31.1434], PEK: [116.5977, 40.0799], ICN: [126.4505, 37.4602],
  NRT: [140.3864, 35.7720], HND: [139.7811, 35.5494], KIX: [135.2440, 34.4347],
  TPE: [121.2330, 25.0777], HKG: [113.9145, 22.3080],
  SYD: [151.1772, -33.9399], MEL: [144.8410, -37.6690], AKL: [174.7922, -37.0082],
};

/** Raw great-circle points — longitudes in -180..180 */
function rawGcPoints([lon1, lat1]: [number, number], [lon2, lat2]: [number, number], n: number): Array<[number, number]> {
  const D2R = Math.PI / 180, R2D = 180 / Math.PI;
  const f1 = lat1 * D2R, l1 = lon1 * D2R, f2 = lat2 * D2R, l2 = lon2 * D2R;
  const d = 2 * Math.asin(Math.sqrt(Math.sin((f2 - f1) / 2) ** 2 + Math.cos(f1) * Math.cos(f2) * Math.sin((l2 - l1) / 2) ** 2));
  if (d < 0.0001) return [[lon1, lat1]];
  return Array.from({ length: n + 1 }, (_, i) => {
    const t = i / n, A = Math.sin((1 - t) * d) / Math.sin(d), B = Math.sin(t * d) / Math.sin(d);
    const x = A * Math.cos(f1) * Math.cos(l1) + B * Math.cos(f2) * Math.cos(l2);
    const y = A * Math.cos(f1) * Math.sin(l1) + B * Math.cos(f2) * Math.sin(l2);
    const z = A * Math.sin(f1) + B * Math.sin(f2);
    return [Math.atan2(y, x) * R2D, Math.atan2(z, Math.sqrt(x * x + y * y)) * R2D] as [number, number];
  });
}

/**
 * Unwrap longitudes so they are continuous from the first point.
 * E.g. a path crossing the antimeridian might go -95 → ... → 147 → 151 ...
 * which becomes -95 → ... → -213 → -209 (always stepping < 180° between pts).
 */
function unwrapPath(pts: Array<[number, number]>): Array<[number, number]> {
  const out: Array<[number, number]> = [[...pts[0]]];
  for (let i = 1; i < pts.length; i++) {
    let lon = pts[i][0];
    const prev = out[i - 1][0];
    while (lon - prev > 180) lon -= 360;
    while (prev - lon > 180) lon += 360;
    out.push([lon, pts[i][1]]);
  }
  return out;
}

/** Bounding box → center (normalised -180..180) + zoom */
function fitBounds(pts: Array<[number, number]>, w: number, h: number, pad = 0.35): { cx: number; cy: number; z: number } {
  const lons = pts.map(p => p[0]), lats = pts.map(p => p[1]);
  const minLon = Math.min(...lons), maxLon = Math.max(...lons);
  const minLat = Math.min(...lats), maxLat = Math.max(...lats);
  const rawCx = (minLon + maxLon) / 2;
  const cx = ((rawCx % 360) + 540) % 360 - 180; // normalise to -180..180
  const cy = (minLat + maxLat) / 2;
  const lonSpan = Math.max(maxLon - minLon, 0.01);
  const latSpan = Math.max(maxLat - minLat, 0.01);
  const zLon = Math.log2((w / TILE_SIZE) * (360 / lonSpan));
  const zLat = Math.log2((h / TILE_SIZE) * (170 / latSpan));
  const z = Math.max(0.3, Math.min(Math.min(zLon, zLat) - Math.log2(1 / (1 - pad * 2)), 14));
  // (z returned uncapped — caller decides style based on z)
  return { cx, cy, z };
}

/** Web Mercator projection at the given zoom (logical CSS pixels, 512px tiles). */
function projectMercator([lon, lat]: [number, number], z: number): [number, number] {
  const ws = TILE_SIZE * Math.pow(2, z);
  const x = ((lon + 180) / 360) * ws;
  const sinLat = Math.sin(Math.max(-85, Math.min(85, lat)) * Math.PI / 180);
  const y = (0.5 - Math.log((1 + sinLat) / (1 - sinLat)) / (4 * Math.PI)) * ws;
  return [x, y];
}

// Walks the path in pixel space (not angular space) so dashes stay visually
// consistent across flight lengths, latitudes, and arc curvature.
function pixelDashedSegments(
  pts: Array<[number, number]>,
  z: number,
  dashPx: number,
  gapPx: number,
): number[][][] {
  const projected = pts.map(p => projectMercator(p, z));
  const cum: number[] = [0];
  for (let i = 1; i < projected.length; i++) {
    const dx = projected[i][0] - projected[i - 1][0];
    const dy = projected[i][1] - projected[i - 1][1];
    cum.push(cum[i - 1] + Math.sqrt(dx * dx + dy * dy));
  }
  const total = cum[cum.length - 1];
  if (total <= 0) return [];

  // Interpolate a lon/lat at cumulative pixel distance d along the path.
  const interp = (d: number): [number, number] => {
    if (d <= 0) return [pts[0][0], pts[0][1]];
    if (d >= total) return [pts[pts.length - 1][0], pts[pts.length - 1][1]];
    let lo = 0, hi = cum.length - 1;
    while (lo + 1 < hi) {
      const mid = (lo + hi) >> 1;
      if (cum[mid] <= d) lo = mid; else hi = mid;
    }
    const segLen = cum[hi] - cum[lo];
    const t = segLen > 0 ? (d - cum[lo]) / segLen : 0;
    return [
      pts[lo][0] + t * (pts[hi][0] - pts[lo][0]),
      pts[lo][1] + t * (pts[hi][1] - pts[lo][1]),
    ];
  };

  // Center the pattern so origin/dest pins each get a small gap (looks balanced).
  const period = dashPx + gapPx;
  const fullPeriods = Math.max(1, Math.floor((total - dashPx) / period));
  const used = fullPeriods * period + dashPx;
  const start = Math.max(0, (total - used) / 2);

  const round = (n: number) => Math.round(n * 1e5) / 1e5;
  const out: number[][][] = [];
  for (let i = 0; i <= fullPeriods; i++) {
    const a = start + i * period;
    const b = a + dashPx;
    if (a >= total) break;
    const aClamped = Math.max(0, a);
    const bClamped = Math.min(total, b);
    const seg: number[][] = [];
    const first = interp(aClamped);
    seg.push([round(first[0]), round(first[1])]);
    // Preserve arc curvature by keeping any path vertices that fall inside the dash.
    for (let k = 0; k < cum.length; k++) {
      if (cum[k] > aClamped && cum[k] < bClamped) {
        seg.push([round(pts[k][0]), round(pts[k][1])]);
      }
    }
    const last = interp(bClamped);
    seg.push([round(last[0]), round(last[1])]);
    out.push(seg);
  }
  return out;
}

function dashOverlay(coords: number[][][], color: string, width: number): string {
  const geojson = JSON.stringify({
    type: 'Feature',
    properties: { stroke: color, 'stroke-width': width, 'stroke-opacity': 1 },
    geometry: { type: 'MultiLineString', coordinates: coords },
  });
  return `geojson(${encodeURIComponent(geojson)})`;
}

export function mapboxFlightImageUrl(originCode: string, destCode: string, w = 400, h = 240, lineColor = '#f7e87a'): string | null {
  const origin = AIRPORT_COORDS[originCode.toUpperCase()];
  const dest   = AIRPORT_COORDS[destCode.toUpperCase()];
  if (!origin || !dest) return null;

  // Compute raw path then unwrap so longitudes are continuous (handles antimeridian)
  const raw      = rawGcPoints(origin, dest, 64); // dense sampling so projected dashes follow the arc smoothly
  const path     = unwrapPath(raw);
  const { cx, cy, z } = fitBounds(path, w, h);

  // Destination pin uses unwrapped lon so it sits in the correct tile region
  const destLon  = path[path.length - 1][0];
  const dashCoords = pixelDashedSegments(path, z, 7, 7);
  // Mapbox draws overlays in URL order — outline first, color on top, then pins.
  const dashOutline = dashOverlay(dashCoords, '#000000', 5);
  const dashColor   = dashOverlay(dashCoords, lineColor, 3);
  const pinO     = `pin-s+f5e3a0(${origin[0].toFixed(4)},${origin[1].toFixed(4)})`;
  const pinD     = `pin-s+f5e3a0(${destLon.toFixed(4)},${dest[1].toFixed(4)})`;
  const overlays = [dashOutline, dashColor, pinO, pinD].join(',');
  // Use streets style (borders visible) only while zoomed out enough that roads won't render
  const style = z <= MAX_ZOOM_STREETS ? MAP_STYLE : MAP_STYLE_PURE;

  return (
    `https://api.mapbox.com/styles/v1/mapbox/${style}/static/` +
    `${overlays}/${cx.toFixed(4)},${cy.toFixed(4)},${z.toFixed(2)}/${w}x${h}@2x` +
    `?access_token=${MAPBOX_TOKEN}`
  );
}

export function hasAirportCoords(code: string): boolean {
  return code.toUpperCase() in AIRPORT_COORDS;
}
