import { coverEmblem } from './passport-cover-art';
import { passportCoverLettering } from './passport-cover-lettering.generated';
import { PAGE_WIDTH, PAGE_HEIGHT, BOOK_MARGIN } from './passport-paper';

// CSS pixels inside the rigid board, before its common 3D transform. The board
// follows viewport width, but the approved logo and title have fixed CSS sizes.
// Both renderers consume this artwork, avoiding a second native font/layout.
export function passportCoverFaceMetrics(renderedWidth: number) {
  const ratio = renderedWidth / (PAGE_WIDTH * 2 + BOOK_MARGIN * 2);
  const width = (PAGE_WIDTH + 8) * ratio, height = (PAGE_HEIGHT + 8) * ratio;
  // Newsreader's 26px line box is 19px ascent + 7px descent. Retain the
  // original cover's 48px emblem, 24px gap and offset from the thicker spine.
  const groupTop = (height - 98) / 2, center = width / 2 + 2;
  return {
    width, height,
    emblem: { x: center - 65 / 2, y: groupTop, width: 65, height: 48 },
    title: { x: center - passportCoverLettering.advance / 2, y: groupTop + 91 },
  };
}

export function passportCoverFace(renderedWidth: number) {
  const { width: w, height: h, emblem, title } = passportCoverFaceMetrics(renderedWidth);
  const logo = coverEmblem
    .replace('<svg width="110" height="82"', `<svg id="cover-emblem" x="${emblem.x}" y="${emblem.y}" width="65" height="48"`)
    .replace('currentColor', '#d5e2e8');
  return `<svg xmlns="http://www.w3.org/2000/svg" width="100%" height="100%" viewBox="0 0 ${w} ${h}" fill="none" aria-hidden="true">
  <defs>
    <linearGradient id="cover-cloth" x1="0" y1="0" x2="1" y2="0"><stop stop-color="#17384d"/><stop offset=".07" stop-color="#294e65"/><stop offset="1" stop-color="#294e65"/></linearGradient>
    <pattern id="cover-weave" width="2" height="2" patternUnits="userSpaceOnUse"><rect width="2" height=".6" fill="#fff" fill-opacity=".027"/><rect y=".6" width="2" height="1.4" fill="#000" fill-opacity=".016"/><rect width=".6" height="2" fill="#fff" fill-opacity=".027"/></pattern>
    <clipPath id="cover-clip"><rect x=".5" y=".5" width="${w - 1}" height="${h - 1}" rx="5"/></clipPath>
  </defs>
  <g clip-path="url(#cover-clip)"><rect width="${w}" height="${h}" fill="url(#cover-cloth)"/><rect width="${w}" height="${h}" fill="url(#cover-weave)"/><rect width="5" height="${h}" fill="#17384d"/></g>
  <rect x=".5" y=".5" width="${w - 1}" height="${h - 1}" rx="5" stroke="#17384d"/>
  <rect x="10" y="10" width="${w - 20}" height="${h - 20}" stroke="#d5e2e8" stroke-opacity=".3"/>
  ${logo}
  <path transform="translate(${title.x} ${title.y + 1})" d="${passportCoverLettering.path}" fill="#071f32" fill-opacity=".53"/>
  <path id="cover-lettering" transform="translate(${title.x} ${title.y})" d="${passportCoverLettering.path}" fill="#d5e2e8"/>
  </svg>`;
}
