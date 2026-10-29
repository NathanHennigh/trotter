import type { ViewStyle } from 'react-native';

/** Coordinates are relative to the screen's safe-area top. */
export const HEADER_GEOMETRY = {
  horizontalInset: 24,
  topInset: 14,
  bottomInset: 19,
  touchSize: 44,
  avatarSize: 32,
} as const;

export const headerRowStyle: ViewStyle = {
  flexDirection: 'row',
  alignItems: 'flex-start',
  gap: 14,
  paddingHorizontal: HEADER_GEOMETRY.horizontalInset,
  paddingTop: HEADER_GEOMETRY.topInset,
  paddingBottom: HEADER_GEOMETRY.bottomInset,
  minHeight: HEADER_GEOMETRY.topInset + HEADER_GEOMETRY.touchSize + HEADER_GEOMETRY.bottomInset,
};

export const headerActionStyle: ViewStyle = {
  flexShrink: 0,
  alignSelf: 'flex-start',
  minHeight: HEADER_GEOMETRY.touchSize,
  justifyContent: 'center',
};
