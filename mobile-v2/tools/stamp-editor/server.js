#!/usr/bin/env node
const fs = require('fs');
const path = require('path');
const http = require('http');

const ROOT = path.resolve(__dirname, '..', '..');
const TEMPLATES_PATH = path.join(ROOT, 'src', 'components', 'trotter', 'stamps', 'stampTemplates.json');
const ASSETS_DIR = path.join(ROOT, 'assets', 'processed');
const PUBLIC_DIR = path.join(__dirname, 'public');

const PORT = process.env.STAMP_EDITOR_PORT ? Number(process.env.STAMP_EDITOR_PORT) : 5173;

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.png': 'image/png',
  '.svg': 'image/svg+xml',
  '.ico': 'image/x-icon',
};

const COUNTRY_ROSTER = [
  { country: 'United States', icon: 'united_states_golden_gate_bridge' },
  { country: 'Canada', icon: 'canada_rocky_mountains' },
  { country: 'Mexico', icon: 'mexico_chichen_itza' },
  { country: 'Brazil', icon: 'brazil_christ_the_redeemer' },
  { country: 'Argentina', icon: 'argentina_obelisco_de_buenos_aires' },
  { country: 'Chile', icon: 'chile_torres_del_paine' },
  { country: 'Peru', icon: 'peru_machu_picchu' },
  { country: 'Colombia', icon: 'colombia_cartagena_clock_tower' },
  { country: 'Costa Rica', icon: 'costa_rica_arenal_volcano' },
  { country: 'Panama', icon: 'panama_panama_canal' },
  { country: 'Cuba', icon: 'cuba_havana_capitol' },
  { country: 'Jamaica', icon: 'jamaica_dunns_river_falls' },
  { country: 'Dominican Republic', icon: 'dominican_republic_puerta_del_conde' },
  { country: 'Iceland', icon: 'iceland_northern_lights' },
  { country: 'Ireland', icon: 'ireland_cliffs_of_moher' },
  { country: 'United Kingdom', icon: 'united_kingdom_big_ben' },
  { country: 'France', icon: 'france_eiffel_tower' },
  { country: 'Spain', icon: 'spain_sagrada_familia' },
  { country: 'Portugal', icon: 'portugal_belem_tower' },
  { country: 'Italy', icon: 'italy_colosseum' },
  { country: 'Greece', icon: 'greece_parthenon' },
  { country: 'Germany', icon: 'germany_brandenburg_gate' },
  { country: 'Netherlands', icon: 'netherlands_amsterdam_canal_houses' },
  { country: 'Belgium', icon: 'belgium_atomium' },
  { country: 'Switzerland', icon: 'switzerland_matterhorn' },
  { country: 'Austria', icon: 'austria_st_stephens_cathedral' },
  { country: 'Czech Republic', icon: 'czech_republic_charles_bridge_prague_castle' },
  { country: 'Hungary', icon: 'hungary_hungarian_parliament' },
  { country: 'Poland', icon: 'poland_palace_of_culture' },
  { country: 'Norway', icon: 'norway_fjord_cliffs' },
  { country: 'Sweden', icon: 'sweden_stockholm_city_hall' },
  { country: 'Denmark', icon: 'denmark_nyhavn_harbor' },
  { country: 'Finland', icon: 'finland_helsinki_cathedral' },
  { country: 'Turkey', icon: 'turkey_hagia_sophia' },
  { country: 'Morocco', icon: 'morocco_hassan_ii_mosque' },
  { country: 'Egypt', icon: 'egypt_pyramids_of_giza' },
  { country: 'South Africa', icon: 'south_africa_table_mountain' },
  { country: 'Kenya', icon: 'kenya_mount_kenya' },
  { country: 'Tanzania', icon: 'tanzania_mount_kilimanjaro' },
  { country: 'Ethiopia', icon: 'ethiopia_lalibela_church' },
  { country: 'United Arab Emirates', icon: 'united_arab_emirates_burj_khalifa' },
  { country: 'Saudi Arabia', icon: 'saudi_arabia_alula' },
  { country: 'Jordan', icon: 'jordan_petra' },
  { country: 'Israel', icon: 'israel_dome_of_the_rock' },
  { country: 'India', icon: 'india_taj_mahal' },
  { country: 'Nepal', icon: 'nepal_mount_everest' },
  { country: 'Sri Lanka', icon: 'sri_lanka_sigiriya_rock' },
  { country: 'Thailand', icon: 'thailand_wat_arun' },
  { country: 'Vietnam', icon: 'vietnam_ha_long_bay' },
  { country: 'Cambodia', icon: 'cambodia_angkor_wat' },
  { country: 'Singapore', icon: 'singapore_marina_bay_sands' },
  { country: 'Malaysia', icon: 'malaysia_petronas_towers' },
  { country: 'Indonesia', icon: 'indonesia_borobudur' },
  { country: 'Philippines', icon: 'philippines_mayon_volcano' },
  { country: 'China', icon: 'china_great_wall' },
  { country: 'Japan', icon: 'japan_mount_fuji' },
  { country: 'South Korea', icon: 'south_korea_n_seoul_tower' },
  { country: 'Taiwan', icon: 'taiwan_taipei_101' },
  { country: 'Hong Kong', icon: 'hong_kong_victoria_peak_skyline' },
  { country: 'Australia', icon: 'australia_sydney_opera_house' },
  { country: 'New Zealand', icon: 'new_zealand_milford_sound' },
  { country: 'Fiji', icon: 'fiji_tropical_island' },
  { country: 'French Polynesia', icon: 'french_polynesia_bora_bora_overwater_huts' },
  { country: 'Maldives', icon: 'maldives_overwater_bungalow' },
  { country: 'Qatar', icon: 'qatar_museum_of_islamic_art' },
  { country: 'Oman', icon: 'oman_sultan_qaboos_grand_mosque' },
  { country: 'Iran', icon: 'iran_azadi_tower' },
  { country: 'Iraq', icon: 'iraq_ziggurat_of_ur' },
  { country: 'Lebanon', icon: 'lebanon_baalbek_ruins' },
  { country: 'Armenia', icon: 'armenia_mount_ararat' },
  { country: 'Georgia', icon: 'georgia_gergeti_trinity_church' },
  { country: 'Romania', icon: 'romania_bran_castle' },
  { country: 'Croatia', icon: 'croatia_dubrovnik_city_walls' },
  { country: 'Slovenia', icon: 'slovenia_lake_bled_church' },
  { country: 'Serbia', icon: 'serbia_saint_sava' },
  { country: 'Bulgaria', icon: 'bulgaria_alexander_nevsky_cathedral' },
  { country: 'Ukraine', icon: 'ukraine_saint_sophia_cathedral' },
  { country: 'Russia', icon: 'russia_saint_basils_cathedral' },
  { country: 'Mongolia', icon: 'mongolia_yurt' },
  { country: 'Kazakhstan', icon: 'kazakhstan_bayterek_tower' },
];

