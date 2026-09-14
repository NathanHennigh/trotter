import type { StampShapeKey, StampTemplate, StampTemplateBundle } from '../../trotter/stamps/PngStamp';
import templates from '../../trotter/stamps/stampTemplates.json';
import { resolveStampGeometry } from '../../trotter/stamps/stampGeometry';
export function nativeStampTemplate(shape: StampShapeKey, country: string) {
  const bundle = (templates as unknown as Record<StampShapeKey, StampTemplateBundle>)[shape];
  const preset = bundle.presets?.find(p => country.length >= p.charRange[0] && country.length <= p.charRange[1]);
  const result = { ...bundle.default, ...preset?.overrides } as StampTemplate;
  for (const box of ['frame', 'country', 'icon', 'place', 'date', 'airport'] as const) result[box] = { ...bundle.default[box], ...preset?.overrides[box] };
  return resolveStampGeometry(shape, result, 204.75, 165.75);
}
