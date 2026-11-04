// Forthmark desktop shell: tray, popover and panel windows around the local service.
//
// The counterpart of app/Forthmark.swift. All product logic stays in tools/forthmark.py and the
// panel page; this file only hosts them. The page talks to us through the same bridge as on macOS
// (window.webkit.messageHandlers.forthmark, see preload.js).

const { app, BrowserWindow, Menu, Notification, Tray, dialog, ipcMain, nativeTheme, screen, session, shell } = require("electron");
const { execFile, execFileSync } = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");
const { trayImage } = require("./trayicon");

const APP_ID = "app.forthmark.desktop";
const IS_WINDOWS = process.platform === "win32";
const KIT = app.isPackaged ? path.join(process.resourcesPath, "kit") : path.join(__dirname, "..");
const PYTHON = app.isPackaged ? path.join(process.resourcesPath, "python", IS_WINDOWS ? "python.exe" : "bin/python3")
  : process.env.FORTHMARK_PYTHON || (IS_WINDOWS ? "python" : "python3");
const CLI = path.join(KIT, "tools", "forthmark.py");
const STARTED_HIDDEN = process.argv.includes("--hidden");  // launched at login: stay in the tray

// The data directory, the same rule as forthmark.py: $FORTHMARK_HOME, else ~/.forthmark.
const HOME = process.env.FORTHMARK_HOME ? path.resolve(process.env.FORTHMARK_HOME.replace(/^~/, os.homedir()))
  : path.join(os.homedir(), ".forthmark");
const SETUP_MARK = path.join(HOME, "desktop-setup.json");

function logFailure(e) {
  console.error(e);
  try {
    fs.mkdirSync(HOME, { recursive: true });
    fs.appendFileSync(path.join(HOME, "desktop.log"), `${new Date().toISOString()} ${e?.stack || e}\n`);
  } catch {}
}

let tray, popover, panelWindow;
let serviceStartedHere = false;
let starting = null;
let modalOpen = false, ignoreBlurUntil = 0, popoverHiddenAt = 0;
let badgeCount = 0, badgeBroken = false;
const notifications = new Set();  // a collected Notification no longer reports its click

function readJson(file) {
  try { return JSON.parse(fs.readFileSync(file, "utf8")); } catch { return null; }
}

// Interface language, the same rule as forthmark.py: config.json "lang", else the system language.
function isEnglish() {
  const lang = readJson(path.join(HOME, "config.json"))?.lang;
  if (lang === "zh" || lang === "en") return lang === "en";
  return !app.getLocale().toLowerCase().startsWith("zh");
}
const L = (zh, en) => (isEnglish() ? en : zh);

function runCli(...args) {
  return new Promise((resolve, reject) => {
    execFile(PYTHON, [CLI, ...args], { windowsHide: true, timeout: 60000 }, (err, stdout, stderr) =>
      err ? reject(new Error(String(stderr || err.message).trim())) : resolve(stdout));
  });
}

// ---------------------------------------------------------------- setup and local service

// Connect to Claude Code on first launch and after each update (hooks name this app's python and kit).
// A development run only does it against a sandbox, never the real ~/.claude.
async function ensureSetup() {
  if (!app.isPackaged && !process.env.FORTHMARK_CLAUDE_DIR) return;
  const wanted = { version: app.getVersion(), python: PYTHON, kit: KIT };
  if (JSON.stringify(readJson(SETUP_MARK)) === JSON.stringify(wanted)) return;
  await runCli("setup");
  fs.writeFileSync(SETUP_MARK, JSON.stringify(wanted));
}

function serverInfo() {
  const info = readJson(path.join(HOME, "server.json"));
  return info?.port && info?.token ? info : null;
}

async function ping() {
  const s = serverInfo();
  if (!s) return null;
  try {
    const r = await fetch(`http://127.0.0.1:${s.port}/api/ping`, { signal: AbortSignal.timeout(1000) });
    const obj = await r.json();
    return obj.home === HOME ? obj : null;  // another data dir's service doesn't count
  } catch { return null; }
}

