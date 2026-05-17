import React, { useCallback, useEffect, useMemo, useRef } from 'react';
import { PanResponder, StyleSheet, View } from 'react-native';
import { GLView } from 'expo-gl';
import Renderer from 'expo-three/build/Renderer';
import TextureLoader from 'expo-three/build/TextureLoader';
import * as THREE from 'three';
import { FontLoader } from 'three/examples/jsm/loaders/FontLoader.js';
import { TextGeometry } from 'three/examples/jsm/geometries/TextGeometry.js';
import { colors } from '../theme/tokens';
import { flightMapPoints, flightRoutes, FlightRoute, RoutePoint } from '../data/demoTravel';
import countryBorderRings from '../data/countryBorders110m.json';
import { globeDayDetailTiles } from '../data/globeDayDetailTiles';

const RADIUS = 2.08;
const DEG = Math.PI / 180;
const IDLE_ROTATION_SPEED = 0.00032;
const DEFAULT_CAMERA_Z = 10.85;
const MIN_CAMERA_Z = 3.9;
const MAX_CAMERA_Z = 12.4;
const EARTH_DAY_TEXTURE_STANDARD = require('../../assets/globe/blue-marble-day-2048.jpg');
const EARTH_DAY_TEXTURE_HIGH = require('../../assets/globe/blue-marble-day-4096.jpg');
const EARTH_NIGHT_TEXTURE = require('../../assets/globe/black-marble-2016-3600.jpg');
const HELVETIKER_FONT = require('three/examples/fonts/helvetiker_regular.typeface.json');
const GLOBE_SEGMENTS = 96;
const DETAIL_TILE_ROWS = globeDayDetailTiles.length;
const DETAIL_TILE_COLS = globeDayDetailTiles[0].length;
const DETAIL_TILE_SHOW_Z = 7.5;
const DEFAULT_MAX_TILT = 0.42;
const CLOSE_MAX_TILT = 1.08;

const globeLabels = [
  { label: 'NORTH\nAMERICA', lat: 43, lon: -101, kind: 'land' },
  { label: 'SOUTH\nAMERICA', lat: -24, lon: -59, kind: 'land' },
  { label: 'EUROPE', lat: 51, lon: 13, kind: 'land' },
  { label: 'AFRICA', lat: 7, lon: 20, kind: 'land' },
  { label: 'North Atlantic\nOcean', lat: 27, lon: -38, kind: 'ocean' },
  { label: 'South Atlantic\nOcean', lat: -27, lon: -19, kind: 'ocean' },
] as const;

function latLonToVector(lat: number, lon: number, radius = RADIUS) {
  const phi = (90 - lat) * DEG;
  const theta = (lon + 180) * DEG;
  return new THREE.Vector3(
    -radius * Math.sin(phi) * Math.cos(theta),
    radius * Math.cos(phi),
    radius * Math.sin(phi) * Math.sin(theta),
  );
}

function normalizeDegrees(value: number) {
  return ((value % 360) + 360) % 360;
}

function normalizeLongitude(value: number) {
  const degrees = normalizeDegrees(value + 180) - 180;
  return degrees === -180 ? 180 : degrees;
}

function getSubsolarPoint(date = new Date()) {
  const julianDate = date.getTime() / 86400000 + 2440587.5;
  const daysSinceJ2000 = julianDate - 2451545.0;
  const meanLongitude = normalizeDegrees(280.46 + 0.9856474 * daysSinceJ2000);
  const meanAnomaly = normalizeDegrees(357.528 + 0.9856003 * daysSinceJ2000) * DEG;
  const eclipticLongitude = (meanLongitude + 1.915 * Math.sin(meanAnomaly) + 0.02 * Math.sin(2 * meanAnomaly)) * DEG;
  const obliquity = (23.439 - 0.0000004 * daysSinceJ2000) * DEG;
  const rightAscension = Math.atan2(Math.cos(obliquity) * Math.sin(eclipticLongitude), Math.cos(eclipticLongitude));
  const declination = Math.asin(Math.sin(obliquity) * Math.sin(eclipticLongitude));
  const greenwichSiderealTime = normalizeDegrees(
    280.46061837
      + 360.98564736629 * daysSinceJ2000
      + 0.000387933 * (daysSinceJ2000 / 36525) ** 2
      - ((daysSinceJ2000 / 36525) ** 3) / 38710000,
  );

  return {
    lat: declination / DEG,
    lon: normalizeLongitude(rightAscension / DEG - greenwichSiderealTime),
  };
}

