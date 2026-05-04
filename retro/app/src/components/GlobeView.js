import React, { useEffect, useRef, useState, useMemo, useCallback } from 'react';
import { View, PanResponder } from 'react-native';
import Svg, {
  Path, Circle, Text as SvgText,
  Defs, ClipPath,
} from 'react-native-svg';
import { geoOrthographic, geoPath, geoGraticule, geoDistance } from 'd3-geo';
import { feature, mesh } from 'topojson-client';
import { FLIGHTS, CITY_GEO } from '../data/flights';

const TOPO_URL = 'https://cdn.jsdelivr.net/npm/world-atlas@2/countries-110m.json';
const CITY_ENTRIES = Object.entries(CITY_GEO);

export default function GlobeView({ activePath, displayMode, showGrid = true, showPaths = true, W = 362, H = 210 }) {
  const [worldTopo, setWorldTopo] = useState(null);
  const rotRef   = useRef([20, -20]);
  const [rot, setRot] = useState([20, -20]);
  const spinRef  = useRef(true);
  const dragRef  = useRef(null);
  // RAF gate: only one setState per animation frame during drag
  const rafPendingRef = useRef(false);

  const phos     = displayMode === 'amber' ? '#ff9500' : '#6ab04c';
  const phosDim  = displayMode === 'amber' ? '#2a1000' : '#0f2808';
  const landClr  = displayMode === 'amber' ? 'rgba(50,18,0,0.85)' : 'rgba(10,32,5,0.85)';
  const oceanClr = displayMode === 'amber' ? '#0e0500' : '#040c02';

  const R  = Math.min(W, H) / 2 - 6;
  const cx = W / 2, cy = H / 2;

  useEffect(() => {
    fetch(TOPO_URL).then(r => r.json()).then(setWorldTopo).catch(() => {});
  }, []);

  // Auto-spin: 100ms interval (~10fps). Slow enough to not clog the JS thread.
  useEffect(() => {
    const id = setInterval(() => {
      if (!spinRef.current || dragRef.current) return;
      rotRef.current = [rotRef.current[0] + 0.6, rotRef.current[1]];
      setRot([...rotRef.current]);
    }, 100);
    return () => clearInterval(id);
  }, []);

  // Pre-extract GeoJSON objects from topo once
  const geoData = useMemo(() => {
    if (!worldTopo) return null;
    return {
      land:      feature(worldTopo, worldTopo.objects.land),
      borders:   mesh(worldTopo, worldTopo.objects.countries, (a, b) => a !== b),
      graticule: geoGraticule().step([30, 30])(),
    };
  }, [worldTopo]);

  // Build projection + paths for current rotation
  const proj = geoOrthographic()
    .scale(R).translate([cx, cy])
    .rotate([rot[0], rot[1], 0]).clipAngle(90);
  const pg = geoPath().projection(proj);

  const sphereD    = pg({ type: 'Sphere' });
  const graticuleD = geoData ? pg(geoData.graticule) : null;
  const landD      = geoData ? pg(geoData.land)      : null;
  const bordersD   = geoData ? pg(geoData.borders)   : null;

  // Flight arcs — only visible ones
  const center = [-rot[0], -rot[1]];
  const arcElements = FLIGHTS.map((f, i) => {
    const isComplete = i < activePath, isActive = i === activePath;
    if (!isComplete && !isActive) return null;
    const fromC = CITY_GEO[f.from], toC = CITY_GEO[f.to];
    if (!fromC || !toC) return null;
    const d = pg({ type: 'Feature', geometry: { type: 'LineString', coordinates: [fromC, toC] } });
    if (!d) return null;
    return (
      <Path key={i} d={d} fill="none" stroke={phos}
        strokeWidth={isActive ? 1.8 : 1.0} opacity={isActive ? 0.95 : 0.5}
        clipPath="url(#gc)" />
    );
  });

  // City dots — only on visible hemisphere
  const cityElements = CITY_ENTRIES.map(([code, coords]) => {
    if (geoDistance(coords, center) >= Math.PI / 2 - 0.05) return null;
    const pt = proj(coords);
    if (!pt) return null;
    return (
      <React.Fragment key={code}>
        <Circle cx={pt[0]} cy={pt[1]} r={2.2} fill={phos} opacity={0.9} />
        <SvgText x={pt[0] + 4} y={pt[1] - 3} fontSize={5.5} fill={phos}
          opacity={0.8} fontFamily="SpaceMono,monospace">{code}</SvgText>
      </React.Fragment>
    );
  });

  // PanResponder — RAF-gated to prevent flooding setState
  const panResponder = PanResponder.create({
    onStartShouldSetPanResponder: () => true,
    onMoveShouldSetPanResponder: () => true,
    onPanResponderGrant: (e) => {
      spinRef.current = false;
      const t = e.nativeEvent.touches?.[0] ?? e.nativeEvent;
      dragRef.current = { x: t.pageX, y: t.pageY, rot: [...rotRef.current] };
    },
    onPanResponderMove: (e) => {
      if (!dragRef.current) return;
      const t = e.nativeEvent.touches?.[0] ?? e.nativeEvent;
      const dx = t.pageX - dragRef.current.x;
      const dy = t.pageY - dragRef.current.y;
      // Update the ref immediately (no render cost)
      rotRef.current = [
        dragRef.current.rot[0] + dx * 0.55,
        Math.max(-85, Math.min(85, dragRef.current.rot[1] - dy * 0.55)),
      ];
      // Commit to state at most once per animation frame
      if (!rafPendingRef.current) {
        rafPendingRef.current = true;
        requestAnimationFrame(() => {
          setRot([...rotRef.current]);
          rafPendingRef.current = false;
        });
      }
    },
    onPanResponderRelease: () => {
      dragRef.current = null;
      spinRef.current = true;
    },
  });

  return (
    <View
      style={{ width: W, height: H }}
      // Hardware texture acceleration — big win on Android
      renderToHardwareTextureAndroid
      shouldRasterizeIOS
      {...panResponder.panHandlers}
    >
      <Svg width={W} height={H} viewBox={`0 0 ${W} ${H}`}>
        <Defs>
          <ClipPath id="gc">
            <Circle cx={cx} cy={cy} r={R} />
          </ClipPath>
        </Defs>

        {sphereD    && <Path d={sphereD} fill={oceanClr} />}
        {showGrid && graticuleD && (
          <Path d={graticuleD} fill="none" stroke={phosDim} strokeWidth={0.3} opacity={0.45} clipPath="url(#gc)" />
        )}
        {landD      && <Path d={landD} fill={landClr} clipPath="url(#gc)" />}
        {bordersD   && <Path d={bordersD} fill="none" stroke={phos} strokeWidth={0.45} opacity={0.8} clipPath="url(#gc)" />}

        {/* Flight arcs — respects showPaths */}
        {showPaths && arcElements}
        {cityElements}

        {sphereD && <Path d={sphereD} fill="none" stroke={phos} strokeWidth={0.6} opacity={0.45} />}
      </Svg>
    </View>
  );
}
