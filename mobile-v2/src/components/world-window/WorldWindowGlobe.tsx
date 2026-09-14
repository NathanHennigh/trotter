import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  AccessibilityInfo,
  AppState,
  PanResponder,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { GLView } from "expo-gl";
import * as THREE from "three";
import { ExpoRenderer, ExpoTextureLoader } from "../../lib/expoThree";
import type { FlightRoute, RoutePoint } from "../../data/demoTravel";
import { globeDayDetailTiles } from "../../data/globeDayDetailTiles";
import { globeNightDetailTiles } from "../../data/globeNightDetailTiles";
import { globeCountryDetailTiles } from "../../data/globeCountryDetailTiles";
import { colors, fonts } from "../../theme/trotterTheme";
import {
  countryAt,
  flightCountryKey,
  globeCountries,
  sunPosition,
  type GeoCountry,
} from "./globe-geography";

const R = 2.08,
  RAD = Math.PI / 180;
const DAY = require("../../../assets/world-window/nasa-day-base-4096.jpg"),
  SMALL_DAY = require("../../../assets/world-window/nasa-day-base-2048.jpg"),
  NIGHT = require("../../../assets/world-window/nasa-night-4096.jpg"),
  SMALL_NIGHT = require("../../../assets/world-window/nasa-night-2048.jpg"),
  INDEX = require("../../../assets/world-window/country-index-4096.png"),
  SMALL_INDEX = require("../../../assets/world-window/country-index.png");
const vector = (lat: number, lon: number, r = R) =>
  new THREE.Vector3(
    r * Math.cos(lat * RAD) * Math.cos(lon * RAD),
    r * Math.sin(lat * RAD),
    -r * Math.cos(lat * RAD) * Math.sin(lon * RAD),
  );