function getSunDirection(date = new Date()) {
  const subsolar = getSubsolarPoint(date);
  return latLonToVector(subsolar.lat, subsolar.lon, 1).normalize();
}

function clamp(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, value));
}

function closeZoomProgress(z: number) {
  return 1 - clamp((z - MIN_CAMERA_Z) / (DEFAULT_CAMERA_Z - MIN_CAMERA_Z), 0, 1);
}

function getTouchDistance(touches: readonly { pageX: number; pageY: number }[]) {
  if (touches.length < 2) return 0;
  const [a, b] = touches;
  return Math.hypot(a.pageX - b.pageX, a.pageY - b.pageY);
}

function makeArc(from: RoutePoint, to: RoutePoint) {
  const startDir = latLonToVector(from.lat, from.lon, 1).normalize();
  const endDir = latLonToVector(to.lat, to.lon, 1).normalize();
  const angle = Math.acos(clamp(startDir.dot(endDir), -1, 1));
  const steps = Math.max(36, Math.ceil((angle / Math.PI) * 88));
  const altitude = 0.16 + (angle / Math.PI) * 0.72;
  const points: THREE.Vector3[] = [];

  for (let i = 0; i <= steps; i += 1) {
    const t = i / steps;
    let direction: THREE.Vector3;
    if (angle < 0.0001) {
      direction = startDir.clone();
    } else {
      const sinAngle = Math.sin(angle);
      direction = startDir.clone()
        .multiplyScalar(Math.sin((1 - t) * angle) / sinAngle)
        .add(endDir.clone().multiplyScalar(Math.sin(t * angle) / sinAngle))
        .normalize();
    }
    const lift = Math.sin(Math.PI * t) * altitude;
    points.push(direction.multiplyScalar(RADIUS + 0.04 + lift));
  }

  return points;
}

function makeTube(points: THREE.Vector3[], color: string, opacity: number, radius: number) {
  const curve = new THREE.CatmullRomCurve3(points);
  const geometry = new THREE.TubeGeometry(curve, Math.max(22, points.length - 1), radius, 4, false);
  const material = new THREE.MeshBasicMaterial({
    color,
    transparent: true,
    opacity,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
  });
  const mesh = new THREE.Mesh(geometry, material);
  mesh.renderOrder = 10;
  return mesh;
}

function makeLine(points: THREE.Vector3[], color: string, opacity: number, width = 1) {
  const geometry = new THREE.BufferGeometry().setFromPoints(points);
  const material = new THREE.LineBasicMaterial({
    color,
    transparent: true,
    opacity,
    blending: THREE.AdditiveBlending,
    linewidth: width,
  });
  return new THREE.Line(geometry, material);
}

function makeGridLines() {
  const group = new THREE.Group();
  for (let lat = -60; lat <= 60; lat += 20) {
    const points: THREE.Vector3[] = [];
    for (let lon = -180; lon <= 180; lon += 4) points.push(latLonToVector(lat, lon, RADIUS + 0.006));
    group.add(makeLine(points, '#6A5A38', 0.18));
  }
  for (let lon = -180; lon < 180; lon += 20) {
    const points: THREE.Vector3[] = [];
    for (let lat = -82; lat <= 82; lat += 4) points.push(latLonToVector(lat, lon, RADIUS + 0.006));
    group.add(makeLine(points, '#6A5A38', 0.13));
  }
  return group;
}

function makeCountryBorderGroup() {
  const group = new THREE.Group();
  const material = new THREE.LineBasicMaterial({
    color: '#E3C984',
    transparent: true,
    opacity: 0.18,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
  });

  (countryBorderRings as [number, number][][]).forEach((ring) => {
    let segment: THREE.Vector3[] = [];
    ring.forEach(([lon, lat], index) => {
      const previous = ring[index - 1];
      if (previous && Math.abs(lon - previous[0]) > 180) {
        if (segment.length > 1) {
          group.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(segment), material));
        }
        segment = [];
      }
      segment.push(latLonToVector(lat, lon, RADIUS + 0.0048));
    });
    if (segment.length > 1) {
      group.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(segment), material));
    }
  });

  return group;
}

