// === Stamp engine port (mirrors PngStamp.tsx logic so the editor preview matches the app) ===

const STAMP_W = 410;
const STAMP_H = 332;
const COUNTRY_BASE = 22.75 * (STAMP_W / 204.75); // scale base size to canvas size
const META_BASE = 18.3 * (STAMP_W / 204.75);
const DATE_BASE = 16.5 * (STAMP_W / 204.75);
const FOOTER_BASE = 15.3 * (STAMP_W / 204.75);

const SHAPE_TO_ASSET = {
  archedCountryCanonical: 'arched_country_canonical',
  archedCountryBanner: 'arched_country_banner',
  archedCountryVariant: 'arched_country_variant',
  circularCityClean: 'circular_city_clean',
  circularCityDoubleLine: 'circular_city_double_line',
  roundedImmigrationCanonical: 'rounded_immigration_canonical',
  roundedImmigrationWithBand: 'rounded_immigration_with_band',
  shieldBadgeRounded: 'shield_badge_rounded',
  ticketStubNotched: 'ticket_stub_notched',
  horizontalAirportOblong: 'horizontal_airport_oblong',
};

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
  const tracking = (opts.tracking ?? 0) * (STAMP_W / 204.75);
  const adjusted = baseSize * lengthBoost(text.length);
  const estW = Math.max(1, text.length * adjusted * charFactor + Math.max(0, text.length - 1) * tracking);
  const wScale = Math.min(1, boxWidth / estW);
  const hScale = Math.min(1, (boxHeight * 0.88) / adjusted);
  return adjusted * Math.max(minScale, Math.min(wScale, hScale));
}

function fitToLimit(value, maxChars) {
  if (!value) return undefined;
  const normalized = value.replace(/\s+/g, ' ').trim();
  if (normalized.length <= maxChars) return normalized;
  if (normalized.includes(' ')) return normalized;
  return normalized.slice(0, maxChars);
}

function formatStampDate(date) {
  if (!date) return undefined;
  const parsed = new Date(`${date}T00:00:00`);
  if (Number.isNaN(parsed.getTime())) return date.toUpperCase();
  const day = String(parsed.getDate()).padStart(2, '0');
  const month = parsed.toLocaleString('en-US', { month: 'short' }).toUpperCase();
  return `${day} ${month} ${parsed.getFullYear()}`;
}

function resolveTemplate(bundle, length) {
  const preset = (bundle.presets || []).find((p) => length >= p.charRange[0] && length <= p.charRange[1]);
  if (!preset) return JSON.parse(JSON.stringify(bundle.default));
  const o = preset.overrides || {};
  const t = JSON.parse(JSON.stringify(bundle.default));
  for (const k of Object.keys(o)) {
    if (typeof o[k] === 'object' && !Array.isArray(o[k]) && t[k] && typeof t[k] === 'object') {
      t[k] = { ...t[k], ...o[k] };
    } else {
      t[k] = o[k];
    }
  }
  return t;
}

// === SVG renderer ===

function svg(tag, attrs = {}, children = []) {
  const el = document.createElementNS('http://www.w3.org/2000/svg', tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v !== undefined && v !== null) el.setAttribute(k, String(v));
  }
  for (const c of children) {
    if (c) el.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
  }
  return el;
}