const samePath = (a, b) => path.resolve(a || "").toLowerCase() === path.resolve(b || "").toLowerCase();

function ensureServer() {
  starting ??= (async () => {
    const alive = await ping();
    if (alive && samePath(alive.kit, KIT)) return;
    if (alive) await runCli("stop");  // left over from another copy of the kit, e.g. install.ps1 before this app
    await runCli("open", "--no-browser");  // the CLI starts it detached, with a hidden console for its git calls
    serviceStartedHere = true;
  })().finally(() => { starting = null; });
  return starting;
}

async function api(route) {
  const s = serverInfo();
  if (!s) return null;
  try {
    const r = await fetch(`http://127.0.0.1:${s.port}${route}`,
      { headers: { "X-Forthmark-Token": s.token }, signal: AbortSignal.timeout(10000) });
    return r.ok ? await r.json() : null;
  } catch { return null; }
}

const panelURL = (fragment = "") => {
  const s = serverInfo();
  return s ? `http://127.0.0.1:${s.port}/${fragment && "#" + fragment}` : null;
};

// ---------------------------------------------------------------- tray

const paintTray = () => tray.setImage(trayImage(badgeBroken ? "!" : badgeCount, nativeTheme.shouldUseDarkColorsForSystemIntegratedUI));

function setBadge(count, broken, tip) {
  badgeCount = count;
  badgeBroken = broken;
  paintTray();
  tray.setToolTip(tip.slice(0, 120));  // Windows cuts tray tooltips at 127 characters
}

async function refreshBadge() {
  const b = await api("/api/badge");
  if (b) return setBadge(b.count, false, `Forthmark\n${b.tooltip}`);
  if (await ping()) {
    return setBadge(0, true, L("本地服务需要重启：退出 Forthmark 后重新打开", "The local service needs a restart: quit Forthmark and open it again"));
  }
  try { await ensureServer(); await refreshBadge(); } catch (e) { serviceFailed(e); }
}

function serviceFailed(e) {
  logFailure(e);
  setBadge(0, true, L(`本地服务没有启动，见 ${HOME}\\server.log`, `The local service didn't start, see ${HOME}\\server.log`));
}

function buildMenu() {
  return Menu.buildFromTemplate([
    { label: L("打开面板窗口", "Open Panel Window"), click: () => openPanelWindow() },
    { label: L("在浏览器打开", "Open in Browser"), click: () => withServer(() => shell.openExternal(panelURL())) },
    { label: L("刷新", "Refresh"), click: () => { refreshBadge(); popover.webContents.reload(); } },
    { type: "separator" },
    { label: L("开机自启", "Launch at Login"), type: "checkbox", checked: app.getLoginItemSettings().openAtLogin,
      click: item => app.setLoginItemSettings({ openAtLogin: item.checked, args: ["--hidden"] }) },
    { label: L("发送测试通知", "Send Test Notification"), click: testNotification },
    { type: "separator" },
    { label: L("退出 Forthmark", "Quit Forthmark"), click: () => app.quit() },
  ]);
}

function withServer(then) {
  return ensureServer().then(then).catch(serviceFailed);
}

// ---------------------------------------------------------------- windows

function secureWindow(win) {
  const wc = win.webContents;
  // Web links only: a previewed doc must not be able to open local files, apps or custom URL schemes.
  const external = url => { if (/^(https?|mailto):/i.test(url)) shell.openExternal(url); };
  wc.setWindowOpenHandler(({ url }) => { external(url); return { action: "deny" }; });
  wc.on("will-navigate", (e, url) => {
    if (!url.startsWith(panelURL() || "\0")) { e.preventDefault(); external(url); }
  });
}

function makeWindow(options) {
  const win = new BrowserWindow({
    show: false,
    autoHideMenuBar: true,
    icon: app.isPackaged ? undefined : path.join(__dirname, "build", "icon.png"),
    webPreferences: { preload: path.join(__dirname, "preload.js"), contextIsolation: true, sandbox: true, nodeIntegration: false },
    ...options,
  });
  secureWindow(win);
  win.on("page-title-updated", e => e.preventDefault());
  return win;
}

