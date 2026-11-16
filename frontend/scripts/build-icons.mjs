// Rasterise app/icon.svg into the icons that can't be SVG:
//   app/favicon.ico    16 + 32 + 48 px (browsers without SVG favicon support)
//   app/apple-icon.png 180 px, full-bleed square (iOS rounds the corners itself)
// Next picks all three up from app/ as metadata files, so they survive the static export.
// Run from frontend/: node scripts/build-icons.mjs
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import sharp from "sharp";

const app = join(dirname(fileURLToPath(import.meta.url)), "..", "app");
const svg = readFileSync(join(app, "icon.svg"), "utf8");

const png = (src, size) =>
  sharp(Buffer.from(src), { density: (72 * size) / 32 }).resize(size, size).png().toBuffer();

// ICO with PNG-encoded entries (supported by every browser that still asks for .ico).
function ico(images) {
  const header = Buffer.alloc(6 + 16 * images.length);
  header.writeUInt16LE(0, 0);
  header.writeUInt16LE(1, 2);
  header.writeUInt16LE(images.length, 4);
  let offset = header.length;
  images.forEach(({ size, data }, i) => {
    const e = 6 + 16 * i;
    header.writeUInt8(size % 256, e);
    header.writeUInt8(size % 256, e + 1);
    header.writeUInt16LE(1, e + 4); // colour planes
    header.writeUInt16LE(32, e + 6); // bits per pixel
    header.writeUInt32LE(data.length, e + 8);
    header.writeUInt32LE(offset, e + 12);
    offset += data.length;
  });
  return Buffer.concat([header, ...images.map((i) => i.data)]);
}

const sizes = [16, 32, 48];
const entries = await Promise.all(sizes.map(async (size) => ({ size, data: await png(svg, size) })));
writeFileSync(join(app, "favicon.ico"), ico(entries));

const square = svg.replace(/<clipPath id="tile">.*?<\/clipPath>/, '<clipPath id="tile"><rect width="32" height="32"/></clipPath>');
if (square === svg) throw new Error("icon.svg: no <clipPath id=\"tile\"> to square off for apple-icon.png");
writeFileSync(join(app, "apple-icon.png"), await png(square, 180));

console.log("wrote app/favicon.ico (16/32/48) and app/apple-icon.png (180)");
