import type { ImageSourcePropType } from "react-native";

export type CountryArtwork = {
  code: string;
  country: string;
  source: ImageSourcePropType;
  aliases: readonly string[];
};

// One reusable country cover, independent of the number of cities or saves.
// Metro needs literal requires to include every picture in the offline bundle.
// Add new countries here as the collection grows; unsupported names use a reel.
export const countryArtworkCatalog: readonly CountryArtwork[] = [
  { code: "FR", country: "France", aliases: ["FRA", "French Republic"], source: require("../../../../assets/world-window/dreams/countries/FR.webp") },
  { code: "ES", country: "Spain", aliases: ["ESP", "España", "Kingdom of Spain"], source: require("../../../../assets/world-window/dreams/countries/ES.webp") },
  { code: "IT", country: "Italy", aliases: ["ITA", "Italia", "Italian Republic"], source: require("../../../../assets/world-window/dreams/countries/IT.webp") },
  { code: "GR", country: "Greece", aliases: ["GRC", "EL", "Hellenic Republic", "Hellas"], source: require("../../../../assets/world-window/dreams/countries/GR.webp") },
  { code: "PT", country: "Portugal", aliases: ["PRT", "Portuguese Republic"], source: require("../../../../assets/world-window/dreams/countries/PT.webp") },
  { code: "GB", country: "United Kingdom", aliases: ["GBR", "UK", "U.K.", "Great Britain", "Britain", "United Kingdom of Great Britain and Northern Ireland"], source: require("../../../../assets/world-window/dreams/countries/GB.webp") },
  { code: "CH", country: "Switzerland", aliases: ["CHE", "Swiss Confederation", "Schweiz", "Suisse", "Svizzera"], source: require("../../../../assets/world-window/dreams/countries/CH.webp") },
  { code: "TR", country: "Türkiye", aliases: ["TUR", "Turkey", "Republic of Türkiye", "Republic of Turkey"], source: require("../../../../assets/world-window/dreams/countries/TR.webp") },
  { code: "US", country: "United States", aliases: ["USA", "U.S.", "U.S.A.", "United States of America"], source: require("../../../../assets/world-window/dreams/countries/US.webp") },
  { code: "MX", country: "Mexico", aliases: ["MEX", "México", "United Mexican States"], source: require("../../../../assets/world-window/dreams/countries/MX.webp") },
  { code: "JP", country: "Japan", aliases: ["JPN", "日本"], source: require("../../../../assets/world-window/dreams/countries/JP.webp") },
  { code: "TH", country: "Thailand", aliases: ["THA", "Kingdom of Thailand"], source: require("../../../../assets/world-window/dreams/countries/TH.webp") },
  { code: "ID", country: "Indonesia", aliases: ["IDN", "Republic of Indonesia"], source: require("../../../../assets/world-window/dreams/countries/ID.webp") },
  { code: "VN", country: "Vietnam", aliases: ["VNM", "Viet Nam", "Việt Nam", "Socialist Republic of Vietnam"], source: require("../../../../assets/world-window/dreams/countries/VN.webp") },
  { code: "MA", country: "Morocco", aliases: ["MAR", "Kingdom of Morocco", "Maroc"], source: require("../../../../assets/world-window/dreams/countries/MA.webp") },
  { code: "SG", country: "Singapore", aliases: ["SGP", "Republic of Singapore"], source: require("../../../../assets/world-window/dreams/countries/SG.webp") },
];

export function normalizeArtworkCountry(value?: string | null) {
  return (value ?? "")
    .normalize("NFKD")
    .replace(/\p{M}/gu, "")
    .replace(/\./g, "")
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .trim()
    .toLowerCase();
}

const byCountry = new Map<string, CountryArtwork>();
for (const artwork of countryArtworkCatalog) {
  for (const name of [artwork.code, artwork.country, ...artwork.aliases]) {
    byCountry.set(normalizeArtworkCountry(name), artwork);
  }
}

/** Exact country/ISO-code matching; never infer a country from a city substring. */
export function findCountryArtwork(countryOrCode?: string | null) {
  return byCountry.get(normalizeArtworkCountry(countryOrCode));
}
