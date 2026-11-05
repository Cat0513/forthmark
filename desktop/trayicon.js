// The Forthmark mark (assets/logo.svg, a 128 x 104 grid) drawn in code, so the tray gets a crisp icon at
// every Windows display scale, follows the taskbar's color, and can carry the count.
const { nativeImage } = require("electron");
const { paint } = require("./trayicon-paint");

const SCALES = [[1, 16], [1.25, 20], [1.5, 24], [2, 32], [3, 48]];

function trayImage(badge, darkTaskbar) {
  const image = nativeImage.createEmpty();
  for (const [scaleFactor, size] of SCALES) {
    image.addRepresentation({ scaleFactor, width: size, height: size, buffer: paint(size, badge, darkTaskbar) });
  }
  return image;
}

module.exports = { trayImage };
