// Drives the app's windows from this folder against a sandbox (never the real ~/.forthmark or ~/.claude).
// test/smoke.js covers the installed app.
const assert = require("node:assert");
const fs = require("fs");
const os = require("os");
const path = require("path");
const { _electron: electron } = require("playwright-core");

const sandbox = fs.mkdtempSync(path.join(os.tmpdir(), "fm-e2e-"));
const home = path.join(sandbox, "home"), claude = path.join(sandbox, "claude");
fs.mkdirSync(home); fs.mkdirSync(claude);
const env = { ...process.env, FORTHMARK_HOME: home, FORTHMARK_CLAUDE_DIR: claude, FORTHMARK_TEST: "1" };

const sleep = ms => new Promise(r => setTimeout(r, ms));
async function until(what, check, ms = 30000) {
  const end = Date.now() + ms;
  for (;;) {
    const got = await check().catch(e => (Date.now() > end ? Promise.reject(e) : null));
    if (got) return got;
    if (Date.now() > end) throw new Error(`timed out: ${what}`);
    await sleep(200);
  }
}
const step = name => console.log(`ok - ${name}`);

(async () => {
  const app = await electron.launch({ args: [path.join(__dirname, "..")], env });
  try {
    await until("app ready", () => app.evaluate(() => Boolean(globalThis.forthmarkTest?.ready)), 60000);
    const settings = JSON.parse(fs.readFileSync(path.join(claude, "settings.json"), "utf8"));
    assert.ok(settings.hooks.SessionStart && settings.hooks.Stop && settings.hooks.UserPromptSubmit);
    const info = JSON.parse(fs.readFileSync(path.join(home, "server.json"), "utf8"));
    step("first launch connected Claude Code and started the service");

    const pop = await until("popover loaded", async () => app.windows().find(w => w.url().includes("shell=popover")));
    await pop.waitForSelector("#app", { state: "attached" });
    const bridge = await pop.evaluate(() => Boolean(window.webkit?.messageHandlers?.forthmark) && document.documentElement.classList.contains("glass"));
    assert.ok(bridge);
    assert.ok(await pop.evaluate(async () => (await fetch("/api/ping")).ok));
    step("popover renders the panel with the native bridge");

    await pop.click("[data-settings]");
    await pop.waitForSelector(".modal.settings select[name=terminal]");
    await pop.selectOption("select[name=agent]", "codex");
    await pop.click('.modal [type="submit"]');
    await until("settings saved", async () => JSON.parse(fs.readFileSync(path.join(home, "config.json"), "utf8")).agent === "codex");
    await pop.waitForSelector(".modal.settings", { state: "detached" });
    await pop.click("[data-settings]");
    await until("the window shows what was saved", () => pop.evaluate(() => document.querySelector("select[name=agent]")?.value === "codex"), 5000);
    await pop.click(".modal [data-close]");
    await pop.click("#adoptproj");
    await pop.waitForSelector("#pickdir");
    await pop.click(".modal [data-close]");
    await pop.click("#newproj");
    await pop.click("#toadopt");
    await pop.click(".modal [data-close]");
    step("with no projects, the panel offers new project and existing folder");

    const visible = () => app.evaluate(() => globalThis.forthmarkTest.popover().isVisible());
    await app.evaluate(() => globalThis.forthmarkTest.panelWindow()?.hide());
    await app.evaluate(() => globalThis.forthmarkTest.showPopover());
    await until("popover visible", visible);
    await app.evaluate(() => globalThis.forthmarkTest.popover().emit("blur"));
    assert.strictEqual(await visible(), false);
    await app.evaluate(() => globalThis.forthmarkTest.togglePopover());  // the same click that blurred it
    assert.strictEqual(await visible(), false);
    step("blur hides the popover and the icon click doesn't reopen it");

    await sleep(350);
    await app.evaluate(() => globalThis.forthmarkTest.showPopover());
    await until("popover visible again", visible);
    const h = 400;
    await pop.evaluate(height => window.webkit.messageHandlers.forthmark.postMessage({ action: "resize", height }), h);
    await until("popover resized", () => app.evaluate(({ }, want) => globalThis.forthmarkTest.popover().getBounds().height === want, h));
    step("the page can resize the popover");

    const title = await until("panel window", () => app.evaluate(() => {
      const w = globalThis.forthmarkTest.panelWindow();
      return w && !w.isDestroyed() && w.getTitle();
    }));
    assert.strictEqual(title, "Forthmark");
    assert.ok(await pop.evaluate(() => typeof window.confirm === "function" && String(window.alert).length > 0));
    step("panel window exists");

    await app.evaluate(() => globalThis.forthmarkTest.post("Forthmark", "e2e"));
    step("notification posted without error");

    await app.evaluate(({ app }) => {
      app.setLoginItemSettings({ openAtLogin: true, args: ["--hidden"] });
    });
    const login = await app.evaluate(({ app }) => {
      const on = app.getLoginItemSettings({ args: ["--hidden"] }).openAtLogin;
      app.setLoginItemSettings({ openAtLogin: false, args: ["--hidden"] });
      return on;
    });
    if (process.platform === "win32") assert.strictEqual(login, true);
    step("launch at login can be switched on and off");

    await app.evaluate(({ app }) => app.quit());
    await until("service stopped with the app", async () => {
      try { await fetch(`http://127.0.0.1:${info.port}/api/ping`, { signal: AbortSignal.timeout(500) }); return false; } catch { return true; }
    }, 15000);
    step("quitting stops the service this app started");
  } finally {
    await app.close().catch(() => {});
    fs.rmSync(sandbox, { recursive: true, force: true, maxRetries: 5, retryDelay: 300 });
  }
  console.log("all passed");
})().catch(e => { console.error(e); process.exit(1); });
