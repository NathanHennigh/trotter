"use client";

import {useEffect, useRef, useState} from "react";
import type * as Leaflet from "leaflet";
import type {} from "leaflet.markercluster";
import {hasLocation, type DreamPlace} from "./dream-country-model";

type Props = {
  places: DreamPlace[];
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  active: boolean;
  fitKey: string;
  placingName?: string;
  onLocate?: (lat: number, lon: number) => void;
};
type L = typeof Leaflet;
// Public in markercluster 1.5.3's Spiderfier implementation; its DefinitelyTyped
// interface currently omits the group-level convenience method.
type ClusterGroup = Leaflet.MarkerClusterGroup & {unspiderfy: () => void};
type Runtime = {
  L: L;
  map: Leaflet.Map;
  tiles: Leaflet.TileLayer;
  cluster: ClusterGroup;
  markers: Map<string, Leaflet.Marker>;
  places: DreamPlace[];
  fittedKey: string | null;
  selectedId: string | null | undefined;
  disposed: boolean;
};
type View = {center: Leaflet.LatLng; zoom: number; fitKey: string};

// A failed chunk load must be retryable. Leaflet is imported only in the browser.
let libraryRequest: Promise<L> | undefined;
function loadLibrary(): Promise<L> {
  return libraryRequest ??= import("leaflet").then(async module => {
    const library = ("default" in module ? module.default : module) as L;
    await import("leaflet.markercluster");
    if (typeof library.markerClusterGroup !== "function") throw new Error("Marker clustering did not load");
    return library;
  }).catch(error => {libraryRequest = undefined; throw error;});
}

function markerIcon(library: L, number: number, selected: boolean, approximate: boolean) {
  const numberElement = document.createElement("span");
  numberElement.className = "dream-map-marker-number";
  numberElement.textContent = String(number);
  return library.divIcon({
    html: numberElement,
    className: `dream-map-marker${selected ? " is-selected" : ""}${approximate ? " is-area" : ""}`,
    iconSize: [36, 36],
    iconAnchor: [18, 18],
    tooltipAnchor: [0, -18],
  });
}

function fitPlaces(runtime: Runtime, fitKey: string, force = false) {
  if (runtime.disposed || (!force && runtime.fittedKey === fitKey)) return;
  const size = runtime.map.getSize();
  if (size.x < 1 || size.y < 1) return;
  const located = runtime.places.filter(hasLocation);
  if (located.length) {
    const bounds = runtime.L.latLngBounds(located.map(place => [place.location.lat, place.location.lon]));
    runtime.map.fitBounds(bounds, {padding: [35, 35], maxZoom: 14, animate: false});
  } else {
    runtime.map.setView([20, 0], 2, {animate: false});
  }
  runtime.fittedKey = fitKey;
}

