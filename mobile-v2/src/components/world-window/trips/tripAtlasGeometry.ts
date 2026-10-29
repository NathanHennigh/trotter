import type { TripSegmentSummary } from "../../../data/trotterMock";
import { validPoint } from "./tripPresentation";

export type MapLand = {
  features: { geometry: { type: string; coordinates: unknown } | null }[];
};
type Vector = [number, number, number];
type MapPoint = [number, number];
type AtlasLabel = { x: number; y: number; width: number; height: number };
type AtlasPort = { code: string; x: number; y: number; radius: number; label?: AtlasLabel };
// These are the painted backgrounds used by TripAtlas, not just text bounds.
const labelBounds = (label: AtlasLabel) => ({
  left: label.x - 3, top: label.y - 1,
  right: label.x + label.width + 3, bottom: label.y + label.height,
});
const endpoint = (lon: number, lat: number): Vector => {
  const l = (lon * Math.PI) / 180,
    p = (lat * Math.PI) / 180;
  return [Math.cos(p) * Math.sin(l), Math.sin(p), Math.cos(p) * Math.cos(l)];
};
function arc(a: Vector, b: Vector) {
  const theta = Math.acos(
    Math.max(
      -1,
      Math.min(
        1,
        a.reduce((sum, n, i) => sum + n * b[i], 0),
      ),
    ),
  );
  const sin = Math.sin(theta);
  return Array.from({ length: 65 }, (_, index): Vector => {
    const t = index / 64;
    if (index === 0) return a;
    if (index === 64) return b;
    if (theta < 0.000001) return a;
    if (Math.abs(sin) < 0.00001) {
      const axis: Vector = Math.abs(a[1]) < 0.9 ? [0, 1, 0] : [1, 0, 0];
      const dot = axis.reduce((sum, n, i) => sum + n * a[i], 0);
      const v = axis.map((n, i) => n - a[i] * dot),
        length = Math.hypot(...v);
      return a.map(
        (n, i) =>
          n * Math.cos(theta * t) + (v[i] / length) * Math.sin(theta * t),
      ) as Vector;
    }
    return a.map(
      (n, i) =>
        (n * Math.sin((1 - t) * theta)) / sin +
        (b[i] * Math.sin(t * theta)) / sin,
    ) as Vector;
  });
}

/** A wrapped longitude is a break in the drawing, not a flight across the map. */
function splitRouteAtSeam(points: MapPoint[], left: number, right: number): MapPoint[][] {
  const period = right - left;
  const pieces: MapPoint[][] = [];
  let piece = [points[0]];
  for (let i = 1; i < points.length; i += 1) {
    const previous = points[i - 1], current = points[i];
    const jump = current[0] - previous[0];
    if (Math.abs(jump) > period / 2) {
      const edge = jump > 0 ? left : right;
      const unwrappedX = current[0] + (jump > 0 ? -period : period);
      const fraction = (edge - previous[0]) / (unwrappedX - previous[0]);
      const y = previous[1] + (current[1] - previous[1]) * fraction;
      piece.push([edge, y]);
      pieces.push(piece);
      piece = [[jump > 0 ? right : left, y]];
    }
    piece.push(current);
  }
  pieces.push(piece);
  return pieces;
}

