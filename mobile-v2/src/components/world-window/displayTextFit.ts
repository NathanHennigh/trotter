import widths from './display-font-widths.json';

/** Unkerned advances measured from the two bundled Newsreader fonts, in em. */
export function longestDisplayWord(text: string, variant: 'regular' | 'italic' = 'regular') {
  const advances = widths[variant] as Record<string, number>;
  return Math.max(0, ...text.split(/\s+/u).map(word => [...word.normalize('NFD').replace(/\p{M}/gu, '')]
    .reduce((sum, character) => sum + (advances[character] ?? 1), 0)));
}

/** Fit complete words only when text is enlarged; ordinary typography is unchanged. */
export function fitDisplayFont(text: string, baseSize: number, availableWidth: number, fontScale = 1, variant: 'regular' | 'italic' = 'regular') {
  if (fontScale <= 1 || !Number.isFinite(fontScale)) return baseSize;
  const word = longestDisplayWord(text, variant);
  if (!word || !Number.isFinite(availableWidth) || availableWidth <= 2) return baseSize;
  // No negative letter-spacing/kerning credit; 2px covers rounding at the edge.
  return Math.min(baseSize, (availableWidth - 2) / (word * fontScale));
}
