import React, { useEffect, useState, useMemo } from 'react';
import { View, PanResponder } from 'react-native';
import Svg, {
  Path, Circle, Text as SvgText,
  Defs, Filter, FeGaussianBlur, FeMerge, FeMergeNode, ClipPath, Rect,
} from 'react-native-svg';
import { geoNaturalEarth1, geoPath, geoGraticule } from 'd3-geo';
import { feature, mesh } from 'topojson-client';
import { FLIGHTS, CITY_GEO } from '../data/flights';

const TOPO_URL = 'https://cdn.jsdelivr.net/npm/world-atlas@2/countries-110m.json';

export default function WorldMap({ activePath, displayMode, showGrid = true, showPaths = true, W = 362, H = 210 }) {
  const [worldTopo, setWorldTopo] = useState(null);
  const [zoom, setZoom] = useState({ k: 1, x: 0, y: 0 });

  const phos    = displayMode === 'amber' ? '#ff9500' : '#6ab04c';
  const phosDim = displayMode === 'amber' ? 'rgba(42,16,0,0.6)' : 'rgba(15,40,8,0.6)';
  const landClr = displayMode === 'amber' ? 'rgba(50,18,0,0.75)' : 'rgba(10,32,5,0.75)';
  const oceanClr= displayMode === 'amber' ? '#0e0500' : '#040c02';

  useEffect(() => {
    fetch(TOPO_URL)
      .then(r => r.json())
      .then(setWorldTopo)
      .catch(e => console.warn('WorldMap: failed to load topo', e));
  }, []);

  const proj = geoNaturalEarth1()
    .scale(56 * zoom.k)
    .translate([W / 2 + zoom.x, H / 2 + 6 + zoom.y]);
  const pathGen = geoPath().projection(proj);

  const land      = worldTopo ? feature(worldTopo, worldTopo.objects.land) : null;
  const borders   = worldTopo ? mesh(worldTopo, worldTopo.objects.countries, (a, b) => a !== b) : null;
  const graticule = geoGraticule().step([30, 20])();

  const landPath    = land    ? pathGen(land)    : null;
  const bordersPath = borders ? pathGen(borders) : null;
  const graticPath  = pathGen(graticule);

  // Flight arcs
  const arcPaths = FLIGHTS.map((f, i) => {
    const fromCoord = CITY_GEO[f.from], toCoord = CITY_GEO[f.to];
    if (!fromCoord || !toCoord) return null;
    const isComplete = i < activePath, isActive = i === activePath;
    if (!isComplete && !isActive) return null;
    const arc = { type: 'Feature', geometry: { type: 'LineString', coordinates: [fromCoord, toCoord] } };
    const d = pathGen(arc);
    return d ? { d, isActive } : null;
  }).filter(Boolean);

  // City dots
  const cityDots = Object.entries(CITY_GEO).map(([code, coords]) => {
    const pt = proj(coords);
    return pt ? { code, x: pt[0], y: pt[1] } : null;
  }).filter(Boolean);

  // Pan to drag the map
  const dragRef = React.useRef(null);
  const panResponder = PanResponder.create({
    onStartShouldSetPanResponder: () => zoom.k > 1,
    onMoveShouldSetPanResponder: () => zoom.k > 1,
    onPanResponderGrant: (e) => {
      const t = e.nativeEvent.touches?.[0] ?? e.nativeEvent;
      dragRef.current = { x: t.pageX, y: t.pageY, ox: zoom.x, oy: zoom.y };
    },
    onPanResponderMove: (e) => {
      if (!dragRef.current) return;
      const t = e.nativeEvent.touches?.[0] ?? e.nativeEvent;
      const dx = t.pageX - dragRef.current.x;
      const dy = t.pageY - dragRef.current.y;
      setZoom(z => ({ ...z, x: dragRef.current.ox + dx, y: dragRef.current.oy + dy }));
    },
    onPanResponderRelease: () => { dragRef.current = null; },
  });

  return (
    <View style={{ width: W, height: H }} {...panResponder.panHandlers}>
      <Svg width={W} height={H} viewBox={`0 0 ${W} ${H}`}>
        <Defs>
          <ClipPath id="map-clip">
            <Rect x={0} y={0} width={W} height={H} />
          </ClipPath>
        </Defs>

        {/* Background ocean */}
        <Rect width={W} height={H} fill={oceanClr} />

        {showGrid && graticPath && (
          <Path d={graticPath} fill="none" stroke={phosDim} strokeWidth={0.4}
            opacity={0.6} clipPath="url(#map-clip)" />
        )}

        {/* Land fill */}
        {landPath && (
          <Path d={landPath} fill={landClr} clipPath="url(#map-clip)" />
        )}

        {/* Country borders — thin */}
        {bordersPath && (
          <Path d={bordersPath} fill="none" stroke={phos} strokeWidth={0.2}
            opacity={0.7} clipPath="url(#map-clip)" />
        )}

        {/* Flight arcs — respects showPaths */}
        {showPaths && arcPaths.map(({ d, isActive }, i) => (
          <Path key={i} d={d} fill="none"
            stroke={phos}
            strokeWidth={isActive ? 1.8 : 1.1}
            opacity={isActive ? 1 : 0.6}
            clipPath="url(#map-clip)"
          />
        ))}

        {/* City dots */}
        {cityDots.map(({ code, x, y }) => (
          <React.Fragment key={code}>
            <Circle cx={x} cy={y} r={2.2} fill={phos} opacity={0.9} />
            <SvgText x={x + 4} y={y - 3} fontSize={5.5} fill={phos} opacity={0.8}
              fontFamily="SpaceMono, monospace">{code}</SvgText>
          </React.Fragment>
        ))}
      </Svg>
    </View>
  );
}