function renderArcText({ text, box, rootW, rootH, baseSize, color, arcDepth, arcTextLength }) {
  if (!text) return null;
  const boxW = rootW * box.width;
  const boxH = rootH * box.height;
  const fontSize = fitFontSize(text, baseSize * (box.fontScale ?? 1), boxW, boxH * 0.85, box);
  const isCircleArc = arcDepth >= 1.8;
  const yStart = boxH * (isCircleArc ? 0.96 : Math.min(0.88, 0.6 + arcDepth * 0.15));
  const yMid = boxH * (isCircleArc ? -0.18 : Math.max(0.06, 0.52 - arcDepth * 0.34));
  const xInset = isCircleArc ? -0.06 : (arcDepth >= 1.2 ? 0.04 : 0.08);
  const startX = boxW * xInset;
  const endX = boxW * (1 - xInset);
  const midX = boxW / 2;
  const cp1X = boxW * 0.25;
  const cp2X = boxW * 0.75;
  const cpY = yMid - (yStart - yMid) * 0.4;
  const arcLen = boxW * (arcTextLength ?? 0.7);
  const left = rootW * box.left;
  const top = rootH * box.top;
  const pathId = `arcpath_${Math.random().toString(36).slice(2, 9)}`;
  const path = `M ${startX} ${yStart} C ${cp1X} ${cpY}, ${cp2X} ${cpY}, ${endX} ${yStart}`;
  const g = svg('g', { transform: `translate(${left} ${top})` });
  const defs = svg('defs', {}, [svg('path', { id: pathId, d: path, fill: 'none' })]);
  g.appendChild(defs);
  const txt = svg('text', {
    fill: color,
    'font-family': "'Outfit', sans-serif",
    'font-weight': '700',
    'font-size': fontSize.toFixed(2),
    'letter-spacing': ((box.tracking ?? 0) * (STAMP_W / 204.75)).toFixed(2),
    'text-anchor': 'middle',
    dy: (fontSize * 0.32).toFixed(2),
  });
  const tp = svg('textPath', { href: `#${pathId}`, startOffset: '50%', textLength: arcLen.toFixed(2), lengthAdjust: 'spacingAndGlyphs' });
  tp.textContent = text;
  txt.appendChild(tp);
  g.appendChild(txt);
  return { node: g, fontSize };
}

function renderCircleArcText({ text, box, frame, rootW, rootH, baseSize, color, arcCenterYOffset }) {
  if (!text) return null;
  const frameLeft = rootW * frame.left;
  const frameTop = rootH * frame.top;
  const frameW = rootW * frame.width;
  const frameH = rootH * frame.height;
  const ringSize = Math.min(frameW, frameH);
  const centerX = frameLeft + frameW / 2;
  const centerY = frameTop + frameH / 2 + frameH * (arcCenterYOffset ?? -0.02);
  const radius = ringSize * 0.32;
  const maxArcWidth = radius * 2.35;
  const chars = text.split('');
  const minHalfAngle = chars.length >= 10 ? 53 : chars.length >= 8 ? 44 : chars.length >= 7 ? 36 : 0;
  const maxHalfAngle = chars.length >= 14 ? 78 : chars.length >= 10 ? 70 : chars.length >= 8 ? 60 : 48;
  let fontSize = fitFontSize(text, baseSize * (box.fontScale ?? 1), maxArcWidth, rootH * box.height * 0.7, box);
  if (chars.length > 1) {
    const arcLen = ((maxHalfAngle * 2) * Math.PI) / 180 * radius;
    const required = (chars.length - 1) * fontSize * 0.78;
    if (required > arcLen) {
      const minFloor = baseSize * (box.minScale ?? 0.36) * 0.85;
      fontSize = Math.max(minFloor, (arcLen / (chars.length - 1)) / 0.78);
    }
  }
  const desiredStepRad = (fontSize * 0.76) / radius;
  const computedHalfAngle = ((desiredStepRad * Math.max(0, chars.length - 1)) / 2) * (180 / Math.PI);
  const halfAngleDeg = Math.min(maxHalfAngle, Math.max(minHalfAngle, computedHalfAngle));
  const step = chars.length > 1 ? (halfAngleDeg * 2) / (chars.length - 1) : 0;
  const start = -halfAngleDeg;
  const g = svg('g');
  for (let i = 0; i < chars.length; i++) {
    const angleDeg = start + step * i;
    const angleRad = (angleDeg * Math.PI) / 180;
    const x = centerX + Math.sin(angleRad) * radius;
    const y = centerY - Math.cos(angleRad) * radius - fontSize * 0.52;
    const t = svg('text', {
      x: x.toFixed(2),
      y: y.toFixed(2),
      fill: color,
      'font-family': "'Outfit', sans-serif",
      'font-weight': '700',
      'font-size': fontSize.toFixed(2),
      'text-anchor': 'middle',
      transform: `rotate(${(angleDeg * 0.92).toFixed(2)} ${x.toFixed(2)} ${y.toFixed(2)})`,
    });
    t.textContent = chars[i];
    g.appendChild(t);
  }
  return { node: g, fontSize };
}

