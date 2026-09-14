import React from "react";
import {
  Linking,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { WebView } from "react-native-webview";
import { colors, fonts } from "../../../theme/trotterTheme";
import { leafletCSS, leafletJS, clusterJS } from "./leafletAssets";
import { MapLine, MapPoint } from "./tripPresentation";
import { placeSymbol, symbolPaths } from "../dreams/placeSymbols";
import type { CountryRegion } from "../dreams/countryRegion";

type Props = {
  points: MapPoint[];
  lines?: MapLine[];
  fitKey: string;
  selectedId?: string;
  placing?: boolean;
  onSelect?: (id: string | undefined) => void;
  onPlace?: (lat: number, lon: number) => void;
  height?: number;
  overview?: CountryRegion;
};
const scriptJSON = (value: unknown) =>
  JSON.stringify(value)
    .replace(/</g, "\\u003c")
    .replace(/\u2028/g, "\\u2028")
    .replace(/\u2029/g, "\\u2029");
const mapHTML = `<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1"><style>${leafletCSS}
html,body,#map{height:100%;width:100%;margin:0;background:#e5e9df}#map{font-family:Arial,sans-serif}.leaflet-tile-pane{filter:saturate(.45) contrast(.94)}.leaflet-control-attribution{font-size:9px!important;background:#fffdf4!important}.leaflet-control-attribution a{color:#194a73}.leaflet-bar{box-shadow:none;border:1px solid #b6c4bf!important}.leaflet-bar a{background:#fffdf4;color:#194a73;width:36px;height:36px;line-height:36px}.travel-pin,.travel-cluster{border:0;background:none}.travel-pin span,.travel-cluster span{display:flex;align-items:center;justify-content:center;width:30px;height:30px;border:2px solid #fffdf4;border-radius:50%;color:#fffdf4;background:#194a73;box-shadow:0 1px 4px #18334266}.travel-pin.selected span{background:#995e3d;box-shadow:0 0 0 2px #fffdf4}.travel-pin.area span{border-style:dashed}.travel-cluster span{font-size:13px;font-weight:600}.travel-label{background:#fffdf4;color:#194a73;border:1px solid #b6c4bf;box-shadow:none}#fit{position:absolute;right:10px;top:10px;z-index:900;background:#fffdf4;color:#194a73;border:1px solid #b6c4bf;border-radius:2px;padding:11px;font:12px Arial}#map-error{position:absolute;bottom:21px;left:0;right:0;z-index:900;padding:4px 8px;background:#fffdf4;font:11px Arial;color:#675a4a;text-align:center;display:none}
</style></head><body><div id="map" aria-label="Map"></div><button id="fit">Fit places</button><div id="map-error">Map detail is unavailable. Saved locations are still shown.</div><script>${leafletJS}</script><script>${clusterJS}</script><script>
var map=L.map('map',{attributionControl:true,scrollWheelZoom:false,maxZoom:19,minZoom:2}).setView([20,0],2);map.attributionControl.setPrefix(false);
var tiles=L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:'&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors'}).addTo(map);
tiles.on('tileerror',function(){document.getElementById('map-error').style.display='block'});tiles.on('tileload',function(){document.getElementById('map-error').style.display='none'});
var paths=L.layerGroup().addTo(map),pins=L.markerClusterGroup({showCoverageOnHover:false,maxClusterRadius:35,animate:false,spiderfyOnMaxZoom:true,iconCreateFunction:function(group){var el=document.createElement('span');el.textContent=String(group.getChildCount());return L.divIcon({html:el,className:'travel-cluster',iconSize:[34,34]})}}).addTo(map),data={points:[]},lastKey=null;
function send(value){if(window.ReactNativeWebView)window.ReactNativeWebView.postMessage(JSON.stringify(value));else window.parent.postMessage({trotterMap:value},'*')}
function fit(){if(data.points.length)map.fitBounds(L.latLngBounds(data.points.map(function(p){return[p.lat,p.displayLon]})),{padding:[28,28],maxZoom:15,animate:false});else if(data.overview)map.fitBounds(data.overview.bounds,{padding:[18,18],maxZoom:8,animate:false})}
function anchor(points){var x=points.map(function(p){return(p.lon+360)%360}).sort(function(a,b){return a-b});if(!x.length)return 0;var largest=-1,start=x[0];x.forEach(function(v,i){var next=i===x.length-1?x[0]+360:x[i+1];if(next-v>largest){largest=next-v;start=next%360}});return start}
window.drawTravelMap=function(next){data=next;var origin=anchor(data.points);data.points.forEach(function(p){p.displayLon=(p.lon+360)%360;if(p.displayLon<origin)p.displayLon+=360});pins.clearLayers();paths.clearLayers();var byId={};data.points.forEach(function(p){byId[p.id]=p});(data.lines||[]).forEach(function(line){var a=byId[line.from],b=byId[line.to];if(a&&b)L.polyline([[a.lat,a.displayLon],[b.lat,b.displayLon]],{color:'#a1663d',weight:2,opacity:.85}).addTo(paths)});
data.points.forEach(function(p){var wrap=document.createElement('span');if(p.symbol){var svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('width','19');svg.setAttribute('height','19');svg.setAttribute('fill','none');svg.setAttribute('stroke','currentColor');svg.setAttribute('stroke-width','1.5');svg.setAttribute('stroke-linecap','round');svg.setAttribute('stroke-linejoin','round');p.symbol.forEach(function(d){var path=document.createElementNS('http://www.w3.org/2000/svg','path');path.setAttribute('d',d);svg.appendChild(path)});wrap.appendChild(svg)}else{wrap.textContent=p.id;wrap.style.fontSize='9px'}var marker=L.marker([p.lat,p.displayLon],{title:p.label,bubblingMouseEvents:false,icon:L.divIcon({html:wrap,className:'travel-pin'+(p.id===data.selectedId?' selected':'')+(p.area?' area':''),iconSize:[34,34],iconAnchor:[17,17]})});var label=document.createElement('span');label.textContent=p.label;marker.bindTooltip(label,{className:'travel-label'});marker.on('click',function(){send(data.placing?{type:'place',lat:p.lat,lon:p.lon}:{type:'select',id:p.id})});pins.addLayer(marker)});map.invalidateSize(false);var fitButton=document.getElementById('fit');fitButton.disabled=!data.points.length&&!data.overview;fitButton.textContent=data.points.length?'Fit places':data.overview?'Country view':'Fit places';document.getElementById('map').setAttribute('aria-label',data.overview?data.overview.label+' saved places map':'Travel map');var fitSignature=JSON.stringify([data.fitKey,data.points.map(function(p){return[p.id,p.lat,p.lon]}),data.overview]);if(lastKey!==fitSignature){lastKey=fitSignature;fit()}};
map.on('click',function(e){send(data.placing?{type:'place',lat:e.latlng.lat,lon:((e.latlng.lng+180)%360+360)%360-180}:{type:'select'})});document.getElementById('fit').onclick=fit;window.addEventListener('message',function(e){if(e.data&&e.data.trotterMapData)window.drawTravelMap(e.data.trotterMapData)});
</script></body></html>`;

export function PaperMap({
  points,
  lines,
  fitKey,
  selectedId,
  placing,
  onSelect,
  onPlace,
  height = 240,
  overview,
}: Props) {
  const webview = React.useRef<WebView>(null),
    frame = React.useRef<HTMLIFrameElement>(null);
  const [ready, setReady] = React.useState(false),
    [failed, setFailed] = React.useState(false),
    [attempt, setAttempt] = React.useState(0);
  const payload = React.useMemo(
    () => ({
      points: points.map((point) => ({
        ...point,
        symbol: point.category
          ? symbolPaths[placeSymbol(point.category)]
          : undefined,
      })),
      lines,
      fitKey,
      selectedId,
      placing,
      overview,
    }),
    [points, lines, fitKey, selectedId, placing, overview],
  );
  const receive = React.useCallback(
    (value: unknown) => {
      if (!value || typeof value !== "object") return;
      const message = value as {
        type?: string;
        id?: string;
        lat?: number;
        lon?: number;
      };
      if (
        message.type === "select" &&
        (!message.id || points.some((point) => point.id === message.id))
      )
        onSelect?.(message.id);
      if (
        placing &&
        message.type === "place" &&
        typeof message.lat === "number" &&
        typeof message.lon === "number" &&
        Number.isFinite(message.lat) &&
        Number.isFinite(message.lon) &&
        Math.abs(message.lat) <= 85.05112878 &&
        Math.abs(message.lon) <= 180
      )
        onPlace?.(message.lat, message.lon);
    },
    [points, placing, onPlace, onSelect],
  );
  React.useEffect(() => {
    if (!ready) return;
    if (Platform.OS === "web")
      frame.current?.contentWindow?.postMessage(
        { trotterMapData: payload },
        "*",
      );
    else
      webview.current?.injectJavaScript(
        `window.drawTravelMap(${scriptJSON(payload)});true;`,
      );
  }, [payload, ready]);
  React.useEffect(() => {
    if (Platform.OS !== "web") return;
    const handler = (event: MessageEvent) => {
      if (event.source === frame.current?.contentWindow)
        receive(event.data?.trotterMap);
    };
    window.addEventListener("message", handler);
    return () => window.removeEventListener("message", handler);
  }, [receive]);
  return (
    <View style={[styles.paper, { height }]}>
      {failed ? (
        <View style={styles.error}>
          <Text style={styles.errorText}>
            The map couldn’t load. Your itinerary and saved places are still
            available.
          </Text>
          <Pressable
            onPress={() => {
              setFailed(false);
              setReady(false);
              setAttempt((value) => value + 1);
            }}
          >
            <Text style={styles.retry}>Retry map</Text>
          </Pressable>
        </View>
      ) : Platform.OS === "web" ? (
        React.createElement("iframe", {
          key: attempt,
          ref: frame,
          srcDoc: mapHTML,
          title: overview ? `${overview.label} saved places map` : "Travel map",
          onLoad: () => setReady(true),
          sandbox:
            "allow-scripts allow-same-origin allow-popups allow-popups-to-escape-sandbox",
          style: { height: "100%", width: "100%", border: 0 },
        })
      ) : (
        <WebView
          key={attempt}
          ref={webview}
          source={{ html: mapHTML, baseUrl: "https://trotter.local/" }}
          originWhitelist={["https://*", "about:*"]}
          applicationNameForUserAgent="Trotter/0.1"
          allowFileAccess={false}
          javaScriptEnabled
          domStorageEnabled={false}
          scrollEnabled={false}
          onLoadEnd={() => setReady(true)}
          onError={() => setFailed(true)}
          onMessage={(event) => {
            try {
              receive(JSON.parse(event.nativeEvent.data));
            } catch {
              /* Ignore malformed web messages. */
            }
          }}
          onShouldStartLoadWithRequest={(request) => {
            if (
              request.url === "about:blank" ||
              request.url.startsWith("https://trotter.local/")
            )
              return true;
            if (request.url === "https://www.openstreetmap.org/copyright")
              void Linking.openURL(request.url).catch(() => {});
            return false;
          }}
          style={styles.map}
        />
      )}
      <View pointerEvents="none" style={styles.fold} />
    </View>
  );
}
const styles = StyleSheet.create({
  paper: {
    borderWidth: 1,
    borderColor: colors.paperBorder,
    overflow: "hidden",
    backgroundColor: "#e5e9df",
  },
  map: { flex: 1, backgroundColor: "#e5e9df" },
  fold: {
    position: "absolute",
    top: 0,
    bottom: 0,
    left: "51%",
    width: 1,
    backgroundColor: "#d0d5c94d",
  },
  error: { flex: 1, padding: 22, justifyContent: "center" },
  errorText: {
    fontFamily: fonts.sansRegular,
    color: colors.mutedInk,
    textAlign: "center",
  },
  retry: {
    fontFamily: fonts.sansSemi,
    color: colors.blue,
    textAlign: "center",
    padding: 14,
  },
});