// Under the page's translucent "glass" colors. Opaque: Windows has no popover material to show through.
const popoverColor = () => (nativeTheme.shouldUseDarkColors ? "#1b1f27" : "#eef0f3");

function createPopover() {
  popover = makeWindow({
    width: 460, height: 760, frame: false, resizable: false, movable: false, minimizable: false, maximizable: false,
    fullscreenable: false, skipTaskbar: true, backgroundColor: popoverColor(),
  });
  popover.on("blur", () => {
    if (modalOpen || Date.now() < ignoreBlurUntil) return;
    popover.hide();
    popoverHiddenAt = Date.now();
  });
  popover.on("close", e => { if (!app.isQuitting) { e.preventDefault(); popover.hide(); } });
}

function loadPopover() {
  const url = panelURL("shell=popover");
  if (url && !popover.webContents.getURL().startsWith(panelURL())) popover.loadURL(url);
}

// Next to the tray icon, wherever the taskbar is, inside the screen.
function placePopover(height) {
  const icon = tray.getBounds();
  const center = { x: icon.x + icon.width / 2, y: icon.y + icon.height / 2 };
  const area = screen.getDisplayNearestPoint({ x: Math.round(center.x), y: Math.round(center.y) }).workArea;
  const gap = 8, width = 460;
  const h = Math.round(Math.min(Math.max(height, 260), area.height * 0.85));
  const x = Math.min(Math.max(center.x - width / 2, area.x + gap), area.x + area.width - width - gap);
  const atTop = center.y < area.y + area.height / 2;
  const y = atTop ? area.y + gap : area.y + area.height - h - gap;
  popover.setBounds({ x: Math.round(x), y: Math.round(y), width, height: h });
}

function showPopover() {
  return withServer(() => {
    loadPopover();
    placePopover(popover.getBounds().height);
    popover.show();
    popover.focus();
  });
}

function togglePopover() {
  if (popover.isVisible()) { popover.hide(); popoverHiddenAt = Date.now(); return; }
  // Clicking the icon blurs the popover first; without this the same click would reopen it.
  if (Date.now() - popoverHiddenAt < 300) return;
  return showPopover();
}

function openWindow(url, title, width, height) {
  const win = makeWindow({ title, width, height, backgroundColor: nativeTheme.shouldUseDarkColors ? "#0b0f16" : "#f6f7f9" });
  win.loadURL(url);
  win.once("ready-to-show", () => win.show());
  return win;
}

function openPanelWindow(newProject = false) {
  return withServer(() => {
    popover.hide();
    const url = panelURL(newProject ? "newproj=1" : "");
    if (panelWindow && !panelWindow.isDestroyed()) {
      if (newProject) panelWindow.loadURL(url);
      if (panelWindow.isMinimized()) panelWindow.restore();
      panelWindow.show();
      panelWindow.focus();
      return;
    }
    panelWindow = openWindow(url, "Forthmark", 1320, 900);
  });
}

function openDocWindow(project, doc) {
  popover.hide();
  const url = panelURL(`p=${encodeURIComponent(project)}&doc=${encodeURIComponent(doc)}&view=doc`);
  if (url) openWindow(url, path.basename(doc), 900, 860);
}

// ---------------------------------------------------------------- the page's bridge

ipcMain.on("native", (e, message) => {
  if (message?.action === "openPanel") return void openPanelWindow(Boolean(message.newProject));
  if (message?.action === "openDoc") return void openDocWindow(String(message.project), String(message.path));
  if (message?.action === "resize" && e.sender === popover.webContents && Number.isFinite(message.height)) {
    placePopover(message.height);
  }
});

// Native dialogs take the focus: keep the popover open while one is up.
function modal(e, options) {
  const win = BrowserWindow.fromWebContents(e.sender);
  modalOpen = true;
  try {
    return dialog.showMessageBoxSync(win, { title: "Forthmark", noLink: true, ...options });
  } finally {
    modalOpen = false;
    ignoreBlurUntil = Date.now() + 300;
    win?.focus();
  }
}
ipcMain.on("dialog-alert", (e, text) => {
  modal(e, { message: String(text), buttons: [L("确定", "OK")] });
  e.returnValue = null;
});
ipcMain.on("dialog-confirm", (e, text) => {
  e.returnValue = modal(e, { message: String(text), buttons: [L("确定", "OK"), L("取消", "Cancel")], defaultId: 0, cancelId: 1 }) === 0;
});