const sunVector = (date: Date) => {
  const p = sunPosition(date);
  return vector(p.lat, p.lon, 1);
};
const clamp = (n: number, a: number, b: number) => Math.min(b, Math.max(a, n));
type Props = {
  routes: FlightRoute[];
  active: boolean;
  mapStyle: "classic" | "nasa";
  cycle: boolean;
  visited: string[];
  selectedRouteId?: string;
  selectedCountryCode?: string;
  onRoute: (r: FlightRoute) => void;
  onCountry: (c: GeoCountry) => void;
  onClear: () => void;
};
function disposeObject(object: THREE.Object3D) {
  object.traverse((o) => {
    const m = o as THREE.Mesh;
    m.geometry?.dispose();
    const materials = Array.isArray(m.material) ? m.material : [m.material];
    materials.forEach((x) => x?.dispose());
  });
}
export function WorldWindowGlobe(props: Props) {
  const live = useRef(props);
  live.current = props;
  const host = useRef<View>(null),
    size = useRef({ width: 1, height: 1 }),
    context = useRef<{
      scene: THREE.Scene;
      globe: THREE.Group;
      earth: THREE.Mesh;
      camera: THREE.OrthographicCamera;
      routes: THREE.Group;
      ports: THREE.Group;
      material: THREE.ShaderMaterial;
      lookup: THREE.DataTexture;
      renderer: ExpoRenderer;
    } | null>(null);
  const frame = useRef(0),
    rotation = useRef({ x: 22 * RAD, y: -Math.PI / 2 + 0.95 }),
    zoom = useRef({ current: 1, target: 1 }),
    pan = useRef({
      x: 0,
      y: 0,
      rx: 0,
      ry: 0,
      distance: 0,
      zoom: 1,
      pinched: false,
      dragged: false,
      active: false,
      vx: 0,
      vy: 0,
    });
  const foreground = useRef(true),
    lastInteraction = useRef(-Infinity),
    reduced = useRef(false),
    mounted = useRef(true),
    [error, setError] = useState(false),
    [attempt, setAttempt] = useState(0);
  const clearResources = useRef<() => void>(() => {}),
    generation = useRef(0);
  useEffect(() => {
    mounted.current = true;
    const app = AppState.addEventListener("change", (s) => {
      foreground.current = s === "active";
    });
    AccessibilityInfo.isReduceMotionEnabled().then((v) => {
      reduced.current = v;
    });
    const motion = AccessibilityInfo.addEventListener(
      "reduceMotionChanged",
      (v) => {
        reduced.current = v;
      },
    );
    return () => {
      mounted.current = false;
      cancelAnimationFrame(frame.current);
      clearResources.current();
      app.remove();
      motion.remove();
    };
  }, []);
  const refreshRoutes = useCallback(() => {
    const ctx = context.current;
    if (!ctx) return;
    for (const group of [ctx.routes, ctx.ports]) {
      group.children.forEach(disposeObject);
      group.clear();
    }
    const points = new Map<string, RoutePoint>();
    for (const route of live.current.routes) {
      if (
        ![route.from.lat, route.from.lon, route.to.lat, route.to.lon].every(
          Number.isFinite,
        )
      )
        continue;
      const from = vector(route.from.lat, route.from.lon, 1),
        to = vector(route.to.lat, route.to.lon, 1),
        angle = Math.acos(clamp(from.dot(to), -1, 1));
      const samples = Array.from({ length: 57 }, (_, i) => {
        const t = i / 56;
        let v: THREE.Vector3;
        if (angle < 0.0001) v = from.clone();
        else if (Math.abs(Math.sin(angle)) < 0.0001) {
          const axis = new THREE.Vector3(0, 1, 0).cross(from).normalize();
          if (axis.length() < 0.5) axis.set(1, 0, 0);
          v = from.clone().applyAxisAngle(axis, angle * t);
        } else
          v = from
            .clone()
            .multiplyScalar(Math.sin((1 - t) * angle))
            .addScaledVector(to, Math.sin(t * angle))
            .normalize();
        return v.multiplyScalar(
          R +
            0.012 +
            Math.sin(Math.PI * t) *
              R *
              (0.04 + Math.min(0.2, angle * 0.09)) *
              0.325,
        );
      });
      const curve = new THREE.CatmullRomCurve3(samples),
        material = makeRouteMaterial();
      const geometry = new THREE.TubeGeometry(curve, 56, 0.0055, 4, false);
      const centers: number[] = [];
      for (let i = 0; i <= 56; i++) {
        const center = curve.getPointAt(i / 56);
        for (let j = 0; j <= 4; j++) centers.push(...center.toArray());
      }
      geometry.setAttribute(
        "routeCenter",
        new THREE.Float32BufferAttribute(centers, 3),
      );
      const line = new THREE.Mesh(geometry, material);
      line.userData = {
        route,
        normal: from,
        countries: [
          flightCountryKey(
            route.from.country,
            route.from.countryCode,
            route.from.code,
          ),
          flightCountryKey(
            route.to.country,
            route.to.countryCode,
            route.to.code,
          ),
        ],
      };
      ctx.routes.add(line);
      const hit = new THREE.Mesh(
        new THREE.TubeGeometry(curve, 35, 0.035, 3, false),
        new THREE.MeshBasicMaterial({
          transparent: true,
          opacity: 0,
          depthWrite: false,
        }),
      );
      hit.visible = false;
      hit.userData = { route, hit: true };
      ctx.routes.add(hit);
      points.set(route.from.code, route.from);
      points.set(route.to.code, route.to);
    }
    for (const p of points.values()) {
      const orb = new THREE.Mesh(
        new THREE.SphereGeometry(0.022, 8, 6),
        new THREE.MeshBasicMaterial({ color: "#ebc99d", transparent: true }),
      );
      orb.position.copy(vector(p.lat, p.lon, R + 0.024));
      orb.userData = { point: p };
      ctx.ports.add(orb);
    }
  }, []);
  useEffect(refreshRoutes, [props.routes, refreshRoutes]);
  const updateVisited = useCallback(() => {
    const ctx = context.current;
    if (!ctx) return;
    const data = ctx.lookup.image.data as Uint8Array;
    data.fill(0);
    for (const country of globeCountries) {
      const offset = country.index * 4;
      data[offset] = live.current.visited.includes(country.code) ? 255 : 0;
      data[offset + 1] =
        live.current.selectedCountryCode === country.code ? 255 : 0;
      data[offset + 3] = 255;
    }
    ctx.lookup.needsUpdate = true;
  }, []);
  useEffect(updateVisited, [
    props.visited,
    props.selectedCountryCode,
    updateVisited,
  ]);
  const pick = useCallback((x: number, y: number) => {
    if (live.current.selectedRouteId || live.current.selectedCountryCode) {
      live.current.onClear();
      return;
    }
    const ctx = context.current;
    if (!ctx) return;
    const ray = new THREE.Raycaster();
    ray.setFromCamera(
      new THREE.Vector2(
        (x / size.current.width) * 2 - 1,
        1 - (y / size.current.height) * 2,
      ),
      ctx.camera,
    );
    const earth = ray.intersectObject(ctx.earth)[0],
      route = ray.intersectObjects(ctx.routes.children)[0];
    if (route && (!earth || route.distance < earth.distance + 0.015)) {
      live.current.onRoute(route.object.userData.route);
      return;
    }
    if (earth) {
      const p = ctx.globe.worldToLocal(earth.point.clone()).normalize(),
        country = countryAt(Math.atan2(-p.z, p.x) / RAD, Math.asin(p.y) / RAD);
      if (country) {
        live.current.onCountry(country);
        return;
      }
    }
    live.current.onClear();
  }, []);
  const responder = useMemo(
    () =>
      PanResponder.create({
        onStartShouldSetPanResponder: () => true,
        onMoveShouldSetPanResponder: () => true,
        onPanResponderGrant: (e, g) => {
          lastInteraction.current = Date.now();
          const t = e.nativeEvent.touches;
          pan.current = {
            x: g.x0,
            y: g.y0,
            rx: rotation.current.x,
            ry: rotation.current.y,
            distance:
              t.length > 1
                ? Math.hypot(t[0].pageX - t[1].pageX, t[0].pageY - t[1].pageY)
                : 0,
            zoom: zoom.current.target,
            pinched: t.length > 1,
            dragged: false,
            active: true,
            vx: 0,
            vy: 0,
          };
        },
        onPanResponderMove: (e, g) => {
          const p = pan.current,
            t = e.nativeEvent.touches;
          if (t.length > 1) {
            const distance = Math.hypot(
              t[0].pageX - t[1].pageX,
              t[0].pageY - t[1].pageY,
            );
            if (!p.distance) {
              p.distance = distance;
              p.zoom = zoom.current.target;
            }
            p.pinched = true;
            zoom.current.target = clamp(
              (p.zoom * distance) / p.distance,
              1,
              4.8,
            );
            return;
          }
          if (p.pinched) {
            p.rx = rotation.current.x;
            p.ry = rotation.current.y;
            p.x = g.dx;
            p.y = g.dy;
            p.distance = 0;
            return;
          }
          p.dragged = p.dragged || Math.hypot(g.dx, g.dy) > 5;
          rotation.current.y =
            p.ry + (g.dx * 0.006) / Math.sqrt(zoom.current.current);
          rotation.current.x = clamp(
            p.rx + (g.dy * 0.004) / Math.sqrt(zoom.current.current),
            -1.25,
            1.25,
          );
          p.vx = clamp(g.vx * 0.008, -0.025, 0.025);
          p.vy = clamp(g.vy * 0.004, -0.012, 0.012);
        },
        onPanResponderRelease: (e, g) => {
          lastInteraction.current = Date.now();
          const p = pan.current;
          p.active = false;
          if (!p.pinched && !p.dragged && Math.hypot(g.dx, g.dy) < 8)
            pick(e.nativeEvent.locationX, e.nativeEvent.locationY);
          if (p.pinched) p.vx = p.vy = 0;
        },
        onPanResponderTerminate: () => {
          pan.current.active = false;
          pan.current.vx = pan.current.vy = 0;
        },
      }),
    [pick],
  );
  const create = useCallback(
    async (gl: any) => {
      const ownGeneration = ++generation.current;
      try {
        clearResources.current();
        const original = gl.pixelStorei.bind(gl);
        const unsupported = new Set([
          gl.UNPACK_FLIP_Y_WEBGL,
          gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL,
          gl.UNPACK_COLORSPACE_CONVERSION_WEBGL,
        ]);
        gl.pixelStorei = (p: number, v: number) => {
          if (!unsupported.has(p)) original(p, v);
        };
        const renderer = new ExpoRenderer({ gl, antialias: true });
        // Expo's drawing buffer already includes device pixel density. Do not
        // replace it with layout points or multiply by PixelRatio a second time.
        let bufferWidth = gl.drawingBufferWidth,
          bufferHeight = gl.drawingBufferHeight;
        renderer.setSize(bufferWidth, bufferHeight, false);
        renderer.setClearColor(colors.paperSoft, 1);
        const scene = new THREE.Scene(),
          globe = new THREE.Group(),
          camera = new THREE.OrthographicCamera(-3, 3, 6, -6, 0.1, 100);
        scene.add(globe);
        const textureError = () => {
          if (mounted.current && ownGeneration === generation.current) {
            clearResources.current();
            setError(true);
          }
        };
        const quality = globeTextureQuality(
          gl.getParameter(gl.MAX_TEXTURE_SIZE),
        );
        const loader = new ExpoTextureLoader(),
          day = loader.load(
            quality.baseWidth === 4096 ? DAY : SMALL_DAY,
            undefined,
            undefined,
            textureError,
          ),
          night = loader.load(
            quality.baseWidth === 4096 ? NIGHT : SMALL_NIGHT,
            undefined,
            undefined,
            textureError,
          ),
          index = loader.load(
            quality.baseWidth === 4096 ? INDEX : SMALL_INDEX,
            undefined,
            undefined,
            textureError,
          );
        for (const t of [day, night]) configureGlobeTexture(t, false, renderer);
        configureGlobeTexture(index, true, renderer);
        index.minFilter = index.magFilter = THREE.NearestFilter;
        index.generateMipmaps = false;
        index.colorSpace = THREE.NoColorSpace;
        const lookup = new THREE.DataTexture(
          new Uint8Array(256 * 4),
          256,
          1,
          THREE.RGBAFormat,
        );
        lookup.minFilter = lookup.magFilter = THREE.NearestFilter;
        lookup.needsUpdate = true;
        const material = new THREE.ShaderMaterial({
          uniforms: {
            dayMap: { value: day },
            nightMap: { value: night },
            indexMap: { value: index },
            visitedMap: { value: lookup },
            indexSize: {
              value: new THREE.Vector2(
                quality.baseWidth,
                quality.baseWidth / 2,
              ),
            },
            dayBounds: { value: new THREE.Vector4(0, 0, 1, 1) },
            nightBounds: { value: new THREE.Vector4(0, 0, 1, 1) },
            indexBounds: { value: new THREE.Vector4(0, 0, 1, 1) },
            surfaceOpacity: { value: 1 },
            sun: { value: sunVector(new Date()) },
            textureMix: { value: live.current.mapStyle === "nasa" ? 1 : 0 },
          },
          vertexShader: `varying vec3 local;void main(){local=normal;gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.);}`,
          fragmentShader: `precision highp float;
uniform sampler2D dayMap,nightMap,indexMap,visitedMap;
uniform vec3 sun;uniform float textureMix,surfaceOpacity;uniform vec2 indexSize;uniform vec4 dayBounds,nightBounds,indexBounds;varying vec3 local;
vec2 regionUV(vec2 uv,vec4 bounds){
 if(uv.x<bounds.x-.5)uv.x+=1.;if(uv.x>bounds.x+bounds.z+.5)uv.x-=1.;
 return (uv-bounds.xy)/bounds.zw;
}
vec3 countryMask(vec2 p){
 vec3 code=texture2D(indexMap,p).rgb;float id=floor(code.r*255.+.5);
 float land=step(.5,code.b);vec2 marked=texture2D(visitedMap,vec2((id+.5)/256.,.5)).rg;
 return vec3(land,marked*land);
}
vec3 filteredMask(vec2 uv){
 vec2 pixel=uv*indexSize-.5,blend=fract(pixel),base=(floor(pixel)+.5)/indexSize,stepUV=1./indexSize;
 return mix(mix(countryMask(base),countryMask(base+vec2(stepUV.x,0.)),blend.x),mix(countryMask(base+vec2(0.,stepUV.y)),countryMask(base+stepUV),blend.x),blend.y);
}
void main(){
 vec3 n=normalize(local);
 vec2 uv=vec2(atan(-n.z,n.x)/6.28318530718+.5,.5-asin(clamp(n.y,-1.,1.))/3.14159265359);
 vec3 mask=filteredMask(regionUV(uv,indexBounds));vec2 marked=mask.yz;
 float isLand=mask.x,mu=dot(n,normalize(sun));
 float day=smoothstep(-.104528463,0.,mu),direct=.78+.22*sqrt(max(0.,mu));
 vec3 earth=texture2D(dayMap,regionUV(uv,dayBounds)).rgb,lights=texture2D(nightMap,regionUV(uv,nightBounds)).rgb;
 vec3 sea=vec3(92.,147.,169.)/255.,land=vec3(233.,218.,177.)/255.,visited=vec3(201.,132.,93.)/255.;
 vec3 nightSea=vec3(12.,31.,48.)/255.,nightLand=vec3(42.,57.,64.)/255.,nightVisited=vec3(104.,66.,48.)/255.;
 float terrain=1.+.085*(dot(earth,vec3(.299,.587,.114))-.40);
 vec3 daytime=(sea*(1.-isLand)+land*(isLand-marked.r)+visited*marked.r)*terrain;
 vec3 nighttime=nightSea*(1.-isLand)+nightLand*(isLand-marked.r)+nightVisited*marked.r;
 float glow=pow(max(0.,min(lights.r,lights.g)-lights.b*.95)*1.7,1.3);
 nighttime+=vec3(1.,.73,.39)*glow*.16;
 daytime=mix(daytime,mix(earth,visited,marked.r*.25),textureMix);
 nighttime=mix(nighttime,mix(lights*.78+vec3(.012,.021,.038),nightVisited,marked.r*.28),textureMix);
 float lat=asin(clamp(n.y,-1.,1.)),lon=atan(-n.z,n.x);
 vec2 gridDistance=abs(sin(vec2(lat,lon)*6.)),gridWidth=max(fwidth(vec2(lat,lon)*6.),vec2(.000001));
 float grid=1.-min(smoothstep(0.,gridWidth.x*.8,gridDistance.x),smoothstep(0.,gridWidth.y*.8,gridDistance.y));
 vec3 color=mix(nighttime,daytime*direct,day)*(1.-grid*.035);
 color=mix(color,mix(visited,vec3(1.),.20),marked.g*.24);
 gl_FragColor=vec4(color,surfaceOpacity);
}`,
        });
        const earth = new THREE.Mesh(
            new THREE.SphereGeometry(R, 256, 160),
            material,
          ),
          routes = new THREE.Group(),
          ports = new THREE.Group();
        globe.add(earth, routes, ports);
        const coastPositions: number[] = [];
        for (const c of globeCountries)
          for (const polygon of c.polygons)
            for (const ring of polygon)
              for (let i = 1; i < ring.length; i++) {
                const a = ring[i - 1],
                  b = ring[i];
                if (Math.abs(a[0] - b[0]) > 180) continue;
                for (const p of [a, b])
                  coastPositions.push(
                    ...vector(p[1], p[0], R + 0.002).toArray(),
                  );
              }
        const coasts = new THREE.LineSegments(
          new THREE.BufferGeometry().setAttribute(
            "position",
            new THREE.Float32BufferAttribute(coastPositions, 3),
          ),
          new THREE.LineBasicMaterial({
            color: "#577a82",
            transparent: true,
            opacity: 0.14,
          }),
        );
        globe.add(coasts);
        const detail = createGlobeDetail(
          globe,
          material,
          renderer,
          quality.detailTiles,
        );
        context.current = {
          scene,
          globe,
          earth,
          camera,
          routes,
          ports,
          material,
          lookup,
          renderer,
        };
        refreshRoutes();
        updateVisited();
        clearResources.current = () => {
          cancelAnimationFrame(frame.current);
          detail.dispose();
          disposeObject(scene);
          for (const t of [day, night, index, lookup]) t.dispose();
          renderer.dispose();
          context.current = null;
        };
        let previous = 0,
          cycleStart: number | undefined;
        const portNight = new THREE.Color("#fbd3a0"),
          portDay = new THREE.Color("#e5bc8d");
        const draw = (time: number) => {
          if (!mounted.current) return;
          frame.current = requestAnimationFrame(draw);
          const dt = Math.min(40, previous ? time - previous : 16);
          previous = time;
          if (!foreground.current || !live.current.active) return;
          if (
            bufferWidth !== gl.drawingBufferWidth ||
            bufferHeight !== gl.drawingBufferHeight
          ) {
            bufferWidth = gl.drawingBufferWidth;
            bufferHeight = gl.drawingBufferHeight;
            renderer.setSize(bufferWidth, bufferHeight, false);
          }
          const p = pan.current;
          if (!p.active) {
            const decay = Math.exp(-dt / 70);
            p.vx *= decay;
            p.vy *= decay;
            const focused = Boolean(
              live.current.selectedRouteId || live.current.selectedCountryCode,
            );
            rotation.current.y +=
              reduced.current || focused
                ? 0
                : (p.vx * dt) / 16 +
                  0.000022 *
                    dt *
                    clamp(
                      (Date.now() - lastInteraction.current - 3000) / 1200,
                      0,
                      1,
                    );
            rotation.current.x = clamp(
              rotation.current.x +
                (reduced.current || focused ? 0 : (p.vy * dt) / 16),
              -1.25,
              1.25,
            );
          }
          globe.rotation.set(rotation.current.x, rotation.current.y, 0);
          globe.updateMatrixWorld();
          const aspect = size.current.width / size.current.height;
          zoom.current.current +=
            (zoom.current.target - zoom.current.current) *
            (1 - Math.exp(-dt / 80));
          const halfWidth = (R * 1.1) / zoom.current.current;
          const halfHeight = halfWidth / aspect;
          camera.left = -halfWidth;
          camera.right = halfWidth;
          camera.top = halfHeight * 0.97;
          camera.bottom = -halfHeight * 1.03;
          camera.updateProjectionMatrix();
          camera.position.set(0, 0, 10);
          camera.lookAt(0, 0, 0);
          detail.update(zoom.current.current, time, dt);
          if (live.current.cycle) cycleStart ??= time;
          else cycleStart = undefined;
          const sun = sunVector(
            new Date(
              Date.now() +
                (cycleStart === undefined
                  ? 0
                  : ((time - cycleStart) / 45000) * 86400000),
            ),
          );
          material.uniforms.sun.value
            .lerp(sun, 1 - Math.exp(-dt / 130))
            .normalize();
          const target = live.current.mapStyle === "nasa" ? 1 : 0;
          material.uniforms.textureMix.value +=
            (target - material.uniforms.textureMix.value) *
            (1 - Math.exp(-dt / 180));
          for (const child of routes.children) {
            const m = child as THREE.Mesh;
            const mat = m.material as THREE.ShaderMaterial;
            if (m.userData.hit) continue;
            const r = m.userData.route as FlightRoute,
              focused = live.current.selectedRouteId
                ? r.id === live.current.selectedRouteId
                : !live.current.selectedCountryCode ||
                  m.userData.countries.includes(
                    live.current.selectedCountryCode,
                  );
            mat.uniforms.alpha.value +=
              ((focused ? 0.72 : 0.075) - mat.uniforms.alpha.value) *
              (1 - Math.exp(-dt / 90));
            mat.uniforms.sun.value.copy(material.uniforms.sun.value);
            mat.uniforms.imagery.value = material.uniforms.textureMix.value;
            mat.uniforms.widthScale.value = 1 / zoom.current.current;
          }
          for (const child of ports.children) {
            const m = child as THREE.Mesh;
            const port = m.userData.point as RoutePoint;
            m.scale.setScalar(1 / zoom.current.current);
            const selectedRoute = live.current.routes.find(
              (r) => r.id === live.current.selectedRouteId,
            );
            const related = selectedRoute
              ? [selectedRoute.from.code, selectedRoute.to.code].includes(
                  port.code,
                )
              : !live.current.selectedCountryCode ||
                flightCountryKey(port.country, port.countryCode, port.code) ===
                  live.current.selectedCountryCode;
            const pointMaterial = m.material as THREE.MeshBasicMaterial;
            pointMaterial.opacity +=
              ((related ? 1 : 0.3) - pointMaterial.opacity) *
              (1 - Math.exp(-dt / 90));
            const daylight = clamp(
              (m.position.dot(sun) / m.position.length() + 0.11) / 0.31,
              0,
              1,
            );
            (m.material as THREE.MeshBasicMaterial).color.lerpColors(
              portNight,
              portDay,
              daylight,
            );
          }
          try {
            renderer.render(scene, camera);
            gl.endFrameEXP();
          } catch {
            textureError();
          }
        };
        frame.current = requestAnimationFrame(draw);
      } catch {
        if (mounted.current && ownGeneration === generation.current) {
          clearResources.current();
          setError(true);
        }
      }
    },
    [refreshRoutes, updateVisited],
  );
  return (
    <View
      ref={host}
      style={StyleSheet.absoluteFill}
      onLayout={(e) => {
        size.current = e.nativeEvent.layout;
      }}
      {...responder.panHandlers}
    >
      {error ? (
        <View style={styles.error}>
          <Text style={styles.errorText}>The globe could not load.</Text>
          <Pressable
            accessibilityRole="button"
            onPress={() => {
              setError(false);
              setAttempt((n) => n + 1);
            }}
          >
            <Text style={styles.retry}>Try again</Text>
          </Pressable>
        </View>
      ) : (
        <GLView
          key={attempt}
          style={StyleSheet.absoluteFill}
          msaaSamples={4}
          onContextCreate={create}
        />
      )}
    </View>
  );
}
const styles = StyleSheet.create({
  error: { flex: 1, alignItems: "center", justifyContent: "center", gap: 16 },
  errorText: { fontFamily: fonts.sansRegular, color: colors.ink },
  retry: { fontFamily: fonts.sansSemi, color: colors.blue, padding: 14 },
});

