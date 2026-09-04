#!/usr/bin/env node
const fs = require('fs');
const path = require('path');

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
  if (!preset) return { name: shape, ...def };
  const o = preset.overrides || {};
  const merged = { name: shape, ...def, ...o };
  for (const grp of ['frame', 'country', 'icon', 'place', 'date', 'airport']) {
    merged[grp] = { ...def[grp], ...(o[grp] || {}) };
  }
  return merged;
}

function parseTemplate(name) {
  const def = TEMPLATE_BUNDLES[name]?.default;
  if (!def) return null;
  return { name, ...def };
}

function lengthBoost(len) {
  if (len <= 4) return 1.18;
  if (len <= 6) return 1.08;
  if (len <= 9) return 1.0;
  if (len <= 12) return 0.92;
  if (len <= 15) return 0.84;
  return 0.76;
}

function fitFontSize(text, baseSize, boxWidth, boxHeight, opts = {}) {
  const charFactor = opts.charFactor ?? 0.62;
  const minScale = opts.minScale ?? 0.5;
  const tracking = opts.tracking ?? 0;
  const adjusted = baseSize * lengthBoost(text.length);
  const estW = Math.max(1, text.length * adjusted * charFactor + Math.max(0, text.length - 1) * tracking);
  const wScale = Math.min(1, boxWidth / estW);
  const hScale = Math.min(1, (boxHeight * 0.88) / adjusted);
  return adjusted * Math.max(minScale, Math.min(wScale, hScale));
}

function rectsOverlap(a, b, slackY = 0) {
  if (!a || !b) return false;
  const aRight = a.left + a.width;
  const aBottom = a.top + a.height - slackY;
  const bRight = b.left + b.width;
  const bBottom = b.top + b.height - slackY;
  return !(aRight <= b.left || bRight <= a.left || aBottom <= b.top || bBottom <= a.top);
}

function resolveAirportBox(template) {
  if (!rectsOverlap(template.date, template.airport)) return template.airport;
  const gap = 0.012;
  const top = Math.min(0.985 - template.airport.height, template.date.top + template.date.height + gap);
  return { ...template.airport, top };
}

const templates = {};
for (const s of SHAPES) templates[s] = parseTemplate(s);

const STAMP_WIDTH = 204.75;
const STAMP_HEIGHT = 165.75;
const COUNTRY_BASE = 22.75;

let failures = 0;
const summary = {};

function fail(msg) { console.error('  ✗ ' + msg); failures += 1; }

console.log('=== Template structural checks ===');
for (const t of Object.values(templates)) {
  console.log(`\n[${t.name}]`);
  const rendered = { ...t, airport: resolveAirportBox(t) };
  for (const key of ['country', 'icon', 'place', 'date', 'airport']) {
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

  // Apply fitToLimit for single-word truncation
  const limited = display.length <= t.maxCountryChars || display.includes(' ') ? display : display.slice(0, t.maxCountryChars);
  const len = limited.length;

  // Compute font size as the renderer would
  const baseSize = COUNTRY_BASE * (t.country.fontScale ?? 1);
  const boxW = t.country.width * STAMP_WIDTH;
  const boxH = t.country.height * STAMP_HEIGHT;
  let fontSize;
  let mode;
  if (t.titleMode === 'arc' && (!t.straightTitleMaxChars || len > t.straightTitleMaxChars)) {
    mode = 'arc';
    fontSize = fitFontSize(limited, baseSize, boxW, boxH * 0.85, t.country);
  } else if (t.titleMode === 'circleArc' && (!t.straightTitleMaxChars || len > t.straightTitleMaxChars)) {
    mode = 'circleArc';
    // mimic CircleArcStampText sizing
    const frameW = t.frame.width * STAMP_WIDTH;
    const frameH = t.frame.height * STAMP_HEIGHT;
    const ringSize = Math.min(frameW, frameH);
    const radius = ringSize * 0.32;
    const maxArcWidth = radius * 2.35;
    fontSize = fitFontSize(limited, baseSize, maxArcWidth, STAMP_HEIGHT * t.country.height * 0.7, t.country);
    const maxHalf = len >= 14 ? 78 : len >= 10 ? 70 : len >= 8 ? 60 : 48;
    const arcLen = ((maxHalf * 2) * Math.PI) / 180 * radius;
    if (len > 1 && (len - 1) * fontSize * 0.78 > arcLen) {
      const minFloor = baseSize * (t.country.minScale ?? 0.36) * 0.85;
      fontSize = Math.max(minFloor, (arcLen / (len - 1)) / 0.78);
    }
  } else {
    mode = 'straight';
    fontSize = fitFontSize(limited, baseSize, boxW, boxH, t.country);
  }

  const entry = { country, display: limited, shape, mode, len, fontSize: +fontSize.toFixed(2) };
  lengthBuckets[bucket(len)].push(entry);
  if (!summary[shape]) summary[shape] = [];
  summary[shape].push(entry);

  if (fontSize < 6) fail(`${country} (${shape}): font too small ${fontSize.toFixed(1)}px`);
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

console.log(`\n${failures === 0 ? '✓ All checks passed' : `✗ ${failures} failure(s)`}`);
process.exit(failures === 0 ? 0 : 1);