function makeTileGeometry(row: number, col: number) {
  const latNorth = 90 - (row * 180) / DETAIL_TILE_ROWS;
  const latSouth = 90 - ((row + 1) * 180) / DETAIL_TILE_ROWS;
  const lonWest = -180 + (col * 360) / DETAIL_TILE_COLS;
  const lonEast = -180 + ((col + 1) * 360) / DETAIL_TILE_COLS;
  const horizontalSegments = 36;
  const verticalSegments = 24;
  const positions: number[] = [];
  const uvs: number[] = [];
  const indices: number[] = [];

  for (let y = 0; y <= verticalSegments; y += 1) {
    const v = y / verticalSegments;
    const lat = latNorth + (latSouth - latNorth) * v;
    for (let x = 0; x <= horizontalSegments; x += 1) {
      const u = x / horizontalSegments;
      const lon = lonWest + (lonEast - lonWest) * u;
      const point = latLonToVector(lat, lon, RADIUS + 0.0018);
      positions.push(point.x, point.y, point.z);
      uvs.push(u, v);
    }
  }

  for (let y = 0; y < verticalSegments; y += 1) {
    for (let x = 0; x < horizontalSegments; x += 1) {
      const a = y * (horizontalSegments + 1) + x;
      const b = a + horizontalSegments + 1;
      indices.push(a, b, a + 1, b, b + 1, a + 1);
    }
  }

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  geometry.setAttribute('uv', new THREE.Float32BufferAttribute(uvs, 2));
  geometry.setIndex(indices);
  geometry.computeVertexNormals();
  return geometry;
}

function makeDetailTileGroup() {
  const group = new THREE.Group();
  globeDayDetailTiles.forEach((row, rowIndex) => {
    row.forEach((tileAsset, colIndex) => {
      const material = new THREE.MeshBasicMaterial({
        transparent: true,
        opacity: 0,
        depthWrite: false,
      });
      const centerLat = 90 - ((rowIndex + 0.5) * 180) / DETAIL_TILE_ROWS;
      const centerLon = -180 + ((colIndex + 0.5) * 360) / DETAIL_TILE_COLS;
      const mesh = new THREE.Mesh(makeTileGeometry(rowIndex, colIndex), material);
      mesh.userData = {
        tileAsset,
        center: latLonToVector(centerLat, centerLon, 1).normalize(),
        loaded: false,
      };
      group.add(mesh);
    });
  });
  return group;
}

function makeRouteGroup(routeMeshes: THREE.Object3D[], routes: FlightRoute[]) {
  const group = new THREE.Group();
  routes.forEach((route, index) => {
    const points = makeArc(route.from, route.to);
    const glow = makeTube(points, '#FFBE6A', index % 3 === 0 ? 0.24 : 0.16, 0.0046);
    const core = makeTube(points, index % 3 === 0 ? colors.orange : '#D58B45', index % 3 === 0 ? 0.72 : 0.5, 0.0018);
    const hitArea = makeTube(points, '#FFFFFF', 0, 0.042);
    hitArea.userData = { route };
    core.userData = { route };
    glow.userData = { route };
    routeMeshes.push(hitArea, core, glow);
    group.add(glow);
    group.add(core);
    group.add(hitArea);
  });
  return group;
}

function makeOrb(group: THREE.Group, point: RoutePoint, isHub = false) {
  const haloMaterial = new THREE.MeshBasicMaterial({
    color: isHub ? '#FFB15F' : '#FFD88A',
    transparent: true,
    opacity: isHub ? 0.34 : 0.22,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
  });
  const coreMaterial = new THREE.MeshBasicMaterial({
    color: isHub ? '#FFF5C8' : '#FFF0B6',
    transparent: true,
    opacity: isHub ? 1 : 0.94,
    blending: THREE.AdditiveBlending,
  });
  const halo = new THREE.Mesh(new THREE.SphereGeometry(isHub ? 0.06 : 0.034, 12, 10), haloMaterial);
  const core = new THREE.Mesh(new THREE.SphereGeometry(isHub ? 0.019 : 0.01, 8, 8), coreMaterial);
  halo.position.copy(latLonToVector(point.lat, point.lon, RADIUS + 0.035));
  core.position.copy(latLonToVector(point.lat, point.lon, RADIUS + 0.04));
  halo.renderOrder = 12;
  core.renderOrder = 13;
  group.add(halo);
  group.add(core);
}

