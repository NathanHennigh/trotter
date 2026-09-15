const fs = require('node:fs');
const path = require('node:path');
const sharp = require('../../mobile-v2/node_modules/sharp');
// Historical generated set only; do not overwrite the curated photographs.
const output = path.join(__dirname, 'generated-archive');
fs.mkdirSync(output, { recursive: true });

// Keep full-resolution generated PNG masters here; encode compact app copies.
// No crop, resize, compositing, or color treatment is applied.
(async () => {
  const results = [];
  for (const filename of fs.readdirSync(__dirname).filter(name => /^[A-Z]{2}\.png$/.test(name))) {
    const source = path.join(__dirname, filename);
    const target = path.join(output, filename.replace('.png', '.webp'));
    const info = await sharp(source).webp({ quality: 90, effort: 6 }).toFile(target);
    results.push({ country: filename.slice(0, 2), width: info.width, height: info.height, bytes: info.size });
  }
  fs.writeFileSync(path.join(__dirname, 'encoded-assets.json'), JSON.stringify(results, null, 2));
  console.log(JSON.stringify({ count: results.length, bytes: results.reduce((sum, item) => sum + item.bytes, 0) }));
})();
