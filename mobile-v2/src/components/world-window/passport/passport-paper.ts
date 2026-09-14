import type { StampFootprint, StampLabelBox } from './passport-footprint';
export const PAGE_WIDTH = 320, PAGE_HEIGHT = 440, BOOK_MARGIN = 12;
export type StampPlacement = { code: string; x: number; y: number; width: number; height: number; angle: number };
export type PaperPage = { kind: 'identity' | 'stamps' | 'record'; stamps: StampPlacement[] };
export type PageTexture = { canvas: HTMLCanvasElement; page: PaperPage };

/** Physical pages run from the first recorded arrival to the most recent one.
 * Keep unknown dates at the end and use a stable tie-breaker for same-day stamps. */
export function chronologicalStamps<T extends {code:string;date:string}>(stamps:readonly T[]):T[]{
  const time=(value:string)=>{const parsed=Date.parse(value);return Number.isFinite(parsed)?parsed:Infinity;};
  return [...stamps].sort((a,b)=>{
    const left=time(a.date),right=time(b.date);
    return (left===right?0:left<right?-1:1)||a.code.localeCompare(b.code);
  });
}

function random(key: string) {
  let state = 2166136261; for (const c of key) state = Math.imul(state ^ c.charCodeAt(0), 16777619);
  return () => { state += 0x6d2b79f5; let n = state; n = Math.imul(n ^ (n >>> 15), n | 1); n ^= n + Math.imul(n ^ (n >>> 7), n | 61); return ((n ^ (n >>> 14)) >>> 0) / 4294967296; };
}
export function stampBounds(s: StampPlacement) {
  const rx = Math.abs(Math.cos(s.angle)) * s.width / 2 + Math.abs(Math.sin(s.angle)) * s.height / 2;
  const ry = Math.abs(Math.sin(s.angle)) * s.width / 2 + Math.abs(Math.cos(s.angle)) * s.height / 2;
  return { left: s.x - rx, right: s.x + rx, top: s.y - ry, bottom: s.y + ry };
}
type Footprints = Record<string, StampFootprint>;
const defaultFootprint: StampFootprint = { x: 0, y: 0, width: 155, height: 165, labels: [{ x: .1, y: .12, width: .8, height: .22 }, { x: .1, y: .75, width: .8, height: .16 }] };
function polygon(stamp: StampPlacement, box: StampLabelBox = { x: 0, y: 0, width: 1, height: 1 }) {
  return [[box.x, box.y], [box.x + box.width, box.y], [box.x + box.width, box.y + box.height], [box.x, box.y + box.height]].map(([x, y]) => {
    const dx = (x - .5) * stamp.width, dy = (y - .5) * stamp.height, c = Math.cos(stamp.angle), n = Math.sin(stamp.angle);
    return { x: stamp.x + dx * c - dy * n, y: stamp.y + dx * n + dy * c };
  });
}
function intersects(a: { x: number; y: number }[], b: { x: number; y: number }[]) {
  for (const shape of [a, b]) for (let i = 0; i < shape.length; i++) {
    const next = shape[(i + 1) % shape.length], axis = { x: next.y - shape[i].y, y: shape[i].x - next.x };
    const project = (points: typeof a) => points.map(p => p.x * axis.x + p.y * axis.y), pa = project(a), pb = project(b);
    if (Math.max(...pa) < Math.min(...pb) || Math.max(...pb) < Math.min(...pa)) return false;
  }
  return true;
}
export function stampLabelsClear(stamps: StampPlacement[], footprints: Footprints = {}) {
  return stamps.every((a, i) => stamps.every((b, j) => i === j || (footprints[a.code] ?? defaultFootprint).labels.every(label =>
    !intersects(polygon(a, { x: label.x - .012, y: label.y - .012, width: label.width + .024, height: label.height + .024 }), polygon(b)))));
}
function valid(stamps: StampPlacement[], footprints: Footprints) {
  return stampLabelsClear(stamps, footprints) && stamps.every(s => {
    const b = stampBounds(s);
    return b.left >= 12 && b.right <= PAGE_WIDTH - 12 && b.top >= 12 && b.bottom <= PAGE_HEIGHT - 12 && stampAt({ kind: 'stamps', stamps }, s.x, s.y) === s.code;
  });
}
export function naturalStampPlacements(codes: string[], footprints: Footprints = {}): StampPlacement[] {
  if (!codes.length) return [];
  const rand = random(codes.join('|')), mirror = rand() > .5, upsideDown = codes.length === 3 && rand() > .5;
  const slots = codes.length === 4 ? [[89, 98], [229, 138], [91, 296], [230, 341]] : codes.length === 3 ? [[89, 98], [229, 134], [156, 326]] : codes.length === 1 ? [[160, 215]] : [[160, 109], [160, 331]];
  let base: StampPlacement[] = [];
  // Same staggered composition as the approved web passport. Later attempts
  // reserve extra room for unusually wide or tall edited stamp templates.
  for (let attempt = 0; attempt < 1200; attempt++) {
    const shrink = Math.max(.55, 1 - Math.floor(attempt / 100) * .035);
    base = codes.map((code, i) => {
      const shape = footprints[code] ?? defaultFootprint, large = codes.length === 3 && i === 2;
      const width = Math.min(codes.length <= 2 ? 264 : large ? 222 : codes.length === 3 ? 158 : 146, (codes.length <= 2 ? 204 : large ? 199 : 165) * shape.width / shape.height) * shrink * (.96 + rand() * .06);
      const height = width * shape.height / shape.width, angle = (rand() - .5) * (codes.length <= 2 ? .1 : .23);
      const rx = Math.abs(Math.cos(angle)) * width / 2 + Math.abs(Math.sin(angle)) * height / 2, ry = Math.abs(Math.sin(angle)) * width / 2 + Math.abs(Math.cos(angle)) * height / 2;
      const slot = slots[i], x = Math.max(rx + 16, Math.min(PAGE_WIDTH - rx - 16, (mirror ? PAGE_WIDTH - slot[0] : slot[0]) + (rand() - .5) * 15));
      const y = Math.max(ry + 14, Math.min(PAGE_HEIGHT - ry - 14, (upsideDown ? PAGE_HEIGHT - slot[1] : slot[1]) + (rand() - .5) * 18));
      return { code, x, y, width, height, angle };
    });
    if (valid(base, footprints)) break;
  }
  const ink = random('passport-ink-' + codes.join('|'));
  for (let attempt = 0; attempt < 400; attempt++) {
    const stamps = base.map(s => {
      const scale = (codes.length === 2 ? .89 : .94) + ink() * .12, angle = (ink() - .5) * .46;
      const width = s.width * scale, height = s.height * scale;
      const rx = Math.abs(Math.cos(angle)) * width / 2 + Math.abs(Math.sin(angle)) * height / 2, ry = Math.abs(Math.sin(angle)) * width / 2 + Math.abs(Math.cos(angle)) * height / 2;
      return { ...s, width, height, angle, x: Math.max(rx + 16, Math.min(PAGE_WIDTH - rx - 16, s.x + (ink() - .5) * 108)), y: Math.max(ry + 16, Math.min(PAGE_HEIGHT - ry - 16, s.y + (ink() - .5) * 80)) };
    });
    if (valid(stamps, footprints)) return stamps;
  }
  return base;
}
export function passportPages(codes: string[], footprints: Footprints = {}): PaperPage[] {
  const count = codes.length;
  if (!count) return [{ kind: 'identity', stamps: [] }, { kind: 'record', stamps: [] }];
  if (count <= 3) return [{ kind: 'identity', stamps: [] }, { kind: 'stamps', stamps: naturalStampPlacements(codes, footprints) }];
  const pageCount = Math.max(2, Math.floor(count / 4) * 2);
  const pages: PaperPage[] = [{ kind: 'identity', stamps: [] }]; let index = 0;
  for (let i = 0; i < pageCount; i++) {
    const take = Math.ceil((count - index) / (pageCount - i));
    pages.push({ kind: 'stamps', stamps: naturalStampPlacements(codes.slice(index, index + take), footprints) }); index += take;
  }
  pages.push({ kind: 'record', stamps: [] }); return pages;
}
export function stampAt(page: PaperPage, x: number, y: number) {
  return [...page.stamps].reverse().find(s => {
    const dx = x - s.x, dy = y - s.y, c = Math.cos(s.angle), n = Math.sin(s.angle);
    return Math.abs(dx * c + dy * n) < s.width / 2 && Math.abs(-dx * n + dy * c) < s.height / 2;
  })?.code;
}
export function passportEdgeTurn(point: { x: number; y: number }, renderedWidth: number): 1 | -1 | null {
  if (!Number.isFinite(point.x) || !Number.isFinite(point.y) || !Number.isFinite(renderedWidth) || renderedWidth <= 0 || point.x < 0 || point.x > PAGE_WIDTH * 2 || point.y < 0 || point.y > PAGE_HEIGHT) return null;
  const edge = Math.min(PAGE_WIDTH * .23, 28 * (PAGE_WIDTH * 2 + BOOK_MARGIN * 2) / renderedWidth);
  return point.x <= edge ? -1 : point.x >= PAGE_WIDTH * 2 - edge ? 1 : null;
}
