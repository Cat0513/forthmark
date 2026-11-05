// Runs the installed app as a user would, with nothing attached, against a sandbox.
//   node test/smoke.js <path to Forthmark.exe>
const assert = require("node:assert");
const { execFileSync, spawn } = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");

const exe = process.argv[2], resources = path.join(path.dirname(exe), "resources");
const sandbox = fs.mkdtempSync(path.join(os.tmpdir(), "fm-smoke-"));
const home = path.join(sandbox, "数据 目录"), claude = path.join(sandbox, "claude"), project = path.join(sandbox, "项目 demo");
const report = path.join(sandbox, "report.json");
for (const d of [home, claude, project]) fs.mkdirSync(d);
const env = { ...process.env, FORTHMARK_HOME: home, FORTHMARK_CLAUDE_DIR: claude, FORTHMARK_TEST_REPORT: report };
const step = name => console.log(`ok - ${name}`);
const sleep = ms => new Promise(r => setTimeout(r, ms));
async function until(what, check, ms = 60000) {
  for (const end = Date.now() + ms; Date.now() < end; await sleep(300)) if (await check()) return;
  const tail = name => (fs.existsSync(path.join(home, name)) ? fs.readFileSync(path.join(home, name), "utf8").slice(-1200) : "none");
  throw new Error(`timed out: ${what}\ndesktop.log: ${tail("desktop.log")}\nserver.log: ${tail("server.log")}`);
}

(async () => {
  // A service left over from a command line install: the app must replace it, not talk to it.
  const leftover = path.resolve(__dirname, "..", "..", "tools", "forthmark.py");
  execFileSync("python", [leftover, "open", "--no-browser"], { env });
  const old = JSON.parse(fs.readFileSync(path.join(home, "server.json"), "utf8"));
  assert.ok(!(await (await fetch(`http://127.0.0.1:${old.port}/api/ping`)).json()).kit.toLowerCase().includes("programs"));
  step("started from a leftover command line service");

  const app = spawn(exe, [], { env, stdio: "ignore" });
  let exited = false;
  app.on("exit", () => { exited = true; });
  await until("the app's self check", () => fs.existsSync(report));
  const self = JSON.parse(fs.readFileSync(report, "utf8"));
  assert.ok(self.url.includes("shell=popover"), self.url);
  assert.strictEqual(self.bridge, true);
  step("packaged app starts and its popover renders with the bridge");

  const settings = JSON.parse(fs.readFileSync(path.join(claude, "settings.json"), "utf8"));
  const hook = settings.hooks.SessionStart[0].hooks[0];
  assert.ok(hook.command.includes(path.join("resources", "python")), hook.command);
  step("hooks point at the bundled python");

  const cli = path.join(resources, "kit", "tools", "forthmark.py");
  execFileSync(hook.command, [cli, "add", project], { env });
  const out = execFileSync(hook.command, hook.args, { env, cwd: project,
    input: JSON.stringify({ cwd: project, source: "startup", hook_event_name: "SessionStart" }) }).toString();
  assert.ok(out.includes("Forthmark"), out.slice(0, 300));
  step("bundled python runs the CLI and a hook, in a project with a Chinese name");

  const info = JSON.parse(fs.readFileSync(path.join(home, "server.json"), "utf8"));
  const ping = await (await fetch(`http://127.0.0.1:${info.port}/api/ping`)).json();
  assert.strictEqual(ping.kit.toLowerCase(), path.join(resources, "kit").toLowerCase());
  const page = await fetch(`http://127.0.0.1:${info.port}/`);
  assert.strictEqual(page.status, 200);
  step("the service runs from the app's kit and serves the panel");

  spawn(exe, ["--quit"], { env, stdio: "ignore" });
  await until("the app quits", () => exited, 20000);
  await until("the service stops with it", () => fetch(`http://127.0.0.1:${info.port}/api/ping`, { signal: AbortSignal.timeout(500) }).then(() => false, () => true), 15000);
  step("quitting stops the app and its service");
  fs.rmSync(sandbox, { recursive: true, force: true, maxRetries: 5, retryDelay: 300 });
  console.log("all passed");
})().catch(e => { console.error(e); process.exit(1); });
