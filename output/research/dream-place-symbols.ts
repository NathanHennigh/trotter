/**
 * Small travel-stationery symbols. All geometry uses a 24 × 24 viewBox.
 * Render paths with fill="none", stroke="currentColor", strokeWidth={1.4},
 * strokeLinecap="round" and strokeLinejoin="round". No icon needs a fill.
 * Designed for a 20 px map glyph or a 20–22 px glyph inside a 30 px paper tile.
 * Keep any pin, perforation or tile treatment outside this geometry.
 */
export type PlaceSymbol =
  | 'cafe'
  | 'restaurant'
  | 'hotel'
  | 'landmark'
  | 'bookshop'
  | 'walk'
  | 'lookout'
  | 'pin';

export const symbolPaths: Record<PlaceSymbol, string[]> = {
  // A shallow porcelain cup, open handle, two short curls and a saucer.
  cafe: [
    'M5 9h11.5v4.8a5.2 5.2 0 0 1-5.2 5.2h-1.1A5.2 5.2 0 0 1 5 13.8Z',
    'M16.5 10h1.6a3 3 0 0 1 0 6h-2.1',
    'M3.5 21h15',
    'M8 6.5c-1.4-1.1 1.3-2.3 0-3.5M12.5 6.5c-1.4-1.1 1.3-2.3 0-3.5',
  ],
  // A dinner plate between a three-tine fork and a slim table knife.
  restaurant: [
    'M17.8 12a5.6 5.6 0 1 1-11.2 0a5.6 5.6 0 0 1 11.2 0Z',
    'M2.5 4v4a1.5 1.5 0 0 0 3 0V4M4 4v16',
    'M21.5 4c-2 1.8-2.3 4.5-2.3 7h2.3M21.5 4v16',
  ],
  // An old room key: generous oval bow, simple shaft and stepped bit.
  hotel: [
    'M15.7 6.1a3.7 4.1 0 1 1-7.4 0a3.7 4.1 0 0 1 7.4 0Z',
    'M12 10.2V21h4v-3h-4M12 15.5h2.5',
  ],
  // A three-column portico, with a single pediment and two low steps.
  landmark: [
    'M3 8.5 12 3l9 5.5Z',
    'M6 11v7.5M12 11v7.5M18 11v7.5',
    'M4.5 18.5h15M3 21h18',
  ],
  // An open cloth-bound book. The centre seam remains clear at small sizes.
  bookshop: [
    'M12 6.5C9.5 4.6 6.6 4.3 3 5v13c3.6-.7 6.5-.4 9 1.5 2.5-1.9 5.4-2.2 9-1.5V5c-3.6-.7-6.5-.4-9 1.5Z',
    'M12 6.5v13',
    'M6 8.5c1.1 0 2.1.2 3 .6M15 9.1c.9-.4 1.9-.6 3-.6',
  ],
  // A winding path between two small open waypoints.
  walk: [
    'M8.5 4a1.5 1.5 0 1 1-3 0a1.5 1.5 0 0 1 3 0Z',
    'M8.5 4c11 0 12.2 5.2 3.3 8S3.5 20 14.5 20',
    'M17.5 20a1.5 1.5 0 1 1-3 0a1.5 1.5 0 0 1 3 0Z',
  ],
  // Compact field glasses, with two lens rings and a plain central bridge.
  lookout: [
    'M10 16.5a3.7 3.7 0 1 1-7.4 0a3.7 3.7 0 0 1 7.4 0Z',
    'M21.4 16.5a3.7 3.7 0 1 1-7.4 0a3.7 3.7 0 0 1 7.4 0Z',
    'M2.9 15.1 5.3 5.5h3l1.5 9.6M14.2 15.1l1.5-9.6h3l2.4 9.6',
    'M10 12.4h4',
  ],
  // The fallback remains a quiet map pin, with one open centre.
  pin: [
    'M18.5 9.2C18.5 14 12 21 12 21S5.5 14 5.5 9.2a6.5 6.5 0 0 1 13 0Z',
    'M14.2 9.2a2.2 2.2 0 1 1-4.4 0a2.2 2.2 0 0 1 4.4 0Z',
  ],
};

/** Supports the existing save categories and imported singular/plural labels. */
export function placeSymbol(category: string): PlaceSymbol {
  const value = category
    .normalize('NFKD')
    .replace(/\p{M}/gu, '')
    .toLowerCase()
    .replace(/[_-]+/g, ' ')
    .trim();

  // Specific compound categories take priority over general ones.
  if (/\b(bookshops?|bookstores?|books?|libraries|library)\b/.test(value)) return 'bookshop';
  if (/\b(lookouts?|viewpoints?|observation|miradouro|binoculars?)\b/.test(value)) return 'lookout';
  if (/\b(cafes?|cafeterias?|coffee|tearooms?|tea room|bakeries|bakery|patisseries?)\b/.test(value)) return 'cafe';
  if (/\b(restaurants?|dining|eateries|eatery|bistros?|brasseries?)\b/.test(value)) return 'restaurant';
  if (/\b(hotels?|hostels?|lodging|stays?|resorts?|inns?|guesthouses?|guest house)\b/.test(value)) return 'hotel';
  if (/\b(walks?|walking|trails?|hikes?|hiking|paths?|promenades?)\b/.test(value)) return 'walk';
  if (/\b(landmarks?|monuments?|museums?|architecture|historic|temples?|palaces?|attractions?)\b/.test(value)) return 'landmark';
  return 'pin';
}
