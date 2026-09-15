const fs = require('node:fs');
const path = require('node:path');
const sharp = require('../../../../artifacts/trotter-directions-site/node_modules/sharp');
const marks = {
  window: { color:'#427494', paper:'#faf8f2', body:`<defs><mask id="cut"><rect width="48" height="48" fill="white"/><path d="M5.590 30.315A20 5 -23 0 0 42.410 14.685" stroke="black" stroke-width="3.5" fill="none"/><circle cx="42.462" cy="15.636" r="3.8" fill="black"/></mask></defs><path d="M5.590 30.315A20 5 -23 0 1 42.410 14.685" stroke="currentColor" stroke-width="1.35"/><path d="M14 13h20v4h-7.5v15h-5V17H14Z" fill="currentColor" mask="url(#cut)"/><path d="M5.590 30.315A20 5 -23 0 0 42.410 14.685" stroke="currentColor" stroke-width="1.7"/><circle cx="42.462" cy="15.636" r="2.3" fill="currentColor"/>` },
  lounge: { color:'#284f40', paper:'#faf7ee', body:`<ellipse cx="24" cy="24" rx="18" ry="22" stroke="currentColor"/><ellipse cx="24" cy="24" rx="15" ry="19" stroke="currentColor" stroke-width=".6"/><path d="M13 13h22l1 7h-1c-1-4-3-5-7-5h-1v20l5 1v1H16v-1l5-1V15h-1c-4 0-6 1-7 5h-1Z" fill="currentColor"/>` },
  continental: { color:'#174d87', paper:'#f7f7f0', body:`<path d="M5 6h38v9H29v27H19V15H5Z" fill="currentColor"/><path d="M5 23h9M5 30h9M5 37h9M34 23h9M34 30h9M34 37h9" stroke="currentColor" stroke-width="3"/>` }
};
(async () => {
  for(const [key, mark] of Object.entries(marks)) {
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="800" height="800" viewBox="-12 -12 72 72" style="color:${mark.color}" fill="none"><rect x="-12" y="-12" width="72" height="72" fill="${mark.paper}"/>${mark.body}</svg>`;
    fs.writeFileSync(path.join(__dirname,`${key}-current.svg`), svg);
    await sharp(Buffer.from(svg)).png().toFile(path.join(__dirname,`${key}-current.png`));
  }
  process.stdout.write('Rendered three current source marks as reference images.\n');
})();
