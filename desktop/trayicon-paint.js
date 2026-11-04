// Pixels only, no Electron: returns a premultiplied BGRA buffer of size x size.
const MARK = [
  [[0, 0], [20, 0], [20, 32], [0, 32]],
  [[0, 44], [20, 44], [20, 76], [0, 76]],
  [[0, 88], [12, 88], [20, 96], [12, 104], [0, 104]],
  [[32, 0], [112, 0], [128, 16], [112, 32], [32, 32]],
  [[32, 44], [88, 44], [104, 60], [88, 76], [32, 76]],
];
const DIGITS = {  // 3 x 5
  0: "111101101101111", 1: "010110010010111", 2: "111001111100111", 3: "111001111001111", 4: "101101111001001",
  5: "111100111001111", 6: "111100111101111", 7: "111001010010010", 8: "111101111101111", 9: "111101111001111",
  "+": "000010111010000", "!": "010010010000010",
};
const SAMPLES = 4;
const RED = [229, 57, 53];

function insideConvex(poly, x, y) {
  for (let i = 0; i < poly.length; i++) {
    const [ax, ay] = poly[i], [bx, by] = poly[(i + 1) % poly.length];
    if ((bx - ax) * (y - ay) - (by - ay) * (x - ax) < 0) return false;
  }
  return true;
}

function paint(size, badge, darkTaskbar) {
  const scale = size / 128, top = (size - 104 * scale) / 2;
  const mark = darkTaskbar ? [255, 255, 255] : [17, 17, 17];
  const label = badge === "!" ? "!" : badge > 9 ? "+" : badge > 0 ? String(badge) : "";
  const unit = Math.max(1, Math.floor(size / 16));  // one font pixel
  const radius = label ? Math.max(4.5, unit * 3.75) : 0;
  const cx = size - radius, cy = size - radius;
  const fontX = Math.round(cx - 1.5 * unit), fontY = Math.round(cy - 2.5 * unit);
  const buf = Buffer.alloc(size * size * 4);

  for (let py = 0; py < size; py++) {
    for (let px = 0; px < size; px++) {
      let markHits = 0, dotHits = 0, ringHits = 0;
      for (let sy = 0; sy < SAMPLES; sy++) {
        for (let sx = 0; sx < SAMPLES; sx++) {
          const x = px + (sx + 0.5) / SAMPLES, y = py + (sy + 0.5) / SAMPLES;
          const d = Math.hypot(x - cx, y - cy);
          if (radius && d <= radius) dotHits++;
          else if (radius && d <= radius + 1) ringHits++;  // a clear ring separates the badge from the mark
          else if (MARK.some(poly => insideConvex(poly, x / scale, (y - top) / scale))) markHits++;
        }
      }
      const total = SAMPLES * SAMPLES;
      const col = Math.floor((px - fontX) / unit), row = Math.floor((py - fontY) / unit);
      const inFont = label && px >= fontX && py >= fontY && col < 3 && row < 5 && DIGITS[label][row * 3 + col] === "1";
      const rgb = inFont ? [255, 255, 255] : dotHits ? RED : mark;
      const alpha = inFont ? 1 : (dotHits + markHits) / total;
      const at = (py * size + px) * 4;
      // Premultiplied, as the bitmap API expects: otherwise a transparent pixel shows its color.
      buf[at] = Math.round(rgb[2] * alpha); buf[at + 1] = Math.round(rgb[1] * alpha); buf[at + 2] = Math.round(rgb[0] * alpha);
      buf[at + 3] = Math.round(alpha * 255);
    }
  }
  return buf;
}

module.exports = { paint };