const COUNTRY_ABBREVIATIONS = {
  'United States': 'USA',
  'United Arab Emirates': 'U.A.E.',
  'United Kingdom': 'U.K.',
};

const STAMP_SHAPE_KEYS = [
  'archedCountryCanonical',
  'archedCountryBanner',
  'archedCountryVariant',
  'circularCityClean',
  'circularCityDoubleLine',
  'roundedImmigrationCanonical',
  'roundedImmigrationWithBand',
  'shieldBadgeRounded',
];

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

const STAMP_INK_COLORS = ['#B6543F', '#2F5E9E', '#52745A', '#9A5A32', '#C79A43'];

function hashString(v) {
  let h = 0;
  for (let i = 0; i < v.length; i++) h = ((h << 5) - h + v.charCodeAt(i)) | 0;
  return Math.abs(h);
}

function buildStampDate(country) {
  const h = hashString(`date:${country}`);
  const day = ((h % 27) + 1).toString().padStart(2, '0');
  const month = (((h >> 4) % 12) + 1).toString().padStart(2, '0');
  const year = 2018 + ((h >> 9) % 8);
  return `${year}-${month}-${day}`;
}

function buildPreview(country) {
  const h = hashString(country.country);
  const display = COUNTRY_ABBREVIATIONS[country.country] ?? country.country;
  return {
    country: country.country,
    display,
    icon: country.icon,
    shape: STAMP_SHAPE_KEYS[h % STAMP_SHAPE_KEYS.length],
    color: STAMP_INK_COLORS[(h >> 3) % STAMP_INK_COLORS.length],
    date: buildStampDate(country.country),
  };
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    let data = '';
    req.on('data', (c) => (data += c));
    req.on('end', () => resolve(data));
    req.on('error', reject);
  });
}

