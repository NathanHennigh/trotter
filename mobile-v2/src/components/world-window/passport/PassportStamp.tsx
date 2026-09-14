import React from "react";
import { Image, View } from "react-native";
import { PngStamp } from "../../trotter/stamps/PngStamp";
import type { CountryArrival } from "../../../utils/countryArrivals";
import { extraPassportArtwork } from "./passport-artwork";
import { nativeStampTemplate } from "./passport-native-template";
import { stampFootprint } from "./passport-footprint";

/** Fit the visible, calibrated stamp impression rather than its old canvas. */
export function CroppedPassportStamp({ arrival, width, height }: { arrival: CountryArrival; width: number; height: number }) {
  const crop = stampFootprint(nativeStampTemplate(arrival.stamp.shape, arrival.country.toUpperCase()));
  const scale = Math.min(width / crop.width, height / crop.height);
  return <View style={{ width, height, alignItems: "center", justifyContent: "center" }}>
    <View style={{ width: crop.width * scale, height: crop.height * scale, overflow: "hidden" }}>
      <View style={{ position: "absolute", left: -crop.x * scale, top: -crop.y * scale }}>
        <PassportStamp arrival={arrival} scale={scale} />
      </View>
    </View>
  </View>;
}
export function PassportStamp({
  arrival,
  scale = 1,
  rotate = 0,
}: {
  arrival: CountryArrival;
  scale?: number;
  rotate?: number;
}) {
  const extra = extraPassportArtwork[arrival.stamp.icon],
    width = 204.75 * scale,
    height = 165.75 * scale;
  const stamp = (
    <PngStamp
      {...arrival.stamp}
      country={arrival.country}
      city={undefined}
      airportCode={arrival.airportCode}
      date={arrival.firstVisitDate}
      size="md"
      scale={scale}
      rotate={extra ? 0 : rotate}
    />
  );
  if (!extra) return stamp;
  const box = nativeStampTemplate(
    arrival.stamp.shape,
    arrival.country.toUpperCase(),
  ).icon;
  return (
    <View style={{ width, height, transform: [{ rotate: `${rotate}deg` }] }}>
      {stamp}
      <Image
        source={extra}
        resizeMode="contain"
        tintColor={arrival.stamp.color}
        style={{
          position: "absolute",
          left: width * box.left,
          top: height * box.top,
          width: width * box.width,
          height: height * box.height,
          opacity: 0.78,
        }}
      />
    </View>
  );
}
