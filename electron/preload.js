/**
 * Electron Preload script for secure desktop integration.
 * Implements Section 5.2:
 * Exposes only session token, file open/save dialogs, and quit via contextBridge.
 */

const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("electronAPI", {
  isElectron: true,
  platform: process.platform,
  sessionToken: process.env.MINI_COLOSSEUM_SESSION_TOKEN || "",
  showOpenDialog: (opts) => ipcRenderer.invoke("dialog:open", opts),
  showSaveDialog: (opts) => ipcRenderer.invoke("dialog:save", opts),
  quit: () => ipcRenderer.invoke("app:quit"),
});
