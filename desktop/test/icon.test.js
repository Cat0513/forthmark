const assert = require("node:assert");
const test = require("node:test");
const { paint } = require("../trayicon-paint");

const pixel = (buf, size, x, y) => [...buf.subarray((y * size + x) * 4, (y * size + x) * 4 + 4)];

test("every scale has the right size and draws the mark in the taskbar's contrast color", () => {
  for (const size of [16, 20, 24, 32, 48]) {
    const buf = paint(size, 0, true);
    assert.strictEqual(buf.length, size * size * 4);
    const y = Math.round(size * 0.2), x = Math.round(size * 0.5);  // inside the top bar of the mark
    assert.deepStrictEqual(pixel(buf, size, x, y), [255, 255, 255, 255]);
    assert.deepStrictEqual(pixel(paint(size, 0, false), size, x, y), [17, 17, 17, 255]);
  }
});

test("no color channel exceeds alpha (premultiplied), so transparent stays transparent", () => {
  for (const dark of [true, false]) {
    const buf = paint(32, 3, dark);
    for (let i = 0; i < buf.length; i += 4) assert.ok(Math.max(buf[i], buf[i + 1], buf[i + 2]) <= buf[i + 3], `pixel ${i / 4}`);
  }
});

test("a count adds a red badge with a white digit; no count, no red", () => {
  const isRed = ([b, g, r, a]) => a > 200 && r > 200 && g < 100 && b < 100;
  const count = buf => { let n = 0; for (let i = 0; i < buf.length; i += 4) if (isRed(buf.subarray(i, i + 4))) n++; return n; };
  for (const size of [16, 32]) {
    assert.strictEqual(count(paint(size, 0, true)), 0);
    for (const b of [1, 9, 12, "!"]) assert.ok(count(paint(size, b, true)) > 0, `${size} ${b}`);
    assert.notDeepStrictEqual(paint(size, 1, true), paint(size, 8, true));
  }
});
