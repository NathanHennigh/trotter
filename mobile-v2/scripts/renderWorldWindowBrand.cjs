const path = require('node:path');
const sharp = require('sharp');
const root = path.resolve(__dirname, '..');
const paths = require('../src/components/world-window/emblem-paths.json');
const emblem = paths.map(d => `<path d="${d}"/>`).join('');
function svg(size, splash = false) {
  const width = splash ? 180 : 660;
  return Buffer.from(`<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 1024 1024">${splash ? '' : '<rect width="1024" height="1024" fill="#FAF8F2"/>'}<svg x="${(1024-width)/2}" y="${(1024-width*333/450)/2}" width="${width}" height="${width*333/450}" viewBox="64 147 450 333" fill="#427494">${emblem}</svg></svg>`);
}
async function build() {
  await sharp(svg(1024)).png().toFile(path.join(root, 'assets/world-window/app-icon.png'));
  for (const [dpi, size] of Object.entries({ mdpi: 48, hdpi: 72, xhdpi: 96, xxhdpi: 144, xxxhdpi: 192 })) {
    for (const name of ['ic_launcher', 'ic_launcher_round']) await sharp(svg(size)).webp({ lossless: true }).toFile(path.join(root, `android/app/src/main/res/mipmap-${dpi}/${name}.webp`));
  }
  for (const [dpi, size] of Object.entries({ mdpi: 288, hdpi: 432, xhdpi: 576, xxhdpi: 864, xxxhdpi: 1152 })) {
    await sharp(svg(size, true)).png().toFile(path.join(root, `android/app/src/main/res/drawable-${dpi}/splashscreen_logo.png`));
  }
  console.log('World Window launcher and splash artwork rendered from the approved R07 vector.');
}
build().catch(error => { console.error(error); process.exitCode = 1; });