function renderStraightText({ text, box, rootW, rootH, baseSize, color, mono }) {
  if (!text) return null;
  const left = rootW * box.left;
  const top = rootH * box.top;
  const w = rootW * box.width;
  const h = rootH * box.height;
  const fontSize = fitFontSize(text, baseSize * (box.fontScale ?? 1), w, h, box);
  const t = svg('text', {
    x: (left + w / 2).toFixed(2),
    y: (top + h / 2).toFixed(2),
    fill: color,
    'font-family': mono ? "'Courier New', monospace" : "'Outfit', sans-serif",
    'font-weight': '700',
    'font-size': fontSize.toFixed(2),
    'letter-spacing': ((box.tracking ?? 0) * (STAMP_W / 204.75)).toFixed(2),
    'text-anchor': 'middle',
    'dominant-baseline': 'middle',
  });
  t.textContent = text;
  return { node: t, fontSize };
}

function hexToRGB(hex) {
  const m = hex.replace('#', '').match(/.{2}/g);
  if (!m) return [0, 0, 0];
  return m.slice(0, 3).map((c) => parseInt(c, 16) / 255);
}

function renderStamp(svgEl, { template, country, display, color, date, icon, shape }) {
  while (svgEl.firstChild) svgEl.removeChild(svgEl.firstChild);
  svgEl.setAttribute('viewBox', `0 0 ${STAMP_W} ${STAMP_H}`);
  svgEl.setAttribute('width', STAMP_W);
  svgEl.setAttribute('height', STAMP_H);

  // Define a tint filter so non-transparent PNG pixels become the ink color
  const [r, g, b] = hexToRGB(color);
  const filterId = `tint_${Math.random().toString(36).slice(2, 9)}`;
  const defs = svg('defs', {}, [
    svg('filter', { id: filterId, 'color-interpolation-filters': 'sRGB' }, [
      svg('feColorMatrix', { type: 'matrix', values: `0 0 0 0 ${r}  0 0 0 0 ${g}  0 0 0 0 ${b}  0 0 0 0.92 0` }),
    ]),
  ]);
  svgEl.appendChild(defs);

  // Background stamp shape (tinted)
  const img = svg('image', {
    href: `/assets/shape/${SHAPE_TO_ASSET[shape]}`,
    x: 0,
    y: 0,
    width: STAMP_W,
    height: STAMP_H,
    preserveAspectRatio: 'xMidYMid meet',
    filter: `url(#${filterId})`,
  });
  svgEl.appendChild(img);

  // Frame box outline (debug only - dotted)
  const frameRect = svg('rect', {
    x: STAMP_W * template.frame.left,
    y: STAMP_H * template.frame.top,
    width: STAMP_W * template.frame.width,
    height: STAMP_H * template.frame.height,
    fill: 'none',
    stroke: '#0001',
    'stroke-width': 0.5,
    'stroke-dasharray': '2 3',
  });
  svgEl.appendChild(frameRect);

  // Icon (tinted same as stamp ink)
  const iconLeft = STAMP_W * template.icon.left;
  const iconTop = STAMP_H * template.icon.top;
  const iconW = STAMP_W * template.icon.width;
  const iconH = STAMP_H * template.icon.height;
  const iconImg = svg('image', {
    href: `/assets/icon/${icon}`,
    x: iconLeft,
    y: iconTop,
    width: iconW,
    height: iconH,
    preserveAspectRatio: 'xMidYMid meet',
    filter: `url(#${filterId})`,
  });
  svgEl.appendChild(iconImg);

  const countryLabel = (display || country).toUpperCase();
  const limited = fitToLimit(countryLabel, template.maxCountryChars) ?? countryLabel.slice(0, template.maxCountryChars);
  const dateStr = formatStampDate(date);

  const titleArc =
    (template.titleMode === 'arc' || template.titleMode === 'circleArc') &&
    (!template.straightTitleMaxChars || limited.length > template.straightTitleMaxChars);

  let countryRender = null;
  if (template.titleMode === 'circleArc' && titleArc) {
    countryRender = renderCircleArcText({
      text: limited,
      box: template.country,
      frame: template.frame,
      rootW: STAMP_W,
      rootH: STAMP_H,
      baseSize: COUNTRY_BASE,
      color,
      arcCenterYOffset: template.arcCenterYOffset,
    });
  } else if (titleArc) {
    countryRender = renderArcText({
      text: limited,
      box: template.country,
      rootW: STAMP_W,
      rootH: STAMP_H,
      baseSize: COUNTRY_BASE,
      color,
      arcDepth: template.arcDepth ?? 0.6,
      arcTextLength: template.arcTextLength,
    });
  } else {
    countryRender = renderStraightText({
      text: limited,
      box: template.country,
      rootW: STAMP_W,
      rootH: STAMP_H,
      baseSize: COUNTRY_BASE,
      color,
    });
  }
  if (countryRender) svgEl.appendChild(countryRender.node);

  const dateRender = renderStraightText({
    text: dateStr,
    box: template.date,
    rootW: STAMP_W,
    rootH: STAMP_H,
    baseSize: DATE_BASE,
    color,
    mono: true,
  });
  if (dateRender) svgEl.appendChild(dateRender.node);

  // Render box outlines (subtle, for debug-feedback)
  for (const [name, b] of Object.entries({ country: template.country, date: template.date, icon: template.icon, place: template.place, footer: template.footer })) {
    const r = svg('rect', {
      x: STAMP_W * b.left,
      y: STAMP_H * b.top,
      width: STAMP_W * b.width,
      height: STAMP_H * b.height,
      fill: 'none',
      stroke: name === 'country' ? '#b6543f55' : name === 'date' ? '#2f5e9e55' : name === 'icon' ? '#52745a55' : '#0002',
      'stroke-width': 0.5,
      'stroke-dasharray': '2 2',
    });
    svgEl.appendChild(r);
  }

  return { country: countryRender, date: dateRender, limited, dateStr };
}

