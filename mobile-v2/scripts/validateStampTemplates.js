const fs = require('fs');
const path = require('path');

const stampFile = path.join(__dirname, '..', 'src', 'components', 'trotter', 'stamps', 'PngStamp.tsx');
const source = fs.readFileSync(stampFile, 'utf8');

const shapeNames = [
  'archedCountryCanonical',
  'archedCountryBanner',
  'archedCountryVariant',
  'circularCityClean',
  'circularCityDoubleLine',
  'roundedImmigrationCanonical',
  'roundedImmigrationWithBand',
  'shieldBadgeRounded',
  'ticketStubNotched',
  'horizontalAirportOblong',
];

const requiredBoxes = ['frame', 'country', 'icon', 'place', 'date', 'footer'];
const sampleCountryNames = ['JAPAN', 'MEXICO', 'PHILIPPINES', 'SINGAPORE', 'DOMINICAN REPUBLIC', 'UNITED KINGDOM'];
const sampleCityNames = ['TOKYO', 'PUNTA CANA', 'FRANKFURT AM MAIN', 'ADDIS ABABA', 'MARRAKESH'];
let failures = 0;

for (const shape of shapeNames) {
  const shapeStart = source.indexOf(`${shape}: {`);
  if (shapeStart === -1) {
    console.error(`Missing template for ${shape}`);
    failures += 1;
    continue;
  }

  const nextShapeStarts = shapeNames
    .map((name) => source.indexOf(`${name}: {`, shapeStart + 1))
    .filter((index) => index !== -1);
  const shapeEnd = nextShapeStarts.length ? Math.min(...nextShapeStarts) : source.indexOf('};', shapeStart);
  const block = source.slice(shapeStart, shapeEnd);

  for (const boxName of requiredBoxes) {
    const match = block.match(new RegExp(`${boxName}: \\{ left: ([0-9.]+), top: ([0-9.]+), width: ([0-9.]+), height: ([0-9.]+)`));
    if (!match) {
      console.error(`Missing ${boxName} box for ${shape}`);
      failures += 1;
      continue;
    }

    const [, left, top, width, height] = match.map(Number);
    const right = left + width;
    const bottom = top + height;
    if (left < 0 || top < 0 || right > 1 || bottom > 1 || width <= 0 || height <= 0) {
      console.error(`${shape}.${boxName} out of bounds: left=${left}, top=${top}, right=${right}, bottom=${bottom}`);
      failures += 1;
    }
  }

  const countryMatch = block.match(/maxCountryChars: ([0-9]+)/);
  const placeMatch = block.match(/maxPlaceChars: ([0-9]+)/);
  if (!countryMatch || !placeMatch) {
    console.error(`Missing text limits for ${shape}`);
    failures += 1;
    continue;
  }

  const maxCountryChars = Number(countryMatch[1]);
  const maxPlaceChars = Number(placeMatch[1]);
  if (shape.startsWith('circularCity')) {
    const straightMatch = block.match(/straightTitleMaxChars: ([0-9]+)/);
    const circleArcMatch = block.match(/titleMode: 'circleArc'/);
    const arcDepthMatch = block.match(/arcDepth: ([0-9.]+)/);
    const arcTextLengthMatch = block.match(/arcTextLength: ([0-9.]+)/);
    if (!circleArcMatch) {
      console.error(`${shape} must use the inner-ring circle arc title renderer`);
      failures += 1;
    }
    if (!straightMatch || Number(straightMatch[1]) > 6) {
      console.error(`${shape} must arc country titles longer than 6 characters`);
      failures += 1;
    }
    if (!arcDepthMatch || Number(arcDepthMatch[1]) < 2.2) {
      console.error(`${shape} needs a strong circle arc depth`);
      failures += 1;
    }
    if (!arcTextLengthMatch || Number(arcTextLengthMatch[1]) < 0.85) {
      console.error(`${shape} needs long country text stretched across the circle arc`);
      failures += 1;
    }
  }
  for (const sample of sampleCountryNames) {
    const firstWord = sample.split(' ')[0];
    const fitted = sample.length <= maxCountryChars ? sample : firstWord.length <= maxCountryChars ? firstWord : firstWord.slice(0, maxCountryChars);
    if (fitted.length > maxCountryChars) {
      console.error(`${shape} country limit failed for ${sample}`);
      failures += 1;
    }
  }
  for (const sample of sampleCityNames) {
    const firstWord = sample.split(' ')[0];
    const fitted = sample.length <= maxPlaceChars ? sample : firstWord.length <= maxPlaceChars ? firstWord : firstWord.slice(0, maxPlaceChars);
    if (fitted.length > maxPlaceChars) {
      console.error(`${shape} place limit failed for ${sample}`);
      failures += 1;
    }
  }
}

if (failures > 0) {
  process.exitCode = 1;
} else {
  console.log(`Validated ${shapeNames.length} stamp templates.`);
}
