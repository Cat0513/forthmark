// The panel page's native bridge: the same names as in the macOS app's web view, so the page needs no changes.
const { contextBridge, ipcRenderer, webFrame } = require("electron");

contextBridge.exposeInMainWorld("webkit", {
  messageHandlers: { forthmark: { postMessage: message => ipcRenderer.send("native", message) } },
});

// Electron's own alert / confirm can't tell us they're up; ours keep the popover from closing behind them.
contextBridge.exposeInMainWorld("forthmarkDialogs", {
  alert: text => ipcRenderer.sendSync("dialog-alert", String(text)),
  confirm: text => ipcRenderer.sendSync("dialog-confirm", String(text)),
  pickFolder: () => ipcRenderer.invoke("pick-folder"),
});
webFrame.executeJavaScript("window.alert = forthmarkDialogs.alert; window.confirm = forthmarkDialogs.confirm;");