// === UI state ===

const state = {
  templates: null,
  previews: [],
  shapeKeys: [],
  selectedShape: null,
  selectedCountry: null,
  selectedPresetIndex: -1, // -1 = default
  dirty: false,
};

// === DOM helpers ===

function $(id) { return document.getElementById(id); }

function fmtNum(v) { return typeof v === 'number' ? v.toFixed(3).replace(/0+$/, '').replace(/\.$/, '') : ''; }

function buildBoxForm(containerId, box, defaultBox, isOverride, onChange) {
  const c = $(containerId);
  c.innerHTML = '';
  const fields = ['left', 'top', 'width', 'height', 'fontScale', 'minScale', 'charFactor', 'tracking'];
  for (const f of fields) {
    if (defaultBox[f] === undefined && (!box || box[f] === undefined)) continue;
    const row = document.createElement('div');
    row.className = 'form-row';
    const lab = document.createElement('label');
    lab.textContent = f;
    const inp = document.createElement('input');
    inp.type = 'number';
    inp.step = '0.001';
    inp.value = box && box[f] !== undefined ? box[f] : defaultBox[f] ?? '';
    inp.dataset.field = f;
    inp.placeholder = defaultBox[f] !== undefined ? `default ${fmtNum(defaultBox[f])}` : '';
    inp.addEventListener('input', () => {
      const v = inp.value === '' ? undefined : Number(inp.value);
      onChange(f, v);
    });
    row.appendChild(lab);
    row.appendChild(inp);
    c.appendChild(row);
  }
}

