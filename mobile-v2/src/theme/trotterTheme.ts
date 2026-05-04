export const colors = {
  appBackground: '#07141A',
  dashboard: '#151412',
  dashboardSoft: '#201D19',
  paper: '#F3E7CF',
  paperSoft: '#F8EEDB',
  paperDeep: '#E7D7B8',
  ink: '#1B1B18',
  mutedInk: '#5D5549',
  creamText: '#EADDC4',
  subtleText: '#A89674',
  brass: '#B98A42',
  brassSoft: '#D5B46D',
  red: '#B6543F',
  redDeep: '#8F382B',
  teal: '#4F8780',
  tealDeep: '#356B66',
  mustard: '#C79A43',
  green: '#52745A',
  blue: '#2F5E9E',
  purple: '#6C4C85',
  paperBorder: '#D8C49E',
  paperBorderSoft: '#E5D5B7',
  darkBorder: '#3A3024',
  divider: '#C8B895',
  shadow: 'rgba(34, 22, 10, 0.24)',
  darkShadow: 'rgba(0, 0, 0, 0.45)',
};

export const radii = {
  xs: 6,
  sm: 10,
  md: 14,
  lg: 20,
  xl: 28,
  pill: 999,
};

export const spacing = {
  xs: 4,
  sm: 8,
  md: 12,
  lg: 16,
  xl: 24,
  xxl: 32,
};

export const layout = {
  screenPadding: 24,
  cardGap: 12,
  bottomNavHeight: 88,
};

export const fonts = {
  display: 'Outfit_700Bold',
  sans: 'Outfit_500Medium',
  sansRegular: 'Outfit_400Regular',
  sansSemi: 'Outfit_600SemiBold',
  sansBold: 'Outfit_700Bold',
  mono: 'Courier New',
};

export const shadows = {
  paper: {
    shadowColor: '#22160A',
    shadowOpacity: 0.18,
    shadowRadius: 10,
    shadowOffset: { width: 0, height: 5 },
    elevation: 4,
  },
  darkPanel: {
    shadowColor: '#000',
    shadowOpacity: 0.45,
    shadowRadius: 12,
    shadowOffset: { width: 0, height: 6 },
    elevation: 6,
  },
};

export type TrotterAccent = 'red' | 'teal' | 'mustard' | 'blue' | 'green';

export const accentColors: Record<TrotterAccent, string> = {
  red: colors.red,
  teal: colors.teal,
  mustard: colors.mustard,
  blue: colors.blue,
  green: colors.green,
};
