// This DOM/canvas entry is compiled into passport-runtime.generated.ts. It runs
// locally inside WebView (or a sandboxed web iframe), never on a remote site.
import { PassportController } from './passport-controller';
import { PassportCoverController, passportPoint, passportPose } from './passport-cover';
import { drawPassport } from './passport-canvas';
import { PAGE_WIDTH as W, PAGE_HEIGHT as H, BOOK_MARGIN as M, passportPages, chronologicalStamps, passportEdgeTurn, stampAt, type PageTexture } from './passport-paper';
import { makeTextures } from './passport-textures';
import { stampFootprint } from './passport-footprint';
import { coverEmblem } from './passport-cover-art';
import type { BookPayload } from './passport-payload';
import { passportPageDescription } from './passport-accessibility';

type NativeWindow = Window & { ReactNativeWebView?: { postMessage: (data: string) => void }; __PASSPORT__: BookPayload; updatePassport?: (payload: BookPayload) => void };
const bridge = window as unknown as NativeWindow;
const post = (type: string, data: Record<string, unknown> = {}) => {
  const message = { source: 'trotter-passport', type, ...data };
  if (bridge.ReactNativeWebView) bridge.ReactNativeWebView.postMessage(JSON.stringify(message));
  else window.parent.postMessage(message, '*');
};
const host = document.getElementById('book')!, canvas = document.getElementById('paper') as HTMLCanvasElement;
const scene = document.getElementById('cover-scene')!, board = document.getElementById('cover-board')!, back = document.getElementById('cover-back') as HTMLCanvasElement;
const targets = document.getElementById('targets')!, loading = document.getElementById('loading')!, status = document.getElementById('status')!;
const description = document.getElementById('page-description')!;
document.getElementById('emblem')!.innerHTML = coverEmblem;
const pagesFor = (data: BookPayload) => passportPages(chronologicalStamps(data.stamps).map(s => s.code), Object.fromEntries(data.stamps.map(s => [s.code, stampFootprint(s.template)])));
let payload = bridge.__PASSPORT__, pages = pagesFor(payload), textures: PageTexture[] = [];
let model = new PassportController(pages.length / 2, payload.state?.spread ?? 0), cover = new PassportCoverController(payload.state?.closed ?? true);
let ready = false, disposed = false, generation = 0, lastBack: HTMLCanvasElement | undefined, lastReported = '', lastTargets = '', lastHeight = 0, lastHeightAt = 0;
let frame = 0, lastTime = 0, pointer: null | { id: number; left: number; top: number; factor: number; kind: 'paper' | 'cover'; x: number; y: number; moved: boolean } = null;
const reduced = () => matchMedia('(prefers-reduced-motion: reduce)').matches;
const position = (event: PointerEvent) => {
  const box = host.getBoundingClientRect(), space = pointer ?? { left: box.left, top: box.top, factor: (W * 2 + M * 2) / box.width };
  const x = (event.clientX - space.left) * space.factor, y = (event.clientY - space.top) * space.factor;
  return { stage: { x, y }, paper: passportPoint(x, y, cover.progress,box.width) };
};
function button(label: string, className: string, action: () => void) {
  const b = document.createElement('button'); b.type = 'button'; b.className = className; b.setAttribute('aria-label', label);
  b.addEventListener('click', event => { if (event.detail === 0) action(); }); targets.append(b); return b;
}
function refreshTargets() {
  const blocked = cover.blocksPages, key = `${blocked}-${Boolean(model.fold)}-${ready}-${model.spread}`;
  if (key === lastTargets) return; lastTargets = key; const focused = targets.contains(document.activeElement); targets.replaceChildren();
  description.replaceChildren();
  if (ready && !blocked && !model.fold) for (const page of pages.slice(model.spread * 2, model.spread * 2 + 2)) {
    const copy = passportPageDescription(page, payload); if (!copy) continue;
    const section = document.createElement('section'); section.setAttribute('aria-label', copy.label);
    for (const line of copy.lines) { const paragraph = document.createElement('p'); paragraph.textContent = line; section.append(paragraph); }
    description.append(section);
  }
  host.tabIndex = blocked ? -1 : 0;
  if (blocked) button('Open passport', 'cover-target', () => { cover.go(1, true); wake(); host.focus(); });
  else {
    if (ready && !model.fold) for (const side of [0, 1]) for (const stamp of pages[model.spread * 2 + side]?.stamps ?? []) {
      const arrival = payload.stamps.find(s => s.code === stamp.code)!;
      const target = button(`${arrival.country}, first entry ${arrival.airport}, ${arrival.date}`, 'stamp-target', () => post('country', { code: stamp.code }));
      const pose=passportPose(1,host.getBoundingClientRect().width);
      Object.assign(target.style, { left: `${(M + side * W + stamp.x) / pose.width * 100}%`, top: `${(pose.top + stamp.y) / pose.height * 100}%`, width: `${stamp.width / pose.width * 100}%`, height: `${stamp.height / pose.height * 100}%`, transform: `translate(-50%,-50%) rotate(${stamp.angle}rad)` });
    }
    button(model.spread === 0 ? 'Close passport' : 'Previous pages', 'edge-target previous', () => go(-1, true));
    if (ready && model.spread < pages.length / 2 - 1) button('Next pages', 'edge-target next', () => go(1, true));
  }
  if (focused) (blocked ? targets.querySelector('button') : host)?.focus({ preventScroll: true });
}
function paint() {
  if (disposed) return;
  const width = host.getBoundingClientRect().width; if (!width) return;
  const pose = passportPose(cover.progress,width), pixelScale = width / pose.width * Math.min(3, devicePixelRatio || 1);
  host.style.height = `${width * pose.height / pose.width}px`;
  const w = Math.round(pose.width * pixelScale), h = Math.round(pose.height * pixelScale);
  if (canvas.width !== w) canvas.width = w; if (canvas.height !== h) canvas.height = h;
  const c = canvas.getContext('2d'); if (c) drawPassport(c, textures, model.spread, model.fold, pixelScale, cover.blocksPages ? { ...pose, progress: cover.progress } : undefined, 'window',pose.top);
  scene.style.display = cover.blocksPages ? 'block' : 'none'; scene.style.height = `${width * (H + M * 2) / pose.width}px`;
  scene.style.transform = `translateX(${pose.scale * pose.offset / pose.width * 100}%) scale(${pose.scale})`;
  scene.style.top = `${(pose.top-M)*width/pose.width}px`;
  board.style.transform = `rotateY(${-180 * cover.progress}deg)`;
  const sheet = textures[model.spread * 2]?.canvas;
  if (sheet && sheet !== lastBack) { back.width = sheet.width; back.height = sheet.height; back.getContext('2d')?.drawImage(sheet, 0, 0); lastBack = sheet; }
  loading.hidden = ready || cover.blocksPages;
  refreshTargets();
  const settled = !cover.busy && !model.fold;
  const stateKey = `${model.spread}-${cover.settled}-${settled}`;
  if (stateKey !== lastReported && settled) { lastReported = stateKey; status.textContent = cover.progress === 0 ? 'Passport closed' : `Pages ${model.spread * 2 + 1} and ${model.spread * 2 + 2} of ${pages.length}`; post('state', { spread: model.spread, closed: cover.progress === 0 }); }
  const height = Math.ceil(width * pose.height / pose.width), now = performance.now();
  if (Math.abs(lastHeight - height) >= 1 && (settled || now - lastHeightAt > 25)) { lastHeight = height; lastHeightAt = now; post('size', { height }); }
}
function tick(time: number) { frame = 0; if (disposed) return; const dt = lastTime ? time - lastTime : 16; model.advance(dt); cover.advance(dt); lastTime = time; paint(); if (model.settling || cover.settling) frame = requestAnimationFrame(tick); }
function wake() { paint(); if (!frame && (model.settling || cover.settling)) { lastTime = performance.now(); frame = requestAnimationFrame(tick); } }
function go(direction: 1 | -1, instant = false) {
  if (cover.blocksPages) return;
  if (direction === -1 && model.spread === 0) { model.cancel(); cover.go(0, instant || reduced()); }
  else if (ready) model.go(direction, instant || reduced());
  wake(); if (instant) (cover.progress === 0 ? targets.querySelector('button') : host)?.focus({ preventScroll: true });
}
function finish(event: PointerEvent, cancel = false) {
  if (!pointer || pointer.id !== event.pointerId) return;
  const point = position(event).paper, current = pointer;
  const moved = current.moved || Math.hypot(event.clientX - current.x, event.clientY - current.y) > 6;
  pointer = null; if (host.hasPointerCapture(event.pointerId)) host.releasePointerCapture(event.pointerId); post('gesture', { active: false });
  const edge = passportEdgeTurn(point, host.getBoundingClientRect().width);
  if (current.kind === 'cover') {
    const tapCloses = !cancel && !moved && cover.progress === 1 && edge === -1;
    cover.release(cancel || (moved && !cover.grab?.moved), reduced(), performance.now());
    if (tapCloses) { model.cancel(); cover.go(0, reduced()); } wake(); return;
  }
  const turned = model.release(cancel, reduced(), performance.now()); wake();
  if (!turned && !moved && !cancel) {
    if (edge) { go(edge); return; }
    const side = point.x < W ? 0 : 1, page = pages[model.spread * 2 + side];
    const code = page && stampAt(page, point.x - side * W, point.y); if (code) post('country', { code });
  }
}
host.addEventListener('pointerdown', event => {
  if (pointer || !event.isPrimary || event.button !== 0 || (event.target as HTMLElement).closest('#loading')) return;
  const point = position(event).paper;
  if (point.x < 0 || point.x > W * 2 || point.y < 0 || point.y > H) return;
  const hard = cover.blocksPages || model.spread === 0 && point.x < W && !model.fold;
  if (hard && cover.progress === 0 && point.x < W || !hard && !ready) return;
  const box = host.getBoundingClientRect(); pointer = { id: event.pointerId, left: box.left, top: box.top, factor: (W * 2 + M * 2) / box.width, kind: hard ? 'cover' : 'paper', x: event.clientX, y: event.clientY, moved: false };
  event.preventDefault(); host.setPointerCapture(event.pointerId); cancelAnimationFrame(frame); frame = 0; post('gesture', { active: true });
  if (hard) { model.cancel(); cover.begin(position(event).stage.x, performance.now()); } else model.begin(point, performance.now()); wake();
});
host.addEventListener('pointermove', event => {
  if (!pointer || pointer.id !== event.pointerId) return;
  pointer.moved ||= Math.hypot(event.clientX - pointer.x, event.clientY - pointer.y) > 6;
  if (pointer.kind === 'cover') cover.move(position(event).stage.x, performance.now()); else model.move(position(event).paper, performance.now());
  if (!reduced()) wake();
});
host.addEventListener('pointerup', event => finish(event)); host.addEventListener('pointercancel', event => finish(event, true)); host.addEventListener('lostpointercapture', event => finish(event, true));
host.addEventListener('keydown', event => { if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') { event.preventDefault(); go(event.key === 'ArrowLeft' ? -1 : 1, true); } });
async function update(next: BookPayload) {
  const token = ++generation;
  try {
    for (const [name, source] of Object.entries(next.fonts)) { if (document.fonts.check(`16px ${name}`) && payload.fonts[name] === source && textures.length) continue; const font = new FontFace(name, `url(${source})`); await font.load(); (document.fonts as FontFaceSet & { add: (font: FontFace) => FontFaceSet }).add(font); }
    const nextPages = pagesFor(next), nextTextures = await makeTextures(nextPages, next);
    if (disposed || token !== generation) return;
    const savedSpread = model.spread, closed = cover.settled === 0;
    if (pointer) { const id = pointer.id; pointer = null; if (host.hasPointerCapture(id)) host.releasePointerCapture(id); post('gesture', { active: false }); }
    model.cancel(); cover.snap(closed ? 0 : 1); model = new PassportController(nextPages.length / 2, savedSpread);
    pages = nextPages; textures = nextTextures; payload = next; ready = true; lastTargets = ''; lastBack = undefined; wake(); post('ready');
  } catch { if (token !== generation || disposed) return; loading.replaceChildren(); const text = document.createElement('span'); text.textContent = 'Passport could not load.'; const retry = document.createElement('button'); retry.textContent = 'Try again'; retry.addEventListener('click', () => { void update(next); }); loading.append(text, retry); post('error'); paint(); }
}
bridge.updatePassport = next => { void update(next); };
window.addEventListener('message', event => { if (event.source === window.parent && event.data?.type === 'passport-update') void update(event.data.payload); });
const resize = new ResizeObserver(paint); resize.observe(host); window.addEventListener('resize', paint);
document.addEventListener('visibilitychange', () => { if (document.hidden) { pointer = null; model.cancel(); cover.snap(cover.settled); cancelAnimationFrame(frame); frame = 0; post('gesture', { active: false }); paint(); } });
window.addEventListener('pagehide', () => { disposed = true; generation++; cancelAnimationFrame(frame); resize.disconnect(); });
paint(); void update(payload);