/** Same fitted regional atlas and collision-free labels as the approved web wallet. */
export function tripAtlasGeometry(
  segments: TripSegmentSummary[],
  land: MapLand | null,
  destination?: string,
  options: { maxLabels?: number; prioritizeByFrequency?: boolean } = {},
) {
  const airports = new Map<
    string,
    NonNullable<TripSegmentSummary["depPoint"]>
  >();
  for (const flight of segments)
    for (const point of [flight.depPoint, flight.arrPoint])
      if (validPoint(point)) airports.set(point.code, point);
  if (!airports.size)
    return {
      landPath: "",
      paths: [] as string[],
      ports: [] as AtlasPort[],
    };
  const lons = [...airports.values()]
    .map((p) => (p.lon + 360) % 360)
    .sort((a, b) => a - b);
  const gaps = lons.map(
    (lon, i) =>
      lons[(i + 1) % lons.length] + (i === lons.length - 1 ? 360 : 0) - lon,
  );
  const gap = gaps.indexOf(Math.max(...gaps)),
    left = lons[(gap + 1) % lons.length],
    right = lons[gap] + (lons[gap] < left ? 360 : 0),
    center = (left + right) / 2;
  const normalize = (lon: number) => {
    while (lon - center > 180) lon -= 360;
    while (lon - center < -180) lon += 360;
    return lon;
  };
  const latCenter =
    [...airports.values()].reduce((sum, p) => sum + p.lat, 0) / airports.size;
  const longitudeRoutes = segments
    .filter((f) => validPoint(f.depPoint) && validPoint(f.arrPoint))
    .map((f) =>
      arc(
        endpoint(f.depPoint!.lon, f.depPoint!.lat),
        endpoint(f.arrPoint!.lon, f.arrPoint!.lat),
      ).map((p): MapPoint => [
        normalize((Math.atan2(p[0], p[2]) * 180) / Math.PI),
        (-Math.atan2(p[1], Math.hypot(p[0], p[2])) * 180) / Math.PI,
      ]),
    );
  const wrapsWorld = longitudeRoutes.some((route) => route.some((point, i) => i > 0 && Math.abs(point[0] - route[i - 1][0]) > 180));
  // Regional atlases retain their fitted projection. A route crossing the seam
  // needs one complete world width, so the two sides are the same longitude
  // and the continuation is flush with the visible left/right map edges.
  const cosine = wrapsWorld ? 1 : Math.max(0.4, Math.cos((latCenter * Math.PI) / 180));
  const coordinates = longitudeRoutes.map((route) => route.map(([x, y]): MapPoint => [x * cosine, y]));
  const routePieces = coordinates.map((route) => splitRouteAtSeam(route, (center - 180) * cosine, (center + 180) * cosine));
  // Exact seam intersections keep the same fit for a route in either direction.
  // Include known endpoints even when the other end of their route has no pin.
  const points = [
    ...routePieces.flat(2),
    ...[...airports.values()].map((p) => [normalize(p.lon) * cosine, -p.lat]),
  ];
  const xs = points.map((p) => p[0]),
    ys = points.map((p) => p[1]);
  const minX = Math.min(...xs),
    maxX = Math.max(...xs),
    minY = Math.min(...ys),
    maxY = Math.max(...ys);
  const scale = wrapsWorld ? 400 / 360 : Math.min(
      330 / Math.max(20, maxX - minX),
      165 / Math.max(12, maxY - minY),
    ),
    midX = wrapsWorld ? center : (minX + maxX) / 2,
    midY = (minY + maxY) / 2;
  const project = ([x, y]: number[]) => [
    200 + (x - midX) * scale,
    115 + (y - midY) * scale,
  ];
  const path = (points: number[][]) =>
    points
      .map(
        (point, i) =>
          (i ? "L" : "M") +
          project(point)
            .map((n) => n.toFixed(2))
            .join(","),
      )
      .join("");
  const landPath =
    land?.features
      .flatMap((feature) => {
        const geometry = feature.geometry;
        if (!geometry) return [];
        const polygons =
          geometry.type === "Polygon"
            ? [geometry.coordinates as number[][][]]
            : (geometry.coordinates as number[][][][]);
        return polygons.flatMap((polygon) => {
          const ring = polygon[0];
          if (!ring?.length) return [];
          const lonMin = Math.min(...ring.map((p) => p[0])),
            lonMax = Math.max(...ring.map((p) => p[0])),
            latMin = Math.min(...ring.map((p) => -p[1])),
            latMax = Math.max(...ring.map((p) => -p[1]));
          return [-720, -360, 0, 360, 720]
            .filter(
              (offset) =>
                (lonMax + offset) * cosine >= midX - 200 / scale &&
                (lonMin + offset) * cosine <= midX + 200 / scale &&
                latMax >= midY - 115 / scale &&
                latMin <= midY + 115 / scale,
            )
            .map((offset) =>
              polygon
                .map(
                  (ring) =>
                    path(
                      ring.map(([lon, lat]) => [(lon + offset) * cosine, -lat]),
                    ) + "Z",
                )
                .join(""),
            );
        });
      })
      .join("") ?? "";
  const labels: AtlasLabel[] = [];
  const frequency = new Map<string, number>();
  for (const segment of segments) for (const code of [segment.depAirport, segment.arrAirport])
    frequency.set(code, (frequency.get(code) ?? 0) + 1);
  const projected = [...airports.keys()]
    .sort((a, b) => Number(b === destination) - Number(a === destination)
      || (options.prioritizeByFrequency ? (frequency.get(b) ?? 0) - (frequency.get(a) ?? 0) : 0) || a.localeCompare(b))
    .map((code) => {
      const airport = airports.get(code)!,
        [x, y] = project([normalize(airport.lon) * cosine, -airport.lat]);
      return { code, x, y, radius: code === destination ? 4.2 : 2.7 };
    });
  const ports: AtlasPort[] = projected.map((port) => {
    if (labels.length >= (options.maxLabels ?? Infinity)) return port;
    const { x, y } = port;
    const label = [
      [x + 9, y - 15],
      [x - 41, y - 15],
      [x + 9, y + 5],
      [x - 41, y + 5],
      [x - 16, y - 23],
      [x - 16, y + 9],
    ]
      .map(([x, y]) => ({
        x: Math.max(7, Math.min(361, x)),
        y: Math.max(7, Math.min(210, y)),
        width: 32,
        height: 16,
      }))
      .find((candidate) => {
        const a = labelBounds(candidate);
        return labels.every((label) => {
          const b = labelBounds(label);
          return a.left > b.right + 3 || a.right + 3 < b.left || a.top > b.bottom + 3 || a.bottom + 3 < b.top;
        }) && projected.every((marker) => {
          // Circle/rectangle distance also protects neighboring markers that
          // have not yet received a label. Include stroke and breathing room.
          const dx = marker.x - Math.max(a.left, Math.min(a.right, marker.x));
          const dy = marker.y - Math.max(a.top, Math.min(a.bottom, marker.y));
          return Math.hypot(dx, dy) >= marker.radius + 0.6 + 1;
        });
      });
    if (label) labels.push(label);
    return { ...port, label };
  });
  return { landPath, paths: routePieces.map((pieces) => pieces.map(path).join('')), ports };
}

/** Reopening a wallet should reuse its coastline projection, including across
    equivalent provider snapshots. Keep only a bounded set of recent maps. */
export function createTripAtlasGeometryCache(limit = 24) {
  const maps = new Map<string, ReturnType<typeof tripAtlasGeometry>>();
  let lastLand: MapLand | null | undefined;
  return (segments: TripSegmentSummary[], land: MapLand | null, destination?: string,
    options: { maxLabels?: number; prioritizeByFrequency?: boolean } = {}) => {
    if (land !== lastLand) { maps.clear(); lastLand = land; }
    const pointKey = (point: TripSegmentSummary["depPoint"]) => point ? [point.code, point.lat, point.lon] : null;
    const key = JSON.stringify([destination, options.maxLabels, Boolean(options.prioritizeByFrequency),
      segments.map(segment => [segment.depAirport, segment.arrAirport, pointKey(segment.depPoint), pointKey(segment.arrPoint)])]);
    const cached = maps.get(key);
    if (cached) { maps.delete(key); maps.set(key, cached); return cached; }
    const result = tripAtlasGeometry(segments, land, destination, options);
    maps.set(key, result);
    if (maps.size > Math.max(1, limit)) maps.delete(maps.keys().next().value!);
    return result;
  };
}
