#!/usr/bin/env node
const fs = require('fs');
const path = require('path');
const ts = require('typescript');
const layoutFile = path.join(__dirname, '..', 'src', 'components', 'trotter', 'stamps', 'stampLayout.ts');
const layoutModule = { exports: {} };
new Function('module', 'exports', ts.transpileModule(fs.readFileSync(layoutFile, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText)(layoutModule, layoutModule.exports);
const { fitFontSize } = layoutModule.exports;
const geometryModule = { exports: {} };
const geometryFile = path.join(__dirname, '..', 'src/components/trotter/stamps/stampGeometry.ts');
new Function('module', 'exports', ts.transpileModule(fs.readFileSync(geometryFile, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText)(geometryModule, geometryModule.exports);
const { resolveStampGeometry, STAMP_FRAME_PIXELS } = geometryModule.exports;

const templatesFile = path.join(__dirname, '..', 'src', 'components', 'trotter', 'stamps', 'stampTemplates.json');
const TEMPLATE_BUNDLES = JSON.parse(fs.readFileSync(templatesFile, 'utf8'));

const SHAPES = [
  'archedCountryCanonical',
  'archedCountryBanner',
  'archedCountryVariant',
  'circularCityClean',
  'circularCityDoubleLine',
  'roundedImmigrationCanonical',
  'roundedImmigrationWithBand',
  'shieldBadgeRounded',
];

const COUNTRY_LIST = [
  'United States','Canada','Mexico','Brazil','Argentina','Chile','Peru','Colombia','Costa Rica','Panama',
  'Cuba','Jamaica','Dominican Republic','Iceland','Ireland','United Kingdom','France','Spain','Portugal',
  'Italy','Greece','Germany','Netherlands','Belgium','Switzerland','Austria','Czech Republic','Hungary',
  'Poland','Norway','Sweden','Denmark','Finland','Turkey','Morocco','Egypt','South Africa','Kenya',
  'Tanzania','Ethiopia','United Arab Emirates','Saudi Arabia','Jordan','Israel','India','Nepal',
  'Sri Lanka','Thailand','Vietnam','Cambodia','Singapore','Malaysia','Indonesia','Philippines','China',
  'Japan','South Korea','Taiwan','Hong Kong','Australia','New Zealand','Fiji','French Polynesia',
  'Maldives','Qatar','Oman','Iran','Iraq','Lebanon','Armenia','Georgia','Romania','Croatia','Slovenia',
  'Serbia','Bulgaria','Ukraine','Russia','Mongolia','Kazakhstan',
];

const ABBREV = { 'United States': 'USA', 'United Arab Emirates': 'U.A.E.', 'United Kingdom': 'U.K.' };

function hashString(v) {
  let h = 0;
  for (let i = 0; i < v.length; i++) h = ((h << 5) - h + v.charCodeAt(i)) | 0;
  return Math.abs(h);
}

function resolveTemplate(shape, length) {
  const bundle = TEMPLATE_BUNDLES[shape];
  if (!bundle) return null;
  const def = bundle.default;
  const preset = (bundle.presets || []).find((p) => length >= p.charRange[0] && length <= p.charRange[1]);
  if (!preset) return { name: shape, ...resolveStampGeometry(shape, def, 204.75, 165.75) };
  const o = preset.overrides || {};
  const merged = { name: shape, ...def, ...o };
  for (const grp of ['frame', 'country', 'icon', 'place', 'date', 'airport']) {
    merged[grp] = { ...def[grp], ...(o[grp] || {}) };
  }
  return { ...resolveStampGeometry(shape, merged, 204.75, 165.75), name: shape };
}

function parseTemplate(name) {
  const def = TEMPLATE_BUNDLES[name]?.default;
  if (!def) return null;
  return { name, ...resolveStampGeometry(name, def, 204.75, 165.75) };
}

function rectsOverlap(a, b, slackY = 0) {
  if (!a || !b) return false;
  const aRight = a.left + a.width;
  const aBottom = a.top + a.height - slackY;
  const bRight = b.left + b.width;
  const bBottom = b.top + b.height - slackY;
  return !(aRight <= b.left || bRight <= a.left || aBottom <= b.top || bBottom <= a.top);
}

const templates = {};
for (const s of SHAPES) templates[s] = parseTemplate(s);

const STAMP_WIDTH = 204.75;
const STAMP_HEIGHT = 165.75;
const COUNTRY_BASE = 22.75;

let failures = 0;
const summary = {};

function fail(msg) { console.error('  FAIL ' + msg); failures += 1; }

console.log('=== Template structural checks ===');
for (const t of Object.values(templates)) {
  console.log(`\n[${t.name}]`);
  const rendered = t;
  for (const key of ['country', 'icon', 'date', 'airport']) {
    const b = rendered[key];
    if (!b) { fail(`${key} missing`); continue; }
    if (b.left < 0 || b.top < 0 || b.left + b.width > 1.001 || b.top + b.height > 1.001) {
      fail(`${key} out of bounds: ${JSON.stringify(b)}`);
    }
  }
  // No overlap between country/icon, country/date, or the dated airport line.
  const pairs = [['country', 'icon'], ['country', 'date'], ['icon', 'date'], ['date', 'airport']];
  for (const [a, b] of pairs) {
    if (rectsOverlap(rendered[a], rendered[b], 0.005)) fail(`${a} overlaps ${b}`);
  }
}

console.log('\n=== Arrival-label bounds in every preset ===');
for (const shape of SHAPES) {
  const bundle = TEMPLATE_BUNDLES[shape];
  for (const length of [3, 6, 8, 10, 12, 14, 16, 18, 24, 40]) {
    const t = resolveTemplate(shape, length);
    for (const key of ['date', 'airport']) {
      const box = t[key];
      if (box.top < t.frame.top || box.top + box.height > t.frame.top + t.frame.height || box.left < t.frame.left || box.left + box.width > t.frame.left + t.frame.width) fail(`${shape}/${length}: ${key} outside frame`);
      if (rectsOverlap(box, t.icon) || rectsOverlap(box, t.country)) fail(`${shape}/${length}: ${key} overlaps artwork/title`);
    }
    if (rectsOverlap(t.date, t.airport)) fail(`${shape}/${length}: entry airport overlaps date`);
    for (const scale of [.5, .76, 1, 1.3]) {
      for (const [key, text, base] of [['date', '31 DEC 2026', 13.16], ['airport', 'WWWW', 12.2]]) {
        const b = t[key], w = b.width * STAMP_WIDTH * scale, h = b.height * STAMP_HEIGHT * scale;
        const font = fitFontSize(text, base * (b.fontScale ?? 1) * scale, w, h, b, STAMP_WIDTH * scale);
        const estimate = text.length * font * (b.charFactor ?? .62) + (text.length - 1) * (b.tracking ?? 0) * scale;
        if (estimate > w + .01 || font > h * .88 + .01) fail(`${shape}/${length}/${scale}: ${key} text exceeds bounds`);
      }
    }
  }
}

console.log('\n=== Country render simulation (per-length sanity) ===');
const lengthBuckets = { '<=4': [], '5-6': [], '7-9': [], '10-12': [], '13-15': [], '16+': [] };
function bucket(len) {
  if (len <= 4) return '<=4';
  if (len <= 6) return '5-6';
  if (len <= 9) return '7-9';
  if (len <= 12) return '10-12';
  if (len <= 15) return '13-15';
  return '16+';
}

for (const country of COUNTRY_LIST) {
  const display = (ABBREV[country] ?? country).toUpperCase();
  const shape = SHAPES[hashString(country) % SHAPES.length];
  const t = resolveTemplate(shape, display.length);

  // Country names remain complete; font sizing must fit without truncation.
  const limited = display;
  const len = limited.length;

  // Compute font size as the renderer would
  const baseSize = COUNTRY_BASE * (t.country.fontScale ?? 1);
  const boxW = t.country.width * STAMP_WIDTH;
  const boxH = t.country.height * STAMP_HEIGHT;
  let fontSize;
  let mode;
  if (t.titleMode === 'arc' && (!t.straightTitleMaxChars || len > t.straightTitleMaxChars)) {
    mode = 'arc';
    fontSize = fitFontSize(limited, baseSize, boxW * .84, boxH * 0.85, t.country);
  } else if (t.titleMode === 'circleArc' && (!t.straightTitleMaxChars || len > t.straightTitleMaxChars)) {
    mode = 'circleArc';
    const radius = Math.min(t.frame.width * STAMP_WIDTH, t.frame.height * STAMP_HEIGHT) * (t.circleTitleRadius ?? .28);
    fontSize = fitFontSize(limited, baseSize, radius * (70 * Math.PI / 180) * 1.8, STAMP_HEIGHT * t.country.height * .7, t.country);
  } else {
    mode = 'straight';
    fontSize = fitFontSize(limited, baseSize, boxW, boxH, t.country);
  }

  const entry = { country, display: limited, shape, mode, len, fontSize: +fontSize.toFixed(2) };
  lengthBuckets[bucket(len)].push(entry);
  if (!summary[shape]) summary[shape] = [];
  summary[shape].push(entry);

  if (fontSize < 4.8) fail(`${country} (${shape}): font too small ${fontSize.toFixed(1)}px`);
  if (fontSize > 28) fail(`${country} (${shape}): font too large ${fontSize.toFixed(1)}px`);
}

console.log('\n=== Font size by length bucket ===');
for (const [k, items] of Object.entries(lengthBuckets)) {
  if (!items.length) continue;
  const sizes = items.map((i) => i.fontSize).sort((a, b) => a - b);
  console.log(`  ${k} chars (n=${items.length}): min=${sizes[0]} max=${sizes[sizes.length-1]} median=${sizes[Math.floor(sizes.length/2)]}`);
}

console.log('\n=== Per-shape render summary ===');
for (const [shape, items] of Object.entries(summary)) {
  console.log(`\n[${shape}] ${items.length} countries`);
  for (const i of items.sort((a,b)=>a.len-b.len)) {
    console.log(`  ${i.mode.padEnd(9)} ${String(i.len).padStart(2)}ch  ${String(i.fontSize).padStart(5)}px  ${i.display}`);
  }
}

console.log(`\n${failures === 0 ? 'PASS All checks passed' : `FAIL ${failures} failure(s)`}`);
process.exit(failures === 0 ? 0 : 1);