function buildShapeParamsForm(template, defaults, isOverride, onChange) {
  const c = $('form-shape');
  c.innerHTML = '';
  const params = [
    { key: 'titleMode', type: 'select', options: ['straight', 'arc', 'circleArc'] },
    { key: 'arcDepth', type: 'number' },
    { key: 'arcTextLength', type: 'number' },
    { key: 'straightTitleMaxChars', type: 'number', step: 1 },
    { key: 'arcCenterYOffset', type: 'number' },
    { key: 'maxCountryChars', type: 'number', step: 1 },
    { key: 'maxPlaceChars', type: 'number', step: 1 },
  ];
  for (const p of params) {
    const row = document.createElement('div');
    row.className = 'form-row full';
    const lab = document.createElement('label');
    lab.textContent = p.key;
    let inp;
    if (p.type === 'select') {
      inp = document.createElement('select');
      const blank = document.createElement('option');
      blank.value = '';
      blank.textContent = `(default: ${defaults[p.key] ?? '—'})`;
      inp.appendChild(blank);
      for (const o of p.options) {
        const opt = document.createElement('option');
        opt.value = o;
        opt.textContent = o;
        inp.appendChild(opt);
      }
      inp.value = template[p.key] !== undefined && template[p.key] !== defaults[p.key] ? template[p.key] : '';
    } else {
      inp = document.createElement('input');
      inp.type = 'number';
      inp.step = p.step ?? 0.01;
      inp.placeholder = defaults[p.key] !== undefined ? `default ${fmtNum(defaults[p.key])}` : '';
      inp.value = template[p.key] !== undefined && template[p.key] !== defaults[p.key] ? template[p.key] : '';
    }
    inp.addEventListener('input', () => {
      const raw = inp.value;
      const v = raw === '' ? undefined : (p.type === 'number' ? Number(raw) : raw);
      onChange(p.key, v);
    });
    row.appendChild(lab);
    row.appendChild(inp);
    c.appendChild(row);
  }
}

// === Country list ===

function populateShapeList() {
  const sel = $('shape-select');
  sel.innerHTML = '';
  for (const s of state.shapeKeys) {
    const opt = document.createElement('option');
    opt.value = s;
    opt.textContent = s;
    sel.appendChild(opt);
  }
  if (state.selectedShape) sel.value = state.selectedShape;
}

function selectShape(shape) {
  state.selectedShape = shape;
  if (!state.selectedCountry && state.previews.length > 0) {
    state.selectedCountry = state.previews[0].country;
  }
  state.selectedPresetIndex = -1;
  populatePresetSelect();
  refreshAll();
}

function cycleLength(direction) {
  if (!state.selectedCountry || state.previews.length === 0) return;
  const currentPreview = state.previews.find((p) => p.country === state.selectedCountry);
  const currentLength = currentPreview.display.length;

  const lengths = [...new Set(state.previews.map((p) => p.display.length))].sort((a, b) => a - b);
  const currentIndex = lengths.indexOf(currentLength);

  let nextIndex = currentIndex + direction;
  if (nextIndex < 0) nextIndex = lengths.length - 1;
  if (nextIndex >= lengths.length) nextIndex = 0;

  const nextLength = lengths[nextIndex];
  const nextPreview = state.previews.find((p) => p.display.length === nextLength);
  state.selectedCountry = nextPreview.country;

  populatePresetSelect();
  refreshAll();
}

function populatePresetSelect() {
  const sel = $('preset-select');
  sel.innerHTML = '';
  const bundle = state.templates[state.selectedShape];
  const defOpt = document.createElement('option');
  defOpt.value = '-1';
  defOpt.textContent = '(default)';
  sel.appendChild(defOpt);
  for (let i = 0; i < (bundle.presets || []).length; i++) {
    const p = bundle.presets[i];
    const opt = document.createElement('option');
    opt.value = String(i);
    opt.textContent = `${p.name || ''} ${p.charRange[0]}-${p.charRange[1]} chars`;
    sel.appendChild(opt);
  }
  // Auto-select preset matching current country length
  const currentPreview = state.previews.find((x) => x.country === state.selectedCountry);
  const len = currentPreview ? currentPreview.display.length : 0;
  const matchIdx = (bundle.presets || []).findIndex((p) => len >= p.charRange[0] && len <= p.charRange[1]);
  state.selectedPresetIndex = matchIdx;
  sel.value = String(matchIdx);
}

function getActiveContext() {
  const bundle = state.templates[state.selectedShape];
  const target = state.selectedPresetIndex === -1 ? bundle.default : (bundle.presets[state.selectedPresetIndex].overrides ||= {});
  return { bundle, target, isOverride: state.selectedPresetIndex !== -1 };
}

