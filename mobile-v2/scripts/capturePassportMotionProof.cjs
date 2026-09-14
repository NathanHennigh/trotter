// Offline visual regression proof of the actual bundled passport DOM/runtime.
// No preview server, account data, product QA hooks, or controller mutations.
// Run from any cwd: node mobile-v2/scripts/capturePassportMotionProof.cjs --label after
// Use --diagnostic for a pre-fix capture: reports clipping without exiting early.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');
const ts = require('typescript');
const { chromium } = require('C:/Users/natha/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');

const root = path.resolve(__dirname, '..');
const out = path.resolve(root, '../artifacts/world-window-fidelity');
const args = process.argv.slice(2);
const label = args.includes('--label') ? args[args.indexOf('--label') + 1] : 'after';
if (!label || !/^[a-z0-9_-]+$/i.test(label)) throw new Error('Choose an alphanumeric --label.');
const diagnostic = args.includes('--diagnostic');
const cache = new Map();
function load(file) {
  if (cache.has(file)) return cache.get(file).exports;
  const result = { exports: {} }; cache.set(file, result);
  const output = ts.transpileModule(fs.readFileSync(file, 'utf8'), {
    fileName: file,
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, esModuleInterop: true },
  }).outputText;
  new Function('module', 'exports', 'require', output)(result, result.exports, request => {
    if (!request.startsWith('.')) return require(request);
    const base = path.resolve(path.dirname(file), request);
    if (/\.(png|ttf)$/.test(base)) return base;
    if (base.endsWith('.json')) return JSON.parse(fs.readFileSync(base, 'utf8'));
    const resolved = [base, base + '.ts', base + '.tsx', base + '.js'].find(candidate => fs.existsSync(candidate) && fs.statSync(candidate).isFile());
    if (!resolved) throw new Error('Missing offline passport dependency: ' + request);
    return load(resolved);
  });
  return result.exports;
}
const component = file => load(path.join(root, 'src/components/world-window/passport', file));
const uri = (file, mime) => `data:${mime};base64,${fs.readFileSync(file).toString('base64')}`;
const { stampIdentity } = load(path.join(root, 'src/components/trotter/stamps/stampIdentity.ts'));
const { countryIconAssets, stampShapeAssets } = load(path.join(root, 'src/assets/generated/stampAssetManifest.ts'));
const { nativeStampTemplate } = component('passport-native-template.ts');
const { passportDocument } = component('passport-document.ts');
const { PAGE_WIDTH, PAGE_HEIGHT, BOOK_MARGIN } = component('passport-paper.ts');
const { passportPose, passportViewportHeight } = component('passport-cover.ts');
const stageWidth = PAGE_WIDTH * 2 + BOOK_MARGIN * 2;
const shapes = {
  archedCountryCanonical: 'arched_country_canonical', archedCountryBanner: 'arched_country_banner',
  archedCountryVariant: 'arched_country_variant', circularCityClean: 'circular_city_clean',
  circularCityDoubleLine: 'circular_city_double_line', roundedImmigrationCanonical: 'rounded_immigration_canonical',
  roundedImmigrationWithBand: 'rounded_immigration_with_band', shieldBadgeRounded: 'shield_badge_rounded',
};
const countries = [
  ['JP', 'Japan', 'NRT'], ['SG', 'Singapore', 'SIN'], ['TW', 'Taiwan', 'TPE'], ['PH', 'Philippines', 'MNL'],
  ['DO', 'Dominican Republic', 'PUJ'], ['MX', 'Mexico', 'MEX'], ['NI', 'Nicaragua', 'MGA'], ['ET', 'Ethiopia', 'ADD'],
  ['SL', 'Somaliland', 'HGA'], ['AE', 'United Arab Emirates', 'DXB'], ['NL', 'Netherlands', 'AMS'], ['TN', 'Tunisia', 'TUN'],
  ['DE', 'Germany', 'FRA'], ['GB', 'United Kingdom', 'LHR'], ['FR', 'France', 'CDG'], ['US', 'United States', 'IAH'], ['CA', 'Canada', 'YYZ'],
];
// Same synthetic archive, local fonts, and native stamp artwork as capturePassportProof.
const payload = {
  name: 'Traveler', airportLabel: 'Most used airport', homeAirport: 'IAH', homeAirportName: 'Houston',
  homeAirportCountry: 'United States', firstFlightDate: '2016-01-01', flights: 145, miles: 283884,
  countries: countries.length, years: [{ year: 2016, flights: 4 }, { year: 2020, flights: 14 }, { year: 2025, flights: 31 }],
  fonts: {}, stamps: [],
};
for (const [name, file] of Object.entries({ Newsreader: 'Newsreader-Regular', DMSans: 'DMSans-Regular', DMSansBold: 'DMSans-Bold', PlexMono: 'IBMPlexMono-Medium' })) {
  payload.fonts[name] = uri(path.join(root, 'assets/world-window/fonts', file + '.ttf'), 'font/ttf');
}
for (const [code, country, airport] of countries) {
  const identity = stampIdentity(country, code), prefix = country.toLowerCase().replace(/[^a-z0-9]+/g, '_');
  const art = country === 'Nicaragua' ? 'costa_rica_arenal_volcano'
    : Object.keys(countryIconAssets).find(key => key.startsWith((country === 'Somaliland' ? 'somaliland' : prefix) + '_'));
  payload.stamps.push({
    code, country: country.toUpperCase(), airport, date: '2025-01-17', color: identity.color,
    frame: uri(stampShapeAssets[shapes[identity.shape]], 'image/png'),
    icon: art ? uri(countryIconAssets[art], 'image/png') : country === 'Tunisia'
      ? uri(path.join(root, 'assets/world-window/passport/tunisia_el_jem.png'), 'image/png') : undefined,
    template: nativeStampTemplate(identity.shape, country.toUpperCase()),
  });
}

