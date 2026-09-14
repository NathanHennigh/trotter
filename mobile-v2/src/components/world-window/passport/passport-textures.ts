import type { BookPayload, BookStamp } from "./passport-payload";
import { fitFontSize } from "../../trotter/stamps/stampLayout";
import {
  PAGE_WIDTH as W,
  PAGE_HEIGHT as H,
  type PaperPage,
  type PageTexture,
} from "./passport-paper";
import { passportMaterial } from "./passport-material";
import { stampFootprint } from "./passport-footprint";

type Box = {
  left: number;
  top: number;
  width: number;
  height: number;
  fontScale?: number;
  tracking?: number;
  charFactor?: number;
  adaptiveLength?: boolean;
};
const imageCache = new Map<string, Promise<HTMLImageElement>>();
function image(src: string) {
  if (!imageCache.has(src))
    imageCache.set(
      src,
      new Promise<HTMLImageElement>((resolve, reject) => {
        const img = new Image();
        img.onload = () => resolve(img);
        img.onerror = () => {
          imageCache.delete(src);
          reject(new Error("Could not load a passport image"));
        };
        img.src = src;
      }),
    );
  return imageCache.get(src)!;
}
function dateLabel(value: string) {
  const parsed = new Date(`${value.slice(0, 10)}T12:00:00`);
  return Number.isFinite(parsed.getTime())
    ? parsed
        .toLocaleDateString("en-GB", {
          day: "2-digit",
          month: "short",
          year: "numeric",
        })
        .toUpperCase()
    : value;
}
function containedImage(
  c: CanvasRenderingContext2D,
  img: HTMLImageElement,
  box: Box,
  color: string,
  opacity: number,
) {
  const x = box.left * 204.75,
    y = box.top * 165.75,
    w = box.width * 204.75,
    h = box.height * 165.75;
  const fit = Math.min(w / img.naturalWidth, h / img.naturalHeight),
    width = img.naturalWidth * fit,
    height = img.naturalHeight * fit;
  const ink = document.createElement("canvas");
  ink.width = Math.ceil(width * 3);
  ink.height = Math.ceil(height * 3);
  const ctx = ink.getContext("2d")!;
  ctx.drawImage(img, 0, 0, ink.width, ink.height);
  ctx.globalCompositeOperation = "source-in";
  ctx.fillStyle = color;
  ctx.fillRect(0, 0, ink.width, ink.height);
  c.save();
  c.globalAlpha = opacity;
  c.drawImage(ink, x + (w - width) / 2, y + (h - height) / 2, width, height);
  c.restore();
}
function fontFor(
  text: string,
  box: Box,
  base: number,
  availableWidth = box.width * 204.75,
  availableHeight = box.height * 165.75,
) {
  return fitFontSize(
    text,
    base * (box.fontScale ?? 1),
    availableWidth,
    availableHeight,
    box,
    204.75,
  );
}
function lineText(
  c: CanvasRenderingContext2D,
  text: string,
  box: Box,
  base: number,
  mono = false,
) {
  if (!text) return;
  let size = fontFor(text, box, base);
  c.font = `${size}px ${mono ? "PlexMono" : "DMSansBold"}`;
  const measured = c.measureText(text).width;
  if (measured > box.width * 204.75) {
    size *= (box.width * 204.75) / measured;
    c.font = `${size}px ${mono ? "PlexMono" : "DMSansBold"}`;
  }
  c.textAlign = "center";
  c.textBaseline = "middle";
  c.fillText(
    text,
    (box.left + box.width / 2) * 204.75,
    (box.top + box.height / 2) * 165.75,
  );
}
function curvedTitle(c: CanvasRenderingContext2D, stamp: BookStamp) {
  const t = stamp.template,
    box = t.country,
    text = stamp.country,
    points: { x: number; y: number; length: number }[] = [];
  let size: number;
  if (t.titleMode === "circleArc") {
    const fw = t.frame.width * 204.75,
      fh = t.frame.height * 165.75;
    const cx = (t.frame.left + t.frame.width / 2) * 204.75,
      cy = t.frame.top * 165.75 + fh * (0.5 + (t.arcCenterYOffset ?? -0.02));
    const radius = Math.min(fw, fh) * (t.circleTitleRadius ?? 0.28),
      half = (70 * Math.PI) / 180;
    size = fontFor(
      text,
      box,
      22.75,
      radius * half * 1.8,
      box.height * 165.75 * 0.7,
    );
    for (let i = 0; i <= 180; i++) {
      const a = -half + (2 * half * i) / 180;
      points.push({
        x: cx + Math.sin(a) * radius,
        y: cy - Math.cos(a) * radius,
        length: 0,
      });
    }
  } else {
    const w = box.width * 204.75,
      h = box.height * 165.75,
      l = box.left * 204.75,
      top = box.top * 165.75,
      depth = Math.max(0.2, Math.min(1.5, t.arcDepth ?? 0.7));
    const start = top + h * Math.min(0.88, 0.6 + depth * 0.15),
      middle = top + h * Math.max(0.06, 0.52 - depth * 0.34),
      ctrl = middle - (start - middle) * 0.4;
    size = fontFor(text, box, 22.75, w * 0.84, h * 0.85);
    for (let i = 0; i <= 180; i++) {
      const u = i / 180,
        v = 1 - u;
      points.push({
        x:
          l +
          w *
            (v ** 3 * 0.08 +
              3 * v * v * u * 0.25 +
              3 * v * u * u * 0.75 +
              u ** 3 * 0.92),
        y:
          v ** 3 * start +
          3 * v * v * u * ctrl +
          3 * v * u * u * ctrl +
          u ** 3 * start,
        length: 0,
      });
    }
  }
  for (let i = 1; i < points.length; i++)
    points[i].length =
      points[i - 1].length +
      Math.hypot(points[i].x - points[i - 1].x, points[i].y - points[i - 1].y);
  const length = points.at(-1)!.length;
  c.font = `${size}px DMSansBold`;
  const total = c.measureText(text).width;
  if (total > length * 0.9) {
    size *= (length * 0.9) / total;
    c.font = `${size}px DMSansBold`;
  }
  const widths = Array.from(text, (char) => c.measureText(char).width),
    tracking = box.tracking ?? 0;
  let offset =
    (length -
      widths.reduce((sum, w) => sum + w, 0) -
      tracking * Math.max(0, widths.length - 1)) /
    2;
  Array.from(text).forEach((char, index) => {
    const target = offset + widths[index] / 2,
      p = Math.max(
        1,
        points.findIndex((point) => point.length >= target),
      );
    const a = points[p - 1],
      b = points[p],
      f = (target - a.length) / Math.max(0.001, b.length - a.length);
    c.save();
    c.translate(a.x + (b.x - a.x) * f, a.y + (b.y - a.y) * f);
    c.rotate(Math.atan2(b.y - a.y, b.x - a.x));
    c.textAlign = "center";
    c.textBaseline = "alphabetic";
    c.fillText(char, 0, 0);
    c.restore();
    offset += widths[index] + tracking;
  });
}
async function stampTexture(stamp: BookStamp) {
  const [frame, artwork] = await Promise.all([
    image(stamp.frame),
    stamp.icon ? image(stamp.icon) : Promise.resolve(undefined),
  ]);
  const crop = stampFootprint(stamp.template);
  const canvas = document.createElement("canvas");
  canvas.width = Math.ceil(crop.width * 3);
  canvas.height = Math.ceil(crop.height * 3);
  const c = canvas.getContext("2d")!;
  c.scale(3, 3);
  c.translate(-crop.x, -crop.y);
  c.fillStyle = stamp.color;
  containedImage(c, frame, stamp.template.frame, stamp.color, 0.92);
  if (artwork)
    containedImage(c, artwork, stamp.template.icon, stamp.color, 0.78);
  const arc =
    stamp.template.titleMode !== "straight" &&
    (!stamp.template.straightTitleMaxChars ||
      stamp.country.length > stamp.template.straightTitleMaxChars);
  if (arc) curvedTitle(c, stamp);
  else lineText(c, stamp.country, stamp.template.country, 22.75);
  lineText(c, dateLabel(stamp.date), stamp.template.date, 13.16, true);
  lineText(c, stamp.airport.toUpperCase(), stamp.template.airport, 14.2, true);
  return canvas;
}
export function fittedLines(
  c: CanvasRenderingContext2D,
  value: string,
  maxSize: number,
  maxWidth: number,
  maxLines = 3,
) {
  for (let size = maxSize; size >= 12; size--) {
    c.font = `${size}px Newsreader`;
    const lines: string[] = [];
    let line = "";
    for (const word of value.trim().split(/\s+/)) {
      const candidate = (line + " " + word).trim();
      if (c.measureText(candidate).width <= maxWidth) {
        line = candidate;
        continue;
      }
      if (line) {
        lines.push(line);
        line = "";
      }
      for (const char of word) {
        if (line && c.measureText(line + char).width > maxWidth) {
          lines.push(line);
          line = "";
        }
        line += char;
      }
    }
    if (line) lines.push(line);
    if (lines.length <= maxLines && (lines.length - 1) * size <= 94)
      return { lines, size };
  }
  return { lines: [value], size: 12 };
}
export async function makeTextures(
  pages: PaperPage[],
  payload: BookPayload,
): Promise<PageTexture[]> {
  await Promise.all(
    Object.keys(payload.fonts).map((name) =>
      document.fonts.load(`16px ${name}`),
    ),
  );
  const stamps = new Map(
    await Promise.all(
      payload.stamps.map(
        async (stamp) => [stamp.code, await stampTexture(stamp)] as const,
      ),
    ),
  );
  const material = passportMaterial("window");
  return pages.map((page) => {
    const canvas = document.createElement("canvas");
    canvas.width = W * 3;
    canvas.height = H * 3;
    const c = canvas.getContext("2d")!;
    c.scale(3, 3);
    const paintPaper = () => {
      c.fillStyle = material.paper;
      c.fillRect(0, 0, W, H);
      c.strokeStyle = "#79856506";
      c.lineWidth = 0.6;
      for (let y = 2; y < H; y += 4) {
        c.beginPath(); c.moveTo(0, y); c.lineTo(W, y + 12); c.stroke();
      }
    };
    paintPaper();
    const text = (
      value: string,
      x: number,
      y: number,
      size = 22,
      family = "DMSans",
      color: string = material.ink,
    ) => {
      c.fillStyle = color;
      c.textAlign = "left";
      c.textBaseline = "alphabetic";
      c.font = `${size}px ${family}`;
      c.fillText(value, x, y);
    };
    const label = (value: string, x: number, y: number) =>
      text(value.toUpperCase(), x, y, 16, "DMSans", "#526771");
    const rule = (y: number) => {
      c.strokeStyle = "#9dafa8";
      c.lineWidth = 0.8;
      c.beginPath();
      c.moveTo(28, y);
      c.lineTo(292, y);
      c.stroke();
    };
    if (page.kind === "identity") {
      label("Name", 28, 39);
      const name = fittedLines(c, payload.name, 44, 264, 3);
      name.lines.forEach((line, i) =>
        text(line, 28, 78 + i * name.size, name.size, "Newsreader"),
      );
      rule(183);
      label(payload.airportLabel, 28, 213);
      text(payload.homeAirport || "—", 26, 268, 50, "PlexMono");
      const home = fittedLines(c, payload.homeAirportName, 26, 264, 2);
      home.lines.forEach((line, i) =>
        text(line, 28, 302 + i * 27, home.size, "Newsreader"),
      );
      const country = fittedLines(
        c,
        payload.homeAirportCountry ?? "",
        21,
        264,
        1,
      );
      country.lines.forEach((line) =>
        text(line, 28, 354, country.size, "Newsreader", "#526771"),
      );
      rule(371);
      label("Since", 28, 397);
      label(
        payload.scopeYear ? `Countries · ${payload.scopeYear}` : "Countries",
        147,
        397,
      );
      text(payload.firstFlightDate.slice(0, 4) || "—", 28, 426, 28, "PlexMono");
      text(String(payload.countries), 147, 426, 28, "PlexMono");
    } else if (page.kind === "record") {
      const title = fittedLines(
        c,
        payload.scopeYear
          ? `${payload.scopeYear} travel register`
          : "Travel register",
        30,
        264,
        1,
      );
      text(title.lines[0], 28, 43, title.size, "Newsreader");
      rule(60);
      label("Flights", 28, 89);
      label("Miles flown", 142, 89);
      text(String(payload.flights), 28, 126, 32, "PlexMono");
      const miles = fittedLines(c, payload.miles.toLocaleString(), 32, 150, 1);
      text(miles.lines[0] ?? "0", 142, 126, miles.size, "Newsreader");
      rule(143);
      const entries = payload.register ?? [
        { label: "First recorded flight", value: payload.firstFlightDate },
        { label: "Countries recorded", value: String(payload.countries) },
      ];
      entries.slice(0, 5).forEach((entry, index) => {
        const y = 168 + index * 54;
        label(entry.label, 28, y);
        const value =
          entry.label === "First recorded flight"
            ? dateLabel(entry.value)
            : entry.value;
        const fitted = fittedLines(c, value, 23, 264, 1);
        text(fitted.lines[0] ?? "", 28, y + 27, fitted.size, "Newsreader");
        rule(y + 37);
      });
    } else {
      const drawStamps = (code?: string, progress = 1) => {
        // Repaint the inexpensive paper grain instead of retaining an extra
        // full-resolution backing canvas for every passport page.
        paintPaper();
        for (const stamp of page.stamps) {
          const image = stamps.get(stamp.code);
          if (!image) continue;
          const amount =
            stamp.code === code ? 1 - Math.pow(1 - progress, 3) : 1;
          c.save();
          c.translate(stamp.x, stamp.y);
          c.rotate(stamp.angle - (1 - amount) * 0.025);
          c.globalAlpha = 0.35 + amount * 0.65;
          const scale = 1 + (1 - amount) * 0.065;
          c.scale(scale, scale);
          c.drawImage(
            image,
            -stamp.width / 2,
            -stamp.height / 2,
            stamp.width,
            stamp.height,
          );
          c.restore();
        }
      };
      drawStamps();
      return { canvas, page, settleStamp: drawStamps };
    }
    return { canvas, page };
  });
}