function setField(group, field, value) {
  const { bundle, target, isOverride } = getActiveContext();
  if (isOverride) {
    if (group) {
      target[group] = target[group] || {};
      if (value === undefined) {
        delete target[group][field];
        if (Object.keys(target[group]).length === 0) delete target[group];
      } else {
        target[group][field] = value;
      }
    } else {
      if (value === undefined) delete target[field];
      else target[field] = value;
    }
  } else {
    if (group) {
      if (value === undefined) return; // can't delete from default
      target[group][field] = value;
    } else {
      if (value === undefined) return;
      target[field] = value;
    }
  }
  state.dirty = true;
  updateStatus();
  renderPreviewOnly();
}

function updateStatus() {
  $('status').textContent = state.dirty ? 'unsaved changes' : 'saved';
}

function refreshAll() {
  populateShapeList();
  if (!state.selectedShape || !state.selectedCountry) return;
  const p = state.previews.find((x) => x.country === state.selectedCountry);
  $('shape-meta').innerHTML = `
    <div><strong>shape:</strong> ${state.selectedShape}</div>
    <div style="margin-top: 1rem; padding-top: 1rem; border-top: 1px solid #333;">
      <div style="margin-bottom: 0.5rem;"><strong>Test Country:</strong> ${p.display}</div>
      <div><strong>Length:</strong> ${p.display.length} chars</div>
      <div style="margin-top: 0.5rem; display: flex; gap: 0.5rem;">
        <button id="prev-length" class="secondary small">← Shorter</button>
        <button id="next-length" class="secondary small">Longer →</button>
      </div>
    </div>
  `;
  $('prev-length').addEventListener('click', () => cycleLength(-1));
  $('next-length').addEventListener('click', () => cycleLength(1));
  buildEditorForms();
  renderPreviewOnly();
}

function buildEditorForms() {
  const { bundle, target, isOverride } = getActiveContext();
  const def = bundle.default;
  const rangeEl = $('preset-range');

  document.querySelectorAll('.editor-note').forEach(n => n.remove());

  if (state.selectedPresetIndex === -1) {
    rangeEl.textContent = 'Editing the DEFAULT preset (applies when no sub-preset matches).';
  } else {
    const preset = bundle.presets[state.selectedPresetIndex];
    rangeEl.innerHTML = `
      Editing sub-preset for char range:
      <input type="number" min="1" max="40" id="range-min" value="${preset.charRange[0]}" style="width:50px"> –
      <input type="number" min="1" max="40" id="range-max" value="${preset.charRange[1]}" style="width:50px">
      &nbsp; name: <input type="text" id="preset-name" value="${preset.name || ''}" style="width:120px">
    `;
    $('range-min').addEventListener('input', (e) => { preset.charRange[0] = Number(e.target.value); state.dirty = true; updateStatus(); });
    $('range-max').addEventListener('input', (e) => { preset.charRange[1] = Number(e.target.value); state.dirty = true; updateStatus(); });
    $('preset-name').addEventListener('input', (e) => { preset.name = e.target.value; state.dirty = true; updateStatus(); });
  }

  const curTitleMode = target.titleMode ?? def.titleMode;
  if (curTitleMode === 'circleArc') {
    const note = document.createElement('div');
    note.className = 'editor-note';
    note.style.background = '#ffe5e5';
    note.style.color = '#c00';
    note.style.padding = '0.5rem';
    note.style.borderRadius = '4px';
    note.style.marginBottom = '1rem';
    note.style.fontSize = '0.85rem';
    note.innerHTML = `⚠️ <strong>Circle Arc Mode:</strong> Country box top/left are ignored! Use <strong>arcCenterYOffset</strong> in Shape parameters to move the text vertically.`;
    const container = $('form-country').parentNode;
    container.insertBefore(note, $('form-country'));
  }

  for (const grp of ['frame', 'country', 'icon', 'place', 'date', 'footer']) {
    const cur = isOverride ? (target[grp] || {}) : target[grp];
    buildBoxForm(`form-${grp}`, cur, def[grp], isOverride, (f, v) => setField(grp, f, v));
  }
  buildShapeParamsForm(isOverride ? { ...def, ...target } : target, def, isOverride, (k, v) => setField(null, k, v));
}

