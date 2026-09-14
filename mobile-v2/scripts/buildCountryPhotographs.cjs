// Encode the curated real photographs only. The rejected generated artwork
// remains in output/country-postcards and is never an input to this pipeline.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');
const sharp = require('sharp');
const root = path.resolve(__dirname, '../..');
const masters = path.join(root, 'output/country-photographs');
const output = path.join(root, 'mobile-v2/assets/world-window/dreams/countries');
const hash = bytes => crypto.createHash('sha256').update(bytes).digest('hex');

(async () => {
  const sources = fs.readdirSync(masters)
    .filter(name => /^sources-.*\.json$/.test(name))
    .flatMap(name => JSON.parse(fs.readFileSync(path.join(masters, name), 'utf8')))
    .sort((a, b) => a.code.localeCompare(b.code));
  assert.equal(sources.length, 16, 'Every active country must have a curated photograph');
  assert.equal(new Set(sources.map(s => s.code)).size, sources.length, 'Duplicate photo sources');
  const records = [];
  for (const source of sources) {
    assert(/^[A-Z]{2}$/.test(source.code));
    assert(source.photographer && source.sourcePage && source.imageUrl && source.licenseUrl);
    const master = path.join(masters, `${source.code}.jpg`);
    const bytes = fs.readFileSync(master), metadata = await sharp(bytes).metadata();
    assert(metadata.width >= 1600 && metadata.height >= 1000, `${source.code}: insufficient resolution`);
    const file = `${source.code}.webp`;
    // Preserve the photographer's framing and colors. React Native supplies
    // the responsive cover crop; this conversion only reduces file size.
    const encoded = await sharp(bytes).autoOrient().resize({ width: 1600, withoutEnlargement: true })
      .webp({ quality: 88, effort: 6 }).toFile(path.join(output, file));
    records.push({
      code: source.code, country: source.country, title: source.title,
      photographer: source.photographer, sourcePage: source.sourcePage,
      imageUrl: source.imageUrl, license: 'Unsplash License', licenseUrl: source.licenseUrl,
      attributionRequired: false, sourceType: 'photograph',
      verifiedAt: new Date().toISOString(),
      sourceEvidence: source.sourceEvidence || source.notes,
      notes: source.notes || source.cropNotes,
      master: { file: `output/country-photographs/${source.code}.jpg`, width: metadata.width, height: metadata.height, bytes: bytes.length, sha256: hash(bytes) },
      bundled: { file, width: encoded.width, height: encoded.height, bytes: encoded.size, sha256: hash(fs.readFileSync(path.join(output, file))) },
      processing: 'Orientation and proportional downsize to 1600px wide, WebP quality 88. No color filter, generative edits, retouching or compositing.',
    });
  }
  fs.writeFileSync(path.join(output, 'photo-sources.json'), JSON.stringify(records, null, 2) + '\n');
  console.log(JSON.stringify({ photographs: records.length, bytes: records.reduce((n, s) => n + s.bundled.bytes, 0) }));
})().catch(error => { console.error(error); process.exitCode = 1; });
