// The top bar collapses on scroll. Doing so shortens the page, which must never pull the scroll position back
// and flip it open again: a page barely taller than the window used to flicker between the two forever.
const assert = require("node:assert");
const { execFileSync } = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");
const { _electron: electron } = require("playwright-core");

const sandbox = fs.mkdtempSync(path.join(os.tmpdir(), "fm-scroll-"));
const home = path.join(sandbox, "home"), claude = path.join(sandbox, "claude"), project = path.join(sandbox, "demo");
for (const d of [home, claude, project]) fs.mkdirSync(d);
const env = { ...process.env, FORTHMARK_HOME: home, FORTHMARK_CLAUDE_DIR: claude, FORTHMARK_TEST: "1", FORTHMARK_LANG: "zh" };
const python = process.env.FORTHMARK_PYTHON || (process.platform === "win32" ? "python" : "python3");
const cli = (...args) => execFileSync(python, [path.join(__dirname, "..", "..", "tools", "forthmark.py"), ...args], { env, cwd: project });
const sleep = ms => new Promise(r => setTimeout(r, ms));

// Scrolls to y over and over, like a held wheel, and counts how often the bar flips.
const flips = (page, y) => page.evaluate(async y => {
  let n = 0;
  const root = document.documentElement;
  const seen = new MutationObserver(list => { n += list.length; });
  seen.observe(root, { attributes: true, attributeFilter: ["class"] });
  for (let i = 0; i < 30; i++) {
    scrollTo(0, y);
    await new Promise(r => requestAnimationFrame(() => setTimeout(r, 16)));
  }
  seen.disconnect();
  return n;
}, y);

(async () => {
  cli("add", project);
  const status = fs.readdirSync(path.join(home, "projects")).map(d => path.join(home, "projects", d, "status.json"))[0];
  const data = JSON.parse(fs.readFileSync(status, "utf8"));
  data.project.goal = "一个有描述的项目，描述会在滚动时收起";
  fs.writeFileSync(status, JSON.stringify(data));

  const app = await electron.launch({ args: [path.join(__dirname, "..")], env });
  try {
    let page;
    for (let i = 0; i < 300 && !page; i++) {
      page = app.windows().find(w => w.url().startsWith("http") && !w.url().includes("shell=popover"));
      if (!page) await sleep(100);
    }
    await page.waitForSelector(".topbar .goal");
    await page.setViewportSize({ width: 1320, height: 500 });
    await sleep(300);

    const measure = () => page.evaluate(() => {
      scrollTo(0, 0);
      const goal = document.querySelector(".topbar .goal");
      return { doc: document.documentElement.scrollHeight, view: innerHeight, goal: goal.offsetHeight };
    });
    const { doc, goal } = await measure();
    await page.setViewportSize({ width: 1320, height: doc - goal - 14 });  // room to scroll, but barely more than the goal
    await sleep(300);
    const tight = await flips(page, 40);
    assert.ok(tight <= 1, `barely scrollable page: the bar flipped ${tight} times`);
    console.log(`ok - a page barely taller than the window doesn't flicker (${tight} flips)`);

    await page.evaluate(() => scrollTo(0, 0));
    await sleep(100);
    await page.setViewportSize({ width: 1320, height: 400 });
    await sleep(300);
    const roomy = await flips(page, 200);
    assert.ok(roomy <= 1, `long page: the bar flipped ${roomy} times`);
    assert.ok(await page.evaluate(() => document.documentElement.classList.contains("scrolled")), "a long page should collapse");
    await page.evaluate(() => scrollTo(0, 0));
    await sleep(150);
    assert.ok(!(await page.evaluate(() => document.documentElement.classList.contains("scrolled"))), "back at the top it should open");
    console.log("ok - a long page collapses once and opens again at the top");
    await app.evaluate(({ app }) => app.quit());
  } finally {
    await app.close().catch(() => {});
    fs.rmSync(sandbox, { recursive: true, force: true, maxRetries: 5, retryDelay: 300 });
  }
  console.log("all passed");
})().catch(e => { console.error(e.message || e); process.exit(1); });