function renderPreviewOnly() {
  if (!state.selectedShape || !state.selectedCountry) return;
  const p = state.previews.find((x) => x.country === state.selectedCountry);
  const bundle = state.templates[state.selectedShape];
  const len = p.display.length;
  const template = resolveTemplate(bundle, len);
  const stampDiv = $('preview-stamp');
  let svgEl = stampDiv.querySelector('svg');
  if (!svgEl) {
    svgEl = svg('svg', { xmlns: 'http://www.w3.org/2000/svg' });
    stampDiv.appendChild(svgEl);
  }
  const { country: cr, date: dr, limited, dateStr } = renderStamp(svgEl, {
    template,
    country: p.country,
    display: p.display,
    color: p.color,
    date: p.date,
    icon: p.icon,
    shape: state.selectedShape,
  });
  $('preview-info').textContent = [
    `country: "${limited}" (${limited.length}ch) → ${cr ? cr.fontSize.toFixed(2) : '—'}px`,
    `date:    "${dateStr || ''}" → ${dr ? dr.fontSize.toFixed(2) : '—'}px`,
    `mode:    ${template.titleMode}${template.titleMode !== 'straight' && limited.length <= (template.straightTitleMaxChars || 0) ? ' (forced straight)' : ''}`,
    `preset:  ${state.selectedPresetIndex === -1 ? 'default' : bundle.presets[state.selectedPresetIndex].name || `${bundle.presets[state.selectedPresetIndex].charRange.join('-')}ch`}`,
  ].join('\n');
}

// === Save/load ===

async function load() {
  const r = await fetch('/api/state');
  const data = await r.json();
  state.templates = data.templates;
  state.previews = data.previews;
  state.shapeKeys = data.shapeKeys || [];

  state.previews.sort((a, b) => a.display.length - b.display.length);

  populateShapeList();
  if (state.shapeKeys.length) {
    selectShape(state.shapeKeys[0]);
  }
  state.dirty = false;
  updateStatus();
}

async function save() {
  const r = await fetch('/api/templates', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(state.templates, null, 2) });
  if (r.ok) {
    state.dirty = false;
    $('status').textContent = `saved at ${new Date().toLocaleTimeString()}`;
  } else {
    const e = await r.json();
    $('status').textContent = `save failed: ${e.error}`;
  }
}

function addPreset() {
  if (!state.selectedShape || !state.selectedCountry) return;
  const bundle = state.templates[state.selectedShape];
  bundle.presets = bundle.presets || [];
  const display = state.previews.find((x) => x.country === state.selectedCountry).display;
  const len = display.length;

  const existingIdx = bundle.presets.findIndex((p) => len >= p.charRange[0] && len <= p.charRange[1]);
  if (existingIdx !== -1) {
    alert(`A preset already covers length ${len} (${bundle.presets[existingIdx].charRange[0]}-${bundle.presets[existingIdx].charRange[1]}ch). Select it from the dropdown to edit it.`);
    return;
  }

  bundle.presets.push({
    name: `${len}ch`,
    charRange: [len, len],
    overrides: {},
  });
  bundle.presets.sort((a, b) => a.charRange[0] - b.charRange[0]);
  state.dirty = true;
  populatePresetSelect();
  refreshAll();
}

function deletePreset() {
  if (state.selectedPresetIndex === -1) return;
  const bundle = state.templates[state.selectedShape];
  bundle.presets.splice(state.selectedPresetIndex, 1);
  state.selectedPresetIndex = -1;
  state.dirty = true;
  populatePresetSelect();
  refreshAll();
}

// === Wire up ===

$('shape-select').addEventListener('change', (e) => selectShape(e.target.value));
$('preset-select').addEventListener('change', (e) => {
  state.selectedPresetIndex = Number(e.target.value);
  refreshAll();
});
$('add-preset').addEventListener('click', addPreset);
$('delete-preset').addEventListener('click', deletePreset);
$('save').addEventListener('click', save);
$('reset').addEventListener('click', () => load().then(() => refreshAll()));

load();
