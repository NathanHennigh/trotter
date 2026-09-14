import { countryIconAssets } from '../../../assets/generated/stampAssetManifest';
// Artwork added during the World Window exploration; existing calibrated native
// assets/manifest stay untouched. There is no traveler data in these images.
export const extraPassportArtwork: Record<string, number> = { tunisia_el_jem: require('../../../../assets/world-window/passport/tunisia_el_jem.png') };
export const passportArtwork: Record<string, number> = { ...countryIconAssets, ...extraPassportArtwork };