const report = {
  label, diagnostic, source: 'mobile-v2/src/components/world-window/passport/passport-document.ts',
  sourceSha256: Object.fromEntries(['passport-document.ts', 'passport-cover.ts', 'passport-runtime.generated.ts'].map(file => [file,
    crypto.createHash('sha256').update(fs.readFileSync(path.join(root, 'src/components/world-window/passport', file))).digest('hex')])),
  scope: 'Current bundled runtime in offline Chromium, real pointer gestures and CSS perspective; normal motion. Uses the same stable viewport envelope as native PassportBook. Native bridge delivery and Android touch behavior are not asserted.',
  toleranceCssPixels: 1, widths: [], failures: [],
};
function record(condition, message, detail) {
  if (!condition) report.failures.push({ message, ...detail });
}
async function sample(page, name, expectedProgress) {
  const result = await page.evaluate(() => {
    const host = document.getElementById('book'), board = document.getElementById('cover-board');
    const rect = element => { const b = element.getBoundingClientRect(); return { left: b.left, right: b.right, top: b.top, bottom: b.bottom, width: b.width, height: b.height }; };
    const match = board.style.transform.match(/rotateY\(([-\d.]+)deg\)/);
    const angle = match ? Number(match[1]) : 0, progress = -angle / 180;
    const visible = getComputedStyle(document.getElementById('cover-scene')).display !== 'none';
    const faceName = progress < .5 ? 'cover-front' : 'cover-back';
    const face = document.querySelector('.' + faceName), book = rect(host), faceRect = rect(face);
    const canvas = document.getElementById('paper'), context = canvas.getContext('2d');
    const opaquePixels = pixels => { let count = 0; for (let i = 3; i < pixels.length; i += 4) if (pixels[i] > 80) count++; return count; };
    const paperEdgeInk = context ? {
      top: opaquePixels(context.getImageData(0, 0, canvas.width, 1).data),
      bottom: opaquePixels(context.getImageData(0, canvas.height - 1, canvas.width, 1).data),
      left: opaquePixels(context.getImageData(0, 0, 1, canvas.height).data),
      right: opaquePixels(context.getImageData(canvas.width - 1, 0, 1, canvas.height).data),
    } : {};
    return {
      progress, faceName, visible, book, face: faceRect, status: document.getElementById('status').textContent,
      viewport: { width: innerWidth, height: innerHeight },
      paperEdgeInk,
      clipping: visible ? { left: Math.max(0, book.left - faceRect.left), right: Math.max(0, faceRect.right - book.right), top: Math.max(0, book.top - faceRect.top), bottom: Math.max(0, faceRect.bottom - book.bottom) } : {},
      interaction: window.__messages.filter(m => m.type === 'gesture').at(-1)?.active ?? false,
    };
  });
  if (expectedProgress !== undefined) record(Math.abs(result.progress - expectedProgress) < .015, 'Pointer drag did not reach expected cover angle', { name, expectedProgress, ...result });
  for (const [edge, amount] of Object.entries(result.clipping)) record(amount <= report.toleranceCssPixels, 'Projected visible rigid cover is clipped', { name, edge, amount, progress: result.progress, book: result.book, face: result.face });
  if (result.visible) record(result.face.left >= -1 && result.face.top >= -1 && result.face.right <= result.viewport.width + 1 && result.face.bottom <= result.viewport.height + 1,
    'Projected visible cover escapes the stable native viewport', { name, face: result.face, viewport: result.viewport });
  record(result.book.bottom <= result.viewport.height + 1, 'Book/canvas exceeds the stable native viewport', { name, book: result.book, viewport: result.viewport });
  return { name, ...result };
}
async function capture(page, width, name) {
  const filename = `passport-motion-${label}-${width}-${name}.png`;
  const box = await page.locator('#book').boundingBox();
  await page.screenshot({ path: path.join(out, filename), clip: { x: 0, y: 0, width, height: Math.min(page.viewportSize().height, Math.ceil(box.height + 12)) } });
  return filename;
}
async function waitForState(page, spread, closed) {
  await page.waitForFunction(({ spread, closed }) => {
    const state = window.__messages.filter(m => m.type === 'state').at(-1);
    return state?.spread === spread && state.closed === closed;
  }, { spread, closed }, { timeout: 4000 });
}
async function coverDrag(page, width, opening, entry) {
  const face = await page.locator(opening ? '.cover-front' : '#paper').boundingBox();
  const start = opening ? { x: face.x + face.width - 14, y: face.y + 16 }
    : { x: width * .13, y: face.y + face.height * .78 };
  await page.mouse.move(start.x, start.y); await page.mouse.down();
  const distance = PAGE_WIDTH * 1.5 * width / stageWidth;
  for (let i = 1; i < 20; i++) {
    const travel = i / 20, progress = opening ? travel : 1 - travel;
    await page.mouse.move(start.x + (opening ? -1 : 1) * distance * travel, start.y, { steps: 2 });
    await page.waitForTimeout(18);
    const name = `${opening ? 'opening' : 'closing'}-${Math.round(progress * 100)}`;
    const result = await sample(page, name, progress); entry.samples.push(result);
    record(result.interaction, 'Gesture was not captured while the cover was held', { width, name });
    if ([25, 75, 90].includes(Math.round(progress * 100))) entry.images.push(await capture(page, width, name));
  }
  await page.mouse.up(); await waitForState(page, 0, !opening);
  entry.samples.push(await sample(page, opening ? 'fully-open' : 'fully-closed', opening ? 1 : 0));
  const active = await page.evaluate(() => window.__messages.filter(m => m.type === 'gesture').at(-1)?.active);
  record(active === false, 'Released cover left the native gesture lock active', { width, opening });
}
async function paperFold(page, width, corner, entry) {
  const box = await page.locator('#book').boundingBox();
  const pose = passportPose(1, width), factor = width / pose.width;
  // Actual paper coordinates, independent of the canvas's overscan margins.
  const start = {
    x: box.x + ((PAGE_WIDTH - 24 + pose.offset) * pose.scale + pose.width / 2) * factor,
    y: box.y + (pose.top + PAGE_HEIGHT * (corner === 'upper' ? .1 : .9) * pose.scale) * factor,
  };
  const before = await page.locator('#paper').evaluate(canvas => canvas.toDataURL());
  await page.mouse.move(start.x, start.y); await page.mouse.down();
  for (const portion of [.25, .75, .9]) {
    const distance = PAGE_WIDTH * 2 * portion * width / stageWidth;
    await page.mouse.move(start.x - distance, start.y + (corner === 'upper' ? 1 : -1) * PAGE_HEIGHT * factor * .16 * portion, { steps: 5 });
    await page.waitForTimeout(25);
    const name = `${corner}-paper-${Math.round(portion * 100)}`;
    const result = await sample(page, name, 1); entry.samples.push(result);
    const paperChanged = await page.locator('#paper').evaluate((canvas, previous) => canvas.toDataURL() !== previous, before);
    record(paperChanged, 'Pointer drag did not paint a paper fold', { width, corner, portion });
    record(result.interaction && !result.visible, 'Paper fold incorrectly engaged the rigid cover', { width, name });
    for (const [edge, pixels] of Object.entries(result.paperEdgeInk)) record(pixels === 0, 'Folded paper reaches the canvas clipping boundary', { width, name, edge, pixels });
    entry.images.push(await capture(page, width, name));
  }
  await page.mouse.up(); await waitForState(page, 1, false);
  // Outside left edge returns one spread; it must not close from spread two.
  const current = await page.locator('#book').boundingBox();
  await page.mouse.click(current.x + current.width * .035, current.y + current.height * .5);
  await waitForState(page, 0, false);
}
async function cancelledCover(page, width, entry) {
  const box = await page.locator('#book').boundingBox();
  const start = { x: width * .15, y: box.height * .6 };
  await page.mouse.move(start.x, start.y); await page.mouse.down();
  await page.mouse.move(start.x + PAGE_WIDTH * 1.5 * width / stageWidth * .3, start.y, { steps: 8 });
  entry.samples.push(await sample(page, 'cancel-before', .7));
  // A real browser pointer cancellation event exercises the same cancel handler
  // used when native touch ownership changes. No internal controller is exposed.
  await page.locator('#book').dispatchEvent('pointercancel', { pointerId: 1, pointerType: 'mouse', isPrimary: true, clientX: start.x + width * .2, clientY: start.y });
  await page.mouse.up(); await waitForState(page, 0, false);
  await page.waitForTimeout(800);
  entry.samples.push(await sample(page, 'cancel-restored', 1));
  record(await page.evaluate(() => window.__messages.filter(m => m.type === 'gesture').at(-1)?.active === false), 'Cancelled gesture left the native lock active', { width });
}
async function touchIntent(page, width, entry) {
  const cdp = await page.context().newCDPSession(page);
  const face = await page.locator('.cover-front').boundingBox();
  const start = { x: face.x + face.width * .72, y: face.y + face.height * .35 };
  const activeCount = () => page.evaluate(() => window.__messages.filter(m => m.type === 'gesture' && m.active).length);
  const before = await activeCount();
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [start] });
  await page.waitForTimeout(30);
  record(await activeCount() === before, 'A resting touch captured the native scroll before intent', { width });
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{x:start.x+1,y:start.y+65}] });
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
  await page.waitForTimeout(100);
  record(await activeCount() === before, 'Vertical touch motion stole parent scroll', { width });
  await waitForState(page, 0, true);
  const grab = { x: face.x + face.width - 12, y: start.y };
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [grab] });
  for (let i=1;i<=12;i++) {
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{x:grab.x-width*.72*i/12,y:grab.y+3}] });
    await page.waitForTimeout(12);
  }
  record(await activeCount() > before, 'Horizontal touch failed to grab the rigid cover', { width });
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
  await waitForState(page, 0, false);
  const book=await page.locator('#book').boundingBox();
  await page.mouse.click(book.x+book.width*.035,book.y+book.height*.5); await waitForState(page,0,true);
  await cdp.send('Input.dispatchTouchEvent', {type:'touchStart',touchPoints:[grab]});
  await cdp.send('Input.dispatchTouchEvent', {type:'touchMove',touchPoints:[{x:grab.x-35,y:grab.y+2}]});
  await cdp.send('Input.dispatchTouchEvent', {type:'touchCancel',touchPoints:[]});
  await page.waitForTimeout(750); await waitForState(page,0,true);
  record(await page.evaluate(()=>window.__messages.filter(m=>m.type==='gesture').at(-1)?.active===false), 'Cancelled touch retained native scroll lock', {width});
  entry.touchIntent = 'Resting/vertical touch yields; horizontal grabs; cancellation restores cover and unlocks scroll';
  await cdp.detach();
}
async function queuedArchiveUpdate(page,width,entry) {
  const face=await page.locator('.cover-front').boundingBox(),x=face.x+face.width-12,y=face.y+60;
  await page.mouse.move(x,y);await page.mouse.down();await page.mouse.move(x-width*.18,y,{steps:5});
  const readyBefore=await page.evaluate(()=>window.__messages.filter(m=>m.type==='ready').length);
  await page.evaluate(()=>window.updatePassport({...window.__PASSPORT__,name:'Updated Traveler'}));
  await page.waitForTimeout(160);
  record(await page.evaluate(()=>window.__messages.filter(m=>m.type==='ready').length)===readyBefore,'Archive replacement interrupted a held page', {width});
  record(await page.evaluate(()=>window.__messages.filter(m=>m.type==='gesture').at(-1)?.active===true),'Archive replacement released a held page', {width});
  await page.locator('#book').dispatchEvent('pointercancel',{pointerId:1,pointerType:'mouse',isPrimary:true,clientX:x-width*.18,clientY:y});await page.mouse.up();
  await page.waitForFunction(n=>window.__messages.filter(m=>m.type==='ready').length>n,readyBefore);
  await waitForState(page,0,true); entry.archiveUpdate='Queued while held; applied after cancelled turn settled';
}
async function earnedStampOnce(page,width,entry) {
  const update = async () => {
    const count=await page.evaluate(()=>window.__messages.filter(m=>m.type==='ready').length);
    await page.evaluate(()=>window.updatePassport({...window.__PASSPORT__,earned:{key:'synthetic-import',codes:['DE']}}));
    await page.waitForFunction(n=>window.__messages.filter(m=>m.type==='ready').length>n,count);
  };
  await update();
  await page.locator('.cover-target').focus();await page.keyboard.press('Enter');await waitForState(page,0,false);
  const first=await page.locator('#paper').evaluate(canvas=>canvas.toDataURL());
  await page.waitForTimeout(320);
  const settled=await page.locator('#paper').evaluate(canvas=>canvas.toDataURL());
  record(first!==settled,'A newly earned visible country did not settle into the paper', {width});
  await update();
  const sameEvent=await page.locator('#paper').evaluate(canvas=>canvas.toDataURL());await page.waitForTimeout(320);
  record(await page.locator('#paper').evaluate((canvas,expected)=>canvas.toDataURL()===expected,sameEvent),'An existing import replayed its earned-country animation', {width});
  await page.locator('#book').focus();await page.keyboard.press('ArrowLeft');await waitForState(page,0,true);
  entry.earnedStamp='New country settles once; identical import update does not replay';
}

