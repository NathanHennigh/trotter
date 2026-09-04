import { Platform } from 'react-native';

const WEB_PREVIEW_WIDTH = 393;
const MAX_DEVICE_WIDTH = 430;

export function getMobileVisualWidth(windowWidth: number) {
  if (Platform.OS !== 'web') return Math.min(windowWidth, MAX_DEVICE_WIDTH);

  const browserWidth = (globalThis as { innerWidth?: number }).innerWidth;
  const viewportWidth = typeof browserWidth === 'number' && browserWidth > 0
    ? browserWidth
    : windowWidth;
  return Math.min(viewportWidth, WEB_PREVIEW_WIDTH);
}