// Match the reference's light along each arc, including crossings of the terminator.
function makeRouteMaterial() {
  return new THREE.ShaderMaterial({
    transparent: true,
    depthWrite: false,
    uniforms: {
      sun: { value: new THREE.Vector3(1, 0, 0) },
      alpha: { value: 0.72 },
      imagery: { value: 0 },
      widthScale: { value: 1 },
    },
    vertexShader: `attribute vec3 routeCenter;uniform float widthScale;varying vec3 local;void main(){local=routeCenter;vec3 point=routeCenter+(position-routeCenter)*widthScale;gl_Position=projectionMatrix*modelViewMatrix*vec4(point,1.);}`,
    fragmentShader: `precision highp float;varying vec3 local;uniform vec3 sun;uniform float alpha,imagery;void main(){float day=smoothstep(-.104528463,0.,dot(normalize(local),normalize(sun)));vec3 night=vec3(251.,211.,160.)/255.;vec3 light=mix(vec3(123.,60.,34.)/255.,vec3(248.,219.,161.)/255.,imagery);gl_FragColor=vec4(mix(night,light,day),alpha);}`,
  });
}

// Four visible tiles bound day/night/country detail textures to ~85 MiB; the base remains
// available throughout loading/failure. Never retain a growing world-wide cache.
function globeTextureQuality(maxTextureSize: number) {
  return {
    baseWidth: maxTextureSize >= 4096 ? 4096 : 2048,
    detailTiles: maxTextureSize >= 4096 ? 4 : maxTextureSize >= 2048 ? 2 : 0,
  };
}
function configureGlobeTexture(
  texture: THREE.Texture,
  labels: boolean,
  renderer: ExpoRenderer,
) {
  texture.flipY = false;
  texture.colorSpace = THREE.NoColorSpace;
  texture.generateMipmaps = false;
  texture.minFilter = texture.magFilter = labels
    ? THREE.NearestFilter
    : THREE.LinearFilter;
  texture.anisotropy = labels
    ? 1
    : Math.min(4, renderer.capabilities.getMaxAnisotropy());
}
const detailTiles = Array.from({ length: 72 }, (_, key) => {
  const row = Math.floor(key / 12),
    col = key % 12;
  return { key, row, col, center: vector(75 - row * 30, -165 + col * 30, 1) };
});
function selectGlobeTiles(rotation: THREE.Quaternion, limit: number) {
  return detailTiles
    .map((tile) => ({
      key: tile.key,
      facing: tile.center.clone().applyQuaternion(rotation).z,
    }))
    .filter((tile) => tile.facing > 0)
    .sort((a, b) => b.facing - a.facing || a.key - b.key)
    .slice(0, limit)
    .map((tile) => tile.key);
}
function makeGlobeTileGeometry(row: number, col: number) {
  const steps = 48,
    positions: number[] = [],
    normals: number[] = [],
    indices: number[] = [];
  for (let y = 0; y <= steps; y++)
    for (let x = 0; x <= steps; x++) {
      const normal = vector(
        90 - (row + y / steps) * 30,
        -180 + (col + x / steps) * 30,
        1,
      );
      normals.push(...normal.toArray());
      positions.push(...normal.multiplyScalar(R + 0.0008).toArray());
    }
  for (let y = 0; y < steps; y++)
    for (let x = 0; x < steps; x++) {
      const a = y * (steps + 1) + x,
        b = a + steps + 1;
      indices.push(a, b, a + 1, b, b + 1, a + 1);
    }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute(
    "position",
    new THREE.Float32BufferAttribute(positions, 3),
  );
  geometry.setAttribute("normal", new THREE.Float32BufferAttribute(normals, 3));
  geometry.setIndex(indices);
  return geometry;
}
function createGlobeDetail(
  globe: THREE.Group,
  base: THREE.ShaderMaterial,
  renderer: ExpoRenderer,
  limit: number,
  loadOverride?: (asset: number, labels: boolean) => Promise<THREE.Texture>,
) {
  const loaded = new Map<
    number,
    {
      mesh: THREE.Mesh<THREE.BufferGeometry, THREE.ShaderMaterial>;
      day: THREE.Texture;
      night?: THREE.Texture;
      index: THREE.Texture;
    }
  >();
  const failed = new Set<number>();
  let disposed = false,
    busy = false,
    desired: number[] = [],
    lastSelection = -Infinity,
    currentZoom = 1;
  const load =
    loadOverride ??
    ((asset: number, labels: boolean) =>
      new Promise<THREE.Texture>((resolve, reject) => {
        let texture: THREE.Texture | undefined;
        texture = new ExpoTextureLoader().load(
          asset,
          (value) => {
            configureGlobeTexture(value, labels, renderer);
            resolve(value);
          },
          undefined,
          (error) => {
            texture?.dispose();
            reject(error);
          },
        );
      }));
  const remove = (key: number) => {
    const entry = loaded.get(key);
    if (!entry) return;
    globe.remove(entry.mesh);
    entry.mesh.geometry.dispose();
    entry.mesh.material.dispose();
    entry.day.dispose();
    entry.night?.dispose();
    entry.index.dispose();
    loaded.delete(key);
  };
  const pump = async () => {
    if (busy || disposed) return;
    busy = true;
    try {
      while (!disposed) {
        const key = desired.find((key) => !loaded.has(key) && !failed.has(key));
        if (key === undefined) break;
        const tile = detailTiles[key];
        let day: THREE.Texture | undefined,
          index: THREE.Texture | undefined,
          night: THREE.Texture | undefined;
        try {
          day = await load(globeDayDetailTiles[tile.row][tile.col], false);
          if (disposed || !desired.includes(key)) {
            day.dispose();
            continue;
          }
          index = await load(globeCountryDetailTiles[tile.row][tile.col], true);
          if (disposed || !desired.includes(key)) {
            day.dispose();
            index.dispose();
            continue;
          }
          // Night detail is optional: a missing tile must never discard a
          // successfully decoded day tile or prevent the globe from opening.
          try {
            night = await load(
              globeNightDetailTiles[tile.row][tile.col],
              false,
            );
          } catch {
            night = undefined;
          }
          if (disposed || !desired.includes(key)) {
            day.dispose();
            index.dispose();
            night?.dispose();
            continue;
          }
          const uniforms = {
            ...base.uniforms,
            dayMap: { value: day },
            nightMap: night ? { value: night } : base.uniforms.nightMap,
            nightBounds: night
              ? {
                  value: new THREE.Vector4(
                    (tile.col * 1125 - 1) / 13500,
                    (tile.row * 1125 - 1) / 6750,
                    1127 / 13500,
                    1127 / 6750,
                  ),
                }
              : base.uniforms.nightBounds,
            indexMap: { value: index },
            indexSize: { value: new THREE.Vector2(1026, 1026) },
            dayBounds: {
              value: new THREE.Vector4(
                tile.col / 12,
                tile.row / 6,
                1 / 12,
                1 / 6,
              ),
            },
            indexBounds: {
              value: new THREE.Vector4(
                (tile.col * 1024 - 1) / 12288,
                (tile.row * 1024 - 1) / 6144,
                1026 / 12288,
                1026 / 6144,
              ),
            },
            surfaceOpacity: { value: 0 },
          };
          const material = new THREE.ShaderMaterial({
            uniforms,
            vertexShader: base.vertexShader,
            fragmentShader: base.fragmentShader,
            transparent: true,
            depthWrite: false,
          });
          const mesh = new THREE.Mesh(
            makeGlobeTileGeometry(tile.row, tile.col),
            material,
          );
          // Opaque earth first, then detail, then borders/flight routes/airports.
          mesh.renderOrder = -1;
          loaded.set(key, { mesh, day, night, index });
          globe.add(mesh);
        } catch {
          day?.dispose();
          index?.dispose();
          night?.dispose();
          failed.add(key);
        }
      }
    } finally {
      busy = false;
    }
  };
  return {
    update(zoom: number, time: number, dt: number) {
      if (disposed) return;
      currentZoom = zoom;
      if (time - lastSelection >= 250 || zoom < 1.6) {
        lastSelection = time;
        desired = zoom < 1.6 ? [] : selectGlobeTiles(globe.quaternion, limit);
        for (const key of loaded.keys())
          if (!desired.includes(key)) remove(key);
        void pump();
      }
      for (const { mesh } of loaded.values()) {
        const alpha = mesh.material.uniforms.surfaceOpacity;
        alpha.value +=
          (clamp((currentZoom - 1.6) / 0.6, 0, 1) - alpha.value) *
          (1 - Math.exp(-dt / 130));
      }
    },
    dispose() {
      disposed = true;
      desired = [];
      for (const key of [...loaded.keys()]) remove(key);
      // The one outstanding decode is disposed by pump when its callback resolves.
    },
    stats: () => ({
      resident: loaded.size,
      pending: busy,
      desired: [...desired],
      failed: failed.size,
      disposed,
    }),
  };
}