// ---------------------------------------------------------------- notifications

function post(title, body) {
  const n = new Notification({ title, body });
  notifications.add(n);
  const done = () => notifications.delete(n);
  n.on("click", () => { done(); showPopover(); });
  n.on("close", done);
  n.show();
}

async function checkNotifications() {
  for (const item of (await api("/api/notify")) || []) post(item.title || "Forthmark", item.body || "");
}

function testNotification() {
  if (Notification.isSupported()) {
    return post("Forthmark", L("通知正常：卡住的事会在这里提醒你。", "Notifications work: blocked items will be flagged here."));
  }
  dialog.showMessageBox({ message: L("这台电脑的系统不支持通知", "Notifications aren't supported on this system") });
}

// ---------------------------------------------------------------- lifecycle

process.on("uncaughtException", logFailure);
process.on("unhandledRejection", logFailure);

if (!app.requestSingleInstanceLock()) app.quit();
else {
  app.setAppUserModelId(APP_ID);  // Windows attributes notifications through this id
  // Opening the app again while it runs: new tray icons start hidden in Windows' overflow, so show a window.
  app.on("second-instance", (_e, argv) => (argv.includes("--quit") ? app.quit() : openPanelWindow()));
  app.on("window-all-closed", () => {});  // lives in the tray
  app.on("before-quit", () => {
    app.isQuitting = true;
    if (!serviceStartedHere) return;  // only the service this app started; one started elsewhere keeps running
    try { execFileSync(PYTHON, [CLI, "stop"], { windowsHide: true, timeout: 5000 }); } catch {}
  });
  app.whenReady().then(start);
}

async function start() {
  Menu.setApplicationMenu(null);
  session.defaultSession.setPermissionRequestHandler((_wc, _permission, done) => done(false));
  tray = new Tray(trayImage(0, nativeTheme.shouldUseDarkColorsForSystemIntegratedUI));
  tray.setToolTip("Forthmark");
  tray.on("click", togglePopover);
  tray.on("right-click", () => tray.popUpContextMenu(buildMenu()));
  createPopover();
  nativeTheme.on("updated", () => { paintTray(); popover.setBackgroundColor(popoverColor()); });

  try {
    await ensureSetup();
  } catch (e) {
    logFailure(e);
    // Not the blocking error box: the panel should still come up behind it.
    dialog.showMessageBox({ type: "error", title: "Forthmark", message: L("Forthmark 没有接入 Claude Code", "Forthmark couldn't connect to Claude Code"), detail: e.message });
  }
  try {
    await ensureServer();
    loadPopover();
    await refreshBadge();
    if (!STARTED_HIDDEN) openPanelWindow();
  } catch (e) { serviceFailed(e); }

  setInterval(refreshBadge, 60 * 1000);
  setInterval(checkNotifications, 30 * 60 * 1000);
  setTimeout(checkNotifications, 60 * 1000);

  if (process.env.FORTHMARK_TEST_REPORT) {  // for test/smoke.js, which runs the packaged app with nothing attached
    const bridge = popover.webContents.executeJavaScript("Boolean(window.webkit?.messageHandlers?.forthmark) && Boolean(document.querySelector('#app'))");
    const report = { url: popover.webContents.getURL(), bridge: await Promise.race([bridge, new Promise(r => setTimeout(r, 15000, false))]) };
    fs.writeFileSync(process.env.FORTHMARK_TEST_REPORT, JSON.stringify(report));
  }
  if (process.env.FORTHMARK_TEST) {  // for test/e2e.js: what only a real tray click could reach
    globalThis.forthmarkTest = { togglePopover, showPopover, openPanelWindow, popover: () => popover, panelWindow: () => panelWindow, post, ready: true };
  }
}
