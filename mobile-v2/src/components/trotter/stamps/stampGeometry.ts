import type { StampShapeKey, StampTemplate } from './PngStamp';

export type StampBox = { left: number; top: number; width: number; height: number };

// Intrinsic dimensions of the unchanged processed PNGs. Image contain centers
// these inside the template frame box; content must follow the painted image.
export const STAMP_FRAME_PIXELS: Record<StampShapeKey, readonly [number, number]> = {
  archedCountryCanonical: [379, 452],
  archedCountryBanner: [333, 457],
  archedCountryVariant: [265, 291],
  circularCityClean: [316, 316],
  circularCityDoubleLine: [278, 280],
  roundedImmigrationCanonical: [349, 256],
  roundedImmigrationWithBand: [346, 241],
  shieldBadgeRounded: [291, 324],
};

export function containStampFrame(box: StampBox, image: readonly [number, number], width: number, height: number): StampBox {
  const fit = Math.min(box.width * width / image[0], box.height * height / image[1]);
  const imageWidth = image[0] * fit / width;
  const imageHeight = image[1] * fit / height;
  return { left: box.left + (box.width - imageWidth) / 2, top: box.top + (box.height - imageHeight) / 2, width: imageWidth, height: imageHeight };
}

/** Returns canvas-normalized coordinates shared by native and SVG/web renderers. */
export function resolveStampGeometry(shape: StampShapeKey, template: StampTemplate, width: number, height: number): StampTemplate {
  const frame = containStampFrame(template.frame, STAMP_FRAME_PIXELS[shape], width, height);
  // Old saved editor templates use canvas coordinates. New calibrated templates
  // use visible-frame coordinates so headers and footer bands stay aligned.
  if (template.coordinateSpace !== 'frame') return { ...template, frame };
  const inFrame = <T extends StampBox>(box: T): T => ({
    ...box,
    left: frame.left + box.left * frame.width,
    top: frame.top + box.top * frame.height,
    width: box.width * frame.width,
    height: box.height * frame.height,
  });
  return { ...template, coordinateSpace: 'canvas', frame,
    country: inFrame(template.country), icon: inFrame(template.icon),
    place: inFrame(template.place), date: inFrame(template.date), airport: inFrame(template.airport),
  };
}
