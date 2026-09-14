import { Asset } from 'expo-asset';
import * as FileSystem from 'expo-file-system/legacy';
import { Platform, type ImageSourcePropType } from 'react-native';
import { stampShapeAssets } from '../../../assets/generated/stampAssetManifest';
import type { StampShapeKey, StampTemplate } from '../../trotter/stamps/PngStamp';
import { nativeStampTemplate } from './passport-native-template';
import { passportArtwork } from './passport-artwork';
import { passportIdentityAirport, type PassportArchive } from './passport-model';

export type BookStamp = { code: string; country: string; airport: string; date: string; color: string; frame: string; icon?: string; template: StampTemplate };
export type BookPayload = { name: string; airportLabel: string; homeAirport: string; homeAirportName: string; homeAirportCountry?: string; firstFlightDate: string; flights: number; miles: number; countries: number; years: { year: number; flights: number }[]; stamps: BookStamp[]; fonts: Record<string, string>; visible?: boolean; scopeYear?: string; register?: { label: string; value: string; detail?: string }[]; earned?: { key: string; codes: string[] }; state?: { closed: boolean; spread: number } };
const shapes: Record<StampShapeKey, keyof typeof stampShapeAssets> = { archedCountryCanonical: 'arched_country_canonical', archedCountryBanner: 'arched_country_banner', archedCountryVariant: 'arched_country_variant', circularCityClean: 'circular_city_clean', circularCityDoubleLine: 'circular_city_double_line', roundedImmigrationCanonical: 'rounded_immigration_canonical', roundedImmigrationWithBand: 'rounded_immigration_with_band', shieldBadgeRounded: 'shield_badge_rounded' };
const fontAssets = {
  Newsreader: require('../../../../assets/world-window/fonts/Newsreader-Regular.ttf'),
  DMSans: require('../../../../assets/world-window/fonts/DMSans-Regular.ttf'),
  DMSansBold: require('../../../../assets/world-window/fonts/DMSans-Bold.ttf'),
  PlexMono: require('../../../../assets/world-window/fonts/IBMPlexMono-Medium.ttf'),
};
const assets = new Map<string | number, Promise<string>>();
async function inlineAsset(source: ImageSourcePropType | number, mime: string) {
  const asset = Asset.fromModule(source as number); const key = asset.hash ?? asset.uri;
  if (!assets.has(key)) {
    const task = (async () => {
      await asset.downloadAsync(); let uri = asset.localUri ?? asset.uri;
      // Release APK images can resolve to bare Android drawable names. Expo
      // marks those downloaded for <Image>, but filesystem base64 needs a file.
      // A URI asset asks ExpoAsset to copy that packaged resource into its cache.
      if (Platform.OS === 'android' && !uri.includes(':')) {
        const readable = await Asset.fromURI(uri).downloadAsync(); uri = readable.localUri ?? readable.uri;
      }
      if (Platform.OS !== 'web') return `data:${mime};base64,${await FileSystem.readAsStringAsync(uri, { encoding: FileSystem.EncodingType.Base64 })}`;
      const response = await fetch(uri); if (!response.ok) throw new Error('Passport asset unavailable');
      const bytes = new Uint8Array(await response.arrayBuffer()); let binary = '';
      for (let start = 0; start < bytes.length; start += 8192) binary += String.fromCharCode(...bytes.subarray(start, start + 8192));
      return `data:${mime};base64,${btoa(binary)}`;
    })(); assets.set(key, task); task.catch(() => assets.delete(key));
  }
  return assets.get(key)!;
}
export async function preparePassportPayload(archive: PassportArchive): Promise<BookPayload> {
  const fonts = Object.fromEntries(await Promise.all(Object.entries(fontAssets).map(async ([name, source]) => [name, await inlineAsset(source, 'font/ttf')])));
  const stamps = await Promise.all(archive.arrivals.map(async arrival => {
    const s = arrival.stamp, country = arrival.country.toUpperCase();
    const icon = passportArtwork[String(s.icon)];
    return { code: arrival.travelCountryKey ?? arrival.country, country, airport: arrival.airportCode ?? '', date: arrival.firstVisitDate, color: s.color,
      frame: await inlineAsset(stampShapeAssets[shapes[s.shape]], 'image/png'),
      icon: icon ? await inlineAsset(icon, 'image/png') : undefined, template: nativeStampTemplate(s.shape, country) };
  }));
  const identityAirport = passportIdentityAirport(archive);
  return { name: archive.name, airportLabel: identityAirport?.label ?? 'Home airport', homeAirport: identityAirport?.code ?? '', homeAirportName: identityAirport?.place ?? '', homeAirportCountry: archive.airports.find(a => a.code === identityAirport?.code)?.country ?? '', firstFlightDate: archive.firstFlightDate,
    flights: archive.flights, miles: archive.miles, countries: archive.arrivals.length, years: archive.years, stamps, fonts, scopeYear: archive.scopeYear,
    register: [
      { label: 'First recorded flight', value: archive.recordStartDate ?? archive.firstFlightDate },
      ...archive.records.filter(record => ['Most used airport', 'Most common route', 'Furthest flight'].includes(record.label)).map(({ label, value, detail }) => ({ label, value, detail })),
      { label: 'Airports / airlines', value: `${archive.airports.length} / ${archive.airlines.length}` },
    ].filter(entry => entry.value) };
}