export default function DreamsMap(props: Props) {
  const {places, selectedId, active, fitKey, placingName} = props;
  const element = useRef<HTMLDivElement>(null);
  const runtimeRef = useRef<Runtime | null>(null);
  const latest = useRef(props);
  const previousView = useRef<View | null>(null);
  const [started, setStarted] = useState(active);
  const [attempt, setAttempt] = useState(0);
  const [status, setStatus] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [tileIssue, setTileIssue] = useState(false);

  useEffect(() => {latest.current = props;}, [props]);
  useEffect(() => {if (active) setStarted(true);}, [active]);

  // Once first opened, retain the map while the comparison screen is hidden.
  // Each effect owns its runtime so StrictMode cannot remove the next instance.
  useEffect(() => {
    if (!started || !element.current) return;
    let cancelled = false;
    let owned: Runtime | null = null;
    let createdMap: Leaflet.Map | null = null;
    let observer: ResizeObserver | undefined;
    let resizeFrame = 0;
    setStatus("loading");
    setTileIssue(false);

    const initialize = async () => {
      try {
        const library = await loadLibrary();
        if (cancelled || !element.current) return;
        const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
        const map = library.map(element.current, {
          zoomControl: false,
          attributionControl: true,
          scrollWheelZoom: false,
          minZoom: 2,
          maxZoom: 19,
          zoomSnap: 0.5,
          zoomAnimation: !reduced,
          fadeAnimation: !reduced,
          markerZoomAnimation: !reduced,
          inertia: !reduced,
          inertiaMaxSpeed: 650,
          inertiaDeceleration: 4500,
        });
        createdMap = map;
        // Ensure a viewport exists before adding clustering. Bounds are fitted
        // only after markers arrive and the container has a measurable size.
        const remembered = previousView.current;
        const restoreView = remembered?.fitKey === latest.current.fitKey ? remembered : null;
        map.setView(restoreView?.center ?? [20, 0], restoreView?.zoom ?? 2, {animate: false});
        map.attributionControl.setPrefix(false);
        const tiles = library.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
          maxZoom: 19,
          attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap</a> contributors',
          referrerPolicy: "strict-origin-when-cross-origin",
          keepBuffer: 1,
        });
        const cluster = library.markerClusterGroup({
          maxClusterRadius: 44,
          showCoverageOnHover: false,
          zoomToBoundsOnClick: true,
          spiderfyOnMaxZoom: true,
          spiderfyDistanceMultiplier: 1.6,
          spiderLegPolylineOptions: {color: "#194a73", weight: 1.2, opacity: 0.75},
          animate: !reduced,
          animateAddingMarkers: false,
          removeOutsideVisibleBounds: true,
          // Keeping clustering enabled at maxZoom allows exact overlaps to
          // spiderfy instead of permanently hiding one marker behind another.
          iconCreateFunction: group => {
            const count = document.createElement("span");
            count.className = "dream-map-cluster-count";
            count.textContent = String(group.getChildCount());
            const icon = library.divIcon({html: count, className: "dream-map-cluster", iconSize: [42, 42]});
            return icon;
          },
        }) as ClusterGroup;
        owned = {L: library, map, tiles, cluster, markers: new Map(), places: [],
          fittedKey: restoreView ? latest.current.fitKey : null, selectedId: undefined, disposed: false};
        const runtime = owned;
        runtimeRef.current = runtime;

        let pendingTileErrors = 0;
        tiles.on("loading", () => {pendingTileErrors = 0;});
        tiles.on("tileerror", () => {pendingTileErrors += 1;});
        tiles.on("load", () => {if (!cancelled) setTileIssue(pendingTileErrors > 0);});
        tiles.addTo(map);
        cluster.addTo(map);

        map.on("click", event => {
          const current = latest.current;
          if (current.placingName && current.onLocate) {
            current.onLocate(event.latlng.lat, event.latlng.lng);
          } else {
            runtime.selectedId = null;
            cluster.unspiderfy();
            current.onSelect(null);
          }
        });
        cluster.on("clusterclick", event => {
          const mouseEvent = event as Leaflet.LeafletMouseEvent;
          if (mouseEvent.originalEvent) library.DomEvent.stopPropagation(mouseEvent.originalEvent);
        });

        const invalidate = () => {
          cancelAnimationFrame(resizeFrame);
          resizeFrame = requestAnimationFrame(() => {
            if (cancelled || !latest.current.active) return;
            map.invalidateSize({pan: false, debounceMoveend: true});
            if (runtime.places.length || !latest.current.places.length) fitPlaces(runtime, latest.current.fitKey);
          });
        };
        observer = new ResizeObserver(invalidate);
        observer.observe(element.current);
        invalidate();
        setStatus("ready");
      } catch {
        observer?.disconnect();
        cancelAnimationFrame(resizeFrame);
        if (owned) {
          owned.disposed = true;
          owned.map.remove();
          if (runtimeRef.current === owned) runtimeRef.current = null;
        } else createdMap?.remove();
        if (!cancelled) setStatus("error");
      }
    };
    void initialize();
    return () => {
      cancelled = true;
      observer?.disconnect();
      cancelAnimationFrame(resizeFrame);
      if (owned && !owned.disposed) {
        previousView.current = {center: owned.map.getCenter(), zoom: owned.map.getZoom(), fitKey: owned.fittedKey ?? latest.current.fitKey};
        owned.disposed = true;
        owned.map.remove();
      }
      if (runtimeRef.current === owned) runtimeRef.current = null;
    };
  }, [started, attempt]);

  // Data/filter changes update marker membership. Selection is deliberately not
  // a dependency: clicking one marker must not rebuild all clusters.
  useEffect(() => {
    const runtime = runtimeRef.current;
    if (status !== "ready" || !runtime || runtime.disposed) return;
    runtime.places = places;
    runtime.cluster.clearLayers();
    runtime.markers.clear();
    const markers: Leaflet.Marker[] = [];
    places.forEach((place, index) => {
      if (!hasLocation(place)) return;
      const marker = runtime.L.marker([place.location.lat, place.location.lon], {
        icon: markerIcon(runtime.L, index + 1, latest.current.selectedId === place.id, place.location.precision === "area"),
        keyboard: true,
        title: `${index + 1}. ${place.title}, ${place.city}${place.location.precision === "area" ? ". Approximate area" : ""}`,
        alt: place.title,
        bubblingMouseEvents: false,
        riseOnHover: true,
      });
      const tooltip = document.createElement("span");
      tooltip.textContent = place.title;
      marker.bindTooltip(tooltip, {direction: "top", className: "dream-map-tooltip"});
      marker.on("click", () => {
        const current = latest.current;
        if (current.placingName && current.onLocate) {
          const point = marker.getLatLng();
          current.onLocate(point.lat, point.lng);
          return;
        }
        // The marker is already visible. Remember this so the controlled
        // selection effect does not zoom/spiderfy it again.
        runtime.selectedId = place.id;
        current.onSelect(place.id);
      });
      runtime.markers.set(place.id, marker);
      markers.push(marker);
    });
    runtime.cluster.addLayers(markers);
    if (latest.current.active) fitPlaces(runtime, fitKey);
  }, [places, fitKey, status]);

  useEffect(() => {
    const runtime = runtimeRef.current;
    if (status !== "ready" || !runtime || runtime.disposed) return;
    places.forEach((place, index) => {
      const marker = runtime.markers.get(place.id);
      if (!marker || !hasLocation(place)) return;
      marker.setIcon(markerIcon(runtime.L, index + 1, selectedId === place.id, place.location.precision === "area"));
      marker.setZIndexOffset(selectedId === place.id ? 1000 : 0);
      if (selectedId !== place.id) marker.closeTooltip();
    });
    if (!active || runtime.selectedId === selectedId) return;
    runtime.selectedId = selectedId;
    if (!selectedId) {runtime.cluster.unspiderfy(); return;}
    const selectedMarker = runtime.markers.get(selectedId);
    if (!selectedMarker) return;
    runtime.cluster.zoomToShowLayer(selectedMarker, () => {
      if (runtime.disposed || latest.current.selectedId !== selectedId) return;
      runtime.map.panInside(selectedMarker.getLatLng(), {padding: [30, 30], animate: false});
      selectedMarker.openTooltip();
    });
  }, [selectedId, places, active, status]);

  useEffect(() => {
    const runtime = runtimeRef.current;
    if (!active || status !== "ready" || !runtime) return;
    const frame = requestAnimationFrame(() => {
      if (runtime.disposed) return;
      runtime.map.invalidateSize({pan: false});
      fitPlaces(runtime, fitKey);
    });
    return () => cancelAnimationFrame(frame);
  }, [active, fitKey, status]);

  const retry = () => {
    const runtime = runtimeRef.current;
    if (runtime && !runtime.disposed && status === "ready") {
      setTileIssue(false);
      runtime.tiles.redraw();
    } else setAttempt(value => value + 1);
  };
  const locatedCount = places.filter(hasLocation).length;
  const ready = status === "ready";
  return <section className={`dreams-map${placingName ? " is-placing" : ""}`} aria-label="Saved places map">
    <div className="dreams-map-stage">
      <div ref={element} className="dreams-map-canvas" aria-label="Interactive map of saved places" />
      <div className="dreams-map-controls" role="group" aria-label="Map controls">
        <button type="button" disabled={!ready} aria-label="Zoom in" onClick={() => runtimeRef.current?.map.zoomIn()}>+</button>
        <button type="button" disabled={!ready} aria-label="Zoom out" onClick={() => runtimeRef.current?.map.zoomOut()}>−</button>
        <button type="button" disabled={!ready || !locatedCount} onClick={() => {
          const runtime = runtimeRef.current;
          if (runtime) fitPlaces(runtime, fitKey, true);
        }}>Fit places</button>
      </div>
      {status === "loading" && <p className="dreams-map-status" role="status">Loading map…</p>}
      {status === "error" && <div className="dreams-map-error" role="status"><p>The map couldn’t load. Your saved places are still below.</p><button type="button" onClick={retry}>Retry map</button></div>}
    </div>
    {placingName && <p className="dreams-map-instruction" role="status">Tap the map to locate {placingName}.</p>}
    {tileIssue && <p className="dreams-map-tile-error" role="status">Some map detail couldn’t load. <button type="button" onClick={retry}>Retry</button></p>}
    <p className="dreams-map-caption">{locatedCount} of {places.length} {places.length === 1 ? "place" : "places"} located{places.some(place => hasLocation(place) && place.location.precision === "area") ? " · Outlined pins mark approximate areas" : ""}</p>
  </section>;
}
