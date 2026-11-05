// Uninstalling the app takes it out of Claude Code and keeps the status data.
//   node test/uninstall.js <path to Forthmark.exe>
const assert = require("node:assert");
const { execFileSync } = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");

const exe = process.argv[2], dir = path.dirname(exe);
const sandbox = fs.mkdtempSync(path.join(os.tmpdir(), "fm-un-"));
const home = path.join(sandbox, "home"), claude = path.join(sandbox, "claude");
fs.mkdirSync(home); fs.mkdirSync(claude);
fs.writeFileSync(path.join(home, "keep.txt"), "status data");
const settings = path.join(claude, "settings.json");
fs.writeFileSync(settings, JSON.stringify({ model: "mine" }));
const env = { ...process.env, FORTHMARK_HOME: home, FORTHMARK_CLAUDE_DIR: claude };

execFileSync(path.join(dir, "resources", "python", "python.exe"), [path.join(dir, "resources", "kit", "tools", "forthmark.py"), "setup"], { env });
assert.ok(JSON.parse(fs.readFileSync(settings, "utf8")).hooks);

execFileSync(path.join(dir, "Uninstall Forthmark.exe"), ["/S"], { env });
(async () => {
  for (let i = 0; i < 120 && fs.existsSync(exe); i++) await new Promise(r => setTimeout(r, 500));
  assert.ok(!fs.existsSync(exe), "the app is still there");
  const after = JSON.parse(fs.readFileSync(settings, "utf8"));
  assert.strictEqual(after.hooks, undefined);
  assert.strictEqual(after.model, "mine");
  assert.ok(fs.existsSync(path.join(home, "keep.txt")));
  console.log("ok - uninstall removed the app and the hooks, kept the user's settings and data");
})().catch(e => { console.error(e); process.exit(1); });
