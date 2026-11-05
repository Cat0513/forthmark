// A real update: the installed app finds a newer version on a local feed, downloads and installs it.
//   node test/update.js <path to Forthmark.exe> <folder with the newer build> <its version>
const assert = require("node:assert");
const { spawn } = require("child_process");
const fs = require("fs");
const http = require("http");
const os = require("os");
const path = require("path");

const [exe, feedDir, version] = process.argv.slice(2);
const sandbox = fs.mkdtempSync(path.join(os.tmpdir(), "fm-update-"));
const home = path.join(sandbox, "数据 目录"), claude = path.join(sandbox, "claude"), project = path.join(sandbox, "项目");
const report = path.join(sandbox, "report.json");
for (const d of [home, claude, project]) fs.mkdirSync(d);
fs.writeFileSync(path.join(home, "keep.txt"), "status data");
fs.writeFileSync(path.join(project, "work.txt"), "the user's work");
const sleep = ms => new Promise(r => setTimeout(r, ms));
async function until(what, check, ms) {
  for (const end = Date.now() + ms; Date.now() < end; await sleep(500)) if (await check()) return;
  const log = path.join(home, "desktop.log");
  throw new Error(`timed out: ${what}\ndesktop.log: ${fs.existsSync(log) ? fs.readFileSync(log, "utf8").slice(-1500) : "none"}`);
}

const server = http.createServer((req, res) => {
  const file = path.join(feedDir, path.basename(decodeURIComponent(req.url.split("?")[0])));
  if (!fs.existsSync(file)) { res.writeHead(404); return res.end(); }
  res.writeHead(200, { "Content-Length": fs.statSync(file).size });
  fs.createReadStream(file).pipe(res);
});

server.listen(0, "127.0.0.1", async () => {
  try {
    const env = { ...process.env, FORTHMARK_HOME: home, FORTHMARK_CLAUDE_DIR: claude, FORTHMARK_TEST_REPORT: report,
      FORTHMARK_TEST_UPDATE_FEED: `http://127.0.0.1:${server.address().port}/`, FORTHMARK_TEST_UPDATE_TO: version };
    spawn(exe, [], { env, stdio: "ignore", detached: true }).unref();
    const reported = () => (fs.existsSync(report) ? JSON.parse(fs.readFileSync(report, "utf8")) : {});
    await until(`the app to update itself to ${version}`, () => { try { return reported().version === version; } catch { return false; } }, 300000);
    console.log(`ok - the app updated itself to ${version} and started again`);

    const mark = JSON.parse(fs.readFileSync(path.join(home, "desktop-setup.json"), "utf8"));
    assert.strictEqual(mark.version, version);
    const settings = JSON.parse(fs.readFileSync(path.join(claude, "settings.json"), "utf8"));
    assert.ok(settings.hooks?.SessionStart, "the hooks should still be there");
    assert.strictEqual(fs.readFileSync(path.join(home, "keep.txt"), "utf8"), "status data");
    assert.deepStrictEqual(fs.readdirSync(project), ["work.txt"]);
    assert.strictEqual(fs.readFileSync(path.join(project, "work.txt"), "utf8"), "the user's work");
    console.log("ok - hooks, status data and project files came through untouched");

    spawn(exe, ["--quit"], { env, stdio: "ignore" });
    await sleep(3000);
    console.log("all passed");
    server.close();
    process.exit(0);
  } catch (e) {
    console.error(e.message || e);
    process.exit(1);
  }
});