function makeCityLightGroup(routes: FlightRoute[], mapPoints: RoutePoint[]) {
  const group = new THREE.Group();
  const seen = new Set<string>();
  [...mapPoints, ...routes.flatMap((route) => [route.from, route.to])].forEach((city) => {
    if (seen.has(city.code)) return;
    seen.add(city.code);
    makeOrb(group, city, city.code === 'DFW');
  });
  return group;
}

function makeTextLine(text: string, font: any, size: number, color: string, opacity: number) {
  const geometry = new TextGeometry(text, {
    font,
    size,
    depth: 0.002,
    curveSegments: 3,
  });
  geometry.computeBoundingBox();
  const bounds = geometry.boundingBox;
  if (bounds) {
    geometry.translate(-(bounds.max.x - bounds.min.x) / 2, 0, 0);
  }
  const material = new THREE.MeshBasicMaterial({
    color,
    transparent: true,
    opacity,
    depthTest: false,
    depthWrite: false,
  });
  const mesh = new THREE.Mesh(geometry, material);
  mesh.renderOrder = 20;
  return mesh;
}

function makeGlobeLabelObjects() {
  const font = new FontLoader().parse(HELVETIKER_FONT);
  return globeLabels.map((item) => {
    const group = new THREE.Group();
    const lines = item.label.split('\n');
    const isLand = item.kind === 'land';
    const materials: THREE.MeshBasicMaterial[] = [];

    lines.forEach((line, index) => {
      const mesh = makeTextLine(
        line,
        font,
        isLand ? 0.07 : 0.062,
        isLand ? colors.cream : '#8B9BA1',
        isLand ? 0.9 : 0.68,
      );
      mesh.position.y = (lines.length - 1 - index) * 0.086;
      materials.push(mesh.material as THREE.MeshBasicMaterial);
      group.add(mesh);
    });

    group.userData = {
      lat: item.lat,
      lon: item.lon,
      materials,
      baseOpacity: isLand ? 0.9 : 0.68,
    };
    group.scale.setScalar(isLand ? 1 : 0.92);
    group.renderOrder = 20;
    return group;
  });
}

function patchExpoPixelStorei(gl: any) {
  if (gl.__trotterPixelStoreiPatched || typeof gl.pixelStorei !== 'function') return;

  const originalPixelStorei = gl.pixelStorei.bind(gl);
  const unsupportedPnames = new Set(
    [
      gl.UNPACK_FLIP_Y_WEBGL,
      gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL,
      gl.UNPACK_COLORSPACE_CONVERSION_WEBGL,
    ].filter((value) => typeof value === 'number'),
  );

  gl.pixelStorei = (pname: number, param: number) => {
    if (unsupportedPnames.has(pname)) return;
    originalPixelStorei(pname, param);
  };
  gl.__trotterPixelStoreiPatched = true;
}

