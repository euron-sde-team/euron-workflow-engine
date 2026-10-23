// Assemble the tour frames (e2e/.capture/frames, named NNN-<holdMs>.png) into
// docs/assets/tour.gif with a shared palette per frame. Pure JavaScript: no ffmpeg needed.
import { readdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import gifenc from "gifenc";
import { PNG } from "pngjs";

const { GIFEncoder, quantize, applyPalette } = gifenc;
const here = path.dirname(fileURLToPath(import.meta.url));
const frames = path.join(here, "../.capture/frames");
const out = path.join(here, "../../docs/assets/tour.gif");

const files = readdirSync(frames)
  .filter((f) => f.endsWith(".png"))
  .sort();
if (!files.length) throw new Error(`no frames in ${frames}; run the capture project first`);

const gif = GIFEncoder();
for (const file of files) {
  const png = PNG.sync.read(readFileSync(path.join(frames, file)));
  const hold = Number(file.split("-")[1]?.replace(".png", "")) || 1500;
  const palette = quantize(png.data, 256, { format: "rgb444" });
  const indexed = applyPalette(png.data, palette, "rgb444");
  gif.writeFrame(indexed, png.width, png.height, { palette, delay: hold });
}
gif.finish();
writeFileSync(out, gif.bytes());
console.log(
  `wrote ${out} (${files.length} frames, ${(gif.bytes().length / 1024 / 1024).toFixed(1)} MB)`,
);
