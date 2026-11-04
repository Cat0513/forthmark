// Puts the pinned Windows embeddable Python into python-runtime/, which the installer bundles.
const { execFileSync } = require("child_process");
const crypto = require("crypto");
const fs = require("fs");
const path = require("path");

const VERSION = "3.14.7";
const SHA256 = "d297e5ff019966817ad8502465176139f2d3d840fa4ed84b13bed399a6ab1f15";
const URL = `https://www.python.org/ftp/python/${VERSION}/python-${VERSION}-embed-amd64.zip`;
const OUT = path.join(__dirname, "..", "python-runtime");

(async () => {
  const res = await fetch(URL);
  if (!res.ok) throw new Error(`${URL}: HTTP ${res.status}`);
  const zip = Buffer.from(await res.arrayBuffer());
  const got = crypto.createHash("sha256").update(zip).digest("hex");
  if (got !== SHA256) throw new Error(`checksum mismatch: ${got}`);

  fs.rmSync(OUT, { recursive: true, force: true });
  fs.mkdirSync(OUT, { recursive: true });
  const file = path.join(OUT, "python.zip");
  fs.writeFileSync(file, zip);
  execFileSync("powershell", ["-NoProfile", "-Command", `Expand-Archive -LiteralPath '${file}' -DestinationPath '${OUT}'`], { stdio: "inherit" });
  fs.rmSync(file);

  // The ._pth file runs python isolated: no PYTHONPATH, no registry, and no script directory on sys.path,
  // so name the kit's tools directory here (forthmark.py imports fmshared from beside it).
  const pth = path.join(OUT, "python314._pth");
  fs.appendFileSync(pth, "\r\n..\\kit\\tools\r\n");
  console.log(`python ${VERSION} ready in ${OUT}`);
})().catch(e => { console.error(e); process.exit(1); });