export function GlobeScene({
  onRoutePress,
  routes = flightRoutes,
  mapPoints = flightMapPoints,
}: {
  onRoutePress?: (route: FlightRoute) => void;
  routes?: FlightRoute[];
  mapPoints?: RoutePoint[];
}) {
  const globeRef = useRef<THREE.Group | null>(null);
  const detailTileGroupRef = useRef<THREE.Group | null>(null);
  const cameraRef = useRef<THREE.PerspectiveCamera | null>(null);
  const routeMeshesRef = useRef<THREE.Object3D[]>([]);
  const glSizeRef = useRef({ width: 1, height: 1 });
  const tileVisibilityFrameRef = useRef(0);
  const rotationRef = useRef({ x: -0.06, y: -1.18 });
  const dragStart = useRef({ x: 0, y: 0, rx: 0, ry: 0 });
  const touchStart = useRef({ x: 0, y: 0 });
  const zoomRef = useRef({ z: DEFAULT_CAMERA_Z });
  const pinchStart = useRef({ distance: 0, z: DEFAULT_CAMERA_Z });
  const animationFrameRef = useRef<number | null>(null);
  const isMountedRef = useRef(true);

  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
      if (animationFrameRef.current !== null) {
        cancelAnimationFrame(animationFrameRef.current);
        animationFrameRef.current = null;
      }
    };
  }, []);

  const panResponder = useMemo(
    () => PanResponder.create({
      onStartShouldSetPanResponder: () => true,
      onStartShouldSetPanResponderCapture: (event) => event.nativeEvent.touches.length >= 2,
      onMoveShouldSetPanResponder: () => true,
      onMoveShouldSetPanResponderCapture: (event) => event.nativeEvent.touches.length >= 2,
      onPanResponderGrant: (event, gesture) => {
        const touches = event.nativeEvent.touches;
        if (touches.length >= 2) {
          pinchStart.current = {
            distance: getTouchDistance(touches),
            z: zoomRef.current.z,
          };
        } else {
          touchStart.current = { x: gesture.x0, y: gesture.y0 };
          dragStart.current = {
            x: gesture.x0,
            y: gesture.y0,
            rx: rotationRef.current.x,
            ry: rotationRef.current.y,
          };
        }
      },
      onPanResponderMove: (event, gesture) => {
        const touches = event.nativeEvent.touches;
        if (touches.length >= 2) {
          const currentDistance = getTouchDistance(touches);
          if (pinchStart.current.distance <= 0 && currentDistance > 0) {
            pinchStart.current = {
              distance: currentDistance,
              z: zoomRef.current.z,
            };
            return;
          }
          if (pinchStart.current.distance > 0 && currentDistance > 0) {
            const scale = currentDistance / pinchStart.current.distance;
            zoomRef.current.z = clamp(pinchStart.current.z / scale, MIN_CAMERA_Z, MAX_CAMERA_Z);
          }
          return;
        }
        const dragScale = THREE.MathUtils.lerp(1, 0.34, closeZoomProgress(zoomRef.current.z));
        const maxTilt = THREE.MathUtils.lerp(DEFAULT_MAX_TILT, CLOSE_MAX_TILT, closeZoomProgress(zoomRef.current.z));
        rotationRef.current.y = dragStart.current.ry + gesture.dx * 0.006 * dragScale;
        rotationRef.current.x = clamp(dragStart.current.rx + gesture.dy * 0.0035 * dragScale, -maxTilt, maxTilt);
      },
      onPanResponderRelease: (event, gesture) => {
        pinchStart.current.distance = 0;
        const dx = Math.abs(gesture.dx);
        const dy = Math.abs(gesture.dy);
        if (dx < 14 && dy < 14) {
          const nativeEvent = event.nativeEvent;
          const route = pickRouteAt(nativeEvent?.locationX ?? 0, nativeEvent?.locationY ?? 0);
          if (route) onRoutePress?.(route);
        }
      },
      onPanResponderTerminate: () => {
        pinchStart.current.distance = 0;
      },
    }),
    [onRoutePress],
  );

  const pickRouteAt = useCallback((x: number, y: number) => {
    const camera = cameraRef.current;
    const meshes = routeMeshesRef.current;
    if (!camera || meshes.length === 0) return undefined;
    const { width, height } = glSizeRef.current;
    const pointer = new THREE.Vector2((x / width) * 2 - 1, -(y / height) * 2 + 1);
    const raycaster = new THREE.Raycaster();
    raycaster.params.Line.threshold = 0.08;
    raycaster.setFromCamera(pointer, camera);
    const hit = raycaster.intersectObjects(meshes, false)[0];
    return hit?.object.userData.route as FlightRoute | undefined;
  }, []);

  const onContextCreate = useCallback(async (gl: any) => {
    patchExpoPixelStorei(gl);
    const renderer = new Renderer({ gl, antialias: true });
    renderer.setSize(gl.drawingBufferWidth, gl.drawingBufferHeight);

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(34, gl.drawingBufferWidth / gl.drawingBufferHeight, 0.1, 100);
    cameraRef.current = camera;
    if (glSizeRef.current.width <= 1 || glSizeRef.current.height <= 1) {
      glSizeRef.current = { width: gl.drawingBufferWidth, height: gl.drawingBufferHeight };
    }
    routeMeshesRef.current = [];
    camera.position.set(0, 0, zoomRef.current.z);
    camera.lookAt(0, 0, 0);

    const globe = new THREE.Group();
    globe.position.set(0, 0, 0);
    globe.rotation.set(rotationRef.current.x, rotationRef.current.y, 0);
    globeRef.current = globe;
    scene.add(globe);

    const maxTextureSize = gl.getParameter(gl.MAX_TEXTURE_SIZE) ?? 2048;
    const dayTextureAsset =
      typeof maxTextureSize === 'number' && maxTextureSize >= 4096
        ? EARTH_DAY_TEXTURE_HIGH
        : EARTH_DAY_TEXTURE_STANDARD;
    const dayTexture = new TextureLoader().load(dayTextureAsset);
    const nightTexture = new TextureLoader().load(EARTH_NIGHT_TEXTURE);
    const maxAnisotropy = renderer.capabilities?.getMaxAnisotropy?.() ?? 1;
    const textureAnisotropy = Math.max(1, Math.min(4, maxAnisotropy || 1));
    dayTexture.anisotropy = textureAnisotropy;
    nightTexture.anisotropy = textureAnisotropy;
    dayTexture.colorSpace = THREE.SRGBColorSpace;
    nightTexture.colorSpace = THREE.SRGBColorSpace;
    dayTexture.flipY = false;
    nightTexture.flipY = false;

    const earthMaterial = new THREE.ShaderMaterial({
      uniforms: {
        dayMap: { value: dayTexture },
        nightMap: { value: nightTexture },
        sunDirection: { value: getSunDirection() },
      },
      vertexShader: `
        varying vec3 vLocalNormal;
        void main() {
          vLocalNormal = normalize(normal);
          gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
        }
      `,
      fragmentShader: `
        uniform sampler2D dayMap;
        uniform sampler2D nightMap;
        uniform vec3 sunDirection;
        varying vec3 vLocalNormal;

        const float PI = 3.141592653589793;

        vec2 globeUv(vec3 normal) {
          float u = atan(-normal.z, normal.x) / (2.0 * PI) + 0.5;
          float v = 0.5 - asin(clamp(normal.y, -1.0, 1.0)) / PI;
          return vec2(u, v);
        }

        void main() {
          vec3 normal = normalize(vLocalNormal);
          vec2 uv = globeUv(normal);
          vec3 dayColor = texture2D(dayMap, uv).rgb;
          vec3 nightColor = texture2D(nightMap, uv).rgb;
          float sunAmount = dot(normal, normalize(sunDirection));
          float daylight = smoothstep(-0.11, 0.2, sunAmount);
          float twilight = smoothstep(-0.3, 0.08, sunAmount);
          vec3 warmAtmosphere = vec3(0.22, 0.13, 0.045) * twilight * (1.0 - daylight);
          vec3 color = mix(nightColor * 1.58, dayColor * 1.08 + warmAtmosphere, daylight);
          color += nightColor * (1.0 - daylight) * 0.34;
          color += vec3(0.035, 0.045, 0.05);
          gl_FragColor = vec4(color, 1.0);
        }
      `,
    });

    const ocean = new THREE.Mesh(
      new THREE.SphereGeometry(RADIUS, GLOBE_SEGMENTS, GLOBE_SEGMENTS),
      earthMaterial,
    );
    globe.add(ocean);

    const landShadow = new THREE.Mesh(
      new THREE.SphereGeometry(RADIUS + 0.004, GLOBE_SEGMENTS, GLOBE_SEGMENTS),
      new THREE.MeshStandardMaterial({
        color: '#73664A',
        emissive: '#17140D',
        transparent: true,
        opacity: 0.08,
        roughness: 1,
      }),
    );
    globe.add(landShadow);
    const detailTileGroup = makeDetailTileGroup();
    detailTileGroupRef.current = detailTileGroup;
    globe.add(detailTileGroup);
    globe.add(makeGridLines());
    globe.add(makeCountryBorderGroup());
    globe.add(makeRouteGroup(routeMeshesRef.current, routes));
    globe.add(makeCityLightGroup(routes, mapPoints));

    const labelObjects = makeGlobeLabelObjects();
    labelObjects.forEach((label) => scene.add(label));

    const rim = new THREE.Mesh(
      new THREE.SphereGeometry(RADIUS + 0.036, GLOBE_SEGMENTS, GLOBE_SEGMENTS),
      new THREE.ShaderMaterial({
        uniforms: {
          glowColor: { value: new THREE.Color(colors.glow) },
          power: { value: 2.4 },
        },
        vertexShader: `
          varying vec3 vNormal;
          void main() {
            vNormal = normalize(normalMatrix * normal);
            gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
          }
        `,
        fragmentShader: `
          uniform vec3 glowColor;
          uniform float power;
          varying vec3 vNormal;
          void main() {
            float intensity = pow(0.7 - dot(vNormal, vec3(0.0, 0.0, 1.0)), power);
            gl_FragColor = vec4(glowColor, intensity * 0.18);
          }
        `,
        side: THREE.BackSide,
        blending: THREE.AdditiveBlending,
        transparent: true,
      }),
    );
    scene.add(rim);

    scene.add(new THREE.AmbientLight('#B7C7D8', 0.38));
    const sun = new THREE.DirectionalLight('#FFE4A5', 1.45);
    sun.position.set(-4, 3, 5);
    scene.add(sun);

    let lastSunUpdate = 0;
    const animate = () => {
      if (!isMountedRef.current) return;
      animationFrameRef.current = requestAnimationFrame(animate);
      if (globeRef.current) {
        const spinScale = zoomRef.current.z / DEFAULT_CAMERA_Z;
        rotationRef.current.y += IDLE_ROTATION_SPEED * spinScale;
        globeRef.current.rotation.x = rotationRef.current.x;
        globeRef.current.rotation.y = rotationRef.current.y;
        globeRef.current.updateMatrixWorld();
      }
      tileVisibilityFrameRef.current += 1;
      if (detailTileGroupRef.current && tileVisibilityFrameRef.current % 4 === 0) {
        const opacity = THREE.MathUtils.smoothstep(DETAIL_TILE_SHOW_Z - zoomRef.current.z, 0, 1.1);
        const cameraDirection = camera.position.clone().normalize();
        detailTileGroupRef.current.visible = opacity > 0;
        detailTileGroupRef.current.children.forEach((child) => {
          const mesh = child as THREE.Mesh;
          const center = (mesh.userData.center as THREE.Vector3).clone().applyMatrix4(globe.matrixWorld).normalize();
          const isNearVisibleHemisphere = center.dot(cameraDirection) > -0.16;
          const material = mesh.material as THREE.MeshBasicMaterial;
          mesh.visible = opacity > 0 && isNearVisibleHemisphere;
          material.opacity = mesh.visible ? opacity : 0;
          if (mesh.visible && !mesh.userData.loaded) {
            const texture = new TextureLoader().load(mesh.userData.tileAsset);
            texture.colorSpace = THREE.SRGBColorSpace;
            texture.anisotropy = textureAnisotropy;
            material.map = texture;
            material.needsUpdate = true;
            mesh.userData.loaded = true;
          }
        });
      }
      camera.position.z += (zoomRef.current.z - camera.position.z) * 0.22;
      camera.lookAt(0, 0, 0);
      const now = Date.now();
      if (now - lastSunUpdate > 60000) {
        earthMaterial.uniforms.sunDirection.value.copy(getSunDirection(new Date(now)));
        lastSunUpdate = now;
      }
      labelObjects.forEach((label) => {
        const localPosition = latLonToVector(label.userData.lat, label.userData.lon, RADIUS + 0.12);
        const worldPosition = globeRef.current
          ? localPosition.clone().applyMatrix4(globeRef.current.matrixWorld)
          : localPosition;
        label.position.copy(worldPosition);
        label.quaternion.copy(camera.quaternion);
        const facing = worldPosition.clone().normalize().dot(camera.position.clone().normalize());
        const opacity = Math.max(0, Math.min(1, (facing - 0.04) / 0.34)) * label.userData.baseOpacity;
        label.visible = opacity > 0.02;
        label.userData.materials.forEach((material: THREE.MeshBasicMaterial) => {
          material.opacity = opacity;
        });
      });
      renderer.render(scene, camera);
      gl.endFrameEXP();
    };
    animate();
  }, [mapPoints, routes]);

  return (
    <View
      collapsable={false}
      style={styles.wrap}
      onLayout={(event) => {
        glSizeRef.current = {
          width: event.nativeEvent.layout.width,
          height: event.nativeEvent.layout.height,
        };
      }}
      {...panResponder.panHandlers}
    >
      <GLView style={StyleSheet.absoluteFill} onContextCreate={onContextCreate} />
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    height: 760,
    width: '100%',
  },
});
