// Offline, deterministic generation from checked-in, checksum-verified primary-source snapshots.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const zlib = require('node:zlib');
const folder = path.join(__dirname, '../src/data/collections');
const CONTINENTS = { AF:'Africa', AN:'Antarctica', AS:'Asia', EU:'Europe', NA:'North America', OC:'Oceania', SA:'South America' };
const normalize = value => String(value ?? '').normalize('NFKD').replace(/\p{M}/gu, '').toUpperCase().replace(/[^A-Z0-9]+/g, ' ').trim();
const order = (a, b) => a.key < b.key ? -1 : a.key > b.key ? 1 : 0;

function parseCsv(text) {
  const rows = []; let row = [], field = '', quoted = false;
  for (let i = 0; i < text.length; i++) {
    const char = text[i];
    if (char === '"') {
      if (quoted && text[i + 1] === '"') { field += '"'; i++; } else quoted = !quoted;
    } else if (char === ',' && !quoted) { row.push(field); field = ''; }
    else if ((char === '\n' || char === '\r') && !quoted) {
      if (char === '\r' && text[i + 1] === '\n') i++;
      row.push(field); if (row.some(Boolean)) rows.push(row); row = []; field = '';
    } else field += char;
  }
  if (quoted) throw new Error('Unterminated CSV field');
  if (field || row.length) { row.push(field); rows.push(row); }
  return rows;
}
function csvObjects(text) {
  const [header, ...rows] = parseCsv(text.replace(/^\uFEFF/, ''));
  return rows.map(row => { if (row.length !== header.length) throw new Error('Unexpected CSV column count'); return Object.fromEntries(header.map((key, i) => [key, row[i]])); });
}
function buildCountries(rows, overrides) {
  const entries = rows.filter(row => /^[A-Z]{2}$/.test(row.code) && !overrides.exclude.includes(row.code)).map(row => ({
    key: row.code, name: row.name, region: CONTINENTS[row.continent] ?? 'Other',
    ...(overrides.aliases[row.code] ? { aliases: overrides.aliases[row.code] } : {}),
  }));
  for (const addition of overrides.add) {
    if (entries.some(row => row.key === addition.key)) throw new Error(`Country addition already in source: ${addition.key}`);
    entries.push({ key: addition.key, name: addition.name, region: addition.region,
      ...(overrides.aliases[addition.key] ? { aliases: overrides.aliases[addition.key] } : {}) });
  }
  return entries.sort(order);
}
function buildAirports(rows, countries) {
  const byCountry = new Map(countries.map(row => [row.key, row]));
  const entries = [];
  for (const row of rows) {
    if (row.scheduled_service !== 'yes' || !['small_airport','medium_airport','large_airport','seaplane_base'].includes(row.type) || !/^[A-Z]{3}$/.test(row.iata_code)) continue;
    const lat = Number(row.latitude_deg), lon = Number(row.longitude_deg);
    if (!row.latitude_deg?.trim() || !row.longitude_deg?.trim() || !Number.isFinite(lat) || !Number.isFinite(lon) || Math.abs(lat) > 90 || Math.abs(lon) > 180) continue;
    const countryKey = ['HGA','BBO'].includes(row.iata_code) ? 'X-SOMALILAND' : row.iso_country;
    const country = byCountry.get(countryKey);
    entries.push({ key:row.iata_code, name:row.name, city:row.municipality || '', country:countryKey,
      countryName:country?.name ?? countryKey, region:CONTINENTS[row.continent] ?? country?.region ?? 'Other',
      lat, lon, icao:row.icao_code || row.ident, sourceId:row.id });
  }
  if (new Set(entries.map(row => row.key)).size !== entries.length) throw new Error('Ambiguous airport IATA codes require review');
  return entries.sort(order);
}
function buildAirlines(bindings, countries, snapshotDate) {
  const byCountry = new Map(countries.map(row => [row.key, row]));
  const groups = new Map(), rejected = { ended:0, incomplete:0, sharedCodes:[] };
  for (const binding of bindings) {
    const row = Object.fromEntries(Object.entries(binding).map(([key, value]) => [key, value.value]));
    if ([row.dissolved, row.codeEnd].some(date => date && date.slice(0,10) <= snapshotDate)) { rejected.ended++; continue; }
    if (!/^[A-Z0-9]{2}$/.test(row.iata ?? '') || !/^[A-Z]{3}$/.test(row.icao ?? '') || !byCountry.has(row.iso) || !row.airlineLabel || /^Q\d+$/.test(row.airlineLabel)) { rejected.incomplete++; continue; }
    const id = row.airline.split('/').pop();
    const entry = groups.get(id) ?? { id, name:row.airlineLabel, codes:new Set(), icaos:new Set(), countries:new Set() };
    entry.codes.add(row.iata); entry.icaos.add(row.icao); entry.countries.add(row.iso); groups.set(id, entry);
  }
  const owners = new Map();
  for (const entry of groups.values()) for (const code of entry.codes) {
    const candidates = owners.get(code) ?? []; candidates.push(entry); owners.set(code, candidates);
  }
  rejected.sharedCodes = [...owners].filter(([,entries]) => entries.length > 1).map(([code]) => code).sort();
  const entries = [];
  for (const [code,candidates] of owners) {
    // Stable representative, never an assertion that one operating carrier owns a shared code.
    candidates.sort((a,b) => Number(a.id.slice(1)) - Number(b.id.slice(1)));
    const entry = candidates[0], keys = [...entry.countries].sort(), country = keys.length === 1 ? byCountry.get(keys[0]) : undefined;
    entries.push({ key:code, name:entry.name, aliases:[...new Set(candidates.slice(1).map(candidate => candidate.name))],
      ...(country ? {country:country.key,countryName:country.name,region:country.region} : {region:'International'}),
      icao:[...entry.icaos].sort().join(' / '), sourceId:entry.id,
      sourceUrl:`https://www.wikidata.org/wiki/${entry.id}`, sharedCode:candidates.length > 1,
      operators:candidates.map(candidate => ({key:candidate.id,name:candidate.name,
        countries:[...candidate.countries].sort(),icao:[...candidate.icaos].sort(),sourceUrl:`https://www.wikidata.org/wiki/${candidate.id}`})) });
  }
  return { entries:entries.sort(order), rejected };
}
function generate() {
  const manifest = JSON.parse(fs.readFileSync(path.join(folder,'sources/manifest.json'),'utf8'));
  const snapshots = {};
  for (const source of manifest.sources) {
    const bytes = zlib.gunzipSync(fs.readFileSync(path.join(folder,'sources',source.file)));
    if (crypto.createHash('sha256').update(bytes).digest('hex') !== source.sha256) throw new Error(`Source checksum differs: ${source.file}`);
    snapshots[source.file] = bytes.toString('utf8');
  }
  const overrides = JSON.parse(fs.readFileSync(path.join(folder,'country-overrides.json'),'utf8'));
  const countries = buildCountries(csvObjects(snapshots['countries.csv.gz']),overrides);
  const airports = buildAirports(csvObjects(snapshots['airports.csv.gz']),countries);
  const airlines = buildAirlines(JSON.parse(snapshots['airlines.json.gz']).results.bindings,countries,manifest.snapshotDate);
  const source = name => manifest.sources.filter(row => row.file.startsWith(name)).map(row => ({
    name: name === 'airlines' ? 'Wikidata' : 'OurAirports', url:row.url, license:row.license, sha256:row.sha256,
    ...(row.revision ? { revision:row.revision } : {}), retrievedAt:row.retrievedAt,
  }));
  const metadata = (label,scope,notes,sources,entries) => ({version:manifest.version,snapshotDate:manifest.snapshotDate,label,scope,notes,sources,total:entries.length});
  return {
    'countries.json': {metadata:metadata('Countries & territories','ISO countries and territories, plus Kosovo and Somaliland.',
      ['Connections count as visits using the existing passport first-entry rules.','OurAirports names and continents; AX, BV and SJ complete the ISO list. XP and ZZ are excluded. Somaliland uses the existing X-SOMALILAND travel identity.'],source('countries'),countries),entries:countries},
    'airports.json': {metadata:metadata('Scheduled airports','IATA-coded airfields with scheduled airline service in this snapshot.',
      ['Small, medium and large airports and scheduled seaplane bases are included; closed airfields and heliports are excluded.','Scheduled service is the source flag, not independently verified passenger timetables. Historic and other recorded airports remain separate from this catalogue.','Country follows Trotter travel identity for HGA and BBO.'],source('airports'),airports),entries:airports},
    'airlines.json': {metadata:metadata('Airline code catalogue','Distinct IATA airline designators recorded in Wikidata.',
      ['Requires an airline entity, IATA and ICAO designators, and a known country. Recorded dissolution or designator end dates before this snapshot are excluded.','This is a defined code catalogue, not a verified census of airlines operating today. Source data can be incomplete or stale; passenger, charter and cargo airlines can be present.','Shared marketing codes count once, with every eligible source operator retained. The displayed representative is the lowest numbered Wikidata entity, not a claimed code owner. Historical and unknown codes remain in your recorded collection; an old record with a reused code cannot identify its historical operator from that code alone.'],source('airlines'),airlines.entries),entries:airlines.entries},
    'generation-report.json': {version:manifest.version,countries:countries.length,airports:airports.length,airlines:airlines.entries.length,airlineExclusions:airlines.rejected},
  };
}
function main() {
  const check = process.argv.includes('--check'), result = generate();
  for (const [name,value] of Object.entries(result)) {
    const text = JSON.stringify(value,null,2)+'\n', file = path.join(folder,name);
    if (check) { if (!fs.existsSync(file) || fs.readFileSync(file,'utf8') !== text) throw new Error(`Generated catalogue is stale: ${name}`); }
    else fs.writeFileSync(file,text);
  }
  console.log(`${check ? 'Verified' : 'Generated'} collections: ${JSON.stringify(result['generation-report.json'])}`);
}
module.exports = {parseCsv,csvObjects,buildCountries,buildAirports,buildAirlines,generate,normalize};
if (require.main === module) main();