function send(res, status, body, headers = {}) {
  res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8', ...headers });
  res.end(typeof body === 'string' ? body : JSON.stringify(body));
}

function serveStatic(res, filepath) {
  fs.readFile(filepath, (err, data) => {
    if (err) {
      res.writeHead(404);
      res.end('Not found');
      return;
    }
    const ext = path.extname(filepath).toLowerCase();
    res.writeHead(200, { 'Content-Type': MIME[ext] ?? 'application/octet-stream' });
    res.end(data);
  });
}

const ICON_DIR = path.join(ASSETS_DIR, 'country-icons');
const SHAPE_DIR = path.join(ASSETS_DIR, 'stamp-shapes');

const ICON_FILES = fs.existsSync(ICON_DIR) ? fs.readdirSync(ICON_DIR) : [];
const SHAPE_FILES = fs.existsSync(SHAPE_DIR) ? fs.readdirSync(SHAPE_DIR) : [];

function findIconFile(iconKey) {
  const dashed = iconKey.replace(/_/g, '-');
  const pattern = new RegExp(`^\\d{2}_${dashed.replace(/-/g, '[-_]').replace(/[.]/g, '\\.')}\\.png$`, 'i');
  return ICON_FILES.find((f) => pattern.test(f)) || ICON_FILES.find((f) => f.toLowerCase().includes(iconKey.replace(/_/g, '-')) || f.toLowerCase().includes(iconKey));
}

function findShapeFile(shapeAssetKey) {
  return SHAPE_FILES.find((f) => f.endsWith(`${shapeAssetKey}.png`));
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://${req.headers.host}`);
  const pathname = url.pathname;

  if (req.method === 'GET' && pathname === '/api/state') {
    const templates = JSON.parse(fs.readFileSync(TEMPLATES_PATH, 'utf8'));
    const previews = COUNTRY_ROSTER.map(buildPreview);
    send(res, 200, { templates, previews, shapeKeys: STAMP_SHAPE_KEYS, countryAbbreviations: COUNTRY_ABBREVIATIONS, inkColors: STAMP_INK_COLORS });
    return;
  }

  if (req.method === 'PUT' && pathname === '/api/templates') {
    try {
      const body = await readBody(req);
      const parsed = JSON.parse(body);
      // Basic validation: ensure each shape key exists with a default
      for (const k of STAMP_SHAPE_KEYS) {
        if (!parsed[k] || !parsed[k].default) {
          send(res, 400, { error: `Missing default for ${k}` });
          return;
        }
      }
      fs.writeFileSync(TEMPLATES_PATH, JSON.stringify(parsed, null, 2) + '\n');
      send(res, 200, { ok: true, savedAt: new Date().toISOString() });
    } catch (e) {
      send(res, 400, { error: e.message });
    }
    return;
  }

  if (pathname.startsWith('/assets/icon/')) {
    const key = decodeURIComponent(pathname.slice('/assets/icon/'.length));
    const file = findIconFile(key);
    if (!file) { res.writeHead(404); res.end(); return; }
    serveStatic(res, path.join(ICON_DIR, file));
    return;
  }

  if (pathname.startsWith('/assets/shape/')) {
    const key = decodeURIComponent(pathname.slice('/assets/shape/'.length));
    const file = findShapeFile(key);
    if (!file) { res.writeHead(404); res.end(); return; }
    serveStatic(res, path.join(SHAPE_DIR, file));
    return;
  }

  // Static files from public/
  const safe = pathname === '/' ? '/index.html' : pathname;
  const filepath = path.join(PUBLIC_DIR, safe);
  if (filepath.startsWith(PUBLIC_DIR) && fs.existsSync(filepath) && fs.statSync(filepath).isFile()) {
    serveStatic(res, filepath);
    return;
  }

  res.writeHead(404);
  res.end('Not found');
});

function listenWithFallback(port, attemptsLeft) {
  server.once('error', (err) => {
    if (err.code === 'EADDRINUSE' && attemptsLeft > 0) {
      console.log(`Port ${port} in use, trying ${port + 1}…`);
      listenWithFallback(port + 1, attemptsLeft - 1);
    } else {
      throw err;
    }
  });
  server.listen(port, () => {
    console.log(`Stamp editor running at http://localhost:${port}`);
    console.log(`Templates file: ${TEMPLATES_PATH}`);
  });
}

listenWithFallback(PORT, 10);
