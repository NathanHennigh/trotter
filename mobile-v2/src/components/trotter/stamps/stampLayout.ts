export type StampFontOptions = {
  charFactor?: number;
  tracking?: number;
  adaptiveLength?: boolean;
};

function lengthBoost(len: number) {
  if (len <= 4) return 1.18;
  if (len <= 6) return 1.08;
  if (len <= 9) return 1.0;
  if (len <= 12) return 0.92;
  if (len <= 15) return 0.84;
  return 0.76;
}

export function fitFontSize(text: string, baseSize: number, boxWidth: number, boxHeight: number, options?: StampFontOptions, rootWidth: number = 204.75) {
  const charFactor = options?.charFactor ?? 0.62;
  const tracking = (options?.tracking ?? 0) * (rootWidth / 204.75);
  const adaptive = options?.adaptiveLength === false ? 1 : lengthBoost(text.length);
  const adjusted = baseSize * adaptive;
  const glyphWidth = Math.max(1, text.length * adjusted * charFactor);
  const availableWidth = Math.max(0, boxWidth - Math.max(0, text.length - 1) * tracking);
  const widthScale = Math.min(1, availableWidth / glyphWidth);
  const heightScale = Math.min(1, (boxHeight * 0.88) / adjusted);
  // A minimum font floor must never override the measured content bounds.
  return adjusted * Math.min(widthScale, heightScale);
}