(async () => {
  const browser = await chromium.launch({ headless: true, channel: 'chrome' });
  try {
    for (const width of [320, 410]) {
      const viewportHeight = passportViewportHeight(width);
      const page = await browser.newPage({ viewport: { width, height: viewportHeight }, deviceScaleFactor: 2, hasTouch: true, reducedMotion: 'no-preference' });
      const entry = { width, viewportHeight, samples: [], images: [], errors: [], requests: [] }; report.widths.push(entry);
      page.on('pageerror', error => entry.errors.push(error.message));
      await page.route('**/*', route => { entry.requests.push(route.request().url()); route.abort(); });
      const html = passportDocument(payload).replace('<body>', `<body><script>
        window.__messages=[];window.__sizeReports=[];window.__heightLag=[];
        window.ReactNativeWebView={postMessage:s=>{const message=JSON.parse(s);window.__messages.push(message);if(message.type==='size')window.__sizeReports.push({time:performance.now(),height:message.height});}};
        // Observes bridge timing only. Does not alter the runtime, animation, or DOM.
        function observeHeight(){const scene=document.getElementById('cover-scene'),board=document.getElementById('cover-board');
          if(scene&&board&&getComputedStyle(scene).display!=='none'){
            const angle=Number(board.style.transform.match(/rotateY\\(([-\\d.]+)deg\\)/)?.[1]||0);
            const face=document.querySelector(angle> -90?'.cover-front':'.cover-back').getBoundingClientRect(),now=performance.now();
            const estimates=[0,16,33,50].map(delay=>{const size=window.__sizeReports.filter(s=>s.time<=now-delay).at(-1);return size?{delay,height:size.height,overflow:Math.max(0,face.bottom-size.height)}:null}).filter(Boolean);
            if(estimates.some(estimate=>estimate.overflow>1))window.__heightLag.push({time:now,progress:-angle/180,faceBottom:face.bottom,estimates});
          }requestAnimationFrame(observeHeight)}requestAnimationFrame(observeHeight);
      </script>`);
      try {
        await page.setContent(html);
        await page.waitForFunction(() => window.__messages.some(m => m.type === 'ready'), null, { timeout: 15000 });
        entry.samples.push(await sample(page, 'initial-closed', 0));
        entry.images.push(await capture(page, width, 'closed'));
        await coverDrag(page, width, true, entry);
        entry.images.push(await capture(page, width, 'open'));
        await paperFold(page, width, 'upper', entry);
        await paperFold(page, width, 'lower', entry);
        await cancelledCover(page, width, entry);
        await coverDrag(page, width, false, entry);
        // First page left-edge tap closes after a normal-motion tap opening.
        const face = await page.locator('.cover-front').boundingBox();
        await page.mouse.click(face.x + face.width * .6, face.y + face.height * .5);
        await waitForState(page, 0, false);
        const book = await page.locator('#book').boundingBox();
        await page.mouse.click(book.x + book.width * .035, book.y + book.height * .5);
        await waitForState(page, 0, true);
        await touchIntent(page, width, entry);
        await queuedArchiveUpdate(page, width, entry);
        await earnedStampOnce(page, width, entry);
        entry.fonts = await page.evaluate(() => Array.from(document.fonts).map(font => ({ family: font.family, status: font.status })));
        entry.containerHeightLag = await page.evaluate(() => ({
          scope: 'Historical dynamic-host diagnostic using size bridge reports delayed by0/16/33/50ms. Current native host uses the stable viewport envelope instead; these are not clipping failures.',
          samples: window.__heightLag,
          maximumByDelay: Object.fromEntries([0,16,33,50].map(delay => [delay, Math.max(0,...window.__heightLag.flatMap(frame=>frame.estimates.filter(estimate=>estimate.delay===delay).map(estimate=>estimate.overflow)))])),
        }));
        record(entry.fonts.every(font => font.status === 'loaded'), 'A passport font failed to load', { width, fonts: entry.fonts });
      } catch (error) { report.failures.push({ width, message: error.message, stack: error.stack }); }
      record(entry.errors.length === 0, 'Passport emitted runtime errors', { width, errors: entry.errors });
      record(entry.requests.length === 0, 'Offline proof attempted network access', { width, requests: entry.requests });
      await page.close();
    }
  } finally {
    await browser.close();
    const filename = path.join(out, `passport-motion-${label}-report.json`);
    fs.writeFileSync(filename, JSON.stringify(report, null, 2) + '\n');
    console.log(JSON.stringify({ report: filename, widths: report.widths.map(item => ({ width: item.width, samples: item.samples.length, images: item.images.length })), failures: report.failures.length }, null, 2));
  }
  if (!diagnostic) assert.equal(report.failures.length, 0, 'Passport motion proof failed; inspect the saved report and screenshots.');
})().catch(error => { console.error(error); process.exitCode = 1; });
